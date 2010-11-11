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

Installing Nova Development Snapshot on Multiple Servers
========================================================

When you move beyond evaluating the technology and into building an actual
production environemnt, you will need to know how to configure your datacenter
and how to deploy components across your clusters.  This guide should help you
through that process.

You can install multiple nodes to increase performance and availability of the OpenStack Compute installation.

This setup is based on an Ubuntu Lucid 10.04 installation with the latest updates. Most of this works around issues that need to be resolved in the installation and configuration scripts as of October 18th 2010. It also needs to eventually be generalized, but the intent here is to get the multi-node configuration bootstrapped so folks can move forward.


Requirements for a multi-node installation
------------------------------------------

* You need a real database, compatible with SQLAlchemy (mysql, postgresql) There's not a specific reason to choose one over another, it basically depends what you know. MySQL is easier to do High Availability (HA) with, but people may already know Postgres. We should document both configurations, though.
* For a recommended HA setup, consider a MySQL master/slave replication, with as many slaves as you like, and probably a heartbeat to kick one of the slaves into being a master if it dies.
* For performance optimization, split reads and writes to the database. MySQL proxy is the easiest way to make this work if running MySQL.


Assumptions
^^^^^^^^^^^

* Networking is configured between/through the physical machines on a single subnet.
* Installation and execution are both performed by root user.



Step 1 Use apt-get to get the latest code
-----------------------------------------

1. Setup Nova PPA with https://launchpad.net/~nova-core/+archive/ppa.
2. Run update.

::
    
    update

3. Install nova-pkgs (dependencies should be automatically installed).

::

    sudo apt-get install nova-common nova-doc python-nova nova-api nova-network nova-objectstore nova-scheduler

It is highly likely that there will be errors when the nova services come up since they are not yet configured. Don't worry, you're only at step 1!

Step 2 Setup configuration files (installed in /etc/nova)
---------------------------------------------------------

Note: CC_ADDR=<the external IP address of your cloud controller>

1. These need to be defined in EACH configuration file

::

   --sql_connection=mysql://root:nova@$CC_ADDR/nova # location of nova sql db
   --s3_host=$CC_ADDR  # This is where nova is hosting the objectstore service, which
                       # will contain the VM images and buckets
   --rabbit_host=$CC_ADDR # This is where the rabbit AMQP messaging service is hosted
   --cc_host=$CC_ADDR     # This is where the the nova-api service lives
   --verbose              # Optional but very helpful during initial setup
   --ec2_url=http://$CC_ADDR:8773/services/Cloud
   --network_manager=nova.network.manager.FlatManager # simple, no-vlan networking type


2. nova-manage specific flags

::

   --FAKE_subdomain=ec2             # workaround for ec2/euca api
   --fixed_range=<network/prefix>   # ip network to use for VM guests, ex 192.168.2.64/26
   --network_size=<# of addrs>      # number of ip addrs to use for VM guests, ex 64


3. nova-network specific flags

::

   --fixed_range=<network/prefix>   # ip network to use for VM guests, ex 192.168.2.64/26
   --network_size=<# of addrs>      # number of ip addrs to use for VM guests, ex 64

4. nova-api specific flags

::

   --FAKE_subdomain=ec2             # workaround for ec2/euca api


5. nova-objectstore specific flags < no specific config needed >

Config files should be have their owner set to root:nova, and mode set to 0640, since they contain your MySQL server's root password.

Step 3 Setup the sql db
-----------------------

1. First you 'preseed' (using vishy's directions here). Run this as root.
2. Install mysql
3. Configure mysql so that external users can access it, and setup nova db.
4. Edit /etc/mysql/my.cnf and set this line: bind-address=0.0.0.0 and then sighup or restart mysql
5. create nova's db   

::

   mysql -uroot -pnova -e 'CREATE DATABASE nova;'


6. Update the db to include user 'root'@'%'

::

   mysql -u root -p nova 
   GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;
   SET PASSWORD FOR 'root'@'%' = PASSWORD('nova');


Step 4 Setup Nova environment
-----------------------------

::

   /usr/bin/python /usr/bin/nova-manage user admin <user_name>
   /usr/bin/python /usr/bin/nova-manage project create <project_name> <user_name>
   /usr/bin/python /usr/bin/nova-manage project create network

Note: The nova-manage service assumes that the first IP address is your network (like 192.168.0.0), that the 2nd IP is your gateway (192.168.0.1), and that the broadcast is the very last IP in the range you defined (192.168.0.255). If this is not the case you will need to manually edit the sql db 'networks' table.o.

On running this command, entries are made in the 'networks' and 'fixed_ips' table. However, one of the networks listed in the 'networks' table needs to be marked as bridge in order for the code to know that a bridge exists. We ended up doing this manually, (update query fired directly in the DB). Is there a better way to mark a network as bridged?

Update: This has been resolved w.e.f 27/10. network is marked as bridged automatically based on the type of n/w manager selected.

More networking details to create a network bridge for flat network
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Nova defaults to a bridge device named 'br100'. This needs to be created and somehow integrated into YOUR network. In my case, I wanted to keep things as simple as possible and have all the vm guests on the same network as the vm hosts (the compute nodes). Thus, I set the compute node's external IP address to be on the bridge and added eth0 to that bridge. To do this, edit your network interfaces config to look like the following::

   < begin /etc/network/interfaces >
   # The loopback network interface
   auto lo
   iface lo inet loopback

   # Networking for NOVA
   auto br100

   iface br100 inet dhcp
          bridge_ports    eth0
          bridge_stp      off
          bridge_maxwait  0
          bridge_fd       0
   < end /etc/network/interfaces >


Next, restart networking to apply the changes::

   sudo /etc/init.d/networking restart

Step 5: Create nova certs.
--------------------------

Generate the certs as a zip file::

   mkdir creds
   sudo /usr/bin/python /usr/bin/nova-manage project zip admin admin creds/nova.zip

you can get the rc file more easily with::

   sudo /usr/bin/python /usr/bin/nova-manage project env admin admin creds/novarc 

unzip them in your home directory, and add them to your environment::

   unzip creds/nova.zip
   echo ". creds/novarc" >> ~/.bashrc
   ~/.bashrc


Step 6 Restart all relevant services
------------------------------------

Restart Libvirt::

   sudo /etc/init.d/libvirt-bin restart

Restart relevant nova services::

   sudo /etc/init.d/nova-compute restart
   sudo /etc/init.d/nova-volume restart


.. todo:: do we still need the content below?

Bare-metal Provisioning
-----------------------

To install the base operating system you can use PXE booting.

Types of Hosts
--------------

A single machine in your cluster can act as one or more of the following types
of host:

Nova Services

* Network
* Compute
* Volume
* API
* Objectstore

Other supporting services

* Message Queue
* Database (optional)
* Authentication database (optional)

Initial Setup
-------------

* Networking
* Cloudadmin User Creation

Deployment Technologies
-----------------------

Once you have machines with a base operating system installation, you can deploy
code and configuration with your favorite tools to specify which machines in
your cluster have which roles:

* Puppet
* Chef
