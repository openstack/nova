
Installing Nova on Multiple Servers
===================================

When you move beyond evaluating the technology and into building an actual
production environment, you will need to know how to configure your datacenter
and how to deploy components across your clusters.  This guide should help you
through that process.

You can install multiple nodes to increase performance and availability of the OpenStack Compute installation.

This setup is based on an Ubuntu Lucid 10.04 installation with the latest updates. Most of this works around issues that need to be resolved either in packaging or bug-fixing. It also needs to eventually be generalized, but the intent here is to get the multi-node configuration bootstrapped so folks can move forward.

For a starting architecture, these instructions describing installing a cloud controller node and a compute node. The cloud controller node contains the nova- services plus the database. The compute node installs all the nova-services but then refers to the database installation, which is hosted by the cloud controller node.

Requirements for a multi-node installation
------------------------------------------

* You need a real database, compatible with SQLAlchemy (mysql, postgresql) There's not a specific reason to choose one over another, it basically depends what you know. MySQL is easier to do High Availability (HA) with, but people may already know PostgreSQL. We should document both configurations, though.
* For a recommended HA setup, consider a MySQL master/slave replication, with as many slaves as you like, and probably a heartbeat to kick one of the slaves into being a master if it dies.
* For performance optimization, split reads and writes to the database. MySQL proxy is the easiest way to make this work if running MySQL.

Assumptions
-----------

* Networking is configured between/through the physical machines on a single subnet.
* Installation and execution are both performed by ROOT user.


Scripted Installation
---------------------
A script available to get your OpenStack cloud running quickly. You can copy the file to the server where you want to install OpenStack Compute services - typically you would install a compute node and a cloud controller node.

You must run these scripts with root permissions.

From a server you intend to use as a cloud controller node, use this command to get the cloud controller script. This script is a work-in-progress and the maintainer plans to keep it up, but it is offered "as-is." Feel free to collaborate on it in GitHub - https://github.com/dubsquared/OpenStack-NOVA-Installer-Script/.

::

    wget --no-check-certificate https://github.com/dubsquared/OpenStack-NOVA-Installer-Script/raw/master/nova-CC-install-v1.1.sh

Ensure you can execute the script by modifying the permissions on the script file.

::

    sudo chmod 755 nova-CC-install-v1.1.sh


::

    sudo ./nova-CC-install-v1.1.sh

