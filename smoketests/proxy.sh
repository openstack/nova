#!/usr/bin/env bash

# This is a simple shell script that uses netcat to set up a proxy to the
# metadata server on port 80 and to a google ip on port 8080.  This is meant
# to be passed in by a script to an instance via user data, so that
# automatic testing of network connectivity can be performed.

# Example usage:
#   euca-run-instances -t m1.tiny -f proxy.sh ami-tty

mkfifo backpipe1
mkfifo backpipe2

if nc -h 2>&1 | grep -i openbsd
then
	NC_LISTEN="nc -l"
else
	NC_LISTEN="nc -l -p"
fi

# NOTE(vish): proxy metadata on port 80
while true; do
    $NC_LISTEN 80 0<backpipe1 | nc 169.254.169.254 80 1>backpipe1
done &

# NOTE(vish): proxy google on port 8080
while true; do
    $NC_LISTEN 8080 0<backpipe2 | nc 74.125.19.99 80 1>backpipe2
done &
