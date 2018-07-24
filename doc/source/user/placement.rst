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
provides a set of standard resource classes (for example ``DISK_GB``,
``MEMORY_MB``, and ``VCPU``) and provides the ability to define custom
resource classes as needed.

Each resource provider may also have a set of traits which describe qualitative
aspects of the resource provider. Traits describe an aspect of a resource
provider that cannot itself be consumed but a workload may wish to specify. For
example, available disk may be solid state drives (SSD).

References
~~~~~~~~~~

The following specifications represent the stages of design and development of
resource providers and the Placement service. Implementation details may have
changed or be partially complete at this time.

* `Generic Resource Pools <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/generic-resource-pools.html>`_
* `Compute Node Inventory <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/compute-node-inventory-newton.html>`_
* `Resource Provider Allocations <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/resource-providers-allocations.html>`_
* `Resource Provider Base Models <https://specs.openstack.org/openstack/nova-specs/specs/newton/implemented/resource-providers.html>`_
* `Nested Resource Providers`_
* `Custom Resource Classes <http://specs.openstack.org/openstack/nova-specs/specs/ocata/implemented/custom-resource-classes.html>`_
* `Scheduler Filters in DB <http://specs.openstack.org/openstack/nova-specs/specs/ocata/implemented/resource-providers-scheduler-db-filters.html>`_
* `Scheduler claiming resources to the Placement API <http://specs.openstack.org/openstack/nova-specs/specs/pike/approved/placement-claims.html>`_
* `The Traits API - Manage Traits with ResourceProvider <http://specs.openstack.org/openstack/nova-specs/specs/pike/approved/resource-provider-traits.html>`_
* `Request Traits During Scheduling`_
* `filter allocation candidates by aggregate membership`_
* `perform granular allocation candidate requests`_

.. _Nested Resource Providers: http://specs.openstack.org/openstack/nova-specs/specs/queens/approved/nested-resource-providers.html
.. _Request Traits During Scheduling: https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/request-traits-in-nova.html
.. _filter allocation candidates by aggregate membership: https://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/alloc-candidates-member-of.html
.. _perform granular allocation candidate requests: http://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/granular-resource-requests.html

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

At this time the placement API code is still in Nova alongside the compute REST
API code (nova-api). So once you have upgraded nova-api to Newton you already
have the placement API code, you just need to install the service.  Nova
provides a ``nova-placement-api`` WSGI script for running the service with
Apache, nginx or other WSGI-capable web servers. Depending on what packaging
solution is used to deploy OpenStack, the WSGI script may be in ``/usr/bin``
or ``/usr/local/bin``.

.. note:: The placement API service is currently developed within Nova but
        it is designed to be as separate as possible from the existing code so
        that it can eventually be split into a separate project.

``nova-placement-api``, as a standard WSGI script, provides a module level
``application`` attribute that most WSGI servers expect to find. This means it
is possible to run it with lots of different servers, providing flexibility in
the face of different deployment scenarios. Common scenarios include:

* apache2_ with mod_wsgi_
* apache2 with mod_proxy_uwsgi_
* nginx_ with uwsgi_
* nginx with gunicorn_

In all of these scenarios the host, port and mounting path (or prefix) of the
application is controlled in the web server's configuration, not in the
configuration (``nova.conf``) of the placement application.

When placement was `first added to DevStack`_ it used the ``mod_wsgi`` style.
Later it `was updated`_ to use mod_proxy_uwsgi_. Looking at those changes can
be useful for understanding the relevant options.

DevStack is configured to host placement at ``/placement`` on either the
default port for http or for https (``80`` or ``443``) depending on whether TLS
is being used. Using a default port is desirable.

By default, the placement application will get its configuration for settings
such as the database connection URL from ``/etc/nova/nova.conf``. The directory
the configuration file will be found in can be changed by setting
``OS_PLACEMENT_CONFIG_DIR`` in the environment of the process that starts the
application.

.. note:: When using uwsgi with a front end (e.g., apache2 or nginx) something
    needs to ensure that the uwsgi process is running. In DevStack this is done
    with systemd_. This is one of many different ways to manage uwsgi.

This document refrains from declaring a set of installation instructions for
the placement service. This is because a major point of having a WSGI
application is to make the deployment as flexible as possible. Because the
placement API service is itself stateless (all state is in the database), it is
possible to deploy as many servers as desired behind a load balancing solution
for robust and simple scaling. If you familiarize yourself with installing
generic WSGI applications (using the links in the common scenarios list,
above), those techniques will be applicable here.

.. _apache2: http://httpd.apache.org/
.. _mod_wsgi: https://modwsgi.readthedocs.io/
.. _mod_proxy_uwsgi: http://uwsgi-docs.readthedocs.io/en/latest/Apache.html
.. _nginx: http://nginx.org/
.. _uwsgi: http://uwsgi-docs.readthedocs.io/en/latest/Nginx.html
.. _gunicorn: http://gunicorn.org/
.. _first added to DevStack: https://review.openstack.org/#/c/342362/
.. _was updated: https://review.openstack.org/#/c/456717/
.. _systemd: https://review.openstack.org/#/c/448323/

**2. Synchronize the database**

In the Newton release the Nova **api** database is the only deployment
option for the placement API service and the resources it manages. After
upgrading the nova-api service for Newton and running the
``nova-manage api_db sync`` command the placement tables will be created.

With the Rocky release, it has become possible to use a separate database for
placement. If :oslo.config:option:`placement_database.connection` is
configured with a database connect string, that database will be used for
storing placement data. Once the database is created, the
``nova-manage api_db sync`` command will create and synchronize both the
nova api and placement tables. If ``[placement_database]/connection`` is not
set, the nova api database will be used.

