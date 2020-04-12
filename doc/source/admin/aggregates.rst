===============
Host aggregates
===============

Host aggregates are a mechanism for partitioning hosts in an OpenStack cloud,
or a region of an OpenStack cloud, based on arbitrary characteristics.
Examples where an administrator may want to do this include where a group of
hosts have additional hardware or performance characteristics.

Host aggregates started out as a way to use Xen hypervisor resource pools, but
have been generalized to provide a mechanism to allow administrators to assign
key-value pairs to groups of machines. Each node can have multiple aggregates,
each aggregate can have multiple key-value pairs, and the same key-value pair
can be assigned to multiple aggregates. This information can be used in the
scheduler to enable advanced scheduling, to set up Xen hypervisor resource
pools or to define logical groups for migration.

Host aggregates are not explicitly exposed to users. Instead administrators map
flavors to host aggregates. Administrators do this by setting metadata on a
host aggregate, and matching flavor extra specifications. The scheduler then
endeavors to match user requests for instances of the given flavor to a host
aggregate with the same key-value pair in its metadata. Compute nodes can be in
more than one host aggregate. Weight multipliers can be controlled on a
per-aggregate basis by setting the desired ``xxx_weight_multiplier`` aggregate
metadata.

Administrators are able to optionally expose a host aggregate as an
:term:`Availability Zone`. Availability zones are different from host
aggregates in that they are explicitly exposed to the user, and hosts can only
be in a single availability zone. Administrators can configure a default
availability zone where instances will be scheduled when the user fails to
specify one. For more information on how to do this, refer to
:doc:`/admin/availability-zones`.


.. _config-sch-for-aggs:

Configure scheduler to support host aggregates
----------------------------------------------

One common use case for host aggregates is when you want to support scheduling
instances to a subset of compute hosts because they have a specific capability.
For example, you may want to allow users to request compute hosts that have SSD
drives if they need access to faster disk I/O, or access to compute hosts that
have GPU cards to take advantage of GPU-accelerated code.

To configure the scheduler to support host aggregates, the
:oslo.config:option:`filter_scheduler.enabled_filters` configuration option
must contain the ``AggregateInstanceExtraSpecsFilter`` in addition to the other
filters used by the scheduler. Add the following line to ``nova.conf`` on the
host that runs the ``nova-scheduler`` service to enable host aggregates
filtering, as well as the other filters that are typically enabled:

.. code-block:: ini

   [filter_scheduler]
   enabled_filters=...,AggregateInstanceExtraSpecsFilter

Example: Specify compute hosts with SSDs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This example configures the Compute service to enable users to request nodes
that have solid-state drives (SSDs). You create a ``fast-io`` host aggregate in
the ``nova`` availability zone and you add the ``ssd=true`` key-value pair to
the aggregate. Then, you add the ``node1``, and ``node2`` compute nodes to it.

.. code-block:: console

   $ openstack aggregate create --zone nova fast-io
   +-------------------+----------------------------+
   | Field             | Value                      |
   +-------------------+----------------------------+
   | availability_zone | nova                       |
   | created_at        | 2016-12-22T07:31:13.013466 |
   | deleted           | False                      |
   | deleted_at        | None                       |
   | id                | 1                          |
   | name              | fast-io                    |
   | updated_at        | None                       |
   +-------------------+----------------------------+

   $ openstack aggregate set --property ssd=true 1
   +-------------------+----------------------------+
   | Field             | Value                      |
   +-------------------+----------------------------+
   | availability_zone | nova                       |
   | created_at        | 2016-12-22T07:31:13.000000 |
   | deleted           | False                      |
   | deleted_at        | None                       |
   | hosts             | []                         |
   | id                | 1                          |
   | name              | fast-io                    |
   | properties        | ssd='true'                 |
   | updated_at        | None                       |
   +-------------------+----------------------------+

   $ openstack aggregate add host 1 node1
   +-------------------+--------------------------------------------------+
   | Field             | Value                                            |
   +-------------------+--------------------------------------------------+
   | availability_zone | nova                                             |
   | created_at        | 2016-12-22T07:31:13.000000                       |
   | deleted           | False                                            |
   | deleted_at        | None                                             |
   | hosts             | [u'node1']                                       |
   | id                | 1                                                |
   | metadata          | {u'ssd': u'true', u'availability_zone': u'nova'} |
   | name              | fast-io                                          |
   | updated_at        | None                                             |
   +-------------------+--------------------------------------------------+

   $ openstack aggregate add host 1 node2
   +-------------------+--------------------------------------------------+
   | Field             | Value                                            |
   +-------------------+--------------------------------------------------+
   | availability_zone | nova                                             |
   | created_at        | 2016-12-22T07:31:13.000000                       |
   | deleted           | False                                            |
   | deleted_at        | None                                             |
   | hosts             | [u'node1', u'node2']                             |
   | id                | 1                                                |
   | metadata          | {u'ssd': u'true', u'availability_zone': u'nova'} |
   | name              | fast-io                                          |
   | updated_at        | None                                             |
   +-------------------+--------------------------------------------------+

