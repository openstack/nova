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

==============================================
Setting Up and Using a Development Environment
==============================================

This page describes how to setup and use a working Python development
environment that can be used in developing nova on Ubuntu, Fedora or
Mac OS X. These instructions assume you're already familiar with git.

Following these instructions will allow you to build the documentation
and run the nova unit tests. If you want to be able to run nova (i.e.,
launch VM instances), you will also need to --- either manually or by
letting DevStack do it for you --- install libvirt and at least one of
the `supported hypervisors`_. Running nova is currently only supported
on Linux, although you can run the unit tests on Mac OS X.

.. _supported hypervisors: http://wiki.openstack.org/HypervisorSupportMatrix


Setup
=====

There are two ways to create a development environment: using
DevStack, or explicitly installing and cloning just what you need.


Using DevStack
--------------

The easiest way to build a fully functional development environment is
with DevStack. DevStack will hack your machine pretty hard, and so we
recommend that you create a machine (such as a VM or Vagrant box)
running a distribution supported by DevStack and run DevStack
there. For example, there is a Vagrant script for DevStack at
http://git.openstack.org/cgit/openstack-dev/devstack-vagrant/ .

Include the line

.. code-block:: bash

  INSTALL_TESTONLY_PACKAGES=True

in the ``localrc`` file you use to control DevStack.  This will cause
DevStack to install what you need for testing and documentation
building as well as running the system.

Explicit Install/Clone
----------------------

DevStack installs a complete OpenStack environment.  Alternatively,
you can explicitly install and clone just what you need for Nova
development.

The first step of this process is to install the system (not Python)
packages that are required.  Following are instructions on how to do
this on Linux and on the Mac.

Linux Systems
`````````````

.. note::

  This section is tested for Nova on Ubuntu (14.04-64) and
  Fedora-based (RHEL 6.1) distributions. Feel free to add notes and
  change according to your experiences or operating system.

Install the prerequisite packages.

On Ubuntu::

  sudo apt-get install python-dev libssl-dev python-pip git-core libxml2-dev libxslt-dev pkg-config libffi-dev libpq-dev libmysqlclient-dev libvirt-dev graphviz libsqlite3-dev python-tox

On Ubuntu Precise (12.04) you may also need to add the following packages::

  sudo apt-get build-dep python-mysqldb
  # enable cloud-archive to get the latest libvirt
  sudo apt-get install python-software-properties
  sudo add-apt-repository cloud-archive:icehouse
  sudo apt-get install libvirt-dev

On Fedora-based distributions (e.g., Fedora/RHEL/CentOS/Scientific Linux)::

  sudo yum install python-devel openssl-devel python-pip git gcc libxslt-devel mysql-devel postgresql-devel libffi-devel libvirt-devel graphviz sqlite-devel
  sudo pip-python install tox

On openSUSE-based distributions (SLES 12, openSUSE 13.1, Factory or Tumbleweed)::

  sudo zypper in gcc git libffi-devel libmysqlclient-devel libvirt-devel libxslt-devel postgresql-devel python-devel python-pip python-tox python-virtualenv


Mac OS X Systems
````````````````

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
````````````````

Once you have the prerequisite system packages installed, the next
step is to clone the code.

Grab the code from git::

    git clone https://git.openstack.org/openstack/nova
    cd nova


Building the Documentation
==========================

To do a full documentation build, issue the following command while
the nova directory is current.

.. code-block:: bash

  tox -edocs

That will create a Python virtual environment, install the needed
Python prerequisites in that environment, and build all the
documentation in that environment.

The following variant will do the first two steps but not build any
documentation.

.. code-block:: bash

  tox --notest -edocs

The virtual environment built by ``tox`` for documentation building
will be found in ``.tox/docs``.  You can enter that virtual
environment in the usual way, as follows.

.. code-block:: bash

  source .tox/docs/bin/activate

To build just the man pages, enter that virtual environment and issue
the following command while the nova directory is current.

.. code-block:: bash

  python setup.py build_sphinx -b man

After building the man pages, they can be found in ``doc/build/man/``.
A sufficiently authorized user can install the man page onto the
system by following steps like the following, which are for the
``nova-scheduler`` man page.

.. code-block:: bash

  mkdir /usr/local/man/man1
  install -g 0 -o 0 -m 0644 doc/build/man/nova-scheduler.1  /usr/local/man/man1/nova-scheduler.1
  gzip /usr/local/man/man1/nova-scheduler.1
  man nova-scheduler


Running unit tests
==================

See :doc:`unit_tests` for details.


Using a remote debugger
=======================

Some modern IDE such as pycharm (commercial) or Eclipse (open source) support remote debugging.  In order to run nova with remote debugging, start the nova process
with the following parameters
--remote_debug-host <host IP where the debugger is running>
--remote_debug-port <port it is listening on>

Before you start your nova process, start the remote debugger using the instructions for that debugger.
For pycharm - http://blog.jetbrains.com/pycharm/2010/12/python-remote-debug-with-pycharm/
For Eclipse - http://pydev.org/manual_adv_remote_debugger.html

More detailed instructions are located here - http://novaremotedebug.blogspot.com

Using fake computes for tests
=============================

The number of instances supported by fake computes is not limited by physical
constraints. It allows you to perform stress tests on a deployment with few
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
======================

Once your work is complete you may wish to contribute it to the project.
Refer to HowToContribute_ for information.
Nova uses the Gerrit code review system. For information on how to submit
your branch to Gerrit, see GerritWorkflow_.

.. _GerritWorkflow: http://docs.openstack.org/infra/manual/developers.html#development-workflow
.. _HowToContribute: http://docs.openstack.org/infra/manual/developers.html
