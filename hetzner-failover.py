#!/usr/bin/python3 -u
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# This script checks the backend of HAProxy for a given server 
# and switches the Hetzner failover IP that are pointing to this server
# to a given backup server.

import requests
import json
import socket
from argparse import ArgumentParser
from configparser import ConfigParser
import sys
from time import sleep


# Create the Arguments
parser = ArgumentParser(description="check hosts or change target of failover IP")
parser.add_argument("-c", dest="config", type=str, help="Config file", required=True)
parser.add_argument("-v", dest="verbose", action="store_true", help="increase output verbosity")
args = parser.parse_args()


try: # Read configuration file
   config = ConfigParser()
   config.read(args.config)
   host         = config["FAILOVER"]["host"]
   backup       = config["FAILOVER"]["backup"]
   hetzner_auth = config["FAILOVER"]["hetzner_auth"]
   hetzner_api  = config["FAILOVER"]["hetzner_api"]
   haproxy_auth = config["FAILOVER"]["haproxy_auth"]
   haproxy_url  = config["FAILOVER"]["haproxy_url"]
except:
   log(2, "Could not open config file")
   sys.exit(1)

# Send get or post to hetzner API
def api_request(url, data):
   header = {"Authorization": "Basic "+hetzner_auth}
   if data == None:
      response = requests.get(url, headers=header, timeout=5)
   else:
      response = requests.post(url, params=data, headers=header, timeout=60)
   return response

# Get all registered Failover IPs
def get_ips():
   url = hetzner_api+"failover"
   response = api_request(url, None)
   json_data = json.loads(response.text)
   return json_data

# Change the target server of a given failover IP (might take up to 60 secs.)
def change_ip(ip, target):
   url = hetzner_api+"failover/"+ip
   data = "active_server_ip="+target
   try:
      response = api_request(url, data)
      if args.verbose:
         log(4, str(response.status_code)+" "+response.text)
      if response.status_code == 200:
         log(0, "Successfully changed "+ip+" to "+target)
         return True
      else:
         raise Exception("Error changing failover IP")
   except:
      log(2, "Could not change target of "+ip)
      return False

# Find the IP of a given hostname
def get_host_ip(host):
   try:
      host_ip = socket.gethostbyname(host)
      return host_ip
   except Exception as err:
      if args.verbose:
         log(4, str(err))
      return None

# Get all failover IPs that are currently pointing to given host (returns a list)
def get_failover_of_host(host_ip):
   failips = []
   data = get_ips()
   for obj in data:
      failover = obj["failover"]
      if failover["active_server_ip"] != None:
         if (host_ip in failover["active_server_ip"]):
            failips.append(failover["ip"])
   return failips

# Check if the HAProxy stats page is available
def isup(haproxy):
   header = {"Authorization": "Basic "+haproxy_auth}
   requests.packages.urllib3.disable_warnings()
   try:
      response = requests.get(haproxy, headers=header, verify=False, timeout=5)
      return True
   except:
      return False

# Define colored log levels
def log(lvl, msg):
   if lvl == 0:
      lvstr = "INFO "
      col = "\033[92m"
   elif lvl == 1:
      lvstr = "WARN "
      col = "\033[93m"
   elif lvl == 2:
      lvstr = "ERROR"
      col = "\033[91m"
   else:
      lvstr = "DEBUG"
      col = "\033[94m"
   print(col+lvstr+"\033[0m "+str(msg))


def main():
   log(0, "Hetzner Failover Automation Script v0.3")
   try: # Find the IP of the main server
      host_ip = get_host_ip(host)
      main_check_url = haproxy_url.replace("<hostname>", host_ip)
      log(0, host+" - IP address found: "+host_ip)
   except Exception as err:
      log(2, "Could not find IP address of "+host)
      if args.verbose:
         log(4, str(err))
      sys.exit(1)
   try: # Find the IP of the backup server
      backup_ip = get_host_ip(backup)
      back_check_url = haproxy_url.replace("<hostname>", backup_ip)
      log(0, backup+" - IP address found: "+backup_ip)
   except Exception as err:
      log(2, "Could not find IP address of "+backup)
      if args.verbose:
         log(4, str(err))
      sys.exit(1)
   try: # Get failover IPs routed to main server
      failips = get_failover_of_host(host_ip)
      if failips == []:
         raise Exception("Empty response from Hetzner API")
      log(0, "Got active failover IPs for "+host)
      if args.verbose:
         log(4, failips)
   except Exception as err:
      log(2, "Could not get Failover IPs for "+host)
      if args.verbose:
         log(4, str(err))
      sys.exit(1)
   retry = 0
   down = False
   loopcount = 0
   log(0, "Started host checking")
   while True: # Start main loop
      if isup(main_check_url): # Check if server is online
         if args.verbose:
            log(4, host+" is up")
         if loopcount == 15: # Send logmessage after 15 successful checks
            log(0, host+" was up for the last 15 checks")
            loopcount = 0
         if down == True: # Server is now up but was down before
            if retry <= 2: # Retry three times before marking the host as UP again
               retry += 1
            else: # Host is back up. Change back failover IPs
               log(0, host+" is back up. Switching Failover")
               loopcount = 0
               for ip in failips:
                  change_ip(ip, host_ip)
               down = False
               retry = 0
         else:
            retry = 0
         loopcount += 1
      else: # Host is not reachable
         if (retry <=2) and (down != True): # Retry three times before marking the Host as DOWN
            log(1, "Could not reach "+host+"! Retry "+str(retry))
            retry += 1
         elif (down != True): # Host down after three retries. Switch Failover to backup
            if isup(back_check_url): #check if the backup haproxy is available
               log(2, host+" is down! Switching failover")
               down = True
               loopcount = 0
               for ip in failips:
                  change_ip(ip, backup_ip)
               retry = 0
            else: #We should never get here!
               log(2, "All hosts down! Not switching failover.")
               stride("red", "ALL HAPROXY SERVERS ARE DOWN!!!", "This should have never happened...")
         else: # Host is still not back up
            log(2, host+" is still down")
      sleep(2)


if __name__ == "__main__":
   main()
