==============
Manage volumes
==============

Depending on the setup of your cloud provider, they may give you an endpoint to
use to manage volumes. You can use the ``openstack`` CLI to manage volumes.

For the purposes of the compute service, attaching, detaching and
:doc:`creating a server from a volume </user/launch-instance-from-volume>` are
of primary interest.

Refer to the :python-openstackclient-doc:`CLI documentation
<cli/command-objects/volume.html>` for more information.


Volume multi-attach
-------------------

Nova `added support for multiattach volumes`_ in the 17.0.0 Queens release.

This document covers the nova-specific aspects of this feature. Refer
to the :cinder-doc:`block storage admin guide
<admin/blockstorage-volume-multiattach.html>` for more details about creating
multiattach-capable volumes.

:term:`Boot from volume <Boot From Volume>` and attaching a volume to a server
that is not SHELVED_OFFLOADED is supported. Ultimately the ability to perform
these actions depends on the compute host and hypervisor driver that
is being used.

There is also a `recorded overview and demo`_ for volume multi-attach.

Requirements
~~~~~~~~~~~~

* The minimum required compute API microversion for attaching a
  multiattach-capable volume to more than one server is :ref:`2.60
  <api-microversion-queens>`.
* Cinder 12.0.0 (Queens) or newer is required.
* The ``nova-compute`` service must be running at least Queens release level
  code (17.0.0) and the hypervisor driver must support attaching block storage
  devices to more than one guest. Refer to :doc:`/user/support-matrix` for
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
via the ``tempest-full`` and ``tempest-slow`` jobs, which, along with the
tests themselves, are defined in the `tempest repository`_.

.. _added support for multiattach volumes: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/multi-attach-volume.html
.. _recorded overview and demo: https://www.youtube.com/watch?v=hZg6wqxdEHk
.. _tempest repository: http://codesearch.openstack.org/?q=CONF.compute_feature_enabled.volume_multiattach&i=nope&files=&repos=tempest

Managing volume attachments
---------------------------

During the lifecycle of an instance admins may need to check various aspects of
how a given volume is mapped both to an instance and the underlying compute
hosting the instance. This could even include refreshing different elements of
the attachment to ensure the latest configuration changes within the
environment have been applied.

Checking an existing attachment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Existing volume attachments can be checked using the following
:python-openstackclient-doc:`OpenStack Client commands <cli/command-objects>`:

List all volume attachments for a given instance:

.. code-block:: shell

    $ openstack server volume list 216f9481-4c9d-4530-b865-51cedfa4b8e7
    +--------------------------------------+----------+--------------------------------------+--------------------------------------+
    | ID                                   | Device   | Server ID                            | Volume ID                            |
    +--------------------------------------+----------+--------------------------------------+--------------------------------------+
    | 8b9b3491-f083-4485-8374-258372f3db35 | /dev/vdb | 216f9481-4c9d-4530-b865-51cedfa4b8e7 | 8b9b3491-f083-4485-8374-258372f3db35 |
    +--------------------------------------+----------+--------------------------------------+--------------------------------------+

List all volume attachments for a given instance with the Cinder volume
attachment and Block Device Mapping UUIDs also listed with microversion >=2.89:

.. code-block:: shell

    $ openstack --os-compute-api-version 2.89 server volume list 216f9481-4c9d-4530-b865-51cedfa4b8e7
    +----------+--------------------------------------+--------------------------------------+------+------------------------+--------------------------------------+--------------------------------------+
    | Device   | Server ID                            | Volume ID                            | Tag  | Delete On Termination? | Attachment ID                        | BlockDeviceMapping UUID              |
    +----------+--------------------------------------+--------------------------------------+------+------------------------+--------------------------------------+--------------------------------------+
    | /dev/vdb | 216f9481-4c9d-4530-b865-51cedfa4b8e7 | 8b9b3491-f083-4485-8374-258372f3db35 | None | False                  | d338fb38-cfd5-461f-8753-145dcbdb6c78 | 4e957e6d-52f2-44da-8cf8-3f1ab755e26d |
    +----------+--------------------------------------+--------------------------------------+------+------------------------+--------------------------------------+--------------------------------------+

List all Cinder volume attachments for a given volume from microversion >=
3.27:

.. code-block:: shell

    $ openstack --os-volume-api-version 3.27 volume attachment list --volume-id 8b9b3491-f083-4485-8374-258372f3db35
    +--------------------------------------+--------------------------------------+--------------------------------------+----------+
    | ID                                   | Volume ID                            | Server ID                            | Status   |
    +--------------------------------------+--------------------------------------+--------------------------------------+----------+
    | d338fb38-cfd5-461f-8753-145dcbdb6c78 | 8b9b3491-f083-4485-8374-258372f3db35 | 216f9481-4c9d-4530-b865-51cedfa4b8e7 | attached |
    +--------------------------------------+--------------------------------------+--------------------------------------+----------+

