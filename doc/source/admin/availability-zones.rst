==================
Availability Zones
==================

.. note::

    This section provides deployment and admin-user usage information about the
    availability zone feature. For end-user information about availability
    zones, refer to the :doc:`user guide </user/availability-zones>`.

Availability Zones are an end-user visible logical abstraction for partitioning
a cloud without knowing the physical infrastructure. Availability zones are not
modeled in the database; rather, they are defined by attaching specific
metadata information to an :doc:`aggregate </admin/aggregates>` The addition of
this specific metadata to an aggregate makes the aggregate visible from an
end-user perspective and consequently allows users to schedule instances to a
specific set of hosts, the ones belonging to the aggregate.

However, despite their similarities, there are a few additional differences to
note when comparing availability zones and host aggregates:

- A host can be part of multiple aggregates but it can only be in one
  availability zone.

- By default a host is part of a default availability zone even if it doesn't
  belong to an aggregate. The name of this default availability zone can be
  configured using :oslo.config:option:`default_availability_zone` config
  option.

  .. warning::

      The use of the default availability zone name is requests can be very
      error-prone. Since the user can see the list of availability zones, they
      have no way to know whether the default availability zone name (currently
      ``nova``) is provided because an host belongs to an aggregate whose AZ
      metadata key is set to ``nova``, or because there is at least one host
      not belonging to any aggregate.  Consequently, it is highly recommended
      for users to never ever ask for booting an instance by specifying an
      explicit AZ named ``nova`` and for operators to never set the AZ metadata
      for an aggregate to ``nova``. This can result is some problems due to the
      fact that the instance AZ information is explicitly attached to ``nova``
      which could break further move operations when either the host is moved
      to another aggregate or when the user would like to migrate the instance.

  .. note::

      Availability zone names must NOT contain ``:`` since it is used by admin
      users to specify hosts where instances are launched in server creation.
      See `Using availability zones to select hosts`_ for more information.

In addition, other services, such as the :neutron-doc:`networking service <>`
and the :cinder-doc:`block storage service <>`, also provide an availability
zone feature. However, the implementation of these features differs vastly
between these different services. Consult the documentation for these other
services for more information on their implementation of this feature.


.. _availability-zones-with-placement:

Availability Zones with Placement
---------------------------------

In order to use placement to honor availability zone requests, there must be
placement aggregates that match the membership and UUID of nova host aggregates
that you assign as availability zones. The same key in aggregate metadata used
by the `AvailabilityZoneFilter` filter controls this function, and is enabled by
setting :oslo.config:option:`scheduler.query_placement_for_availability_zone`
to ``True``.

.. code-block:: console

  $ openstack --os-compute-api-version=2.53 aggregate create myaz
  +-------------------+--------------------------------------+
  | Field             | Value                                |
  +-------------------+--------------------------------------+
  | availability_zone | None                                 |
  | created_at        | 2018-03-29T16:22:23.175884           |
  | deleted           | False                                |
  | deleted_at        | None                                 |
  | id                | 4                                    |
  | name              | myaz                                 |
  | updated_at        | None                                 |
  | uuid              | 019e2189-31b3-49e1-aff2-b220ebd91c24 |
  +-------------------+--------------------------------------+

  $ openstack --os-compute-api-version=2.53 aggregate add host myaz node1
  +-------------------+--------------------------------------+
  | Field             | Value                                |
  +-------------------+--------------------------------------+
  | availability_zone | None                                 |
  | created_at        | 2018-03-29T16:22:23.175884           |
  | deleted           | False                                |
  | deleted_at        | None                                 |
  | hosts             | [u'node1']                           |
  | id                | 4                                    |
  | name              | myagg                                |
  | updated_at        | None                                 |
  | uuid              | 019e2189-31b3-49e1-aff2-b220ebd91c24 |
  +-------------------+--------------------------------------+

  $ openstack aggregate set --property availability_zone=az002 myaz

  $ openstack --os-placement-api-version=1.2 resource provider aggregate set --aggregate 019e2189-31b3-49e1-aff2-b220ebd91c24 815a5634-86fb-4e1e-8824-8a631fee3e06

