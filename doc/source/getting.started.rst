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

Optional servers

* OpenLDAP: By default, the auth server uses the RDBMS-backed datastore by setting FLAGS.auth_driver to 'nova.auth.dbdriver.DbDriver'. But OpenLDAP (or LDAP) could be configured by specifying 'nova.auth.ldapdriver.LdapDriver'.  There is a script in the sources(nova/auth/slap.sh) to install a very basic openldap server on ubuntu.
* ReDIS: There is a fake ldap driver that backends to redis. This was created for testing ldap implementation on systems that don't have an easy means to install ldap.

Python libraries that we use (from pip-requires):

.. literalinclude:: ../../tools/pip-requires

Other libraries:

* XenAPI: Needed only for Xen Cloud Platform or XenServer support. Available from http://wiki.xensource.com/xenwiki/XCP_SDK or http://community.citrix.com/cdn/xs/sdks.

External unix tools that are required:

* iptables
* ebtables
* gawk
* curl
* kvm
* libvirt
* dnsmasq
* vlan
* open-iscsi and iscsitarget (if you use iscsi volumes)
* aoetools and vblade-persist (if you use aoe-volumes)

Nova uses cutting-edge versions of many packages. There are ubuntu packages in the nova-core ppa.  You can use add this ppa to your sources list on an ubuntu machine with the following commands::

  sudo apt-get install -y python-software-properties
  sudo add-apt-repository ppa:nova-core/ppa

Recommended
-----------

* euca2ools: python implementation of aws ec2-tools and ami tools
* build tornado to use C module for evented section


Installation
--------------

Due to many changes it's best to rely on the `OpenStack wiki <http://wiki.openstack.org>`_ for installation instructions.

Configuration
---------------

These instructions are incomplete, but we are actively updating the `OpenStack wiki <http://wiki.openstack.org>`_ with more configuration information.

On the volume node

* Create a volume group (you can use an actual disk for the volume group as well)

::

    # This creates a 1GB file to create volumes out of
    dd if=/dev/zero of=MY_FILE_PATH bs=100M count=10
    losetup --show -f MY_FILE_PATH
    # replace /dev/loop0 below with whatever losetup returns
    vgcreate nova-volumes /dev/loop0

Running
---------

Launch servers

* rabbitmq
* redis (optional)

Launch nova components

* nova-api
* nova-compute
* nova-objectstore
* nova-volume
* nova-scheduler
