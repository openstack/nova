..
      Copyright [2010] [Anso Labs, LLC]
 
      Licensed under the Apache License, Version 2.0 (the "License");
      you may not use this file except in compliance with the License.
      You may obtain a copy of the License at
 
          http://www.apache.org/licenses/LICENSE-2.0
 
      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS,
      WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
      See the License for the specific language governing permissions and
      limitations under the License.

Getting Started with Nova
=========================


GOTTA HAVE A nova.pth file added or it WONT WORK (will write setup.py file soon)

DEPENDENCIES
------------

* RabbitMQ: messaging queue, used for all communication between components
* OpenLDAP: users, groups (maybe cut)
* Tornado: scalable non blocking web server for api requests
* Twisted: just for the twisted.internet.defer package
* boto: python api for aws api
* M2Crypto: python library interface for openssl
* IPy: library for managing ip addresses
* ReDIS: Remote Dictionary Store (for fast, shared state data)

Recommended
-----------------
* euca2ools: python implementation of aws ec2-tools and ami tools
* build tornado to use C module for evented section


Installation
--------------
::

    # ON ALL SYSTEMS
    apt-get install -y python-libvirt libvirt-bin python-setuptools python-dev python-pycurl python-m2crypto python-twisted
    apt-get install -y aoetools vlan
    modprobe aoe

    # ON THE CLOUD CONTROLLER
    apt-get install -y rabbitmq-server dnsmasq      
    # fix ec2 metadata/userdata uri - where $IP is the IP of the cloud
    iptables -t nat -A PREROUTING -s 0.0.0.0/0 -d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT --to-destination $IP:8773
    iptables --table nat --append POSTROUTING --out-interface $PUBLICIFACE -j MASQUERADE     
    # setup ldap (slap.sh as root will remove ldap and reinstall it)   
    auth/slap.sh     
    /etc/init.d/rabbitmq-server start

    # ON VOLUME NODE:
    apt-get install -y vblade-persist 

    # ON THE COMPUTE NODE:
    apt-get install -y kpartx kvm

    # optional packages
    apt-get install -y euca2ools 
                                   
    # Set up flagfiles with the appropriate hostnames, etc.                                     
    # start api_worker, s3_worker, node_worker, storage_worker
    # Add yourself to the libvirtd group, log out, and log back in
    # Make sure the user who will launch the workers has sudo privileges w/o pass (will fix later)           
