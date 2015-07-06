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

This documentation is intended to help explain what the Nova developers think
is the current scope of the Nova project, as well as the architectural
decisions we have made in order to support that scope. We also document our
plans for evolving our architecture over time. Finally, we documented our
current development process and policies.

Compute API References
======================

Nova has had a v2 API for a long time. We are currently in the process of
moving to a new implementation of that API, which we have called v2.1. v2.1
started life as an API called v3, but that name should never be used any more.
We are currently in the process of transitioning users over to the v2.1
implementation, at which point the v2 code will be deleted.

* `v2.1 (CURRENT)`_
* `v2 (SUPPORTED)`_ and `v2 extensions (SUPPORTED)`_ (Will be deprecated in
  the near future.)

Changes to the Compute API post v2.1 are made using microversions. You can see a history of our microversions here:

.. toctree::
   :maxdepth: 1

   api_microversion_history

We also have a local copy of the v2 docs:

.. toctree::
   :maxdepth: 1

   v2/index


.. _`v2.1 (CURRENT)`: http://developer.openstack.org/api-ref-compute-v2.1.html
.. _`v2 (SUPPORTED)`: http://developer.openstack.org/api-ref-compute-v2.html
.. _`v2 extensions (SUPPORTED)`: http://developer.openstack.org/api-ref-compute-v2-ext.html



Hypervisor Support Matrix
=========================

The hypervisor support matrix is how we document what features we require
hypervisor drivers to implement, as well as the level of support for optional
features that we currently have. You can see the support matrix here:

.. toctree::
   :maxdepth: 1

   support-matrix

Developer Guide
===============

If you are new to Nova, this should help you start to understand what Nova
actually does, and why.

.. toctree::
   :maxdepth: 1

   how_to_get_involved
   architecture
   project_scope
   development.environment

Development Policies
--------------------

The Nova community is a large community. We have lots of users, and they all
have a lot of expectations around upgrade and backwards compatibility.
For example, having a good stable API, with discoverable versions and
capabilities is important for maintaining the strong ecosystem around Nova.

Our process is always evolving, just as Nova and the community around Nova
evolves over time. If there are things that seem strange, or you have
ideas on how to improve things, please engage in that debate, so we
continue to improve how the Nova community operates.

This section looks at the processes and why. The main aim behind all the
process is to aid good communication between all members of the Nova
community, while keeping users happy and keeping developers productive.

.. toctree::
   :maxdepth: 1

   process
   blueprints
   policies

Architecture Concepts
----------------------

This follows on for the discussion in the introduction, and digs into
details on specific parts of the Nova architecture.

We find it important to document the reasons behind our architectural
decisions, so its easier for people to engage in the debates about
the future of Nova's architecture. This is all part of Open Design and
Open Development.

.. toctree::
   :maxdepth: 1

   aggregates
   threading
   vmstates
   i18n
   filter_scheduler
   rpc
   hooks
   addmethod.openstackapi

Architecture Evolution Plans
-----------------------------

The following section includes documents that describe the overall plan behind
groups of nova-specs. Most of these cover items relating to the evolution of
various parts of Nova's architecture. Once the work is complete,
these documents will move into the "Concepts" section.
If you want to get involved in shaping the future of Nova's architecture,
these are a great place to start reading up on the current plans.

.. toctree::
   :maxdepth: 1

   cells
   upgrade
   api_plugins
   api_microversion_dev
   policy_enforcement
   stable_api

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


.. # NOTE(mriedem): This is the section where we hide things that we don't
   # actually want in the table of contents but sphinx build would fail if
   # they aren't in the toctree somewhere. For example, we hide api/autoindex
   # since that's already covered with modindex below.
.. toctree::
   :hidden:

   api/autoindex

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

