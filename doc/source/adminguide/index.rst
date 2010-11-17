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

Administration Guide
====================

This guide describes the basics of running and managing Nova.  

Running the Cloud
-----------------

The fastest way to get a test cloud running is by following the directions in the :doc:`../quickstart`.  

Nova's cloud works via the interaction of a series of daemon processes that reside persistently on the host machine(s).  Fortunately, the :doc:`../quickstart` process launches sample versions of all these daemons for you.  Once you are familiar with basic Nova usage, you can learn more about daemons by reading :doc:`../service.architecture` and :doc:`binaries`.

Administration Utilities
------------------------

There are two main tools that a system administrator will find useful to manage their Nova cloud:

.. toctree::
   :maxdepth: 1

   nova.manage
   euca2ools

nova-manage may only be run by users with admin priviledges.  euca2ools can be used by all users, though specific commands may be restricted by Role Based Access Control.  You can read more about creating and managing users in :doc:`managing.users`

User and Resource Management
----------------------------

nova-manage and euca2ools provide the basic interface to perform a broad range of administration functions.  In this section, you can read more about how to accomplish specific administration tasks.  

For background on the core objects refenced in this section, see :doc:`../object.model`

.. toctree::
   :maxdepth: 1

   managing.users
   managing.projects
   managing.instances
   managing.images
   managing.volumes
   managing.networks

Deployment
----------

.. todo:: talk about deployment scenarios

.. toctree::
   :maxdepth: 1

   multi.node.install


Networking
^^^^^^^^^^

.. toctree::
   :maxdepth: 1

   multi.node.install
   network.vlan.rst
   network.flat.rst


Advanced Topics
---------------

.. toctree::
   :maxdepth: 1

   flags
   monitoring

