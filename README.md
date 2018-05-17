# haproxy-hetzner-failover
HAProxy check script that can switch hetzner failover IPs

The script checks every two seconds if the HAProxy stats page is available 
and triggers a failover switch via the Hetzner ROBOT API to a given backup server.

If the server that died comes back up the script will automatically switch back the failover.


Script can be used with the provided systemd service.
You might want to modify the file to your needs (user and path).