..
      Copyright 2010-2012 United States Government as represented by the
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

==========================================
Welcome to Nova's developer documentation!
==========================================

Nova is an OpenStack project designed to provide power massively scalable, on
demand, self service access to compute resources.

The developer documentation provided here is continually kept up-to-date
based on the latest code, and may not represent the state of the project at
any specific prior release.

.. note:: This is documentation for developers, if you are looking for more
          general documentation including API, install, operator and user
          guides see `docs.openstack.org`_

.. _`docs.openstack.org`: https://docs.openstack.org

Compute API References
=======================

* `v2.1 (CURRENT)`_
* `v2 (SUPPORTED)`_ and `v2 extensions (SUPPORTED)`_ (Will be deprecated in
  the near future.)

Local copy of v2 docs:

.. toctree::
   :maxdepth: 1

   v2/index


.. _`v2.1 (CURRENT)`: http://developer.openstack.org/api-ref-compute-v2.1.html
.. _`v2 (SUPPORTED)`: http://developer.openstack.org/api-ref-compute-v2.html
.. _`v2 extensions (SUPPORTED)`: http://developer.openstack.org/api-ref-compute-v2-ext.html



Hypervisor Support Matrix
=========================

.. toctree::
   :maxdepth: 1

   support-matrix

Developer Guide
===============

Introduction
-------------

.. toctree::
   :maxdepth: 1

   architecture
   project_scope

.. toctree::
   :maxdepth: 1

   development.environment


APIs Development
----------------
.. toctree::
   :maxdepth: 1

   addmethod.openstackapi
   api_plugins
   api_microversions
   policy_enforcement

Concepts
---------
.. toctree::
   :maxdepth: 1

   aggregates
   cells
   threading
   vmstates
   i18n
   filter_scheduler
   rpc
   hooks
   upgrade

Development policies
--------------------
.. toctree::
   :maxdepth: 1

   blueprints
   policies

Advanced testing and guides
----------------------------

.. toctree::
    :maxdepth: 1

    gmr
    testing/libvirt-numa
    testing/serial-console

Man Pages
----------

.. toctree::
   :maxdepth: 1

   man/index

Module Reference
----------------
.. toctree::
   :maxdepth: 1

   services

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

