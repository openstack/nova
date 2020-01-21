Ironic
======

Introduction
------------
The ironic hypervisor driver wraps the Bare Metal (ironic) API,
enabling Nova to provision baremetal resources using the same
user-facing API as for server management.

This is the only driver in nova where one compute service can map to many hosts
, meaning a ``nova-compute`` service can manage multiple ``ComputeNodes``. An
ironic driver managed compute service uses the ironic ``node uuid`` for the
compute node ``hypervisor_hostname`` (nodename) and ``uuid`` fields.
The relationship of ``instance:compute node:ironic node`` is ``1:1:1``.

Scheduling of bare metal nodes is based on custom resource classes, specified
via the ``resource_class`` property on a node and a corresponding resource
property on a flavor (see the `flavor documentation`_).
The RAM and CPU settings on a flavor are ignored, and the disk is only used to
determine the root partition size when a partition image is used (see the
`image documentation`_).


.. _flavor documentation: https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html
.. _image documentation: https://docs.openstack.org/ironic/latest/install/configure-glance-images.html

Configuration
-------------

- `Configure the Compute service to use the Bare Metal service
  <https://docs.openstack.org/ironic/latest/install/configure-compute.html>`_.

- `Create flavors for use with the Bare Metal service
  <https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html>`__.

- `Conductors Groups
  <https://docs.openstack.org/ironic/latest/admin/conductor-groups.html>`_.


Scaling and Performance Issues
------------------------------

- The ``update_available_resource`` periodic task reports all the resources
  managed by Ironic. Depending the number of nodes, it can take a lot of time.
  The nova-compute will not perform any other operations when this task is
  running. You can use conductor groups to help scale, by setting
  :oslo.config:option:`ironic.partition_key`.



Known limitations / Missing features
------------------------------------

* Migrate
* Resize
* Snapshot
* Pause
* Shelve
* Evacuate
