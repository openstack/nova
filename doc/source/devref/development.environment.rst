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

This page describes how to setup a working Python development environment that can be used in developing on OpenStack on Ubuntu or Mac OSX. These instructions assume you're already familiar with bzr and can pull down the code with an existing Launchpad account. Refer to http://wiki.openstack.org/LifeWithBzrAndLaunchpad for additional information.

Linux Systems
-------------

Note: This section is tested for Nova on Ubuntu 10.10-64. Feel free to add notes and change according to your experiences or operating system.

Bring down the Nova source with bzr, then:
::
  cd <your_src_dir>/nova
  sudo apt-get install python-dev swig libssl-dev python-pip
  sudo easy_install nose
  pip install virtualenv
  python tools/install_venv.py

If all goes well, you should get a message something like this:
::
  Nova development environment setup is complete.

Nova development uses virtualenv to track and manage Python dependencies while in development and testing. Virtual env gives you an independent Python environment.

To activate the Nova virtualenv for the extent of your current shell session
 you can run::
 
     $ source .nova-venv/bin/activate 

 Or, if you prefer, you can run commands in the virtualenv on a case by case
 basis by running::

     $ tools/with_venv.sh <your command>

 Also, make test will automatically use the virtualenv.

If you don't want to create a virtualenv every time you branch you can reuse a single virtualenv for all branches.

 #. If you don't have a nova/ directory containing trunk/ and other branches, do so now.
 #. Go into nova/trunk and install a virtualenv.
 #. Move it up a level: mv nova/trunk/.nova-venv nova/.nova-venv.
 #. Symlink the ../nova/.nova-venv directory from your branch:: 
 
    ~/openstack/nova/my_branch$ ln -s ../.nova-venv .nova-venv

This works with run_tests.sh and nosetests -w nova/tests/api

MacOSX Systems
--------------

First, install Virtual Env, which creates an isolated "standalone" Python environment.::

    sudo easy_install virtualenv


Here's how to setup the code initially::

    bzr branch lp:nova
    cd nova
    python tools/install_venv.py
    source .nova_venv/bin/activate
    pip install pep8 # submitting patch so that Nova has pep8 and pylint in PIP requirements file
    pip install pylint

If you have installed OpenSSL 1.0.0a on MacOS, which can happen when installing a MacPorts package for OpenSSL, you will see an error when running nova.tests.auth_unittest.AuthTestCase.test_209_can_generate_x509. The version that functions correctly is OpenSSL 0.9.8l 5, installed with MacOS 10.6 as a base element. 

Here's how to get the latest code::

  cd nova
  bzr pull # get the latest stuff...
  source .nova_venv/bin/activate
  ./run_tests.sh

Then you can do cleaning work or hack hack hack with a branched named cleaning.  

Contributing Your Work
----------------------

Once your work is complete you may wish to contribute it to the project.  Add your name and email address to the `Authors` file, and also to the `.mailmap` file if you use multiple email addresses. Your contributions can not be merged into trunk unless you are listed in the Authors file.  Now, push the branch to Launchpad::

    bzr push lp:~launchpaduserid/nova/cleaning

To submit the merge/patch that you hacked upon:
 * Navigate to https://code.launchpad.net/~launchpaduserid/nova/cleaning.
 * Click on the link "Propose for merging".