Next, from a server you intend to use as a compute node (doesn't contain the database), install the nova services. You can use the nova-NODE-installer.sh script from the above github-hosted project for the compute node installation.

Copy the nova.conf from the cloud controller node to the compute node. 

Restart related services::

    libvirtd restart; service nova-network restart; service nova-compute restart; service nova-api restart; service nova-objectstore restart; service nova-scheduler restart

You can go to the `Configuration section`_ for next steps.

Manual Installation - Step-by-Step
----------------------------------
The following sections show you how to install Nova manually with a cloud controller node and a separate compute node. The cloud controller node contains the database plus all nova- services, and the compute node runs nova- services only.

Cloud Controller Installation
`````````````````````````````
On the cloud controller node, you install nova services and the related helper applications, and then configure with the nova.conf file. You will then copy the nova.conf file to the compute node, which you install as a second node in the `Compute Installation`_.

Step 1 - Use apt-get to get the latest code
-------------------------------------------

1. Setup Nova PPA with https://launchpad.net/~nova-core/+archive/trunk. The ‘python-software-properties’ package is a pre-requisite for setting up the nova package repo:

::

    sudo apt-get install python-software-properties
    sudo add-apt-repository ppa:nova-core/trunk

2. Run update.

::

    sudo apt-get update

3. Install python required packages, nova-packages, and helper apps.

::

    sudo apt-get install python-greenlet python-mysqldb python-nova nova-common nova-doc nova-api nova-network nova-objectstore nova-scheduler nova-compute euca2ools unzip

It is highly likely that there will be errors when the nova services come up since they are not yet configured. Don't worry, you're only at step 1!

Step 2 Set up configuration file (installed in /etc/nova)
---------------------------------------------------------

1.  Nova development has consolidated all config files to nova.conf as of November 2010. There is a default set of options that are already configured in nova.conf:

::

--daemonize=1
--dhcpbridge_flagfile=/etc/nova/nova.conf
--dhcpbridge=/usr/bin/nova-dhcpbridge
--logdir=/var/log/nova
--state_path=/var/lib/nova

The following items ALSO need to be defined in /etc/nova/nova.conf.  I’ve added some explanation of the variables, as comments CANNOT be in nova.conf. There seems to be an issue with nova-manage not processing the comments/whitespace correctly:

--sql_connection ###  Location of Nova SQL DB

--s3_host ###  This is where Nova is hosting the objectstore service, which will contain the VM images and buckets

--rabbit_host ### This is where the rabbit AMQP messaging service is hosted

--cc_host ### This is where the the nova-api service lives

--verbose ###  Optional but very helpful during initial setup

--ec2_url ### The location to interface nova-api

--network_manager ### Many options here, discussed below.  This is how your controller will communicate with additional Nova nodes and VMs:

nova.network.manager.FlatManager # Simple, no-vlan networking type
nova.network.manager. FlatDHCPManager #  Flat networking with DHCP
nova.network.manager.VlanManager # Vlan networking with DHCP – /DEFAULT/ if no network manager is defined in nova.conf

--fixed_range=<network/prefix> ###  This will be the IP network that ALL the projects for future VM guests will reside on.  E.g. 192.168.0.0/12

--network_size=<# of addrs> ### This is the total number of IP Addrs to use for VM guests, of all projects.  E.g. 5000

The following code can be cut and paste, and edited to your setup:

Note: CC_ADDR=<the external IP address of your cloud controller>

Detailed explanation of the following example is available above.

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

2. Create a “nova” group, and set permissions::

    addgroup nova

The Nova config file should have its owner set to root:nova, and mode set to 0644, since they contain your MySQL server's root password. ::

    chown -R root:nova /etc/nova
    chmod 644 /etc/nova/nova.conf

Step 3 - Setup the SQL DB (MySQL for this setup)
------------------------------------------------

1. First you 'preseed' to bypass all the installation prompts::

    bash
    MYSQL_PASS=nova
    cat <<MYSQL_PRESEED | debconf-set-selections
    mysql-server-5.1 mysql-server/root_password password $MYSQL_PASS
    mysql-server-5.1 mysql-server/root_password_again password $MYSQL_PASS
    mysql-server-5.1 mysql-server/start_on_boot boolean true
    MYSQL_PRESEED

2. Install MySQL::

    apt-get install -y mysql-server

3. Edit /etc/mysql/my.cnf to change ‘bind-address’ from localhost to any::

    sed -i 's/127.0.0.1/0.0.0.0/g' /etc/mysql/my.cnf
    service mysql restart

4. MySQL DB configuration:

Create NOVA database::

    mysql -uroot -p$MYSQL_PASS -e 'CREATE DATABASE nova;'

Update the DB to include user 'root'@'%' with super user privileges::

    mysql -uroot -p$MYSQL_PASS -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;"

Set mySQL root password::

    mysql -uroot -p$MYSQL_PASS -e "SET PASSWORD FOR 'root'@'%' = PASSWORD('$MYSQL_PASS');"

Compute Node Installation
`````````````````````````

Repeat steps 1 and 2 from the Cloud Controller Installation section above, then configure the network for your Compute instances on the Compute node. Copy the nova.conf file from the Cloud Controller node to this node.

Network Configuration
---------------------

If you use FlatManager as your network manager (as opposed to VlanManager that is shown in the nova.conf example above), there are some additional networking changes you’ll have to make to ensure connectivity between your nodes and VMs.  If you chose VlanManager or FlatDHCP, you may skip this section, as it’s set up for you automatically.

Nova defaults to a bridge device named 'br100'. This needs to be created and somehow integrated into YOUR network. To keep things as simple as possible, have all the VM guests on the same network as the VM hosts (the compute nodes). To do so, set the compute node's external IP address to be on the bridge and add eth0 to that bridge. To do this, edit your network interfaces config to look like the following::

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

Configuration
`````````````

On the Compute node, you should continue with these configuration steps.

Step 1 - Set up the Nova environment
------------------------------------

These are the commands you run to update the database if needed, and then set up a user and project::

    /usr/bin/python /usr/bin/nova-manage db sync
    /usr/bin/python /usr/bin/nova-manage user admin <user_name>
    /usr/bin/python /usr/bin/nova-manage project create <project_name> <user_name>
    /usr/bin/python /usr/bin/nova-manage network create <project-network> <number-of-networks-in-project> <IPs in project>

Here is an example of what this looks like with real data::

    /usr/bin/python /usr/bin/nova-manage db sync
    /usr/bin/python /usr/bin/nova-manage user admin dub
    /usr/bin/python /usr/bin/nova-manage project create dubproject dub
    /usr/bin/python /usr/bin/nova-manage network create 192.168.0.0/24 1 255

(I chose a /24 since that falls inside my /12 range I set in ‘fixed-range’ in nova.conf.  Currently, there can only be one network, and I am using the max IP’s available in a  /24.  You can choose to use any valid amount that you would like.)

Note: The nova-manage service assumes that the first IP address is your network (like 192.168.0.0), that the 2nd IP is your gateway (192.168.0.1), and that the broadcast is the very last IP in the range you defined (192.168.0.255). If this is not the case you will need to manually edit the sql db 'networks' table.o.

On running the "nova-manage network create" command, entries are made in the 'networks' and 'fixed_ips' table. However, one of the networks listed in the 'networks' table needs to be marked as bridge in order for the code to know that a bridge exists. The Network is marked as bridged automatically based on the type of network manager selected. You only need to mark the network as a bridge if you chose FlatManager as your network type. More information can be found at the end of this document discussing setting up the bridge device.


Step 2 - Create Nova certifications
-----------------------------------

1.  Generate the certs as a zip file.  These are the certs you will use to launch instances, bundle images, and all the other assorted api functions.

::

    mkdir –p /root/creds
    /usr/bin/python /usr/bin/nova-manage project zipfile $NOVA_PROJECT $NOVA_PROJECT_USER /root/creds/novacreds.zip

2.  Unzip them in your home directory, and add them to your environment.

::

    unzip /root/creds/novacreds.zip -d /root/creds/
    cat /root/creds/novarc >> ~/.bashrc
    source ~/.bashrc

Step 3 - Restart all relevant services
--------------------------------------

Restart all six services in total, just to cover the entire spectrum::

    libvirtd restart; service nova-network restart; service nova-compute restart; service nova-api restart; service nova-objectstore restart; service nova-scheduler restart

Step 4 - Closing steps, and cleaning up
---------------------------------------

One of the most commonly missed configuration areas is not allowing the proper access to VMs. Use the 'euca-authorize' command to enable access.  Below, you will find the commands to allow 'ping' and 'ssh' to your VMs::

    euca-authorize -P icmp -t -1:-1 default
    euca-authorize -P tcp -p 22 default

Another common issue is you cannot ping or SSH your instances after issusing the 'euca-authorize' commands.  Something to look at is the amount of 'dnsmasq' processes that are running.  If you have a running instance, check to see that TWO 'dnsmasq' processes are running.  If not, perform the following::

    killall dnsmasq
    service nova-network restart

To avoid issues with KVM and permissions with Nova, run the following commands to ensure we have VM's that are running optimally::

            chgrp kvm /dev/kvm
            chmod g+rwx /dev/kvm

If you want to use the 10.04 Ubuntu Enterprise Cloud images that are readily available at http://uec-images.ubuntu.com/releases/10.04/release/, you may run into delays with booting. Any server that does not have nova-api running on it needs this iptables entry so that UEC images can get metadata info. On compute nodes, configure the iptables with this next step::

    # iptables -t nat -A PREROUTING -d 169.254.169.254/32 -p tcp -m tcp --dport 80 -j DNAT --to-destination $NOVA_API_IP:8773

Testing the Installation
````````````````````````

You can confirm that your compute node is talking to your cloud controller. From the cloud controller, run this database query::

	mysql -u$MYSQL_USER -p$MYSQL_PASS nova -e 'select * from services;'

In return, you should see something similar to this::
            +---------------------+---------------------+------------+---------+----+----------+----------------+-----------+--------------+----------+-------------------+
            | created_at          | updated_at          | deleted_at | deleted | id | host     | binary         | topic     | report_count | disabled | availability_zone |
            +---------------------+---------------------+------------+---------+----+----------+----------------+-----------+--------------+----------+-------------------+
            | 2011-01-28 22:52:46 | 2011-02-03 06:55:48 | NULL       |       0 |  1 | osdemo02 | nova-network   | network   |        46064 |        0 | nova              |
            | 2011-01-28 22:52:48 | 2011-02-03 06:55:57 | NULL       |       0 |  2 | osdemo02 | nova-compute   | compute   |        46056 |        0 | nova              |
            | 2011-01-28 22:52:52 | 2011-02-03 06:55:50 | NULL       |       0 |  3 | osdemo02 | nova-scheduler | scheduler |        46065 |        0 | nova              |
            | 2011-01-29 23:49:29 | 2011-02-03 06:54:26 | NULL       |       0 |  4 | osdemo01 | nova-compute   | compute   |        37050 |        0 | nova              |
            | 2011-01-30 23:42:24 | 2011-02-03 06:55:44 | NULL       |       0 |  9 | osdemo04 | nova-compute   | compute   |        28484 |        0 | nova              |
            | 2011-01-30 21:27:28 | 2011-02-03 06:54:23 | NULL       |       0 |  8 | osdemo05 | nova-compute   | compute   |        29284 |        0 | nova              |
            +---------------------+---------------------+------------+---------+----+----------+----------------+-----------+--------------+----------+-------------------+
You can see that 'osdemo0{1,2,4,5} are all running 'nova-compute.' When you start spinning up instances, they will allocate on any node that is running nova-compute from this list.

You can then use `euca2ools` to test some items::

    euca-describe-images
    euca-describe-instances

If you have issues with the API key, you may need to re-source your creds file::

    . /root/creds/novarc

If you don’t get any immediate errors, you’re successfully making calls to your cloud!

Spinning up a VM for Testing
````````````````````````````

(This excerpt is from Thierry Carrez's blog, with reference to http://wiki.openstack.org/GettingImages.)

The image that you will use here will be a ttylinux image, so this is a limited function server. You will be able to ping and SSH to this instance, but it is in no way a full production VM.

UPDATE: Due to `bug 661159 <https://bugs.launchpad.net/nova/+bug/661159>`_, we can’t use images without ramdisks yet, so we can’t use the classic Ubuntu cloud images from http://uec-images.ubuntu.com/releases/ yet. For the sake of this tutorial, we’ll use the `ttylinux images from Scott Moser instead <http://smoser.brickies.net/ubuntu/ttylinux-uec/>`_.

Download the image, and publish to your bucket:

::

    image="ttylinux-uec-amd64-12.1_2.6.35-22_1.tar.gz"
    wget http://smoser.brickies.net/ubuntu/ttylinux-uec/$image
    uec-publish-tarball $image mybucket

This will output three references, an "emi", an "eri" and an "eki."  (Image, ramdisk, and kernel)  The emi is the one we use to launch instances, so take note of this.

Create a keypair to SSH to the server:

::

    euca-add-keypair mykey > mykey.priv

    chmod 0600 mykey.priv

Boot your instance:

::

    euca-run-instances $emi -k mykey -t m1.tiny

($emi is replaced with the output from the previous command)

Checking status, and confirming communication:

Once you have booted the instance, you can check the status the the `euca-describe-instances` command.  Here you can view the instance ID, IP, and current status of the VM.

::

    euca-describe-instances

Once in a "running" state, you can use your SSH key connect:

::

    ssh -i mykey.priv root@$ipaddress

When you are ready to terminate the instance, you may do so with the `euca-terminate-instances` command:

::

    euca-terminate-instances $instance-id

You can determine the instance-id with `euca-describe-instances`, and the format is "i-" with a series of letter and numbers following:  e.g. i-a4g9d.

For more information in creating you own custom (production ready) instance images, please visit http://wiki.openstack.org/GettingImages for more information!

Enjoy your new private cloud, and play responsibly!
