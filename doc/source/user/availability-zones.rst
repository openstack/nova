==================
Availability zones
==================

Availability Zones are an end-user visible logical abstraction for partitioning
a cloud without knowing the physical infrastructure. Availability zones can be
used to partition a cloud on arbitrary factors, such as location (country,
datacenter, rack), network layout and/or power source. Because of the
flexibility, the names and purposes of availability zones can vary massively
between clouds.

In addition, other services, such as the :neutron-doc:`networking service <>`
and the :cinder-doc:`block storage service <>`, also provide an availability
zone feature. However, the implementation of these features differs vastly
between these different services. Consult the documentation for these other
services for more information on their implementation of this feature.

.. tip::

    Server Groups provide another mechanism for configuring the colocation of
    instances during scheduling. For more information, refer to
    :doc:`/user/server-groups`.


Usage
-----

Availability zones can only be created and configured by an admin but they can
be used by an end-user when creating an instance. For example:

.. code-block:: console

    $ openstack server create --availability-zone ZONE ... SERVER

It is also possible to specify a destination host and/or node using this
command; however, this is an admin-only operation by default. For more
information, see :ref:`using-availability-zones-to-select-hosts`.


Pinning and unpinning
~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 34.0.0 (2026.2)

By default, when a server is created in a specific availability zone it is
*pinned* to that zone: move operations (migrate, evacuate, etc.) will only
place the server on hosts within the same zone.

Starting with microversion 2.104, you can unpin a server from its availability
zone by unsetting ``pinned_availability_zone`` in a server update request:

.. code-block:: console

    $ openstack --os-compute-api-version 2.104 server unset \
        --pinned-availability-zone SERVER

Once unpinned, the server is free to be moved to any availability zone. You can
re-pin it to its current zone by setting ``pinned_availability_zone`` back to
the zone name:

.. code-block:: console

    $ openstack --os-compute-api-version 2.104 server set \
        --pinned-availability-zone ZONE SERVER

.. note::

    A server can only be re-pinned to the availability zone it currently
    resides in. Attempting to pin it to a different zone will result in an
    error.