Use the :command:`openstack flavor create` command to create the ``ssd.large``
flavor called with an ID of 6, 8 GB of RAM, 80 GB root disk, and 4 vCPUs.

.. code-block:: console

   $ openstack flavor create --id 6 --ram 8192 --disk 80 --vcpus 4 ssd.large
   +----------------------------+-----------+
   | Field                      | Value     |
   +----------------------------+-----------+
   | OS-FLV-DISABLED:disabled   | False     |
   | OS-FLV-EXT-DATA:ephemeral  | 0         |
   | disk                       | 80        |
   | id                         | 6         |
   | name                       | ssd.large |
   | os-flavor-access:is_public | True      |
   | ram                        | 8192      |
   | rxtx_factor                | 1.0       |
   | swap                       |           |
   | vcpus                      | 4         |
   +----------------------------+-----------+

Once the flavor is created, specify one or more key-value pairs that match the
key-value pairs on the host aggregates with scope
``aggregate_instance_extra_specs``. In this case, that is the
``aggregate_instance_extra_specs:ssd=true`` key-value pair.  Setting a
key-value pair on a flavor is done using the :command:`openstack flavor set`
command.

.. code-block:: console

   $ openstack flavor set \
       --property aggregate_instance_extra_specs:ssd=true ssd.large

Once it is set, you should see the ``extra_specs`` property of the
``ssd.large`` flavor populated with a key of ``ssd`` and a corresponding value
of ``true``.

.. code-block:: console

   $ openstack flavor show ssd.large
   +----------------------------+-------------------------------------------+
   | Field                      | Value                                     |
   +----------------------------+-------------------------------------------+
   | OS-FLV-DISABLED:disabled   | False                                     |
   | OS-FLV-EXT-DATA:ephemeral  | 0                                         |
   | disk                       | 80                                        |
   | id                         | 6                                         |
   | name                       | ssd.large                                 |
   | os-flavor-access:is_public | True                                      |
   | properties                 | aggregate_instance_extra_specs:ssd='true' |
   | ram                        | 8192                                      |
   | rxtx_factor                | 1.0                                       |
   | swap                       |                                           |
   | vcpus                      | 4                                         |
   +----------------------------+-------------------------------------------+

Now, when a user requests an instance with the ``ssd.large`` flavor,
the scheduler only considers hosts with the ``ssd=true`` key-value pair.
In this example, these are ``node1`` and ``node2``.


Aggregates in Placement
-----------------------

Aggregates also exist in placement and are not the same thing as host
aggregates in nova. These aggregates are defined (purely) as groupings of
related resource providers. Since compute nodes in nova are represented in
placement as resource providers, they can be added to a placement aggregate as
well. For example, get the UUID of the compute node using :command:`openstack
hypervisor list` and add it to an aggregate in placement using
:command:`openstack resource provider aggregate set`.

.. code-block:: console

  $ openstack --os-compute-api-version=2.53 hypervisor list
  +--------------------------------------+---------------------+-----------------+-----------------+-------+
  | ID                                   | Hypervisor Hostname | Hypervisor Type | Host IP         | State |
  +--------------------------------------+---------------------+-----------------+-----------------+-------+
  | 815a5634-86fb-4e1e-8824-8a631fee3e06 | node1               | QEMU            | 192.168.1.123   | up    |
  +--------------------------------------+---------------------+-----------------+-----------------+-------+

  $ openstack --os-placement-api-version=1.2 resource provider aggregate set \
      --aggregate df4c74f3-d2c4-4991-b461-f1a678e1d161 \
      815a5634-86fb-4e1e-8824-8a631fee3e06

Some scheduling filter operations can be performed by placement for increased
speed and efficiency.

.. note::

    The nova-api service attempts (as of nova 18.0.0) to automatically mirror
    the association of a compute host with an aggregate when an administrator
    adds or removes a host to/from a nova host aggregate. This should alleviate
    the need to manually create those association records in the placement API
    using the ``openstack resource provider aggregate set`` CLI invocation.


.. _tenant-isolation-with-placement:

Tenant Isolation with Placement
-------------------------------

In order to use placement to isolate tenants, there must be placement
aggregates that match the membership and UUID of nova host aggregates that you
want to use for isolation. The same key pattern in aggregate metadata used by
the :ref:`AggregateMultiTenancyIsolation` filter controls this function, and is
enabled by setting
:oslo.config:option:`scheduler.limit_tenants_to_placement_aggregate` to
``True``.

