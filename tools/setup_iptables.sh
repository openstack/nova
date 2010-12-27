#!/usr/bin/env bash
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# NOTE(vish): This script sets up some reasonable defaults for iptables and
#             creates nova-specific chains.  If you use this script you should
#             run nova-network and nova-compute with --use_nova_chains=True

# NOTE(vish): If you run nova-api on a different port, make sure to change
#             the port here
API_PORT=${API_PORT:-"8773"}
if [ -n "$1" ]; then
    CMD=$1
else
    CMD="all"
fi

if [ -n "$2" ]; then
    IP=$2
else
    # NOTE(vish): This will just get the first ip in the list, so if you
    #             have more than one eth device set up, this will fail, and
    #             you should explicitly pass in the ip of the instance
    IP=`LC_ALL=C ifconfig  | grep -m 1 'inet addr:'| cut -d: -f2 | awk '{print $1}'`
fi

if [ -n "$3" ]; then
    PRIVATE_RANGE=$3
else
    PRIVATE_RANGE="10.0.0.0/12"
fi


if [ -n "$4" ]; then
    # NOTE(vish): Management IP is the ip over which to allow ssh traffic.  It
    #             will also allow traffic to nova-api
    MGMT_IP=$4
else
    MGMT_IP="$IP"
fi
if [ "$CMD" == "clear" ]; then
    iptables -P INPUT ACCEPT
    iptables -P FORWARD ACCEPT
    iptables -P OUTPUT ACCEPT
    iptables -F
    iptables -t nat -F
    iptables -F nova_input
    iptables -F nova_output
    iptables -F nova_forward
    iptables -t nat -F nova_input
    iptables -t nat -F nova_output
    iptables -t nat -F nova_forward
    iptables -t nat -X
    iptables -X
fi

if [ "$CMD" == "base" ] || [ "$CMD" == "all" ]; then
    iptables -P INPUT DROP
    iptables -A INPUT -m state --state INVALID -j DROP
    iptables -A INPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A INPUT -m tcp -p tcp -d $MGMT_IP --dport 22 -j ACCEPT
    iptables -A INPUT -m udp -p udp --dport 123 -j ACCEPT
    iptables -N nova_input
    iptables -A INPUT -j nova_input
    iptables -A INPUT -p icmp -j ACCEPT
    iptables -A INPUT -p tcp -j REJECT --reject-with tcp-reset
    iptables -A INPUT -j REJECT --reject-with icmp-port-unreachable

    iptables -P FORWARD DROP
    iptables -A FORWARD -m state --state INVALID -j DROP
    iptables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -A FORWARD -p tcp -m tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu
    iptables -N nova_forward
    iptables -A FORWARD -j nova_forward

    # NOTE(vish): DROP on output is too restrictive for now.  We need to add
    #             in a bunch of more specific output rules to use it.
    # iptables -P OUTPUT DROP
    iptables -A OUTPUT -m state --state INVALID -j DROP
    iptables -A OUTPUT -m state --state RELATED,ESTABLISHED -j ACCEPT
    iptables -N nova_output
    iptables -A OUTPUT -j nova_output

    iptables -t nat -N nova_prerouting
    iptables -t nat -A PREROUTING -j nova_prerouting

    iptables -t nat -N nova_postrouting
    iptables -t nat -A POSTROUTING -j nova_postrouting

    iptables -t nat -N nova_output
    iptables -t nat -A OUTPUT -j nova_output
fi

if [ "$CMD" == "ganglia" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 8649 -j ACCEPT
    iptables -A nova_input -m udp -p udp -d $IP --dport 8649 -j ACCEPT
fi

if [ "$CMD" == "web" ] || [ "$CMD" == "all" ]; then
    # NOTE(vish): This opens up ports for web access, allowing web-based
    #             dashboards to work.
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 80 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 443 -j ACCEPT
fi

if [ "$CMD" == "objectstore" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 3333 -j ACCEPT
fi

if [ "$CMD" == "api" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport $API_PORT -j ACCEPT
    if [ "$IP" != "$MGMT_IP" ]; then
        iptables -A nova_input -m tcp -p tcp -d $MGMT_IP --dport $API_PORT -j ACCEPT
    fi
fi

if [ "$CMD" == "redis" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 6379 -j ACCEPT
fi

if [ "$CMD" == "mysql" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 3306 -j ACCEPT
fi

if [ "$CMD" == "rabbitmq" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 4369 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 5672 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 53284 -j ACCEPT
fi

if [ "$CMD" == "dnsmasq" ] || [ "$CMD" == "all" ]; then
    # NOTE(vish): this could theoretically be setup per network
    #             for each host, but it seems like overkill
    iptables -A nova_input -m tcp -p tcp -s $PRIVATE_RANGE --dport 53 -j ACCEPT
    iptables -A nova_input -m udp -p udp -s $PRIVATE_RANGE --dport 53 -j ACCEPT
    iptables -A nova_input -m udp -p udp --dport 67 -j ACCEPT
fi

if [ "$CMD" == "ldap" ] || [ "$CMD" == "all" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 389 -j ACCEPT
fi


