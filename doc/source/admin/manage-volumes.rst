==============
Manage volumes
==============

Depending on the setup of your cloud provider, they may give you an endpoint to
use to manage volumes. You can use the ``openstack`` CLI to manage volumes.

For the purposes of the compute service, attaching, detaching and
:doc:`creating a server from a volume <../user/launch-instance-from-volume>`
are of primary interest.

Refer to the `block storage service CLI guide on managing volumes
<https://docs.openstack.org/cinder/latest/cli/cli-manage-volumes.html>`_.


Volume multi-attach
-------------------

Nova `added support for multiattach volumes`_ in the 17.0.0 Queens release.

This document covers the nova-specific aspects of this feature. Refer
to the `block storage admin guide`_ for more details about creating
multiattach-capable volumes.

Boot from volume and attaching a volume to a server that is not
SHELVED_OFFLOADED is supported. Ultimately the ability to perform
these actions depends on the compute host and hypervisor driver that
is being used.

Requirements
~~~~~~~~~~~~

* The minimum required compute API microversion for attaching a
  multiattach-capable volume to more than one server is `2.60`_.
* Cinder 12.0.0 (Queens) or newer is required.
* The ``nova-compute`` service must be running at least Queens release level
  code (17.0.0) and the hypervisor driver must support attaching block storage
  devices to more than one guest. Refer to the `feature support matrix`_ for
  details on which compute drivers support volume multiattach.
* When using the libvirt compute driver, the following native package versions
  determine multiattach support:

  * libvirt must be greater than or equal to 3.10, or
  * qemu must be less than 2.10

* Swapping an *in-use* multiattach volume is not supported (this is actually
  controlled via the block storage volume retype API).

Known issues
~~~~~~~~~~~~

* Creating multiple servers in a single request with a multiattach-capable
  volume as the root disk is not yet supported: https://bugs.launchpad.net/nova/+bug/1747985
* Subsequent attachments to the same volume are all attached in *read/write*
  mode by default in the block storage service. A future change either in nova
  or cinder may address this so that subsequent attachments are made in
  *read-only* mode, or such that the mode can be specified by the user when
  attaching the volume to the server.

Testing
~~~~~~~

Continuous integration testing of the volume multiattach feature is done
via the ``nova-multiattach`` job, defined in the `nova repository`_.

The tests are defined in the `tempest repository`_.

The CI job is setup to run with the **libvirt** compute driver and the **lvm**
volume back end. It purposefully does not use the Pike Ubuntu Cloud Archive
package mirror so that it gets qemu<2.10.

.. _added support for multiattach volumes: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/multi-attach-volume.html
.. _block storage admin guide: https://docs.openstack.org/cinder/latest/admin/blockstorage-volume-multiattach.html
.. _2.60: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#maximum-in-queens
.. _feature support matrix: https://docs.openstack.org/nova/latest/user/support-matrix.html#operation_multiattach_volume
.. _nova repository: http://git.openstack.org/cgit/openstack/nova/tree/playbooks/legacy/nova-multiattach/run.yaml
.. _tempest repository: http://codesearch.openstack.org/?q=CONF.compute_feature_enabled.volume_multiattach&i=nope&files=&repos=tempest
