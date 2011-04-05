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

Nova Quickstart
===============

.. todo:: 
    P1 (this is one example of how to use priority syntax)
    * Document the assumptions about pluggable interfaces (sqlite3 instead of
      mysql, etc) (todd)
    * Document env vars that can change things (USE_MYSQL, HOST_IP) (todd)

Recommended System Configuration
--------------------------------

Although Nova can be run on a variety of system architectures, for most users the following will be simplest:

* Ubuntu Lucid
* 10GB Hard Disk Space
* 512MB RAM

For development, Nova can run from within a VM.


Getting the Code
----------------

Nova is hosted on launchpad.  You can get the code with the following command

::

    bzr clone lp:nova

The `contrib/nova.sh` file in the source distribution is a script that
will quickly set up nova to run on a single machine.  It is tested against
Ubuntu only, but other distributions are forthcoming.

Environment Variables
---------------------

By tweaking the environment that nova.sh run in, you can build slightly
different configurations (though for more complex setups you should see
`Installing and Configuring OpenStack Compute <http://docs.openstack.org/openstack-compute/admin/content/ch03.html>`_).

* HOST_IP
    * Default: address of first interface from the ifconfig command
    * Values: 127.0.0.1, or any other valid address
* TEST
    * Default: 0
    * Values: 1, run tests after checkout and initial setup
* USE_MYSQL
    * Default: 0, use sqlite3
    * Values: 1, use mysql instead of sqlite3
* MYSQL_PASS (Only useful if $USE_MYSQL=1)
    * Default: nova
    * Values: value of root password for mysql
* USE_LDAP
    * Default: 0, use :mod:`nova.auth.dbdriver`
    * Values: 1, use :mod:`nova.auth.ldapdriver`
* LIBVIRT_TYPE
    * Default: qemu
    * Values: uml, kvm

Usage
-----

Unless you want to spend a lot of time fiddling with permissions and sudoers,
you should probably run nova as root.

::

    sudo -i

If you are concerned about security, nova runs just fine inside a virtual
machine.

Use the script to install and run the current trunk. You can also specify a
specific branch by putting `lp:~someone/nova/some-branch` after the branch
command

::

    ./nova.sh branch
    ./nova.sh install
    ./nova.sh run

The run command will drop you into a screen session with all of the workers
running in different windows  You can use eucatools to run commands against the
cloud.

::

    euca-add-keypair test > test.pem
    euca-run-instances -k test -t m1.tiny ami-tiny
    euca-describe-instances

To see output from the various workers, switch screen windows

::

    <ctrl-a> "

will give you a list of running windows.

When the instance is running, you should be able to ssh to it.

::

    chmod 600 test.pem
    ssh -i test.pem root@10.0.0.3

When you exit screen

::

    <ctrl-a> <ctrl-d>

nova will terminate.  It may take a while for nova to finish cleaning up.  If
you exit the process before it is done because there were some problems in your
build, you may have to clean up the nova processes manually.  If you had any
instances running, you can attempt to kill them through the api:

::

    ./nova.sh terminate

Then you can destroy the screen:

::

    ./nova.sh clean

If things get particularly messed up, you might need to do some more intense
cleanup.  Be careful, the following command will manually destroy all runnning
virsh instances and attempt to delete all vlans and bridges.

:: 

	./nova.sh scrub

You can edit files in the install directory or do a bzr pull to pick up new versions. You only need to do

::

	./nova.sh run

to run nova after the first install. The database should be cleaned up on each run.