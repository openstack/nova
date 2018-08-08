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

========================
OpenStack Compute (nova)
========================

What is nova?
=============

Nova is the OpenStack project that provides a way to provision compute
instances (aka virtual servers). Nova supports creating virtual machines,
baremetal servers (through the use of ironic), and has limited support for
system containers. Nova runs as a set of daemons on top of existing Linux
servers to provide that service.

It requires the following additional OpenStack services for basic function:

* :keystone-doc:`Keystone <>`: This provides identity and authentication for
  all OpenStack services.
* :glance-doc:`Glance <>`: This provides the compute image repository. All
  compute instances launch from glance images.
* :neutron-doc:`Neutron <>`: This is responsible for provisioning the virtual
  or physical networks that compute instances connect to on boot.

It can also integrate with other services to include: persistent block
storage, encrypted disks, and baremetal compute instances.

For End Users
=============

As an end user of nova, you'll use nova to create and manage servers with
either tools or the API directly.

Tools for using Nova
--------------------

* :horizon-doc:`Horizon <user/launch-instances.html>`: The official web UI for
  the OpenStack Project.
* :python-openstackclient-doc:`OpenStack Client <>`: The official CLI for
  OpenStack Projects. You should use this as your CLI for most things, it
  includes not just nova commands but also commands for most of the projects in
  OpenStack.
* :python-novaclient-doc:`Nova Client <user/shell.html>`: For some very
  advanced features (or administrative commands) of nova you may need to use
  nova client. It is still supported, but the ``openstack`` cli is recommended.

Writing to the API
------------------

All end user (and some administrative) features of nova are exposed via a REST
API, which can be used to build more complicated logic or automation with
nova. This can be consumed directly, or via various SDKs. The following
resources will help you get started with consuming the API directly.

* `Compute API Guide <https://developer.openstack.org/api-guide/compute/>`_: The
  concept guide for the API. This helps lay out the concepts behind the API to
  make consuming the API reference easier.
* `Compute API Reference <http://developer.openstack.org/api-ref/compute/>`_:
  The complete reference for the compute API, including all methods and
  request / response parameters and their meaning.
* :doc:`Compute API Microversion History </reference/api-microversion-history>`:
  The compute API evolves over time through `Microversions
  <https://developer.openstack.org/api-guide/compute/microversions.html>`_. This
  provides the history of all those changes. Consider it a "what's new" in the
  compute API.
* `Placement API Reference <https://developer.openstack.org/api-ref/placement/>`_:
  The complete reference for the placement API, including all methods and
  request / response parameters and their meaning.
* :ref:`Placement API Microversion History <placement-api-microversion-history>`:
  The placement API evolves over time through `Microversions
  <https://developer.openstack.org/api-guide/compute/microversions.html>`_. This
  provides the history of all those changes. Consider it a "what's new" in the
  placement API.
* :doc:`Block Device Mapping </user/block-device-mapping>`: One of the trickier
  parts to understand is the Block Device Mapping parameters used to connect
  specific block devices to computes. This deserves its own deep dive.
* :doc:`Configuration drive </user/config-drive>`: Provide information to the
  guest instance when it is created.

Nova can be configured to emit notifications over RPC.

* :ref:`Versioned Notifications <versioned_notification_samples>`: This
  provides the list of existing versioned notifications with sample payloads.

For Operators
=============

Architecture Overview
---------------------

* :doc:`Nova architecture </user/architecture>`: An overview of how all the parts in
  nova fit together.

Installation
------------

.. TODO(sdague): links to all the rest of the install guide pieces.

The detailed install guide for nova. A functioning nova will also require
having installed :keystone-doc:`keystone <install/>`, :glance-doc:`glance
<install/>`, and :neutron-doc:`neutron <install/>`. Ensure that you follow
their install guides first.

.. toctree::
   :maxdepth: 2

   install/index

Deployment Considerations
-------------------------

There is information you might want to consider before doing your deployment,
especially if it is going to be a larger deployment. For smaller deployments
the defaults from the :doc:`install guide </install/index>` will be sufficient.

