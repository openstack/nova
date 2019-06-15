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

=======================
Development Quickstart
=======================

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


.. note:: For how to contribute to Nova, see
          HowToContribute_.
          Nova uses the Gerrit code review system, GerritWorkflow_.

.. _GerritWorkflow: http://docs.openstack.org/infra/manual/developers.html#development-workflow
.. _HowToContribute: http://docs.openstack.org/infra/manual/developers.html
.. _`docs.openstack.org`: http://docs.openstack.org

Setup
=====

There are two ways to create a development environment: using
DevStack, or explicitly installing and cloning just what you need.


Using DevStack
--------------

See `Devstack`_ Documentation. If you would like to use Vagrant, there is a `Vagrant`_ for DevStack.

.. _`Devstack`: http://docs.openstack.org/developer/devstack/
.. _`Vagrant`: https://github.com/openstack-dev/devstack-vagrant/blob/master/README.md

..
    Until the vagrant markdown documents are rendered somewhere on .openstack.org, linking to github

Explicit Install/Clone
----------------------

DevStack installs a complete OpenStack environment.  Alternatively,
you can explicitly install and clone just what you need for Nova
development.

Getting the code
````````````````

Grab the code from git::

    git clone https://opendev.org/openstack/nova
    cd nova


Linux Systems
`````````````

The first step of this process is to install the system (not Python)
packages that are required. Following are instructions on how to do
this on Linux and on the Mac.

.. note::

  This section is tested for Nova on Ubuntu (14.04-64) and
  Fedora-based (RHEL 6.1) distributions. Feel free to add notes and
  change according to your experiences or operating system.

Install the prerequisite packages listed in the ``bindep.txt``
file.

On Debian-based distributions (e.g., Debian/Mint/Ubuntu)::

  sudo apt-get install python-pip
  sudo pip install tox
  tox -e bindep
  sudo apt-get install <indicated missing package names>

On Fedora-based distributions (e.g., Fedora/RHEL/CentOS/Scientific Linux)::

  sudo yum install python-pip
  sudo pip install tox
  tox -e bindep
  sudo yum install <indicated missing package names>

On openSUSE-based distributions (SLES, openSUSE Leap / Tumbleweed)::

  sudo zypper in python-pip
  sudo pip install tox
  tox -e bindep
  sudo zypper in <indicated missing package names>


Mac OS X Systems
````````````````

Install virtualenv::

    sudo easy_install virtualenv

Check the version of OpenSSL you have installed::

    openssl version

The stock version of OpenSSL that ships with Mac OS X 10.6 (OpenSSL 0.9.8l)
or Mac OS X 10.7 (OpenSSL 0.9.8r) or Mac OS X  10.10.3 (OpenSSL 0.9.8zc) works
fine with nova. OpenSSL versions from brew like OpenSSL 1.0.1k work fine
as well.

Brew is very useful for installing dependencies. As a minimum for running tests,
install the following::

    brew install python3 postgres
    python3 -mpip install tox


Building the Documentation
==========================

Install the prerequisite packages: graphviz

To do a full documentation build, issue the following command while
the nova directory is current.

.. code-block:: bash

  tox -edocs

That will create a Python virtual environment, install the needed
Python prerequisites in that environment, and build all the
documentation in that environment.

Running unit tests
==================

See `Running Python Unit Tests`_.

.. _`Running Python Unit Tests`: https://docs.openstack.org/project-team-guide/project-setup/python.html#running-python-unit-tests

Note that some unit and functional tests use a database. See the file
``tools/test-setup.sh`` on how the databases are set up in the
OpenStack CI environment and replicate it in your test environment.

Using the pre-commit hook
=========================

Nova makes use of the `pre-commit framework <https://pre-commit.com/>`__ to
allow running of some linters on each commit. This must be enabled locally to
function:

.. code-block:: shell

    $ pip install --user pre-commit
    $ pre-commit install --allow-missing-config

Using a remote debugger
=======================

Some modern IDE such as pycharm (commercial) or Eclipse (open source) support remote debugging.  In order to
run nova with remote debugging, start the nova process with the following parameters::

    --remote_debug-host <host IP where the debugger is running>
    --remote_debug-port <port it is listening on>

Before you start your nova process, start the remote debugger using the instructions for that debugger:

* For pycharm - http://blog.jetbrains.com/pycharm/2010/12/python-remote-debug-with-pycharm/
* For Eclipse - http://pydev.org/manual_adv_remote_debugger.html

More detailed instructions are located here - https://wiki.openstack.org/wiki/Nova/RemoteDebugging

Using fake computes for tests
=============================

The number of instances supported by fake computes is not limited by physical
constraints. It allows you to perform stress tests on a deployment with few
resources (typically a laptop). Take care to avoid using scheduler filters
that will limit the number of instances per compute, such as ``AggregateCoreFilter``.

Fake computes can also be used in multi hypervisor-type deployments in order to
take advantage of fake and "real" computes during tests:

* create many fake instances for stress tests
* create some "real" instances for functional tests

Fake computes can be used for testing Nova itself but also applications on top
of it.
