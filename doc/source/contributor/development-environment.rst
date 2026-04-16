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
macOS. These instructions assume you're already familiar with git.

Following these instructions will allow you to build the documentation
and run the nova unit tests. If you want to be able to run nova (i.e.,
launch VM instances), you will also need to --- either manually or by
letting DevStack do it for you --- install libvirt and at least one of
the supported hypervisors indicated in :doc:`/user/support-matrix`.
Running nova is currently only supported on Linux, although you can run the
unit tests on macOS

.. note::

    For how to contribute to Nova, see HowToContribute_. Nova uses the Gerrit
    code review system, GerritWorkflow_.

.. _GerritWorkflow: http://docs.openstack.org/infra/manual/developers.html#development-workflow
.. _HowToContribute: http://docs.openstack.org/infra/manual/developers.html


Setup
-----

There are two ways to create a development environment: using
DevStack, or explicitly installing and cloning just what you need.

Using DevStack
~~~~~~~~~~~~~~

See `Devstack`_ Documentation. This should be done in a VM or other throwaway
environment and not on your local host.

Once DevStack is deployed, you can connect to the environment and navigate to
the Nova repo (typically found at ``/opt/stack/nova``).

.. _`Devstack`: http://docs.openstack.org/developer/devstack/

Using your local host
~~~~~~~~~~~~~~~~~~~~~

DevStack installs a complete OpenStack environment. Alternatively, you can
explicitly install and clone just what you need for Nova development. This will
give you an environment suitable for running the Nova unit and functional
tests, and for building documentation.

To begin, first grab the code from git:

.. code-block:: shell

    git clone https://opendev.org/openstack/nova
    cd nova

Then install the required tools and system dependencies. The process to do this
varies depending on your host OS. Following are instructions on how to do this
on Linux and on macOS.

.. rubric:: Linux Systems

Install the prerequisite packages listed in the ``bindep.txt`` file.

On Debian-based distributions (e.g., Debian/Mint/Ubuntu):

.. code-block:: shell

    sudo apt-get install python-pip tox
    tox -e bindep
    sudo apt-get install <indicated missing package names>

On Fedora-based distributions (e.g., Fedora/RHEL/CentOS Stream):

.. code-block:: shell

    sudo dnf install python3-pip tox
    tox -e bindep
    sudo dnf install <indicated missing package names>

.. rubric:: macOS Systems

`Homebrew`_ is very useful for installing dependencies. As a minimum for
running tests, install the following:

.. code-block:: shell

    brew install python3 tox

.. note::

    Nova currently requires tox 4.x (the exact version is specified in ``[tox]
    min_version`` in ``tox.ini``). Ubuntu 24.04, Fedora 43, and Brew all
    provide suitably new versions and tox has the ability to bootstrap itself
    if/when we bump this further. However, if you're on a system where tox is
    not packaged or is too old, you can also install it from PyPI.

.. _Homebrew: https://brew.sh

Building the documentation
--------------------------

Install the prerequisite packages: graphviz

To do a full documentation build, issue the following command from the root
directory of the repo.

.. code-block:: shell

   tox -e docs

That will create a Python virtual environment, install the needed
Python prerequisites in that environment, and build all the
documentation in that environment.


Running unit and functional tests
---------------------------------

See `Running Python Unit Tests`_.

.. _`Running Python Unit Tests`: https://docs.openstack.org/project-team-guide/project-setup/python.html#running-python-unit-tests

Note that some functional tests use a database. See the file
``tools/test-setup.sh`` on how the databases are set up in the
OpenStack CI environment and replicate it in your test environment.


Using the pre-commit hook
-------------------------

Nova can make use of the `pre-commit framework <https://pre-commit.com/>`__ to
allow running of some linters on each commit. This must be enabled locally to
function:

.. code-block:: shell

    $ pip install --user pre-commit
    $ pre-commit install --allow-missing-config

As a reminder, the hooks are optional and you are not enforced to run them.
You can either not install pre-commit or skip the hooks once by using the
``--no-verify`` flag on ``git commit``.


Using fake computes for tests
-----------------------------

The number of instances supported by fake computes is not limited by physical
constraints. It allows you to perform stress tests on a deployment with few
resources (typically a laptop). Take care to avoid using scheduler filters
that will limit the number of instances per compute, such as ``NumInstancesFilter``.

Fake computes can also be used in multi hypervisor-type deployments in order to
take advantage of fake and "real" computes during tests:

* create many fake instances for stress tests
* create some "real" instances for functional tests

Fake computes can be used for testing Nova itself but also applications on top
of it.
