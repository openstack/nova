#!/usr/bin/env bash

CMD="global"
IP="XXX"
PRIVATE_RANGE="10.128.0.0/12"

if [ -n "$1" ]; then
    CMD=$1
fi

if [ -n "$2" ]; then
    IP=$2
fi

if [ -n "$3" ]; then
    PRIVATE_RANGE=$3
fi

if [ "$CMD" == "global" ]; then
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

    iptables -P OUTPUT DROP
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

    # ganglia (all hosts)
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 8649 -j ACCEPT
    iptables -A nova_input -m udp -p udp -d $IP --dport 8649 -j ACCEPT
fi

if [ "$CMD" == "dashboard" ]; then
    # dashboard
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 80 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 443 -j ACCEPT
fi

if [ "$CMD" == "objectstore" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 3333 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 8773 -j ACCEPT
fi

if [ "$CMD" == "redis" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 6379 -j ACCEPT
fi

if [ "$CMD" == "mysql" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 3306 -j ACCEPT
fi

if [ "$CMD" == "rabbitmq" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 4369 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 5672 -j ACCEPT
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 53284 -j ACCEPT
fi

if [ "$CMD" == "dnsmasq" ]; then
    # NOTE(vish): this could theoretically be setup per network
    #             for each host, but it seems like overkill
    iptables -A nova_input -m tcp -p tcp -s $PRIVATE_RANGE --dport 53 -j ACCEPT
    iptables -A nova_input -m udp -p udp -s $PRIVATE_RANGE --dport 53 -j ACCEPT
    iptables -A nova_input -m udp -p udp --dport 67 -j ACCEPT

if [ "$CMD" == "ldap" ]; then
    iptables -A nova_input -m tcp -p tcp -d $IP --dport 389 -j ACCEPT
fi