With the above configuration, the `AvailabilityZoneFilter` filter can be
disabled in :oslo.config:option:`filter_scheduler.enabled_filters` while
retaining proper behavior (and doing so with the higher performance of
placement's implementation).


Implications for moving servers
-------------------------------

There are several ways to move a server to another host: evacuate, resize,
cold migrate, live migrate, and unshelve. Move operations typically go through
the scheduler to pick the target host *unless* a target host is specified and
the request forces the server to that host by bypassing the scheduler. Only
evacuate and live migrate can forcefully bypass the scheduler and move a
server to a specified host and even then it is highly recommended to *not*
force and bypass the scheduler.

With respect to availability zones, a server is restricted to a zone if:

1. The server was created in a specific zone with the ``POST /servers`` request
   containing the ``availability_zone`` parameter.

2. If the server create request did not contain the ``availability_zone``
   parameter but the API service is configured for
   :oslo.config:option:`default_schedule_zone` then by default the server will
   be scheduled to that zone.

3. The shelved offloaded server was unshelved by specifying the
   ``availability_zone`` with the ``POST /servers/{server_id}/action`` request
   using microversion 2.77 or greater.

4. :oslo.config:option:`cinder.cross_az_attach` is False,
   :oslo.config:option:`default_schedule_zone` is None,
   the server is created without an explicit zone but with pre-existing volume
   block device mappings. In that case the server will be created in the same
   zone as the volume(s) if the volume zone is not the same as
   :oslo.config:option:`default_availability_zone`. See `Resource affinity`_
   for details.

If the server was not created in a specific zone then it is free to be moved
to other zones, i.e. the :ref:`AvailabilityZoneFilter <AvailabilityZoneFilter>`
is a no-op.

Knowing this, it is dangerous to force a server to another host with evacuate
or live migrate if the server is restricted to a zone and is then forced to
move to a host in another zone, because that will create an inconsistency in
the internal tracking of where that server should live and may require manually
updating the database for that server. For example, if a user creates a server
in zone A and then the admin force live migrates the server to zone B, and then
the user resizes the server, the scheduler will try to move it back to zone A
which may or may not work, e.g. if the admin deleted or renamed zone A in the
interim.

Resource affinity
~~~~~~~~~~~~~~~~~

The :oslo.config:option:`cinder.cross_az_attach` configuration option can be
used to restrict servers and the volumes attached to servers to the same
availability zone.

A typical use case for setting ``cross_az_attach=False`` is to enforce compute
and block storage affinity, for example in a High Performance Compute cluster.

By default ``cross_az_attach`` is True meaning that the volumes attached to
a server can be in a different availability zone than the server. If set to
False, then when creating a server with pre-existing volumes or attaching a
volume to a server, the server and volume zone must match otherwise the
request will fail. In addition, if the nova-compute service creates the volumes
to attach to the server during server create, it will request that those
volumes are created in the same availability zone as the server, which must
exist in the block storage (cinder) service.

As noted in the `Implications for moving servers`_ section, forcefully moving
a server to another zone could also break affinity with attached volumes.

.. note::

    ``cross_az_attach=False`` is not widely used nor tested extensively and
    thus suffers from some known issues:

    * `Bug 1694844 <https://bugs.launchpad.net/nova/+bug/1694844>`_. This is
      fixed in the 21.0.0 (Ussuri) release by using the volume zone for the
      server being created if the server is created without an explicit zone,
      :oslo.config:option:`default_schedule_zone` is None, and the volume zone
      does not match the value of
      :oslo.config:option:`default_availability_zone`.
    * `Bug 1781421 <https://bugs.launchpad.net/nova/+bug/1781421>`_


.. _using-availability-zones-to-select-hosts:

Using availability zones to select hosts
----------------------------------------

We can combine availability zones with a specific host and/or node to select
where an instance is launched. For example:

.. code-block:: console

    $ openstack server create --availability-zone ZONE:HOST:NODE ... SERVER

.. note::

    It is possible to use ``ZONE``, ``ZONE:HOST``, and ``ZONE::NODE``.

.. note::

    This is an admin-only operation by default, though you can modify this
    behavior using the ``os_compute_api:servers:create:forced_host`` rule in
    ``policy.json``.

However, as discussed `previously <Implications for moving servers>`_, when
launching instances in this manner the scheduler filters are not run. For this
reason, this behavior is considered legacy behavior and, starting with the 2.74
microversion, it is now possible to specify a host or node explicitly. For
example:

.. code-block:: console

    $ openstack --os-compute-api-version 2.74 server create \
        --host HOST --hypervisor-hostname HYPERVISOR ... SERVER

.. note::

    This is an admin-only operation by default, though you can modify this
    behavior using the ``compute:servers:create:requested_destination`` rule in
    ``policy.json``.

This avoids the need to explicitly select an availability zone and ensures the
scheduler filters are not bypassed.


Usage
-----

Creating an availability zone (AZ) is done by associating metadata with a
:doc:`host aggregate </admin/aggregates>`. For this reason, the
:command:`openstack` client provides the ability to create a host aggregate and
associate it with an AZ in one command. For example, to create a new aggregate,
associating it with an AZ in the process, and add host to it using the
:command:`openstack` client, run:

.. code-block:: console

    $ openstack aggregate create --zone my-availability-zone my-aggregate
    $ openstack aggregate add host my-aggregate my-host

.. note::

    While it is possible to add a host to multiple host aggregates, it is not
    possible to add them to multiple availability zones. Attempting to add a
    host to multiple host aggregates associated with differing availability
    zones will result in a failure.

Alternatively, you can set this metadata manually for an existing host
aggregate. For example:

.. code-block:: console

    $ openstack aggregate set \
        --property availability_zone=my-availability-zone my-aggregate

To list all host aggregates and show information about a specific aggregate, in
order to determine which AZ the host aggregate(s) belong to, run:

.. code-block:: console

    $ openstack aggregate list --long
    $ openstack aggregate show my-aggregate

Finally, to disassociate a host aggregate from an availability zone, run:

.. code-block:: console

    $ openstack aggregate unset --property availability_zone my-aggregate


Configuration
-------------

Refer to :doc:`/admin/aggregates` for information on configuring both host
aggregates and availability zones.