* **Compute Driver Features Supported**: While the majority of nova deployments use
  libvirt/kvm, you can use nova with other compute drivers. Nova attempts to
  provide a unified feature set across these, however, not all features are
  implemented on all backends, and not all features are equally well tested.

  * :doc:`Feature Support by Use Case </user/feature-classification>`: A view of
    what features each driver supports based on what's important to some large
    use cases (General Purpose Cloud, NFV Cloud, HPC Cloud).
  * :doc:`Feature Support full list </user/support-matrix>`: A detailed dive through
    features in each compute driver backend.

* :doc:`Cells v2 Planning </user/cellsv2-layout>`: For large deployments, Cells v2
  allows sharding of your compute environment. Upfront planning is key to a
  successful Cells v2 layout.
* :doc:`Placement service </user/placement>`: Overview of the placement
  service, including how it fits in with the rest of nova.
* :doc:`Running nova-api on wsgi <user/wsgi>`: Considerations for using a real
  WSGI container instead of the baked-in eventlet web server.

Maintenance
-----------

Once you are running nova, the following information is extremely useful.

* :doc:`Admin Guide </admin/index>`: A collection of guides for administrating
  nova.
* :doc:`Flavors </user/flavors>`: What flavors are and why they are used.
* :doc:`Upgrades </user/upgrade>`: How nova is designed to be upgraded for minimal
  service impact, and the order you should do them in.
* :doc:`Quotas </user/quotas>`: Managing project quotas in nova.
* :doc:`Aggregates </user/aggregates>`: Aggregates are a useful way of grouping
  hosts together for scheduling purposes.
* :doc:`Filter Scheduler </user/filter-scheduler>`: How the filter scheduler is
  configured, and how that will impact where compute instances land in your
  environment. If you are seeing unexpected distribution of compute instances
  in your hosts, you'll want to dive into this configuration.
* :doc:`Exposing custom metadata to compute instances </user/vendordata>`: How and
  when you might want to extend the basic metadata exposed to compute instances
  (either via metadata server or config drive) for your specific purposes.

Reference Material
------------------

* :doc:`Nova CLI Command References </cli/index>`: the complete command reference
  for all the daemons and admin tools that come with nova.
* :doc:`Configuration Guide <configuration/index>`: Information on configuring
  the system, including role-based access control policy rules.

For Contributors
================

If you are new to Nova, this should help you start to understand what Nova
actually does, and why.

.. toctree::
   :maxdepth: 1

   contributor/index

There are also a number of technical references on both current and future
looking parts of our architecture. These are collected below.

.. toctree::
   :maxdepth: 1

   reference/index


.. # NOTE(mriedem): This is the section where we hide things that we don't
   # actually want in the table of contents but sphinx build would fail if
   # they aren't in the toctree somewhere. For example, we hide api/autoindex
   # since that's already covered with modindex below.
.. toctree::
   :hidden:

   admin/index
   admin/configuration/index
   cli/index
   configuration/index
   contributor/development-environment
   contributor/api
   contributor/api-2
   contributor/api-ref-guideline
   contributor/blueprints
   contributor/code-review
   contributor/documentation
   contributor/microversions
   contributor/placement.rst
   contributor/policies.rst
   contributor/releasenotes
   contributor/testing
   contributor/testing/libvirt-numa
   contributor/testing/serial-console
   contributor/testing/zero-downtime-upgrade
   contributor/how-to-get-involved
   contributor/process
   contributor/project-scope
   reference/api-microversion-history.rst
   reference/gmr
   reference/i18n
   reference/live-migration
   reference/notifications
   reference/policy-enforcement
   reference/rpc
   reference/scheduling
   reference/scheduler-evolution
   reference/services
   reference/stable-api
   reference/threading
   reference/update-provider-tree
   reference/vm-states
   user/index
   user/aggregates
   user/architecture
   user/block-device-mapping
   user/cells
   user/cellsv2-layout
   user/certificate-validation
   user/conductor
   user/config-drive
   user/feature-classification
   user/filter-scheduler
   user/flavors
   user/manage-ip-addresses
   user/placement
   user/quotas
   user/support-matrix
   user/upgrade
   user/user-data
   user/vendordata
   user/wsgi


Search
======

* :ref:`Nova document search <search>`: Search the contents of this document.
* `OpenStack wide search <https://docs.openstack.org>`_: Search the wider
  set of OpenStack documentation, including forums.

