#!/bin/bash

# Copyright (c) 2010 OpenStack, LLC.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#    http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.

# See the License for the specific language governing permissions and
# limitations under the License.

# Written by Wayne A. Walls (dubsquared) with the amazing help of Jordan Rinke (JordanRinke), Vish Ishaya (vishy), 
# and a lot of input from the fine folks in #openstack on irc.freenode.net!

# Please contact script maintainers for questions, comments, or concerns:
# Wayne  ->  wayne@openstack.org
# Jordan ->  jordan@openstack.org

# This script is intended to be ran on a fresh install on Ubuntu 10.04 64-bit.  Once ran with 
# the appropriate variables, will produce a fully functioning Nova Cloud Controller.  I am working on 
# getting this working on all flavors of Ubuntu, and eventually RPM based distros.  Please feel free 
# to reach out to script maintainers for anything that can be done better.  I'm pretty new to this scripting business 
# so I'm sure there is room for improvement!

#Usage:  bash nova-CC-installer.sh

#This is a Linux check
if [ `uname -a | grep -i linux | wc -l` -lt 1 ]; then
echo "Not Linux, not compatible."
exit 1
fi

#Compatible OS Check
    DEB_OS=`cat /etc/issue | grep -i 'ubuntu'`
    RH_OS=`cat /etc/issue | grep -i 'centos'`
    if [[ ${#DEB_OS} -gt 0 ]] ; then
        echo "Valid OS, continuing..."
        CUR_OS="Ubuntu"
    elif [[ ${#RH_OS} -gt 0 ]] ; then
        echo "Unsupported OS, sorry!"
        CUR_OS="CentOS"
        exit 1
    else
     echo "Unsupported OS, sorry!"
        CUR_OS="Unknown"
        exit 1
    fi
    echo $CUR_OS detected! 
    
 #Set up log file for debugging
LOGFILE=/var/log/nova/nova-install.log
mkdir /var/log/nova
touch /var/log/nova/nova-install.log
    
echo "Nova Cloud Controller install script v1.0"
echo
echo "Setting up the Nova cloud controller is a multi-step process.  After you seed information, \
the script will take over and finish off the install for you.  Full log of commands will be available at \
/var/log/nova/nova-install.log"

read -p "Press any key to continue..." -n1 -s 
echo

#Setting up sanity check function
valid_ipv4(){
 newmember=$(echo $1 | egrep '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$');
 members=$(echo $newmember | tr "." "\n");
 memcount=$(echo $newmember | tr "." "\n" | wc -l);
 if [ $memcount -ne 4 ]; then
  echo "fail";
  exit;
 fi
 for i in $members; do
  if [ $i -lt 0 ] || [ $i -gt 255 ]; then
   echo "fail";
   exit;
  fi;
 done;
 echo "success";
}

#Enforcing root user to execute the script
USER=root
USER2=`whoami`

       if [ $USER != $USER2 ]; then
           echo "Please run this as the user, 'root'!"; exit 1
      else
           echo
fi

echo

echo
echo "Step 1: Setting up the database."
#mySQL only for now, will update to include others in next release


echo "mySQL User Config"
echo "#################"

#Setting up mySQL root password, and verify
while true; do                                                                                                                                      
       read -s -p "Desired mySQL Password:  " MYSQL_PASS
       echo "";
       read -s -p "Verify password: " MYSQL_PASS2
       echo "";

       if [ $MYSQL_PASS != $MYSQL_PASS2 ]
       then
               echo "Passwords do not match...try again.";
               continue;
       fi
       break;
done

cat <<MYSQL_PRESEED | debconf-set-selections
mysql-server-5.1 mysql-server/root_password password $MYSQL_PASS
mysql-server-5.1 mysql-server/root_password_again password $MYSQL_PASS
mysql-server-5.1 mysql-server/start_on_boot boolean true
MYSQL_PRESEED
echo 

echo "Step 2: Setting up the controller configuration." 
echo "This includes setting the S3 IP, RabbitMQ IP, Cloud Controller IP, and mySQL host IP"

echo "Nova Cloud Controller Configuration"
echo "###################################"
sleep 1

#Configuring S3 Host IP
set -o nounset
echo

debug=":"
debug="echo"

echo

#Grabs the first real IP of ifconfig, and set it as the default entry
default=`/sbin/ifconfig -a | egrep '.*inet ' | head -n 1|perl -pe 's/.*addr:(.+).*Bcast.*/$1/g' | tr -d " "`

while true; do
read -p "S3 Host IP (Default is $default -- ENTER to accept):" -e t1
if [ -n "$t1" ]
then
  S3_HOST_IP="$t1"
else
  S3_HOST_IP="$default"
fi
if [ $(valid_ipv4 $S3_HOST_IP) == "fail" ]; then
    echo "You have entered an invalid IP address, please try again."
   continue
fi
break;
done;

echo
echo " S3 Host IP set as \"$S3_HOST_IP\""

#Configuring RabbitMQ IP
set -o nounset
echo

debug=":"
debug="echo"

echo

#default=`/sbin/ifconfig -a | egrep '.*inet ' | head -n 1|perl -pe 's/.*addr:(.+).*Bcast.*/$1/g' | tr -d " "`
while true; do
read -p "RabbitMQ Host IP (Default is $default -- ENTER to accept): " -e t1
if [ -n "$t1" ]
then
  RABBIT_IP="$t1"
else
  RABBIT_IP="$default"
fi

if [ $(valid_ipv4 $RABBIT_IP) == "fail" ]; then
    echo "You have entered an invalid IP address, please try again."
    continue
fi
break;
done;

echo
echo " RabbitMQ Host IP set as \"$RABBIT_IP\""

echo "There is an issue bypassing the rabbit package splash screen, so installing here and allowing you to proceed.   There is currently no \
way to background/preseed this, so it will output to terminal..."

echo
sleep 5
apt-get -y install rabbitmq-server 
echo

#Configuring Cloud Controller Host IP
set -o nounset
echo

debug=":"
debug="echo"

echo

#default=`/sbin/ifconfig -a | egrep '.*inet ' | head -n 1|perl -pe 's/.*addr:(.+).*Bcast.*/$1/g' | tr -d " "`
while true; do
read -p "Cloud Controller Host IP (Default is $default -- ENTER to accept): " -e t1
if [ -n "$t1" ]
then
  CC_HOST_IP="$t1"
else
  CC_HOST_IP="$default"
fi

if [ $(valid_ipv4 $CC_HOST_IP) == "fail" ]; then
    echo "You have entered an invalid IP address, please try again."
    continue
fi
break;
done;

echo
echo " Cloud Controller Host IP set as \"$CC_HOST_IP\""

#Configuring mySQL Host IP
set -o nounset
echo

debug=":"
debug="echo"


echo

#default=`/sbin/ifconfig -a | egrep '.*inet ' | head -n 1|perl -pe 's/.*addr:(.+).*Bcast.*/$1/g' | tr -d " "`
while true; do
read -p "mySQL Host IP (Default is $default -- ENTER to accept): " -e t1
if [ -n "$t1" ]
then
  MYSQL_HOST_IP="$t1"
else
  MYSQL_HOST_IP="$default"
fi

if [ $(valid_ipv4 $MYSQL_HOST_IP) == "fail" ]; then
    echo "You have entered an invalid IP address, please try again."
    continue
fi
break;
done;

echo
echo "mySQL Host IP set as \"$MYSQL_HOST_IP\""

echo 

echo "Step 3:  Building the network for your controller."

echo "Here you will set the network range that ALL your projects will reside in.  This is typically \
a large block such as a /12.  You will also choose how many IPs in this block are availible for use."

echo

echo "Nova Network Setup"
echo "##################"

echo

#Set network range and sanity check

while true; do
read -p "Controller network range for ALL projects (normally x.x.x.x/12):" FIXED_RANGE
IP=$(echo $FIXED_RANGE | awk -F/ '{print $1}');
CIDR=$(echo $FIXED_RANGE | awk -F/ '{print $2}' | perl -pe 'if(!($_>=1 && $_<=32)){undef $_;}');
if [ $(valid_ipv4 $IP) == "fail" ] || [ -z "$CIDR" ]
then
 echo "You failed at entering a correct range, try again"
 continue
fi;

break;
done;

while true; do
read -p "Total amount of usable IPs for ALL projects:" NETWORK_SIZE
if [ ! "$( echo $NETWORK_SIZE | egrep '^[0-9]{1,9}$' )" ];
then echo "Not a valid entry, please try again"
continue
fi
break;
done;

echo

echo "Step 4:  Creating a project for Nova"

echo "You will choose an admin for the project, and also name the project here. \
Also, you will build out the network configuration for the project."
sleep 1
echo

read -p "Nova project user name:" NOVA_PROJECT_USER
read -p "Nova project name:" NOVA_PROJECT

while true; do
read -p "Desired network + CIDR for project (normally x.x.x.x/24):" PROJECT_CIDR
  if [ ! "$( echo $PROJECT_CIDR | egrep '^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\/[0-9]{1,2}$' )" ];
        then echo "You failed at entering a correct range, try again"
    continue
fi
break;
done;

while true; do
read -p "How many networks for project:" NOVA_NETWORK_NUMBER
if [ ! "$( echo $NOVA_NETWORK_NUMBER | egrep '^[0-9]{1,3}$' )" ];
then echo "You have not entered a valid network number, try again"
continue
fi
break;
done;

while true; do
read -p "How many available IPs per project network:" IPS_PER_NETWORK
if [ ! "$( echo $IPS_PER_NETWORK | egrep '^[0-9]{1,9}$' )" ];
then echo "You have not entered amount of IPs"
continue
fi
break;
done;

echo

echo "At this point, you've entered all the information needed to finish deployment of your controller!"
echo "Feel free to get some coffee, you have earned it!"
sleep 5

echo

echo "Entering auto-pilot mode..."
sleep 2

echo

#Package installation function, and sanity check

echo "Installing packages"
echo "###################"

install_package() {
  for packages in $@
  do
   printf "%-40s" "Installing package '$packages' ... "
   if dpkg -l | egrep "^ii.* $packages " &>> $LOGFILE
   then
    echo "Already installed";
    continue;
   fi
   apt-get install -y $packages &>> $LOGFILE
   if dpkg -l | egrep "^ii.* $packages " &>> $LOGFILE
   then
    echo "ok";
   else
    echo "Failed";
    #exit -1
   fi
  done
#  return 0;
}

REQUIRED_PACKAGES="python-software-properties"
install_package ${REQUIRED_PACKAGES}
add-apt-repository ppa:nova-core/ppa &>> $LOGFILE
add-apt-repository ppa:nova-core/trunk &>> $LOGFILE
apt-get update &>> $LOGFILE
REQUIRED_PACKAGES="mysql-server bzr nova-common nova-doc nova-api nova-network nova-objectstore nova-scheduler nova-compute unzip vim euca2ools dnsmasq open-iscsi kpartx gawk iptables ebtables user-mode-linux kvm libvirt-bin screen iscsitarget vlan curl python-twisted python-sqlalchemy python-mox python-greenlet python-carrot python-daemon python-eventlet python-gflags python-libvirt python-libxml2 python-routes python-mysqldb python-greenlet python-nova"
#REQUIRED_PACKAGES="mysql-server bzr nova-common nova-doc python-mysqldb python-greenlet python-nova nova-api nova-network nova-objectstore nova-scheduler nova-compute unzip vim euca2ools dnsmasq open-iscsi kpartx kvm gawk iptables ebtables user-mode-linux kvm libvirt-bin screen iscsitarget euca2ools vlan curl python-twisted python-sqlalchemy python-mox python-greenlet python-carrot python-daemon python-eventlet python-gflags python-libvirt python-libxml2 python-routes"
install_package ${REQUIRED_PACKAGES}

echo "Finalizing mySQL setup"
echo "######################"

sed -i 's/127.0.0.1/0.0.0.0/g' /etc/mysql/my.cnf
service mysql restart &>> $LOGFILE

mysql -uroot -p$MYSQL_PASS -e "CREATE DATABASE nova;"
mysql -uroot -p$MYSQL_PASS -e "GRANT ALL PRIVILEGES ON *.* TO 'root'@'%' WITH GRANT OPTION;"
mysql -uroot -p$MYSQL_PASS -e "SET PASSWORD FOR 'root'@'%' = PASSWORD('$MYSQL_PASS');"
echo "...done..."

echo "Setting up Nova configuration files"
echo "###################################"
sleep 1

# Passing info into config files  
cat >> /etc/nova/nova.conf << NOVA_CONF_EOF
--s3_host=$S3_HOST_IP
--rabbit_host=$RABBIT_IP
--cc_host=$CC_HOST_IP
--ec2_url=http://$S3_HOST_IP:8773/services/Cloud
--fixed_range=$FIXED_RANGE
--network_size=$NETWORK_SIZE
--FAKE_subdomain=ec2
--routing_source_ip=$CC_HOST_IP
--verbose
--sql_connection=mysql://root:$MYSQL_PASS@$MYSQL_HOST_IP/nova
NOVA_CONF_EOF

/usr/bin/python /usr/bin/nova-manage user admin $NOVA_PROJECT_USER &>> $LOGFILE
/usr/bin/python /usr/bin/nova-manage project create $NOVA_PROJECT $NOVA_PROJECT_USER &>> $LOGFILE
/usr/bin/python /usr/bin/nova-manage network create $PROJECT_CIDR $NOVA_NETWORK_NUMBER $IPS_PER_NETWORK &>> $LOGFILE
echo "...done..."


echo "Generating Nova credentials"
echo "###########################"

mkdir -p /root/creds
/usr/bin/python /usr/bin/nova-manage project zipfile $NOVA_PROJECT $NOVA_PROJECT_USER /root/creds/novacreds.zip &>> $LOGFILE
sleep 3
unzip -d /root/creds /root/creds/novacreds.zip &>> $LOGFILE
. /root/creds/novarc
cat /root/creds/novarc >> ~/.bashrc
sed -i.bak "s/127.0.0.1/$CC_HOST_IP/g" /root/creds/novarc
echo "...done..."

######
####This is where the bridge info will go for other network managers
######

echo "#################NOTE#####NOTE#####NOTE#####NOTE#####NOTE#####NOTE#################"
echo "#Be sure to source your credential file into your environment after config changes#"
echo "###########################e.g. source /root/creds/novarc##########################"
sleep 1


#Sourcing creds file and restarting all Nova services
. /root/creds/novarc
sleep 1
restart libvirt-bin &>> $LOGFILE; service nova-api restart &>> $LOGFILE; service nova-scheduler restart &>> $LOGFILE; service nova-network restart &>> $LOGFILE; service nova-objectstore restart &>> $LOGFILE; service nova-compute restart &>> $LOGFILE

echo "Ensure all five Nova services are running"
echo "#########################################"
ps aux | grep -i nova
sleep 5

echo "Setup default ICMP and SSH access to your future VMs"
echo "####################################################"

echo "Allowing ping and SSH to your running instances"
euca-authorize -P icmp -t -1:-1 default &>> $LOGFILE
euca-authorize -P tcp -p 22 default &>> $LOGFILE
echo "...done..."

echo "######################################################################"
echo "#You /MUST/ re-source your 'novarc' to use the API commands since the#" 
echo "##script cannot pass the source information out of it's own process###"
echo "######################################################################"

#Only one dnsmasq process starts, supposed to two running at different priorities.  This fixes that...possible bug.
killall dnsmasq
service nova-network restart &>> $LOGFILE

#Needed for KVM to initialize, VMs run in qemu mode otherwise and is very slow
chgrp kvm /dev/kvm
chmod g+rwx /dev/kvm
echo
echo 'The next thing you are going to want to do it get a VM to test with.  You can find a test VM how-to, and read more about custom image creation at "http://nova.openstack.org/adminguide/multi.node.install.html" and "http://wiki.openstack.org/GettingImages'
echo
echo 'Enjoy your new private cloud!'

#If you run into any problems, please feel free to contact the script maintainers. 
#You can also get assistance by stopping by irc.freenode.net - #openstack, sending a message to the OpenStack Users maillist - openstack@lists.launchpad.net, or posting at "https://answers.launchpad.net/openstack"
