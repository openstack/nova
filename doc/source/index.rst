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

.. _`docs.openstack.org`: http://docs.openstack.org

This documentation is intended to help explain what the Nova developers think
is the current scope of the Nova project, as well as the architectural
decisions we have made in order to support that scope. We also document our
plans for evolving our architecture over time. Finally, we documented our
current development process and policies.

Compute API References
======================

The Nova compute API is quite large, we provide a concept guide which
gives some of the high level details, as well as a more detailed API
reference.

The API reference covers all versions of the API. Version 2.0 and
Version 2.1 are actually the same API, and Version 2.1 evolves forward
with microversions. The API ref starts with the base API version, and
specifies all changes that exist to it as microversions roll
forward. You can also see a history of our microversions here:

.. toctree::
   :maxdepth: 1

   api_microversion_history

.. note::
    Only Version 2.1 APIs should be used from this point forward, Version 2.0
    APIs are only provided for backward compatibility purposes.

.. _`Compute API Guide`: http://developer.openstack.org/api-guide/compute/
.. _`Compute API Reference`: http://developer.openstack.org/api-ref/compute/

There was a session on the v2.1 API at the Liberty summit which you can watch
`here <https://www.openstack.org/summit/vancouver-2015/summit-videos/presentation/introduction-of-a-new-nova-rest-api-why-we-need-to-use-nova-v2-1-api>`_.


Feature Status
==============

Nova aims to have a single compute API that works the same across
all deployments of Nova.
While many features are well-tested, well-documented, support live upgrade,
and are ready for production, some are not. Also the choice of underlying
technology affects the list of features that are ready for production.

Our first attempt to communicate this is the feature support matrix
(previously called the hypervisor support matrix).
Over time we hope to evolve that to include a classification of each feature's
maturity and exactly what technology combinations are covered by current
integration testing efforts.

.. toctree::
   :maxdepth: 1

   test_strategy
   feature_classification
   support-matrix

Developer Guide
===============

If you are new to Nova, this should help you start to understand what Nova
actually does, and why.

.. toctree::
   :maxdepth: 1

   how_to_get_involved
   process
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
   code-review
   releasenotes

Architecture Concepts
----------------------

This follows on for the discussion in the introduction, and digs into
details on specific parts of the Nova architecture.

We find it important to document the reasons behind our architectural
decisions, so its easier for people to engage in the debates about
the future of Nova's architecture. This is all part of Open Design and
Open Development.

.. NOTE: keep this list sorted by title

.. toctree::
   :maxdepth: 1

   addmethod.openstackapi
   rpc
   block_device_mapping
   conductor
   filter_scheduler
   aggregates
   i18n
   notifications
   placement
   placement_dev
   quotas
   threading
   vmstates
   wsgi

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
   scheduler_evolution

Advanced testing and guides
----------------------------

.. toctree::
    :maxdepth: 1

    gmr
    testing/libvirt-numa
    testing/serial-console
    testing/zero-downtime-upgrade

Sample Configuration File
-------------------------

.. toctree::
    :maxdepth: 1

    sample_config

Sample Policy file
------------------

.. toctree::
    :maxdepth: 1

    sample_policy

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

Metadata
========

.. toctree::
    :maxdepth: 1

    vendordata

Indices and tables
==================

* :ref:`search`
