===================
Evacuate vs Rebuild
===================

The `evacuate API`_ and `rebuild API`_ are commonly confused in nova because
the internal `conductor code`_ and `compute code`_ use the same methods called
``rebuild_instance``. This document explains some of the differences in what
happens between an evacuate and rebuild operation.

High level
~~~~~~~~~~

*Evacuate* is an operation performed by an administrator when a compute service
or host is encountering some problem, goes down and needs to be fenced from the
network. The servers that were running on that compute host can be rebuilt on
a **different** host using the **same** image. If the source and destination
hosts are running on shared storage then the root disk image of the servers can
be retained otherwise the root disk image (if not using a volume-backed server)
will be lost. This is one example of why it is important to attach data volumes
to a server to store application data and leave the root disk for the operating
system since data volumes will be re-attached to the server as part of the
evacuate process.

*Rebuild* is an operation which can be performed by a non-administrative owner
of the server (the user) performed on the **same** compute host to change
certain aspects of the server, most notably using a **different** image. Note
that the image does not *have* to change and in the case of volume-backed
servers the image `currently cannot change`_. Other attributes of the server
can be changed as well such as ``key_name`` and ``user_data``. See the
`rebuild API`_ reference for full usage details. When a user rebuilds a server
they want to change it which requires re-spawning the guest in the hypervisor
but retain the UUID, volumes and ports attached to the server. For a
non-volume-backed server the root disk image is rebuilt.

Scheduling
~~~~~~~~~~

Evacuate always schedules the server to another host and rebuild always occurs
on the same host.

Note that when `rebuilding with a different image`_, the request is run through
the scheduler to ensure the new image is still valid for the current compute
host.

Image
~~~~~

As noted above, the image that the server uses during an evacuate operation
does not change. The image used to rebuild a server *may* change but does not
have to and in the case of volume-backed servers *cannot* change.

Resource claims
~~~~~~~~~~~~~~~

The compute service ``ResourceTracker`` has a `claims`_ operation which is used
to ensure resources are available before building a server on the host. The
scheduler performs the initial filtering of hosts to ensure a server
can be built on a given host and the compute claim is essentially meant as a
secondary check to prevent races when the scheduler has out of date information
or when there are concurrent build requests going to the same host.

During an evacuate operation there is a `rebuild claim`_ since the server is
being re-built on a different host.

During a rebuild operation, since the flavor does not change, there is
`no claim`_ made since the host does not change.

Allocations
~~~~~~~~~~~

Since the 16.0.0 (Pike) release, the scheduler uses the `placement service`_
to filter compute nodes (resource providers) based on information in the flavor
and image used to build the server. Once the scheduler runs through its filters
and weighers and picks a host, resource class `allocations`_ are atomically
consumed in placement with the server as the consumer.

During an evacuate operation, the allocations held by the server consumer
against the source compute node resource provider are left intact since the
source compute service is down. Note that `migration-based allocations`_,
which were introduced in the 17.0.0 (Queens) release, do not apply to evacuate
operations but only resize, cold migrate and live migrate. So once a server
is successfully evacuated to a different host, the placement service will track
allocations for that server against both the source and destination compute
node resource providers. If the source compute service is restarted after
being evacuated and fixed, the compute service will
`delete the old allocations`_ held by the evacuated servers.

During a rebuild operation, since neither the host nor flavor changes, the
server allocations remain intact.

.. _evacuate API: https://docs.openstack.org/api-ref/compute/#evacuate-server-evacuate-action
.. _rebuild API: https://docs.openstack.org/api-ref/compute/#rebuild-server-rebuild-action
.. _conductor code: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/conductor/manager.py#L944
.. _compute code: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L3052
.. _currently cannot change: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/volume-backed-server-rebuild.html
.. _rebuilding with a different image: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/api.py#L3414
.. _claims: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/claims.py
.. _rebuild claim: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L3104
.. _no claim: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L3108
.. _placement service: https://docs.openstack.org/placement/latest/
.. _allocations: https://docs.openstack.org/api-ref/placement/#allocations
.. _migration-based allocations: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/migration-allocations.html
.. _delete the old allocations: https://opendev.org/openstack/nova/src/tag/19.0.0/nova/compute/manager.py#L627
