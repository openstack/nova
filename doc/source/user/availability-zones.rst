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


Usage
-----

Availability zones can only be created and configured by an admin but they can
be used by an end-user when creating an instance. For example:

.. code-block:: console

    $ openstack server create --availability-zone ZONE ... SERVER

It is also possible to specify a destination host and/or node using this
command; however, this is an admin-only operation by default. For more
information, see :ref:`using-availability-zones-to-select-hosts`.
