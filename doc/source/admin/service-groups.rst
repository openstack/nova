================================
Configure Compute service groups
================================

The Compute service must know the status of each compute node to effectively
manage and use them. This can include events like a user launching a new VM,
the scheduler sending a request to a live node, or a query to the ServiceGroup
API to determine if a node is live.

When a compute worker running the nova-compute daemon starts, it calls the join
API to join the compute group. Any service (such as the scheduler) can query
the group's membership and the status of its nodes.  Internally, the
ServiceGroup client driver automatically updates the compute worker status.

.. _database-servicegroup-driver:

Database ServiceGroup driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

By default, Compute uses the database driver to track if a node is live.  In a
compute worker, this driver periodically sends a ``db update`` command to the
database, saying “I'm OK” with a timestamp. Compute uses a pre-defined
timeout (``service_down_time``) to determine if a node is dead.

The driver has limitations, which can be problematic depending on your
environment. If a lot of compute worker nodes need to be checked, the database
can be put under heavy load, which can cause the timeout to trigger, and a live
node could incorrectly be considered dead. By default, the timeout is 60
seconds. Reducing the timeout value can help in this situation, but you must
also make the database update more frequently, which again increases the
database workload.

The database contains data that is both transient (such as whether the node is
alive) and persistent (such as entries for VM owners). With the ServiceGroup
abstraction, Compute can treat each type separately.

.. _memcache-servicegroup-driver:

Memcache ServiceGroup driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The memcache ServiceGroup driver uses memcached, a distributed memory object
caching system that is used to increase site performance. For more details, see
`memcached.org <http://memcached.org/>`_.

To use the memcache driver, you must install memcached. You might already have
it installed, as the same driver is also used for the OpenStack Object Storage
and OpenStack dashboard. To install memcached, see the *Environment ->
Memcached* section in the `Installation Tutorials and Guides
<https://docs.openstack.org/project-install-guide/ocata>`_ depending on your
distribution.

These values in the ``/etc/nova/nova.conf`` file are required on every node for
the memcache driver:

.. code-block:: ini

   # Driver for the ServiceGroup service
   servicegroup_driver = "mc"

   # Memcached servers. Use either a list of memcached servers to use for caching (list value),
   # or "<None>" for in-process caching (default).
   memcached_servers = <None>

   # Timeout; maximum time since last check-in for up service (integer value).
   # Helps to define whether a node is dead
   service_down_time = 60