.. code-block:: console

    $ openstack --os-compute-api-version=2.53 aggregate create myagg
    +-------------------+--------------------------------------+
    | Field             | Value                                |
    +-------------------+--------------------------------------+
    | availability_zone | None                                 |
    | created_at        | 2018-03-29T16:22:23.175884           |
    | deleted           | False                                |
    | deleted_at        | None                                 |
    | id                | 4                                    |
    | name              | myagg                                |
    | updated_at        | None                                 |
    | uuid              | 019e2189-31b3-49e1-aff2-b220ebd91c24 |
    +-------------------+--------------------------------------+

    $ openstack --os-compute-api-version=2.53 aggregate add host myagg node1
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

    $ openstack project list -f value | grep 'demo'
    9691591f913949818a514f95286a6b90 demo

    $ openstack aggregate set \
        --property filter_tenant_id=9691591f913949818a514f95286a6b90 myagg

    $ openstack --os-placement-api-version=1.2 resource provider aggregate set \
        --aggregate 019e2189-31b3-49e1-aff2-b220ebd91c24 \
        815a5634-86fb-4e1e-8824-8a631fee3e06

Note that the ``filter_tenant_id`` metadata key can be optionally suffixed
with any string for multiple tenants, such as ``filter_tenant_id3=$tenantid``.


Usage
-----

Much of the configuration of host aggregates is driven from the API or
command-line clients. For example, to create a new aggregate and add hosts to
it using the :command:`openstack` client, run:

.. code-block:: console

    $ openstack aggregate create my-aggregate
    $ openstack aggregate add host my-aggregate my-host

To list all aggregates and show information about a specific aggregate, run:

.. code-block:: console

    $ openstack aggregate list
    $ openstack aggregate show my-aggregate

To set and unset a property on the aggregate, run:

.. code-block:: console

    $ openstack aggregate set --property pinned=true my-aggregrate
    $ openstack aggregate unset --property pinned my-aggregate

To rename the aggregate, run:

.. code-block:: console

    $ openstack aggregate set --name my-awesome-aggregate my-aggregate

To remove a host from an aggregate and delete the aggregate, run:

.. code-block:: console

    $ openstack aggregate remove host my-aggregate my-host
    $ openstack aggregate delete my-aggregate

For more information, refer to the :python-openstackclient-doc:`OpenStack
Client documentation <cli/command-objects/aggregate.html>`.


Configuration
-------------

In addition to CRUD operations enabled by the API and clients, the following
configuration options can be used to configure how host aggregates and the
related availability zones feature operate under the hood:

- :oslo.config:option:`default_schedule_zone`
- :oslo.config:option:`scheduler.limit_tenants_to_placement_aggregate`
- :oslo.config:option:`cinder.cross_az_attach`

Finally, as discussed previously, there are a number of host aggregate-specific
scheduler filters. These are:

- :ref:`AggregateCoreFilter`
- :ref:`AggregateDiskFilter`
- :ref:`AggregateImagePropertiesIsolation`
- :ref:`AggregateInstanceExtraSpecsFilter`
- :ref:`AggregateIoOpsFilter`
- :ref:`AggregateMultiTenancyIsolation`
- :ref:`AggregateNumInstancesFilter`
- :ref:`AggregateRamFilter`
- :ref:`AggregateTypeAffinityFilter`

The following configuration options are applicable to the scheduler
configuration:

- :oslo.config:option:`cpu_allocation_ratio`
- :oslo.config:option:`ram_allocation_ratio`
- :oslo.config:option:`filter_scheduler.max_instances_per_host`
- :oslo.config:option:`filter_scheduler.aggregate_image_properties_isolation_separator`
- :oslo.config:option:`filter_scheduler.aggregate_image_properties_isolation_namespace`

.. _image-caching-aggregates:

Image Caching
-------------

Aggregates can be used as a way to target multiple compute nodes for the purpose of
requesting that images be pre-cached for performance reasons.

.. note::

    `Some of the virt drivers`_ provide image caching support, which improves performance
    of second-and-later boots of the same image by keeping the base image in an on-disk
    cache. This avoids the need to re-download the image from Glance, which reduces
    network utilization and time-to-boot latency. Image pre-caching is the act of priming
    that cache with images ahead of time to improve performance of the first boot.

.. _Some of the virt drivers: https://docs.openstack.org/nova/latest/user/support-matrix.html#operation_cache_images

Assuming an aggregate called ``my-aggregate`` where two images should
be pre-cached, running the following command will initiate the
request:

.. code-block:: console

    $ nova aggregate-cache-images my-aggregate image1 image2

Note that image pre-caching happens asynchronously in a best-effort
manner. The images and aggregate provided are checked by the server
when the command is run, but the compute nodes are not checked to see
if they support image caching until the process runs. Progress and
results are logged by each compute, and the process sends
``aggregate.cache_images.start``, ``aggregate.cache_images.progress``,
and ``aggregate.cache_images.end`` notifications, which may be useful
for monitoring the operation externally.

References
----------

- `Curse your bones, Availability Zones! (Openstack Summit Vancouver 2018)
  <https://www.openstack.org/videos/vancouver-2018/curse-your-bones-availability-zones-1>`__
