#!/bin/bash
/root/slap.sh
mysql -e "DROP DATABASE nova"
mysql -e "CREATE DATABASE nova"
mysql -e "GRANT ALL on nova.* to nova@'%' identified by 'TODO:CHANGEME:CMON'"
touch /root/installed
