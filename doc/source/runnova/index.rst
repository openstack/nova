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

Running Nova
============

This guide describes the basics of running and managing Nova. This site is intended to provide developer documentation. For more administrator's documentation, refer to `docs.openstack.org <http://docs.openstack.org>`_.

Running the Cloud
-----------------

The fastest way to get a test cloud running is by following the directions in the :doc:`../quickstart`. It relies on a nova.sh script to run on a single machine.

Nova's cloud works via the interaction of a series of daemon processes that reside persistently on the host machine(s).  Fortunately, the :doc:`../quickstart` process launches sample versions of all these daemons for you. Once you are familiar with basic Nova usage, you can learn more about daemons by reading :doc:`../service.architecture` and :doc:`binaries`.

Administration Utilities
------------------------

There are two main tools that a system administrator will find useful to manage their Nova cloud:

.. toctree::
   :maxdepth: 1

   nova.manage
   euca2ools

The nova-manage command may only be run by users with admin priviledges.  Commands for euca2ools can be used by all users, though specific commands may be restricted by Role Based Access Control.  You can read more about creating and managing users in :doc:`managing.users`

User and Resource Management
----------------------------

The nova-manage and euca2ools commands provide the basic interface to perform a broad range of administration functions.  In this section, you can read more about how to accomplish specific administration tasks.  

For background on the core objects referenced in this section, see :doc:`../object.model`

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

For a starting multi-node architecture, you would start with two nodes - a cloud controller node and a compute node. The cloud controller node contains the nova- services plus the Nova database. The compute node installs all the nova-services but then refers to the database installation, which is hosted by the cloud controller node. Ensure that the nova.conf file is identical on each node. If you find performance issues not related to database reads or writes, but due to the messaging queue backing up, you could add additional messaging services (rabbitmq). For instructions on multi-server installations, refer to `Installing and Configuring OpenStack Compute <http://docs.openstack.org/>`_.


.. toctree::
   :maxdepth: 1

   dbsync


Networking
^^^^^^^^^^

.. toctree::
   :maxdepth: 1

   network.vlan.rst
   network.flat.rst


Advanced Topics
---------------

.. toctree::
   :maxdepth: 1

   flags
   monitoring

