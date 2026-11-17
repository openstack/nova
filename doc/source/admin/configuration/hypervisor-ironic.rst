======
Ironic
======

Introduction
------------

The ironic hypervisor driver wraps the Bare Metal (ironic) API,
enabling Nova to provision baremetal resources using the same
user-facing API as for server management.

This is the only driver in nova where one compute service can map to many
hosts, meaning a ``nova-compute`` service can manage multiple ``ComputeNodes``.
An ironic driver managed compute service uses the ironic ``node uuid`` for the
compute node ``hypervisor_hostname`` (nodename) and ``uuid`` fields.  The
relationship of ``instance:compute node:ironic node`` is 1:1:1.

Scheduling of bare metal nodes is based on custom resource classes, specified
via the ``resource_class`` property on a node and a corresponding resource
property on a flavor (see the :ironic-doc:`flavor documentation
<install/configure-nova-flavors.html>`).
The RAM and CPU settings on a flavor are ignored, and the disk is only used to
determine the root partition size when a partition image is used (see the
:ironic-doc:`image documentation
<install/configure-glance-images.html>`).

VNC console support
-------------------

The nova noVNC VNC console service can connect to bare metal nodes when
ironic has
:ironic-doc:`Graphical console support<install/graphical-console.html>`
enabled and configured.

Configuration
-------------

- :ironic-doc:`Configure the Compute service to use the Bare Metal service
  <install/configure-compute.html>`.

- :ironic-doc:`Create flavors for use with the Bare Metal service
  <install/configure-nova-flavors.html>`.

- :ironic-doc:`Conductors Groups <admin/conductor-groups.html>`.


Scaling and performance issues
------------------------------

- It is typical for a single nova-compute process to support several
  hundred Ironic nodes. There are known issues when you attempt to
  support more than 1000 Ironic nodes associated with a single
  nova-compute process, even though Ironic is able to scale out
  a single conductor group to much larger sizes. There are many
  other factors that can affect what is the maximum practical size of
  a conductor group within your deployment.
- The ``update_available_resource`` periodic task reports all the resources
  managed by Ironic. Depending the number of nodes, it can take a lot of time.
  You can use Ironic shards to help shard your deployment between multiple
  nova-compute processes by setting :oslo.config:option:`ironic.shard` on a
  per nova-compute basis. Setting the shard key restricts a nova-compute
  instance to only manage a subset of Ironic nodes.

  Large Ironic deployments can also tune
  :oslo.config:option:`compute.update_resources_max_workers` to update
  multiple nodes concurrently within a single nova-compute service. The
  default value of ``1`` preserves the previous sequential behavior. Increasing
  the value can reduce nova-compute startup and periodic resource-reporting
  latency, but also increases nova-compute CPU usage and concurrent Placement
  API traffic. Increase it gradually and monitor nova-compute and Placement
  service load.
- The nova-compute process using the Ironic driver can be moved between
  different physical servers using active/passive failover. But when doing
  this failover, you must ensure :oslo.config:option:`host` is the same
  no matter where the nova-compute process is running. Similarly you must
  ensure there are at most one nova-compute processes running for each
  conductor group.
- Running multiple nova-compute processes that point at the same
  conductor group is now deprecated. Please never have more than one
  host in the peer list: :oslo.config:option:`ironic.peer_list`


Known limitations / Missing features
------------------------------------

* Migrate
* Resize
* Snapshot
* Pause
* Shelve
* Evacuate
