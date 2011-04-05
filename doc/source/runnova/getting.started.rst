..
      Copyright 2010-2011 United States Government as represented by the
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

This code base is continually changing, so dependencies also change.  If you
encounter any problems, see the :doc:`../community` page.
The `contrib/nova.sh` script should be kept up to date, and may be a good
resource to review when debugging.

The purpose of this document is to get a system installed that you can use to
test your setup assumptions.  Working from this base installtion you can
tweak configurations and work with different flags to monitor interaction with
your hardware, network, and other factors that will allow you to determine
suitability for your deployment.  After following this setup method, you should
be able to experiment with different managers, drivers, and flags to get the
best performance.

Dependencies
------------

Related servers we rely on

* **RabbitMQ**: messaging queue, used for all communication between components

Optional servers

* **OpenLDAP**: By default, the auth server uses the RDBMS-backed datastore by
  setting FLAGS.auth_driver to `nova.auth.dbdriver.DbDriver`. But OpenLDAP
  (or LDAP) could be configured by specifying `nova.auth.ldapdriver.LdapDriver`.
  There is a script in the sources (`nova/auth/slap.sh`) to install a very basic
  openldap server on ubuntu.
* **ReDIS**: There is a fake ldap auth driver
  `nova.auth.ldapdriver.FakeLdapDriver` that backends to redis. This was
  created for testing ldap implementation on systems that don't have an easy
  means to install ldap.
* **MySQL**: Either MySQL or another database supported by sqlalchemy needs to
  be avilable.  Currently, only sqlite3 an mysql have been tested.

Python libraries that we use (from pip-requires):

.. literalinclude:: ../../../tools/pip-requires

Other libraries:

* **XenAPI**: Needed only for Xen Cloud Platform or XenServer support. Available
  from http://wiki.xensource.com/xenwiki/XCP_SDK or
  http://community.citrix.com/cdn/xs/sdks.

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

Nova uses cutting-edge versions of many packages. There are ubuntu packages in
the nova-core trunk ppa.  You can use add this ppa to your sources list on an
ubuntu machine with the following commands::

  sudo apt-get install -y python-software-properties
  sudo add-apt-repository ppa:nova-core/trunk

Recommended
-----------

* euca2ools: python implementation of aws ec2-tools and ami tools
* build tornado to use C module for evented section


Installation
--------------

You can install from packages for your particular Linux distribution if they are
available.  Otherwise you can install from source by checking out the source
files from the `Nova Source Code Repository <http://code.launchpad.net/nova>`_
and running::

    python setup.py install

Configuration
---------------

Configuring the host system
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Nova can be configured in many different ways. In this "Getting Started with Nova" document, we only provide what you need to get started as quickly as possible. For a more detailed description of system
configuration, start reading through `Installing and Configuring OpenStack Compute <http://docs.openstack.org/openstack-compute/admin/content/ch03.html>`_.

`Detailed instructions for creating a volume group are available <http://docs.openstack.org/openstack-compute/admin/content/ch05s07.html>`_, or use these quick instructions. 

* Create a volume group (you can use an actual disk for the volume group as
  well)::

    # This creates a 1GB file to create volumes out of
    dd if=/dev/zero of=MY_FILE_PATH bs=100M count=10
    losetup --show -f MY_FILE_PATH
    # replace /dev/loop0 below with whatever losetup returns
    # nova-volumes is the default for the --volume_group flag
    vgcreate nova-volumes /dev/loop0


Configuring Nova
~~~~~~~~~~~~~~~~

Configuration of the entire system is performed through python-gflags.  The
best way to track configuration is through the use of a flagfile.

A flagfile is specified with the ``--flagfile=FILEPATH`` argument to the binary
when you launch it.  Flagfiles for nova are typically stored in
``/etc/nova/nova.conf``, and flags specific to a certain program are stored in
``/etc/nova/nova-COMMAND.conf``.  Each configuration file can include another
flagfile, so typically a file like ``nova-manage.conf`` would have as its first
line ``--flagfile=/etc/nova/nova.conf`` to load the common flags before
specifying overrides or additional options.

To get a current comprehensive list of flag file options, run bin/nova-<servicename> --help, or refer to a static list at `Reference for Flags in nova.conf <http://docs.openstack.org/openstack-compute/admin/content/ch05s08.html>`_.

A sample configuration to test the system follows::

    --verbose
    --nodaemon
    --auth_driver=nova.auth.dbdriver.DbDriver

Running
-------

There are many parts to the nova system, each with a specific function.  They
are built to be highly-available, so there are may configurations they can be
run in (ie: on many machines, many listeners per machine, etc).  This part
of the guide only gets you started quickly, to learn about HA options, see
`Installing and Configuring OpenStack Compute <http://docs.openstack.org/openstack-compute/admin/content/ch03.html>`_.

Launch supporting services

* rabbitmq
* redis (optional)
* mysql (optional)
* openldap (optional)

Launch nova components, each should have ``--flagfile=/etc/nova/nova.conf``

* nova-api
* nova-compute
* nova-objectstore
* nova-volume
* nova-scheduler
