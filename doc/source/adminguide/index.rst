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

This guide describes the basics of installing and managing Nova.  If you havn't yet, you should do the :doc:`../quickstart` before proceeding.

Authentication
--------------

.. todo:: Explain authentication

Administration Utilities
------------------------

There are two main tools that a system administrator will find useful to manage their Nova cloud:

.. toctree::
   :maxdepth: 1

   euca2ools
   nova.manage


User and Resource Management
----------------------------

nova-manage and euca2ools provide the basic interface to perform a broad range of administration functions.  In this section, you can read more about how to accomplish specific administration tasks.

.. toctree::
   :maxdepth: 1

   managing.users
   managing.projects
   managing.instances
   managing.images
   managing.volumes
   managing.networks

Advanced Topics
---------------

.. toctree::
   :maxdepth: 1

   multi.node.install
   binaries
   flags
   monitoring

