#!/bin/bash
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration. 
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

# This gets zipped and run on the cloudpipe-managed OpenVPN server

export SUPERVISOR="http://10.255.255.1:8773/cloudpipe"
export VPN_IP=`ifconfig  | grep 'inet addr:'| grep -v '127.0.0.1' | cut -d: -f2 | awk '{print $1}'`
export BROADCAST=`ifconfig  | grep 'inet addr:'| grep -v '127.0.0.1' | cut -d: -f3 | awk '{print $1}'`
export DHCP_MASK=`ifconfig  | grep 'inet addr:'| grep -v '127.0.0.1' | cut -d: -f4 | awk '{print $1}'`
export GATEWAY=`netstat -r | grep default | cut -d' ' -f10`
export SUBJ=/C=US/ST=California/L=Mountain View/O=Anso Labs/OU=Nova Dev/CN=customer-vpn-$VPN_IP

DHCP_LOWER=`echo $BROADCAST | awk -F. '{print $1"."$2"."$3"." $4 - 10 }'`
DHCP_UPPER=`echo $BROADCAST | awk -F. '{print $1"."$2"."$3"." $4 - 1 }'`

# generate a server DH
openssl dhparam -out /etc/openvpn/dh1024.pem 1024

# generate a server priv key
openssl genrsa -out /etc/openvpn/server.key 2048

# generate a server CSR
openssl req -new -key /etc/openvpn/server.key -out /etc/openvpn/server.csr -batch -subj "$SUBJ"

# URLEncode the CSR
CSRTEXT=`cat /etc/openvpn/server.csr`
CSRTEXT=$(python -c "import urllib; print urllib.quote('''$CSRTEXT''')")

# SIGN the csr and save as server.crt
# CURL fetch to the supervisor, POSTing the CSR text, saving the result as the CRT file
curl $SUPERVISOR -d "cert=$CSRTEXT" > /etc/openvpn/server.crt
curl $SUPERVISOR/getca/ > /etc/openvpn/ca.crt

# Customize the server.conf.template
cd /etc/openvpn

sed -e s/VPN_IP/$VPN_IP/g server.conf.template > server.conf
sed -i -e s/DHCP_SUBNET/$DHCP_MASK/g server.conf
sed -i -e s/DHCP_LOWER/$DHCP_LOWER/g server.conf
sed -i -e s/DHCP_UPPER/$DHCP_UPPER/g server.conf
sed -i -e s/max-clients\ 1/max-clients\ 10/g server.conf

echo "\npush \"route 10.255.255.1 255.255.255.255 $GATEWAY\"\n" >> server.conf
echo "\npush \"route 10.255.255.253 255.255.255.255 $GATEWAY\"\n" >> server.conf
echo "\nduplicate-cn\n" >> server.conf

/etc/init.d/openvpn start
