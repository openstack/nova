=============
Server Groups
=============

Server groups provide a mechanism for indicating the locality of servers
relative to other servers. They allow you to indicate whether servers should
run on the same host (affinity) or different hosts (anti-affinity). Affinity is
advantageous if you wish to minimise network latency, while anti-affinity can
improve fault-tolerance and load distribution.

.. note::

    Server groups are useful for separating or grouping workloads but should
    not generally be relied on to provide HA. Instead, consider using
    availability zones. Unlike server groups, availability zones can only be
    configured by admins but they are often used to model failure domains,
    particularly in larger deployments. For more information, refer to
    :doc:`/user/availability-zones`.

Server groups can be configured with a policy and rules. There are currently
four policies supported:

``affinity``
  Restricts instances belonging to the server group to the same host.

``anti-affinity``
  Restricts instances belonging to the server group to separate hosts.

``soft-affinity``
  Attempts to restrict instances belonging to the server group to the same
  host. Where it is not possible to schedule all instances on one host,
  they will be scheduled together on as few hosts as possible.

  .. note::

      Requires API microversion 2.15 or later.

``soft-anti-affinity``
  Attempts to restrict instances belonging to the server group to separate
  hosts. Where it is not possible to schedule all instances to separate hosts,
  they will be scheduled on as many separate hosts as possible.

  .. note::

      Requires API microversion 2.15 or later.

There is currently one rule supported:

``max_server_per_host``
  Indicates the max number of instances that can be scheduled to any given
  host when using the ``anti-affinity`` policy. This rule is not compatible
  with other policies.

  .. note::

      Requires API microversion 2.64 or later.


Usage
-----

Server groups can be configured and used by end-users. For example:

.. code-block:: console

    $ openstack --os-compute-api-version 2.64 server group create \
        --policy POLICY --rule RULE NAME

Once a server group has been created, you can use it when creating a server.
This is achieved using the ``--hint`` option. For example:

.. code-block:: console

    $ openstack server create \
        --hint group=SERVER_GROUP_UUID ... NAME

Once created, a server group cannot be modified. In addition, a server cannot
move between server groups. In both cases, this is because doing so would
require potentially moving the server to satisfy the server group policy.
