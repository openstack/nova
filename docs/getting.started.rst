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

Create a file named nova.pth in your python libraries directory
(usually /usr/local/lib/python2.6/dist-packages) with a single line that points
to the directory where you checked out the source (that contains the nova/
directory).

DEPENDENCIES
------------

Related servers we rely on

* RabbitMQ: messaging queue, used for all communication between components
* OpenLDAP: users, groups (maybe cut)
* ReDIS: Remote Dictionary Store (for fast, shared state data)
* nginx: HTTP server to handle serving large files (because Tornado can't)

Python libraries we don't vendor

* M2Crypto: python library interface for openssl
* curl

Vendored python libaries (don't require any installation)

* Tornado: scalable non blocking web server for api requests
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

    # system libraries and tools
    apt-get install -y aoetools vlan
    modprobe aoe

    # python libraries
    apt-get install -y python-setuptools python-dev python-pycurl python-m2crypto

    # ON THE CLOUD CONTROLLER
    apt-get install -y rabbitmq-server dnsmasq nginx
    # build redis from 2.0.0-rc1 source
    # setup ldap (slap.sh as root will remove ldap and reinstall it)
    NOVA_PATH/nova/auth/slap.sh
    /etc/init.d/rabbitmq-server start

    # ON VOLUME NODE:
    apt-get install -y vblade-persist

    # ON THE COMPUTE NODE:
    apt-get install -y python-libvirt
    apt-get install -y kpartx kvm libvirt-bin

    # optional packages
    apt-get install -y euca2ools

Configuration
---------------

ON CLOUD CONTROLLER

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
      rewrite ^/_images/(.*)\$ /\$1 break;
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
    echo "--storage_dev=/dev/loop0" >> NOVA_PATH/bin/nova.conf

Running
---------

Launch servers

* rabbitmq
* redis
* slapd
* nginx

Launch nova components

* nova-api
* nova-compute
* nova-objectstore
* nova-volume
