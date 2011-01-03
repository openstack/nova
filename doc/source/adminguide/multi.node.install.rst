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

Installing Nova on Multiple Servers

===================================
 
When you move beyond evaluating the technology and into building an actual
production environment, you will need to know how to configure your datacenter
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
------------------------------------
 
* Networking is configured between/through the physical machines on a single subnet.
* Installation and execution are both performed by ROOT user.
  
 
Step 1 - Use apt-get to get the latest code
-------------------------------------------

1. Setup Nova PPA with https://launchpad.net/~nova-core/+archive/trunk. The ‘python-software-properties’ package is a pre-requisite for setting up the nova package repo:

::
    
    sudo apt-get install python-software-properties
    sudo add-apt-repository ppa:nova-core/trunk
	
2. Run update.

::
    
    sudo apt-get update

3. Install nova-pkgs (dependencies should be automatically installed).

::

    sudo apt-get install python-greenlet
    sudo apt-get install nova-common nova-doc python-nova nova-api nova-network nova-objectstore nova-scheduler

It is highly likely that there will be errors when the nova services come up since they are not yet configured. Don't worry, you're only at step 1!

Step 2 Setup configuration file (installed in /etc/nova)
--------------------------------------------------------

1.  Nova development has consolidated all config files to nova.conf as of November 2010.   There is a default set of options that are already configured in nova.conf:
 
::
 
--daemonize=1
--dhcpbridge_flagfile=/etc/nova/nova.conf
--dhcpbridge=/usr/bin/nova-dhcpbridge
--logdir=/var/log/nova
--state_path=/var/lib/nova
 
The following items ALSO need to be defined in /etc/nova/nova.conf.  I’ve added some explanation of the variables, as comments CANNOT be in nova.conf.  There seems to be an issue with nova-manage not processing the comments/whitespace correctly:
 
--sql_connection  ###  Location of Nova SQL DB
 
--s3_host ###  This is where Nova is hosting the objectstore service, which will contain the VM images and buckets
 
--rabbit_host ### This is where the rabbit AMQP messaging service is hosted

--cc_host ### This is where the the nova-api service lives
 
--verbose   ###  Optional but very helpful during initial setup
 
--ec2_url ### The location to interface nova-api
 
--network_manager ### Many options here, discussed below.  This is how your controller will communicate with additional Nova nodes and VMs:
 
nova.network.manager.FlatManager  # Simple, no-vlan networking type
nova.network.manager. FlatDHCPManager #  Flat networking with DHCP
nova.network.manager.VlanManager # Vlan networking with DHCP – /DEFAULT/ if no network manager is defined in nova.conf
 
--fixed_range=<network/prefix>   ###  This will be the IP network that ALL the projects for future VM guests will reside on.  E.g. 192.168.0.0/12
 
--network_size=<# of addrs>      ### This is the total number of IP Addrs to use for VM guests, of all projects.  E.g. 5000
 
The following code can be cut and paste, and edited to your setup:

## Note: CC_ADDR=<the external IP address of your cloud controller>##
## Detailed explanation of the following entries are right above this ##
 
::
 
--sql_connection=mysql://root:nova@<CC_ADDR>/nova
--s3_host=<CC_ADDR>
--rabbit_host=<CC_ADDR>
--cc_host=<CC_ADDR>  
--verbose             
--ec2_url=http://<CC_ADDR>:8773/services/Cloud
--network_manager=nova.network.manager.VlanManager
--fixed_range=<network/prefix>
--network_size=<# of addrs>     
 
2. Create a “nova” group, and set permissions:
 
::
 
addgroup nova
 
The Nova config file should have its owner set to root:nova, and mode set to 0644, since they contain your MySQL server's root password.
 
::
  
chown -R root:nova /etc/nova
chmod 644 /etc/nova/nova.conf
 
Step 3 - Setup the SQL DB (MySQL for this setup)
------------------------------------------------
 
1. First you 'preseed' to bypass all the installation prompts
::
 
bash
MYSQL_PASS=nova
cat <<MYSQL_PRESEED | debconf-set-selections
mysql-server-5.1 mysql-server/root_password password $MYSQL_PASS
mysql-server-5.1 mysql-server/root_password_again password $MYSQL_PASS
mysql-server-5.1 mysql-server/start_on_boot boolean true
MYSQL_PRESEED
 
2. Install MySQL:
 
::
 
apt-get install -y mysql-server
 
3. Edit /etc/mysql/my.cnf to change ‘bind-address’ from localhost to any:
 
::
 
sed -i 's/127.0.0.1/0.0.0.0/g' /etc/mysql/my.cnf
service mysql restart
 
3.  Network Configuration
 
