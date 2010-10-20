..
      Copyright 2010 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration. 
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Getting Started with Nova
=========================

This code base is continually changing so dependencies also change. 

Dependencies
------------

Related servers we rely on

* RabbitMQ: messaging queue, used for all communication between components
* OpenLDAP: users, groups 

Optional servers

* ReDIS: Remote Dictionary Store (for fast, shared state data)
* nginx: HTTP server to handle serving large files 

Python libraries we don't vendor

* M2Crypto: python library interface for openssl
* curl
* XenAPI: Needed only for Xen Cloud Platform or XenServer support.  Available from http://wiki.xensource.com/xenwiki/XCP_SDK or http://community.citrix.com/cdn/xs/sdks.

Vendored python libaries (don't require any installation)

* Twisted: just for the twisted.internet.defer package
* boto: python api for aws api
* IPy: library for managing ip addresses

Recommended
-----------------

* euca2ools: python implementation of aws ec2-tools and ami tools
* build tornado to use C module for evented section


Installation
--------------
::

    Due to many changes it's best to rely on the 'OpenStack wiki <http://wiki.openstack.org>' for installation instructions.

Configuration
---------------

These instructions are incomplete, but we are actively updating the 'OpenStack wiki <http://wiki.openstack.org>' with more configuration information.

On the cloud controller

* Add yourself to the libvirtd group, log out, and log back in
* fix hardcoded ec2 metadata/userdata uri ($IP is the IP of the cloud), and masqurade all traffic from launched instances
::

    iptables -t nat -A PREROUTING -s 0.0.0.0/0 -d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT --to-destination $IP:8773
    iptables --table nat --append POSTROUTING --out-interface $PUBLICIFACE -j MASQUERADE


* Configure NginX proxy (/etc/nginx/sites-enabled/default)

::

  server {
    listen 3333 default;
    server-name localhost;
    client_max_body_size 10m;

    access_log /var/log/nginx/localhost.access.log;

    location ~ /_images/.+ {
      root NOVA_PATH/images;
      rewrite ^/_images/(.*)$ /$1 break;
    }

    location / {
      proxy_pass http://localhost:3334/;
    }
  }

ON VOLUME NODE

* create a filesystem (you can use an actual disk if you have one spare, default is /dev/sdb)

::

    # This creates a 1GB file to create volumes out of
    dd if=/dev/zero of=MY_FILE_PATH bs=100M count=10
    losetup --show -f MY_FILE_PATH
    # replace loop0 below with whatever losetup returns
    echo "--storage_dev=/dev/loop0" >> NOVA_PATH/bin/nova.conf

Running
---------

Launch servers

* rabbitmq
* redis (optional)
* slapd
* nginx

Launch nova components

* nova-api
* nova-compute
* nova-objectstore
* nova-volume
