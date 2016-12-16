..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

===============
 Placement API
===============

Overview
========

Nova introduced the placement API service in the 14.0.0 Newton release. This
is a separate REST API stack and data model used to track resource provider
inventories and usages, along with different classes of resources. For example,
a resource provider can be a compute node, a shared storage pool, or an IP
allocation pool. The placement service tracks the inventory and usage of each
provider. For example, an instance created on a compute node may be a consumer
of resources such as RAM and CPU from a compute node resource provider, disk
from an external shared storage pool resource provider and IP addresses from
an external IP pool resource provider.

The types of resources consumed are tracked as **classes**. The service
provides a set of standard resource classes (for example `DISK_GB`,
`MEMORY_MB`, and `VCPU`) and provides the ability to define custom resource
classes as needed.

References
~~~~~~~~~~

The following specifications are based on Newton work and while they present
the idea or overview for the design, implementation details may have changed
or be partially complete at this time.

* `Generic Resource Pools <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/generic-resource-pools.html>`_
* `Compute Node Inventory <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/compute-node-inventory-newton.html>`_
* `Resource Provider Allocations <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/resource-providers-allocations.html>`_
* `Resource Provider Base Models <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/resource-providers.html>`_

The following specifications are based on Ocata work and are subject to change.

* `Nested Resource Providers <https://review.openstack.org/#/c/386710/>`_
* `Custom Resource Classes <https://review.openstack.org/#/c/312696/>`_
* `Scheduler Filters in DB <https://review.openstack.org/#/c/300178/>`_


Deployment
==========

The placement-api service must be deployed at some point after you have
upgraded to the 14.0.0 Newton release but before you can upgrade to the 15.0.0
Ocata release. This is so that the resource tracker in the nova-compute service
can populate resource provider (compute node) inventory and allocation
information which will be used by the nova-scheduler service in Ocata.

Steps
~~~~~

**1. Deploy the API service**

At this time the placement API code is still in Nova alongside the compute
REST API code (nova-api). So once you have upgraded nova-api to Newton you
already have the placement API code, you just need to install the service.
Nova provides a ``nova-placement-api`` WSGI script for running the service
with Apache.

.. note:: The placement API service is currently developed within Nova but
        it is designed to be as separate as possible from the existing code so
        that it can eventually be split into a separate project.

**2. Synchronize the database**

In the Newton release the Nova **api** database is the only deployment
option for the placement API service and the resources it manages. After
upgrading the nova-api service for Newton and running the
``nova-manage api_db sync`` command the placement tables will be created.

.. note:: There are plans to add the ability to run the placement service
        with a separate **placement** database that would just have the tables
        necessary for that service and not everything else that goes into the
        Nova **api** database.

**3. Create accounts and update the service catalog**

Create a **placement** service user with an **admin** role in Keystone.

The placement API is a separate service and thus should be registered under
a **placement** service type in the service catalog as that is what the
resource tracker in the nova-compute node will use to look up the endpoint.

Devstack sets up the placement service on the default HTTP port (80) with a
``/placement`` prefix instead of using an independent port.

**4. Configure and restart nova-compute services**

The 14.0.0 Newton nova-compute service code will begin reporting resource
provider inventory and usage information as soon as the placement API
service is in place and can respond to requests via the endpoint registered
in the service catalog.

``nova.conf`` on the compute nodes must be updated in the ``[placement]``
group to contain credentials for making requests from nova-compute to the
placement-api service.

.. note:: After upgrading nova-compute code to Newton and restarting the
        service, the nova-compute service will attempt to make a connection
        to the placement API and if that is not yet available a warning will
        be logged. The nova-compute service will keep attempting to connect
        to the placement API, warning periodically on error until it is
        successful. Keep in mind that Placement is optional in Newton, but
        required in Ocata, so the placement service should be enabled before
        upgrading to Ocata. nova.conf on the compute nodes will need to be
        updated in the ``[placement]`` group for credentials to make requests
        from nova-compute to the placement-api service.

References
~~~~~~~~~~

The following changes were made to devstack (from oldest to newest) to enable
the placement-api service and can serve as a guide for your own deployment.

https://review.openstack.org/#/c/342362/

https://review.openstack.org/#/c/363335/

https://review.openstack.org/#/c/363724/


REST API
========

The placement API service has its own REST API and data model.

API Reference
~~~~~~~~~~~~~

A full API reference is forthcoming, but until then one can get a sample of the
REST API via the functional test `gabbits`_.

.. _gabbits: http://git.openstack.org/cgit/openstack/nova/tree/nova/tests/functional/api/openstack/placement/gabbits

Microversions
~~~~~~~~~~~~~

The placement API uses microversions for making incremental changes to the
API which client requests must opt into.

It is especially important to keep in mind that nova-compute is a client of
the placement REST API and based on how Nova supports rolling upgrades the
nova-compute service could be Newton level code making requests to an Ocata
placement API, and vice-versa, an Ocata compute service in a cells v2 cell
could be making requests to a Newton placement API.

.. include:: ../../nova/api/openstack/placement/rest_api_version_history.rst