.. note:: At this time there is no facility for migrating existing placement
        data from the nova api database to a placement database. There are
        many ways to do this. Which one is best will depend on the environment.

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


.. _placement-upgrade-notes:

Upgrade Notes
=============

The following sub-sections provide notes on upgrading to a given target release.

.. note::

   As a reminder, the :doc:`nova-status upgrade check </cli/nova-status>` tool
   can be used to help determine the status of your deployment and how ready it
   is to perform an upgrade.

Ocata (15.0.0)
~~~~~~~~~~~~~~

* The ``nova-compute`` service will fail to start in Ocata unless the
  ``[placement]`` section of nova.conf on the compute is configured. As
  mentioned in the deployment steps above, the Placement service should be
  deployed by this point so the computes can register and start reporting
  inventory and allocation information. If the computes are deployed
  and configured `before` the Placement service, they will continue to try
  and reconnect in a loop so that you do not need to restart the nova-compute
  process to talk to the Placement service after the compute is properly
  configured.
* The ``nova.scheduler.filter_scheduler.FilterScheduler`` in Ocata will
  fallback to not using the Placement service as long as there are older
  ``nova-compute`` services running in the deployment. This allows for rolling
  upgrades of the computes to not affect scheduling for the FilterScheduler.
  However, the fallback mechanism will be removed in the 16.0.0 Pike release
  such that the scheduler will make decisions based on the Placement service
  and the resource providers (compute nodes) registered there. This means if
  the computes are not reporting into Placement by Pike, build requests will
  fail with **NoValidHost** errors.
* While the FilterScheduler technically depends on the Placement service
  in Ocata, if you deploy the Placement service `after` you upgrade the
  ``nova-scheduler`` service to Ocata and restart it, things will still work.
  The scheduler will gracefully handle the absence of the Placement service.
  However, once all computes are upgraded, the scheduler not being able to make
  requests to Placement will result in **NoValidHost** errors.
* It is currently possible to exclude the ``CoreFilter``, ``RamFilter`` and
  ``DiskFilter`` from the list of enabled FilterScheduler filters such that
  scheduling decisions are not based on CPU, RAM or disk usage. Once all
  computes are reporting into the Placement service, however, and the
  FilterScheduler starts to use the Placement service for decisions, those
  excluded filters are ignored and the scheduler will make requests based on
  VCPU, MEMORY_MB and DISK_GB inventory. If you wish to effectively ignore
  that type of resource for placement decisions, you will need to adjust the
  corresponding ``cpu_allocation_ratio``, ``ram_allocation_ratio``, and/or
  ``disk_allocation_ratio`` configuration options to be very high values, e.g.
  9999.0.
* Users of CellsV1 will need to deploy a placement per cell, matching
  the scope and cardinality of the regular ``nova-scheduler`` process.

Pike (16.0.0)
~~~~~~~~~~~~~

* The ``nova.scheduler.filter_scheduler.FilterScheduler`` in Pike will
  no longer fall back to not using the Placement Service, even if older
  computes are running in the deployment.
* The FilterScheduler now requests allocation candidates from the Placement
  service during scheduling. The allocation candidates information was
  introduced in the Placement API 1.10 microversion, so you should upgrade the
  placement service **before** the Nova scheduler service so that the scheduler
  can take advantage of the allocation candidate information.

  The scheduler gets the allocation candidates from the placement API and
  uses those to get the compute nodes, which come from the cell(s). The
  compute nodes are passed through the enabled scheduler filters and weighers.
  The scheduler then iterates over this filtered and weighed list of hosts and
  attempts to claim resources in the placement API for each instance in the
  request. Claiming resources involves finding an allocation candidate that
  contains an allocation against the selected host's UUID and asking the
  placement API to allocate the requested instance resources. We continue
  performing this claim request until success or we run out of allocation
  candidates, resulting in a NoValidHost error.

  For a move operation, such as migration, allocations are made in Placement
  against both the source and destination compute node. Once the
  move operation is complete, the resource tracker in the *nova-compute*
  service will adjust the allocations in Placement appropriately.

  For a resize to the same host, allocations are summed on the single compute
  node. This could pose a problem if the compute node has limited capacity.
  Since resizing to the same host is disabled by default, and generally only
  used in testing, this is mentioned for completeness but should not be a
  concern for production deployments.

Queens (17.0.0)
~~~~~~~~~~~~~~~

* The minimum Placement API microversion required by the *nova-scheduler*
  service is ``1.17`` in order to support `Request Traits During Scheduling`_.
  This means you must upgrade the placement service before upgrading any
  *nova-scheduler* services to Queens.

Rocky (18.0.0)
~~~~~~~~~~~~~~

* The ``nova-api`` service now requires the ``[placement]`` section to be
  configured in nova.conf if you are using a separate config file just for
  that service. This is because the ``nova-api`` service now needs to talk
  to the placement service in order to (1) delete resource provider allocations
  when deleting an instance and the ``nova-compute`` service on which that
  instance is running is down (2) delete a ``nova-compute`` service record via
  the ``DELETE /os-services/{service_id}`` API and (3) mirror aggregate host
  associations to the placement service. This change is idempotent if
  ``[placement]`` is not configured in ``nova-api`` but it will result in new
  warnings in the logs until configured.
* As described above, before Rocky, the placement service used the nova api
  database to store placement data. In Rocky, if the ``connection`` setting in
  a ``[placement_database]`` group is set in configuration, that group will be
  used to describe where and how placement data is stored.

REST API
========

The placement API service has its own `REST API`_ and data model.  One
can get a sample of the REST API via the functional test `gabbits`_.

.. _`REST API`: https://developer.openstack.org/api-ref/placement/
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

.. _placement-api-microversion-history:

.. include:: ../../../nova/api/openstack/placement/rest_api_version_history.rst