Show the details of a Cinder volume attachment from microversion >= 3.27:

.. code-block:: shell

    $ openstack --os-volume-api-version 3.27 volume attachment show d338fb38-cfd5-461f-8753-145dcbdb6c78
    +-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | Field       | Value                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
    +-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+
    | ID          | d338fb38-cfd5-461f-8753-145dcbdb6c78                                                                                                                                                                                                                                                                                                                                                                                                                                   |
    | Volume ID   | 8b9b3491-f083-4485-8374-258372f3db35                                                                                                                                                                                                                                                                                                                                                                                                                                   |
    | Instance ID | 216f9481-4c9d-4530-b865-51cedfa4b8e7                                                                                                                                                                                                                                                                                                                                                                                                                                   |
    | Status      | attached                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
    | Attach Mode | rw                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
    | Attached At | 2021-09-14T13:03:38.000000                                                                                                                                                                                                                                                                                                                                                                                                                                             |
    | Detached At |                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
    | Properties  | access_mode='rw', attachment_id='d338fb38-cfd5-461f-8753-145dcbdb6c78', auth_method='CHAP', auth_password='4XyNNFV2TLPhKXoP', auth_username='jsBMQhWZJXupA4eWHLQG', cacheable='False', driver_volume_type='iscsi', encrypted='False', qos_specs=, target_discovered='False', target_iqn='iqn.2010-10.org.openstack:volume-8b9b3491-f083-4485-8374-258372f3db35', target_lun='0', target_portal='192.168.122.99:3260', volume_id='8b9b3491-f083-4485-8374-258372f3db35' |
    +-------------+------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------+

Refresh a volume attachment with nova-manage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionadded:: 24.0.0 (Xena)

Admins may also refresh an existing volume attachment using the following
:program:`nova-manage` commands.

.. note::

    Users can also refresh volume attachments by shelving and later unshelving
    their instances. The following is an alternative to that workflow and
    useful for admins when having to mass refresh attachments across an
    environment.

.. note::

    Future work will look into introducing an os-refresh admin API that will
    include orchestrating the shutdown of an instance and refreshing volume
    attachments among other things.

To begin the admin can use the `volume_attachment show` subcommand to dump
existing details of the attachment directly from the Nova database. This
includes the stashed `connection_info` not shared by the API.

.. code-block:: shell

    $ nova-manage volume_attachment show 216f9481-4c9d-4530-b865-51cedfa4b8e7 8b9b3491-f083-4485-8374-258372f3db35 --json | jq .attachment_id
    "d338fb38-cfd5-461f-8753-145dcbdb6c78"

If the stored `connection_info` or `attachment_id` are incorrect then the
admin may want to refresh the attachment to the compute host entirely by
recreating the Cinder volume attachment record(s) and pulling down fresh
`connection_info`. To do this we first need to ensure the instance is stopped:

.. code-block:: shell

    $ openstack server stop 216f9481-4c9d-4530-b865-51cedfa4b8e7

Once stopped the host connector of the compute hosting the instance has to be
fetched using the `volume_attachment get_connector` subcommand:

.. code-block:: shell

    root@compute $ nova-manage volume_attachment get_connector --json > connector.json

.. note::

    Future work will remove this requirement and incorporate the gathering of
    the host connector into the main refresh command. Unfortunately until then
    it must remain a separate manual step.

We can then provide this connector to the `volume_attachment refresh`
subcommand. This command will connect to the compute, disconnect any host
volume connections, delete the existing Cinder volume attachment,
recreate the volume attachment and finally update Nova's database.

.. code-block:: shell

    $ nova-manage volume_attachment refresh 216f9481-4c9d-4530-b865-51cedfa4b8e7 8b9b3491-f083-4485-8374-258372f3db35 connector.json

The Cinder volume attachment and connection_info stored in the Nova database
should now be updated:

.. code-block:: shell

    $ nova-manage volume_attachment show 216f9481-4c9d-4530-b865-51cedfa4b8e7 8b9b3491-f083-4485-8374-258372f3db35 --json | jq .attachment_id
    "9ce46f49-5cfc-4c6c-b2f0-0287540d3246"

The instance can then be restarted and the event list checked

.. code-block:: shell

    $ openstack server start $instance
