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

Setting Up a Development Environment
====================================

This page describes how to setup a working Python development
environment that can be used in developing nova on Ubuntu, Fedora or
Mac OS X. These instructions assume you're already familiar with
git.

Following these instructions will allow you to run the nova unit
tests. If you want to be able to run nova (i.e., launch VM instances),
you will also need to install libvirt and at least one of the
`supported hypervisors`_. Running nova is currently only supported on
Linux, although you can run the unit tests on Mac OS X.

.. _supported hypervisors: http://wiki.openstack.org/HypervisorSupportMatrix

Virtual environments
--------------------

Nova development uses a set of shell scripts in DevStack. Virtual
environments with venv are also available with the source code.

The easiest way to build a fully functional development environment is
with DevStack. Create a machine (such as a VM or Vagrant box) running a
distribution supported by DevStack and install DevStack there. For
example, there is a Vagrant script for DevStack at https://github.com/jogo/DevstackUp.

 .. note::

    If you prefer not to use devstack, you can still check out source code on your local
    machine and develop from there.

Linux Systems
-------------

.. note::

  This section is tested for Nova on Ubuntu (10.10-64) and
  Fedora-based (RHEL 6.1) distributions. Feel free to add notes and
  change according to your experiences or operating system.

Install the prerequisite packages.

On Ubuntu::

  sudo apt-get install python-dev libssl-dev python-pip git-core libxml2-dev libxslt-dev pkg-config libffi-dev

On Ubuntu Precise (12.04) you may also need to add the following packages::

  sudo apt-get build-dep python-mysqldb

On Fedora-based distributions (e.g., Fedora/RHEL/CentOS/Scientific Linux)::

  sudo yum install python-devel openssl-devel python-pip git gcc libxslt-devel mysql-devel python-pip postgresql-devel libffi-devel
  sudo pip-python install tox


Mac OS X Systems
----------------

Install virtualenv::

    sudo easy_install virtualenv

Check the version of OpenSSL you have installed::

    openssl version

If you have installed OpenSSL 1.0.0a, which can happen when installing a
MacPorts package for OpenSSL, you will see an error when running
``nova.tests.auth_unittest.AuthTestCase.test_209_can_generate_x509``.

The stock version of OpenSSL that ships with Mac OS X 10.6 (OpenSSL 0.9.8l)
or Mac OS X 10.7 (OpenSSL 0.9.8r) works fine with nova.


Getting the code
----------------
Grab the code from GitHub::

    git clone https://github.com/openstack/nova.git
    cd nova


Running unit tests
------------------
The unit tests will run by default inside a virtualenv in the ``.venv``
directory. Run the unit tests by doing::

    ./run_tests.sh

The first time you run them, you will be asked if you want to create a virtual
environment (hit "y")::

    No virtual environment found...create one? (Y/n)

See :doc:`unit_tests` for more details.

.. _virtualenv:

Manually installing and using the virtualenv
--------------------------------------------

You can manually install the virtual environment instead of having
``run_tests.sh`` do it for you::

  python tools/install_venv.py

This will install all of the Python packages listed in the
``requirements.txt`` file into your virtualenv. There will also be some
additional packages (pip, setuptools, greenlet) that are installed
by the ``tools/install_venv.py`` file into the virutalenv.

If all goes well, you should get a message something like this::

  Nova development environment setup is complete.

To activate the Nova virtualenv for the extent of your current shell session
you can run::

     $ source .venv/bin/activate

Or, if you prefer, you can run commands in the virtualenv on a case by case
basis by running::

     $ tools/with_venv.sh <your command>

Using a remote debugger
-----------------------

Some modern IDE such as pycharm (commercial) or Eclipse (open source) support remote debugging.  In order to run nova with remote debugging, start the nova process
with the following parameters
--remote_debug-host <host IP where the debugger is running>
--remote_debug-port <port it is listening on>

Before you start your nova process, start the remote debugger using the instructions for that debugger.
For pycharm - http://blog.jetbrains.com/pycharm/2010/12/python-remote-debug-with-pycharm/
For Eclipse - http://pydev.org/manual_adv_remote_debugger.html

More detailed instructions are located here - http://novaremotedebug.blogspot.com

Using fake computes for tests
-----------------------------

The number of instances supported by fake computes is not limited by physical
constraints. It allows to perform stress tests on a deployment with few
resources (typically a laptop). But you must avoid using scheduler filters
limiting the number of instances per compute (like RamFilter, DiskFilter,
AggregateCoreFilter), otherwise they will limit the number of instances per
compute.


Fake computes can also be used in multi hypervisor-type deployments in order to
take advantage of fake and "real" computes during tests:

* create many fake instances for stress tests
* create some "real" instances for functional tests

Fake computes can be used for testing Nova itself but also applications on top
of it.

Contributing Your Work
----------------------

Once your work is complete you may wish to contribute it to the project. 
Refer to HowToContribute_ for information.
Nova uses the Gerrit code review system. For information on how to submit
your branch to Gerrit, see GerritWorkflow_.

.. _GerritWorkflow: http://wiki.openstack.org/GerritWorkflow
.. _HowToContribute: http://wiki.openstack.org/HowToContribute