If you use FlatManager (as opposed to VlanManager that we set) as your network manager, there are some additional networking changes you’ll have to make to ensure connectivity between your nodes and VMs.  If you chose VlanManager or FlatDHCP, you may skip this section, as it’s set up for you automatically.
 
Nova defaults to a bridge device named 'br100'. This needs to be created and somehow integrated into YOUR network. To keep things as simple as possible, have all the VM guests on the same network as the VM hosts (the compute nodes). To do so, set the compute node's external IP address to be on the bridge and add eth0 to that bridge. To do this, edit your network interfaces config to look like the following
 
::
 
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
 
4. MySQL DB configuration:
 
Create NOVA database:  
 
::
 
mysql -uroot -p$MYSQL_PASS -e 'CREATE DATABASE nova;'
 
 
Update the DB to include user 'root'@'%' with super user privileges
 
::
 
mysql -uroot -p$MYSQL_PASS -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;"
 
Set mySQL root password
 
::
 
mysql -uroot -p$MYSQL_PASS -e "SET PASSWORD FOR 'root'@'%' = PASSWORD('$MYSQL_PASS');"
 
 
Step 4 - Setup Nova environment
-----------------------------
 
::
 
/usr/bin/python /usr/bin/nova-manage user admin <user_name>
/usr/bin/python /usr/bin/nova-manage project create <project_name> <user_name>
/usr/bin/python /usr/bin/nova-manage network create <project-network> <number-of-networks-in-project> <IPs in project>
 
Here is an example of what this looks like with real data:
 
/usr/bin/python /usr/bin/nova-manage user admin dub
/usr/bin/python /usr/bin/nova-manage project create dubproject dub
/usr/bin/python /usr/bin/nova-manage network create 192.168.0.0/24 1 255
 
(I chose a /24 since that falls inside my /12 range I set in ‘fixed-range’ in nova.conf.  Currently, there can only be one network, and I am using the max IP’s available in a  /24.  You can choose to use any valid amount that you would like.)
 
Note: The nova-manage service assumes that the first IP address is your network (like 192.168.0.0), that the 2nd IP is your gateway (192.168.0.1), and that the broadcast is the very last IP in the range you defined (192.168.0.255). If this is not the case you will need to manually edit the sql db 'networks' table.o.
 
On running this command, entries are made in the 'networks' and 'fixed_ips' table. However, one of the networks listed in the 'networks' table needs to be marked as bridge in order for the code to know that a bridge exists. The Network is marked as bridged automatically based on the type of network manager selected.  This is ONLY necessary if you chose FlatManager as your network type.  More information can be found at the end of this document discussing setting up the bridge device.
 
 
Step 5 - Create Nova certs
--------------------------
 
1.  Generate the certs as a zip file.  These are the certs you will use to launch instances, bundle images, and all the other assorted api functions:
 
::
 
mkdir –p /root/creds
/usr/bin/python /usr/bin/nova-manage project zipfile $NOVA_PROJECT $NOVA_PROJECT_USER /root/creds/novacreds.zip
 
2.  Unzip them in your home directory, and add them to your environment:
 
::
 
unzip /root/creds/novacreds.zip -d /root/creds/ 
cat /root/creds/novarc >> ~/.bashrc
source ~/.bashrc
 
Step 6 - Restart all relevant services
------------------------------------
Restart all six services in total, just to cover the entire spectrum:
 
::
 
libvirtd restart; service nova-network restart; service nova-compute restart; service nova-api restart; service nova-objectstore restart; service nova-scheduler restart

Step 7 - Closing steps, and cleaning up:
------------------------------------

One of the most commonly missed configuration areas is not allowing the proper access to VMs. Use the 'euca-authorize' command to enable access.  Below, you will find the commands to allow 'ping' and 'ssh' to your VMs:

::

euca-authorize -P icmp -t -1:-1 default
euca-authorize -P tcp -p 22 default

Another common issue is you cannot ping or SSH your instances after issusing the 'euca-authorize' commands.  Something to look at is the amount of 'dnsmasq' processes that are running.  If you have a running instance, check to see that TWO 'dnsmasq' processes are running.  If not, perform the following:

::

killall dnsmasq
service nova-network restart

Step 8 – Testing the installation
------------------------------------

You can then use `euca2ools` to test some items:
 
::
 
euca-describe-images
euca-describe-instances
 
If you have issues with the API key, you may need to re-source your creds file:
 
::
 
. /root/creds/novarc
 
If you don’t get any immediate errors, you’re successfully making calls to your cloud!
 
The next thing you are going to need is an image to test.  There will soon be an update on how to capture an image and use it as a bootable AMI so you can ping, ssh, show instances spinning up, etc.
 
Enjoy your new private cloud, and play responsibly!

