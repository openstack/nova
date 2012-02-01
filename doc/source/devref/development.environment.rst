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

This page describes how to setup a working Python development environment that
can be used in developing nova on Ubuntu, Fedora or Mac OS X. These
instructions assume you're already familiar with git. Refer to
http://wiki.openstack.org/GettingTheCode for additional information.

Following these instructions will allow you to run the nova unit tests. If you
want to be able to run nova (i.e., launch VM instances), you will also need to
install libvirt and at least one of the `supported
hypervisors`<http://wiki.openstack.org/HypervisorSupportMatrix>_. Running
nova is currently only supported on Linux, although you can run
the unit tests on Mac OS X. See :doc:`quickstart` for how to get a working
version of OpenStack Compute running as quickly as possible.

Virtual environments
--------------------

Nova development uses `virtualenv <http://pypi.python.org/pypi/virtualenv>`_
to track and manage Python dependencies while in development and testing. This
allows you to install all of the Python package dependencies in a virtual
environment or `virtualenv` (a special subdirectory of your nova directory),
instead of installing the packages at the system level.

Virtualenv is useful for running the unit tests, but is not typically used
for full integration testing or production usage.

Linux Systems
-------------

Note: This section is tested for Nova on Ubuntu (10.10-64) and
Fedora-based (RHEL 6.1) distributions. Feel free to add notes and change
according to your experiences or operating system.

Install the prerequisite packages.

On Ubuntu::

  sudo apt-get install python-dev libssl-dev python-pip git-core

On Fedora-based distributions (e.g., Fedora/RHEL/CentOS/Scientific Linux)::

  sudo yum install python-devel openssl-devel python-pip git


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
``tools/pip-requires`` file into your virtualenv. There will also be some
additional packages (pip, distribute, greenlet) that are installed
by the ``tools/install_venv.py`` file into the virutalenv.

If all goes well, you should get a message something like this::

  Nova development environment setup is complete.

To activate the Nova virtualenv for the extent of your current shell session
you can run::

     $ source .venv/bin/activate

Or, if you prefer, you can run commands in the virtualenv on a case by case
basis by running::

     $ tools/with_venv.sh <your command>

Contributing Your Work
----------------------

Once your work is complete you may wish to contribute it to the project.  Add
your name and email address to the `Authors` file, and also to the `.mailmap`
file if you use multiple email addresses. Your contributions can not be merged
into trunk unless you are listed in the Authors file. Nova uses the Gerrit
code review system. For information on how to submit your branch to Gerrit,
see http://wiki.openstack.org/GerritWorkflow
