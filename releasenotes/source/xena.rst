=========================
Xena Series Release Notes
=========================

.. _Release Notes_24.2.1-17_xena-eom:

24.2.1-17
=========

.. _Release Notes_24.2.1-17_xena-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/service-user-token-421d067c16257782.yaml @ b'b574901500d936488cdedf9fda90c4d36eeddd97'

- Configuration of service user tokens is now **required** for all Nova services
  to ensure security of block-storage volume data.

  All Nova configuration files must configure the ``[service_user]`` section as
  described in the `documentation`__.

  See https://bugs.launchpad.net/nova/+bug/2004555 for more details.

  __ https://docs.openstack.org/nova/latest/admin/configuration/service-user-token.html


.. _Release Notes_24.2.1-17_xena-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1970383-segment-scheduling-permissions-92ba907b10a9eb1c.yaml @ b'28f94eb69a9b8267275460d0dbc18b3d7309cebd'

- `Bug #1970383 <https://bugs.launchpad.net/nova/+bug/1970383>`_: Fixes a
  permissions error when using the
  'query_placement_for_routed_network_aggregates' scheduler variable, which
  caused a traceback on instance creation for non-admin users.

.. releasenotes/notes/bug-1983753-update-requestspec-pci_request-for-resize-a3c6b0a979db723f.yaml @ b'cbf785709968fffc0a760e28f1cdb5c38b254232'

- `Bug #1941005 <https://bugs.launchpad.net/nova/+bug/1941005>`_ is fixed.
  During resize Nova now uses the PCI requests from the new flavor to select
  the destination host.

.. releasenotes/notes/rescue-volume-based-instance-c6e3fba236d90be7.yaml @ b'c977027b1933e408c58508e883f6a799ffacc4cc'

- Fix rescuing volume based instance by adding a check for 'hw_rescue_disk'
  and 'hw_rescue_device' properties in image metadata before attempting
  to rescue instance.


.. _Release Notes_24.2.0_xena-eom:

24.2.0
======

.. _Release Notes_24.2.0_xena-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1942329-22b08fa4b322881d.yaml @ b'a340630c5c78e5f5856004d0a551dfa93df7f28d'

- As a fix for `bug 1942329 <https://bugs.launchpad.net/neutron/+bug/1942329>`_
  nova now updates the MAC address of the ``direct-physical`` ports during
  mova operations to reflect the MAC address of the physical device on the
  destination host. Those servers that were created before this fix need to be
  moved or the port needs to be detached and the re-attached to synchronize the
  MAC address.

.. releasenotes/notes/bug-1958636-smm-check-and-enable.yaml @ b'62e1a621d19e8833a18afdba86de7f8334171c63'

- [`bug 1958636 <https://bugs.launchpad.net/nova/+bug/1958636>`_]
  Explicitly check for and enable SMM when firmware requires it.
  Previously we assumed libvirt would do this for us but this is
  not true in all cases.

.. releasenotes/notes/bug-1978444-db46df5f3d5ea19e.yaml @ b'14f9b7627e8a48f546e2f1c79d4336e1e4923501'

- `Bug #1978444 <https://bugs.launchpad.net/nova/+bug/1978444>`_: Now nova
  retries deleting a volume attachment in case Cinder API returns
  ``504 Gateway Timeout``. Also, ``404 Not Found`` is now ignored and
  leaves only a warning message.

.. releasenotes/notes/bug-1981813-vnic-type-change-9f3e16fae885b57f.yaml @ b'1a98a1a650d065a8ab3e1c474f3b9fd537dc2206'

- `Bug #1981813 <https://bugs.launchpad.net/nova/+bug/1981813>`_: Now nova
  detects if the ``vnic_type`` of a bound port has been changed in neutron
  and leaves an ERROR message in the compute service log as such change on a
  bound port is not supported. Also the restart of the nova-compute service
  will not crash any more after such port change. Nova will log an ERROR and
  skip the  initialization of the instance with such port during the startup.

.. releasenotes/notes/greendns-34df7f9fba952bcd.yaml @ b'a913ab1aabb827771e54ef64b579cebe44ad53d1'

- During the havana cycle it was discovered that eventlet
  monkey patching of greendns broke ipv6.
  https://bugs.launchpad.net/nova/+bug/1164822
  Since then nova has been disabling eventlet monkey patching
  of greendns. Eventlet addressed the ipv6 limitation in v0.17
  with the introduction of python 3 support in 2015. Nova
  however continued to disable it, which can result i slow dns
  queries blocking the entire nova api or other binary
  because socket.getaddrinfo becomes a blocking call into glibc
  see: https://bugs.launchpad.net/nova/+bug/1964149 for
  more details.

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'8e9aa71e1a4d3074a94911db920cae44334ba2c3'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/vdpa-move-ops-a7b3799807807a92.yaml @ b'c3092e3ee791d9e291f829cc3eaa8123560a13ef'

- When vDPA was first introduced move operations were implemented in the code
  but untested either in a real environment or in functional tests. Due to
  this gap nova elected to block move operations for instance with vDPA
  devices. All move operations except for live migration have now been tested
  and found to indeed work so the API blocks have now been removed and
  functional tests introduced. Other operations such as suspend and
  live migration require code changes to support and will be enabled as new
  features in the future.


.. _Release Notes_24.2.0_xena-eom_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1982284-libvirt-handle-no-ram-info-was-set-99784934ed80fd72.yaml @ b'98d9936e54b900db1bd2d5477a9a1d7e5a7be104'

- A workaround has been added to the libvirt driver to catch and pass
  migrations that were previously failing with the error:

  ``libvirt.libvirtError: internal error: migration was active, but no RAM info was set``

  See `bug 1982284`_ for more details.

  .. _bug 1982284: https://bugs.launchpad.net/nova/+bug/1982284


.. _Release Notes_24.1.1_xena-eom:

24.1.1
======

.. _Release Notes_24.1.1_xena-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1944619-fix-live-migration-rollback.yaml @ b'90c51902e9ff9fcc23cba00904a0a5d9db6a5d6a'

- Instances with hardware offloaded ovs ports no longer lose connectivity
  after failed live migrations. The driver.rollback_live_migration_at_source
  function is no longer called during during pre_live_migration rollback
  which previously resulted in connectivity loss following a failed live
  migration. See `Bug 1944619`_ for more details.

  .. _Bug 1944619: https://bugs.launchpad.net/nova/+bug/1944619

.. releasenotes/notes/bug-1948705-ff80ae392c525475.yaml @ b'15c32e89e4f5ad7823c490c976075280c5dfccd9'

- Amended the guest resume operation to support mediated devices, as
  libvirt's minimum required version (v6.0.0) supports the hot-plug/unplug of
  mediated devices, which was addressed in v4.3.0.

.. releasenotes/notes/bug-1960230-cleanup-instances-dir-resize-56282e1b436a4908.yaml @ b'31179f62f1c832e0e894d04e9c9dd59978577cc0'

- Fixed bug `1960230 <https://bugs.launchpad.net/nova/+bug/1960230>`_ that
  prevented resize of instances that had previously failed and not been
  cleaned up.

.. releasenotes/notes/bug-1960401-504eb255253d966a.yaml @ b'a46fc40aa4edde4d426c95999bdac1c315d0276d'

- The `bug 1960401`_  is fixed which can cause invalid ``BlockDeviceMappings``
  to accumulate in the database. This prevented the respective volumes from
  being attached again to the instance.

  .. _bug 1960401: https://bugs.launchpad.net/nova/+bug/1960401

.. releasenotes/notes/fix-ironic-compute-restart-port-attachments-3282e9ea051561d4.yaml @ b'eb6d70f02daa14920a2522e5c734a3775ea2ea7c'

- Fixes slow compute restart when using the ``nova.virt.ironic`` compute
  driver where the driver was previously attempting to attach VIFS on
  start-up via the ``plug_vifs`` driver method. This method has grown
  otherwise unused since the introduction of the ``attach_interface``
  method of attaching VIFs. As Ironic manages the attachment of VIFs to
  baremetal nodes in order to align with the security requirements of a
  physical baremetal node's lifecycle. The ironic driver now ignores calls
  to the ``plug_vifs`` method.


.. _Release Notes_24.1.0_xena-eom:

24.1.0
======

.. _Release Notes_24.1.0_xena-eom_New Features:

New Features
------------

.. releasenotes/notes/announce-self-post-live-migration-936721b1ab887514.yaml @ b'a8981422afdd09f8cfea053e592c15e771fbe969'

- Added a new configuration option ``[workarounds]/enable_qemu_monitor_announce_self``
  that when enabled causes the Libvirt driver to send a announce_self QEMU
  monitor command post live-migration. Please see `bug 1815989 <https://bugs.launchpad.net/nova/+bug/1815989>`_
  for more details. Please note that this causes the domain to be considered
  tainted by libvirt.


.. _Release Notes_24.1.0_xena-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1946729-wait-for-vif-plugged-event-during-hard-reboot-fb491f6a68370bab.yaml @ b'0c41bfb8c5c60f1cc930ae432e6be460ee2e97ac'

- The libvirt virt driver in Nova implements power on and hard reboot by
  destroying the domain first and unplugging the vifs then recreating the
  domain and replugging the vifs. However nova does not wait for the
  network-vif-plugged event before unpause the domain. This can cause
  the domain to start running and requesting IP via DHCP before the
  networking backend has finished plugging the vifs. The config option
  [workarounds]wait_for_vif_plugged_event_during_hard_reboot has been added,
  defaulting to an empty list, that can be used to ensure that the libvirt
  driver waits for the network-vif-plugged event for vifs with specific
  ``vnic_type`` before it unpauses the domain during hard reboot. This should
  only be used if the deployment uses a networking backend that sends such
  event for the given ``vif_type`` at vif plug time. The ml2/ovs and the
  networking-odl Neutron backend is known to send plug time events for ports
  with ``normal`` ``vnic_type``.  For more information see
  https://bugs.launchpad.net/nova/+bug/1946729


.. _Release Notes_24.1.0_xena-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821088-reject-duplicate-port-ids-a38739d67d5d7c5d.yaml @ b'd4c92bc2314c6402c4e3464a5aa61a94293eaf91'

- The ``POST /servers`` (create server) API will now reject attempts to
  create a server with the same port specified multiple times. This was
  previously accepted by the API but the instance would fail to spawn and
  would instead transition to the error state.

.. releasenotes/notes/bug-1829479-cd2db21526965e6d.yaml @ b'037e588788e60d7b51ebe2cbb0787b3008f402fd'

- `Bug #1829479 <https://bugs.launchpad.net/nova/+bug/1829479>`_: Now
  deleting a nova-compute service removes allocations of successfully
  evacuated instances. This allows the associated resource provider to be
  deleted automatically even if the nova-compute service cannot recover after
  all instances on the node have been successfully evacuated.

.. releasenotes/notes/bug-1952941-request-spec-numa-topology-migration-c97dbd51b3c6c116.yaml @ b'7f6ec8cf546cf8f437ee94bb2308447427f54ada'

- The `bug 1952941`_  is fixed where a pre-Victoria server with pinned
  CPUs cannot be migrated or evacuated after the cloud is upgraded to
  Victoria or newer as the scheduling fails with
  ``NotImplementedError: Cannot load 'pcpuset'`` error.

  .. _bug 1952941: https://bugs.launchpad.net/nova/+bug/1952941

.. releasenotes/notes/bug-retry-corrupted-download-5798b0df44a00e4e.yaml @ b'b44ec0dc4927046d15525af78ab9d534cea9ce69'

- `Bug 1950657 <https://bugs.launchpad.net/nova/+bug/1950657>`_, fixing
  behavior when nova-compute wouldn't retry image download when gets
  "Corrupt image download" error from glanceclient and has num_retries
  config option set.


.. _Release Notes_24.0.0_xena-eom:

24.0.0
======

.. _Release Notes_24.0.0_xena-eom_Prelude:

Prelude
-------

.. releasenotes/notes/xena-prelude-515ee8a9e1f71c18.yaml @ b'73d78f01a0d0d20164c3f6b5f3daf1dc2f0bf7a4'

The 24.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 23.0.0 (Wallaby) to 24.0.0 (Xena).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Xena is v2.90.
  Details on REST API microversions added since the 23.0.0 Wallaby release
  can be found in the `REST API Version History`__ page.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html

- `Support for accelerators`__ in Nova servers has been improved. Now
  Cyborg-managed SmartNICs can be attached as SR-IOV devices.

  .. __: https://docs.openstack.org/api-guide/compute/accelerator-support.html


- Two new ``nova-manage`` CLI commands can be used for `checking`__ the
  volume attachment connection information and for `refreshing`__ it if the
  connection is stale (for example with a Ceph backing store and MON IP
  addresses). Some documentation on how to use them can be found `here`__.

  .. __: https://docs.openstack.org/nova/latest/cli/nova-manage.html#volume-attachment-get-connector
  .. __: https://docs.openstack.org/nova/latest/cli/nova-manage.html#volume-attachment-refresh
  .. __: https://docs.openstack.org/nova/latest/admin/manage-volumes.html#managing-volume-attachments

- Instance hostnames published by the metadata API service or config drives
  can be explicitly defined at instance creation time thanks to the new
  `2.90 API microversion`__. See the ``hostname`` field documentation on
  the `API docs`__ for further details.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#maximum-in-xena
  .. __: https://docs.openstack.org/api-ref/compute/?expanded=create-server-detail#create-server

- Libvirt virt driver now supports any PCI device, not just virtual
  GPUs, that are using the ``VFIO-mdev`` virtualization framework, like
  network adapters or compute accelerators. `See more in the spec`__.

  .. __: https://specs.openstack.org/openstack/nova-specs/specs/xena/approved/generic-mdevs.html


.. _Release Notes_24.0.0_xena-eom_New Features:

New Features
------------

.. releasenotes/notes/add-attachment-id-to-os-volume-attachments-a23818d5b11f15a1.yaml @ b'ac21c6674c8444edc5afd25b7d63936182fe3580'

- Microversion 2.89 has been introduced and will include the
  ``attachment_id`` of a volume attachment, ``bdm_uuid`` of the block device
  mapping record and removes the duplicate ``id`` from the responses for ``GET
  /servers/{server_id}/os-volume_attachments`` and ``GET
  /servers/{server_id}/os-volume_attachments/{volume_id}``.

.. releasenotes/notes/add-nova-manage-bdm-commands-19f360dd85c1e81d.yaml @ b'e906a8c0ec87b870b0ae75c20cf1d2da36433636'

- A number of commands have been managed to ``nova-manage`` to help update
  stale volume attachment connection info for a given volume and instance.

  * The ``nova-manage volume_attachment show`` command can be used to show
    the current volume attachment information for a given volume and
    instance.

  * The ``nova-manage volume_attachment get_connector`` command can
    be used to get updated host connector for the localhost.

  * Finally, the ``nova-manage volume_attachment refresh`` command can be
    used to update the volume attachment with this updated connection
    information.

.. releasenotes/notes/archive-sleep-a0cc3d3e7784e5df.yaml @ b'fc77ce191fe9393be815bc32e6da867808dab054'

- A ``--sleep`` option has been added to the ``nova-manage db
  archive_deleted_rows`` CLI. When this command is run with the
  ``--until-complete`` option, the process will archive rows in batches
  in a tight loop, which can cause problems in busy environments where
  the aggressive archiving interferes with other requests trying to write
  to the database. The ``--sleep`` option can be used to specify a time to
  sleep between batches of rows while archiving with ``--until-complete``,
  allowing the process to be throttled.

.. releasenotes/notes/archive-task-logs-fa9dd7c5859b5e30.yaml @ b'd093849c3c70e46bf409b1051454cbf70bc12a1f'

- A ``--task-log`` option has been added to the ``nova-manage db
  archive_deleted_rows`` CLI. When ``--task-log`` is specified, ``task_log``
  table records will be archived while archiving the database. The
  ``--task-log`` option works in conjunction with ``--before`` if operators
  desire archiving only records that are older than ``<date>``. The
  ``updated_at`` field is used by ``--task-log --before <date>`` to determine
  the age of a ``task_log`` record for archival.

  The ``task_log`` database table contains instance usage audit records if
  ``nova-compute`` has been configured with ``[DEFAULT]instance_usage_audit =
  True``. This will be the case if OpenStack Telemetry is being used in the
  deployment, as the option causes Nova to generate audit notifications that
  Telemetry consumes from the message bus.

  Usage data can also be later retrieved by calling the
  ``/os-instance_usage_audit_log`` REST API [1].

  Historically, there has been no way to delete ``task_log`` table records
  other than manual database modification. Because of this, ``task_log``
  records could pile up over time and operators are forced to perform manual
  steps to periodically truncate the ``task_log`` table.

  [1] https://docs.openstack.org/api-ref/compute/#server-usage-audit-log-os-instance-usage-audit-log

.. releasenotes/notes/generic_mdevs_2-d1b1c71e8035527f.yaml @ b'9be996c696e91e82d11d81db72ffb4cc151598b6'

- A new configuration option is now available for supporting PCI devices that
  use the `VFIO-mdev`_ kernel framework and are stateless. Instead of using
  the ``VGPU`` resource class for both the inventory and the related
  allocations, the operator could ask to use another custom resource class
  for a specific mdev type by using the dynamic ``mdev_class``.

  .. _`VFIO-mdev` : https://www.kernel.org/doc/html/latest/driver-api/vfio-mediated-device.html

.. releasenotes/notes/libvirt-vmcoreinfo-3be69e21dfe7dbd2.yaml @ b'740e6f09bf5a3e5ab3c6dd6d412dd1fe33f81d9f'

- When using the libvirt virt driver with the QEMU or KVM backends, instances
  will now be created with the *vmcoreinfo* feature enabled by default. This
  creates a fw_cfg entry for a guest to store dump details, necessary to
  process kernel dump with KASLR enabled and providing additional kernel
  details. For more information, refer to the `libvirt`__ documentation.

  __ https://libvirt.org/formatdomain.html#hypervisor-features

.. releasenotes/notes/microversion-2-90-59fb6d4ec420b9f4.yaml @ b'cfa33d3b06a279f8f6dc6ad7d76d49feb36b0ace'

- The 2.90 microversion has been added. This microversion allows users to
  specify a requested hostname to be configured for the instance metadata
  when creating an instance (``POST /servers``), updating an instance
  (``PUT /servers/{id}``), or rebuilding an instance
  (``POST /servers/{server_id}/action (rebuild)``). When specified, this
  hostname replaces the hostname that nova auto-generates from the instance
  display name. As with the auto-generated hostnames, a service such as
  ``cloud-init`` can automatically configure the hostname in the guest OS
  using this information retrieved from the metadata service.

  In addition, starting with the 2.90 microversion, the
  ``OS-EXT-SRV-ATTR:hostname`` field is now returned for all users.
  Previously this was restricted to admin users.

.. releasenotes/notes/releasenotes/notes/bochs-ffaa289da97d08c8.yaml @ b'c59084397401c690c6b23b5c8631138ec85e8f04'

- Add support for the ``bochs`` libvirt video model.  This is a
  legacy-free video model that is best suited for UEFI guests.  In
  limited cases (e.g. if the guest does not depend on direct VGA
  hardware access), it can be usable for BIOS guests as well.

.. releasenotes/notes/smartnic-support-0339efe4b68075fe.yaml @ b'1f53176d2f4303b909ecad18cb0f027bfcd0b7ae'

- Add support for smartnic via Cyborg device profiles in Neutron ports with
  vnic type ``accelerator-direct``. When such port is used Cyborg will
  manage the smartnic and Nova will pass through the smartnic VF to the
  server. Note that while vnic type ``accelerator-direct-physical`` also
  exists in Neutron it is not yet supported by Nova and the server create
  request will fail with such port.


.. _Release Notes_24.0.0_xena-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/libvirt-disable-apic-39599bdc2d110a1f.yaml @ b'ec48e1523dfdd0f1031e1a70c28c56962db66e8a'

- Linux guest images that have known kernel bugs related to virtualized apic
  initialization previously would sporadically hang. For images where the
  kernel cannot be upgraded, a ``[workarounds]`` config option has been
  introduced:

  ``[workarounds]libvirt_disable_apic``

  This option is primarily intended for CI and development clouds as a bridge
  for operators to mitigate the issue while they work with their upstream
  image vendors.


.. _Release Notes_24.0.0_xena-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1910466-max-vcpu-topologies-with-numa-9a9ceb1b0fc7c33d.yaml @ b'387823b36d091abbaa37efb930fc98b94a5bbb93'

- As part of the fix for bug 1910466, code that attempted to optimize VM CPU
  thread assignment based on the host CPU topology as it was determined
  to be buggy, undocumented and rejected valid virtual CPU topologies while
  also producing different behavior when CPU pinning was enabled vs disabled.
  The optimization may be reintroduced in the future with a more generic
  implementation that works for both pinned and unpinned VMs.

.. releasenotes/notes/convert-features-not-implemented-return-code-bf8beea51705271b.yaml @ b'1b6a6e3916806849025f3a90cd6ec48811b02e8a'

- A few of the APIs return code was not consistent for the operations/
  features not implemented or supported. It was returned as 403, 400, or
  409 (for Operation Not Supported For SEV , Operation Not Supported For
  VTPM cases). Now we have made it consistent and return 400 always when
  any operations/features are not implemented or supported.

.. releasenotes/notes/drop-database-use_db_reconnect-opt-7e0062d3da76032a.yaml @ b'100b9dc62c0ec9f7b38739837c06646122c818d5'

- Support for automatically retrying all database interactions by configuring
  the ``[database] use_db_reconnect`` config option has been removed. This
  behavior was only ever supported for interactions with the main database
  and was generally not necessary as a number of lookups were already
  explicitly wrapped in retries. The ``[database] use_db_reconnect`` option
  is provided by oslo.db and will now be ignored by nova.

.. releasenotes/notes/drop-oslo_db-use_tpool-48542a28d10e1bae.yaml @ b'9799468d6f31ba8d915c851aae1a66340b5d1d7f'

- Experimental support for thread pooling of DB API calls has been removed.
  This feature was first introduced in the 2014.2 (Juno) release but has not
  graduated to fully-supported status since nor was it being used for any
  API DB calls. The ``[oslo_db] use_tpool`` config option used to enable
  this feature will now be ignored by nova.

.. releasenotes/notes/libvirt-workarounds-disable_native_luksv1-18773636b414970e.yaml @ b'9bd62eae6eb98136be7014eb6ca7e54cb41fc7ca'

- The ``[workarounds]disable_native_luksv1`` workaround configurable has been
  removed after previously being deprecated during the Wallaby (23.0.0)
  release.

.. releasenotes/notes/libvirt-workarounds-remove-rbd_volume_local_attach-ebdf9cf313344a45.yaml @ b'122a32ed8295ce1168505ed1b6d0f08422c506c4'

- The ``[workarounds]rbd_volume_local_attach`` workaround configurable has
  been removed after previously being deprecated in the Wallaby (23.0.0)
  release.

.. releasenotes/notes/remove-deprecated-scheduler-opts-37afb63a94e8b47e.yaml @ b'50a7a3050a2fb746a35330f0544320382373bded'

- A number of scheduler-related config options were renamed during the 15.0.0
  (Ocata) release. The deprecated aliases have now been removed. These are:

  - ``[DEFAULT] scheduler_max_attempts`` (now ``[scheduler] max_attempts``)
  - ``[DEFAULT] scheduler_host_subset_size`` (now
    ``[scheduler] host_subset_size``)
  - ``[DEFAULT] max_io_ops_per_host`` (now
    ``[scheduler] max_io_ops_per_host``)
  - ``[DEFAULT] max_instances_per_host`` (now
    ``[scheduler] max_instances_per_host``)
  - ``[DEFAULT] scheduler_tracks_instance_changes`` (now
    ``[scheduler] track_instance_changes``)
  - ``[DEFAULT] scheduler_available_filters`` (now
    ``[scheduler] available_filters``)

.. releasenotes/notes/require-placemnet-api-microversion-1.36-1129fe4afc949075.yaml @ b'f6e8c512fbce7c8ab2444c6a31132dc461f5638b'

- Nova now requires that the Placement API supports at least
  microversion 1.36, added in Train. The related nova-upgrade
  check has been modified to warn if this prerequisite is not
  fulfilled.

.. releasenotes/notes/switch-to-alembic-ed5c64f62b6c91a3.yaml @ b'905c9723e9b8398010c57b3609310315a913bef1'

- The database migration engine has changed from `sqlalchemy-migrate`__ to
  `alembic`__. For most deployments, this should have minimal to no impact
  and the switch should be mostly transparent. The main user-facing impact is
  the change in schema versioning. While sqlalchemy-migrate used a linear,
  integer-based versioning scheme, which required placeholder migrations to
  allow for potential migration backports, alembic uses a distributed version
  control-like schema where a migration's ancestor is encoded in the file and
  branches are possible. The alembic migration files therefore use a
  arbitrary UUID-like naming scheme and the ``nova-manage db sync`` and
  ``nova-manage api_db sync`` commands now expect such an version when
  manually specifying the version that should be applied. For example::

      $ nova-manage db sync 8f2f1571d55b

  It is no longer possible to specify an sqlalchemy-migrate-based version.
  When the ``nova-manage db sync`` and ``nova-manage api_db sync`` commands
  are run, all remaining sqlalchemy-migrate-based migrations will be
  automatically applied. Attempting to specify an sqlalchemy-migrate-based
  version will result in an error.

  .. __: https://sqlalchemy-migrate.readthedocs.io/en/latest/
  .. __: https://alembic.sqlalchemy.org/en/latest/


.. _Release Notes_24.0.0_xena-eom_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-AZ-filter-28406abc0135c1c3.yaml @ b'7c7a2a142d74a7deeda2a79baf21b689fe32cd08'

- The ``AvailabilityZoneFilter`` scheduler filters is now deprecated
  for removal in a future release. The functionality of the
  ``AvailabilityZoneFilter`` has been replaced by the
  ``map_az_to_placement_aggregate`` pre-filter which was introduced in
  18.0.0 (Rocky). This pre-filter is now enabled by default and will be
  mandatory in a future release.

.. releasenotes/notes/generic_mdevs-0e1b3ef8385f7fae.yaml @ b'ff4d0d002a35022df1cb71029ad82ad8f3b327df'

- The existing config options in the ``[devices]`` group for managing virtual
  GPUs are now renamed in order to be more generic since the mediated devices
  framework from the linux kernel can support other devices:

  - ``enabled_vgpu_types`` is now deprecated in favour of
    ``enabled_mdev_types``
  - Dynamic configuration groups called ``[vgpu_*]`` are now deprecated in
    favour of ``[mdev_*]``

  Support for the deprecated options will be removed in a future release.

.. releasenotes/notes/microversion-2-90-59fb6d4ec420b9f4.yaml @ b'cfa33d3b06a279f8f6dc6ad7d76d49feb36b0ace'

- The ``os_compute_api:os-extended-server-attributes`` policy controls
  which users a number of server extended attributes are shown to.
  Configuring visibility of the ``OS-EXT-SRV-ATTR:hostname`` attribute via
  this policy has now been deprecated and will be removed in a future
  release. Upon removal, this attribute will be shown for all users
  regardless of policy configuration.


.. _Release Notes_24.0.0_xena-eom_Security Issues:

Security Issues
---------------

.. releasenotes/notes/console-proxy-reject-open-redirect-4ac0a7895acca7eb.yaml @ b'781612b33282ed298f742c85dab58a075c8b793e'

- A vulnerability in the console proxies (novnc, serial, spice) that allowed
  open redirection has been `patched`_. The novnc, serial, and spice console
  proxies are implemented as websockify servers and the request handler
  inherits from the python standard SimpleHTTPRequestHandler. There is a
  `known issue`_ in the SimpleHTTPRequestHandler which allows open redirects
  by way of URLs in the following format::

    http://vncproxy.my.domain.com//example.com/%2F..

  which if visited, will redirect a user to example.com.

  The novnc, serial, and spice console proxies will now reject requests that
  pass a redirection URL beginning with "//" with a 400 Bad Request.

  .. _patched: https://bugs.launchpad.net/nova/+bug/1927677
  .. _known issue: https://bugs.python.org/issue32084

.. releasenotes/notes/libvirt-delegate-ovs-plugging-to-os-vif-6adc0398a0e0df58.yaml @ b'a62dd42c0dbb6b2ab128e558e127d76962738446'

- In this release OVS port creation has been delegated to os-vif when the
  ``noop`` or ``openvswitch`` security group firewall drivers are
  enabled in Neutron. Those options, and others that disable the
  ``hybrid_plug`` mechanism, will now use os-vif instead of libvirt to plug
  VIFs into the bridge.  By delegating port plugging to os-vif we can use the
  ``isolate_vif`` config option to ensure VIFs are plugged securely preventing
  guests from accessing other tenants' networks before the neutron ovs agent
  can wire up the port. See `bug #1734320`_ for details.
  Note that OVN, ODL and other SDN solutions also use
  ``hybrid_plug=false`` but they are not known to be affected by the security
  issue caused by the previous behavior. As such the ``isolate_vif``
  os-vif config option is only used when deploying with ml2/ovs.


.. _Release Notes_24.0.0_xena-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821755-7bd03319e34b6b10.yaml @ b'33c8af1f8c46c9c37fcc28fb3409fbd3a78ae39f'

- Improved detection of anti-affinity policy violation when performing live
  and cold migrations. Most of the violations caused by race conditions due
  to performing concurrent live or cold migrations should now be addressed
  by extra checks in the compute service. Upon detection, cold migration
  operations are automatically rescheduled, while live migrations have two
  checks and will be rescheduled if detected by the first one, otherwise the
  live migration will fail cleanly and revert the instance state back to its
  previous value.

.. releasenotes/notes/bug-1851545-781c358939d96cea.yaml @ b'00f1d4757e503bb9807d7a8d7035c061a97db983'

- `Bug 1851545 <https://bugs.launchpad.net/nova/+bug/1851545>`_, wherein
  unshelving an instance with SRIOV Neutron ports did not update the port
  binding's ``pci_slot`` and could cause libvirt PCI conflicts, has been
  fixed.

  .. important:: Constraints in the fix's implementation mean that it only
    applies to instances booted **after** it has been applied. Existing
    instances will still experience bug 1851545 after being shelved and
    unshelved, even with the fix applied.

.. releasenotes/notes/bug-1853009-99414e14d1491b5f.yaml @ b'a8492e88783b40f6dc61888fada232f0d00d6acf'

- Fixes an issue with multiple ``nova-compute`` services used with Ironic,
  where a rebalance operation could result in a compute node being deleted
  from the database and not recreated. See `bug 1853009
  <https://bugs.launchpad.net/nova/+bug/1853009>`__ for details.

.. releasenotes/notes/bug-1910466-max-vcpu-topologies-with-numa-9a9ceb1b0fc7c33d.yaml @ b'387823b36d091abbaa37efb930fc98b94a5bbb93'

- The nova libvirt driver supports two independent features, virtual CPU
  topologies and virtual NUMA topologies. Previously, when
  ``hw:cpu_max_sockets``, ``hw:cpu_max_cores`` and ``hw:cpu_max_threads``
  were specified for pinned instances (``hw:cpu_policy=dedicated``)
  without explicit ``hw:cpu_sockets``, ``hw:cpu_cores``, ``hw:cpu_threads``
  extra specs or their image equivalent, nova failed to generate a valid
  virtual CPU topology. This has now been fixed and it is now possible to
  use max CPU constraints with pinned instances.
  e.g. a combination of  ``hw:numa_nodes=2``, ``hw:cpu_max_sockets=2``,
  ``hw:cpu_max_cores=2``, ``hw:cpu_max_threads=8`` and
  ``hw:cpu_policy=dedicated`` can now generate a valid topology using
  a flavor with 8 vCPUs.

.. releasenotes/notes/bug-1939604-547c729b7741831b.yaml @ b'7fc6fe6fae891eae42b36ccb9d69cd0f6d6db21d'

- Addressed an issue that prevented instances with 1 vcpu using multiqueue
  feature from being created successfully when their vif_type is TAP.

.. releasenotes/notes/fix-pci-passthrough-for-cavium-thunderx-8fbd1c40718569e2.yaml @ b'a569a51fedd058fdae2eb0066e087c37688987f8'

- On some hardware platforms, an SR-IOV virtual function for a NIC port may
  exist without being associated with a parent physical function that has
  an assocatied netdev. In such a case the the PF interface name lookup
  will fail. As the ``PciDeviceNotFoundById`` exception was not handled
  this would prevent the nova compute agent from starting on affected
  hardware. See: https://bugs.launchpad.net/nova/+bug/1915255 for more
  details. This edgecase has now been addressed, however, features
  that depend on the PF name such as minimum bandwidth based QoS cannot
  be supported on these platforms.

.. releasenotes/notes/libvirt-delegate-ovs-plugging-to-os-vif-6adc0398a0e0df58.yaml @ b'a62dd42c0dbb6b2ab128e558e127d76962738446'

- In this release we delegate port plugging to os-vif for all OVS interface
  types. This allows os-vif to create the OVS port before libvirt creates
  a tap device during a live migration therefore preventing the loss of
  the MAC learning frames generated by QEMU. This resolves a long-standing
  race condition between Libvirt creating the OVS port, Neutron wiring up
  the OVS port and QEMU generating RARP packets to populate the vswitch
  MAC learning table. As a result this reduces the interval during a live
  migration where packets can be lost. See `bug #1815989`_ for details.

  .. _`bug #1734320`: https://bugs.launchpad.net/neutron/+bug/1734320
  .. _`bug #1815989`: https://bugs.launchpad.net/neutron/+bug/1815989

.. releasenotes/notes/libvirt-event-based-device-detach-23ac037004d753b1.yaml @ b'e56cc4f439846558fc13298c2360d7cdd473cc89'

- To fix `device detach issues`__ in the libvirt driver the detach logic has
  been changed from a sleep based retry loop to waiting for libvirt domain
  events. During this change we also introduced two new config options to
  allow fine tuning the retry logic. For details see the description of the
  new ``[libvirt]device_detach_attempts`` and
  ``[libvirt]device_detach_timeout`` config options.

  .. __: https://bugs.launchpad.net/nova/+bug/1882521

.. releasenotes/notes/minimize-bug-1841481-race-window-f76912d4985770ad.yaml @ b'f84d5917c6fb045f03645d9f80eafbc6e5f94bdd'

- Minimizes a race condition window when using the ``ironic`` virt driver
  where the data generated for the Resource Tracker may attempt to compare
  potentially stale instance information with the latest known baremetal
  node information. While this doesn't completely prevent nor resolve the
  underlying race condition identified in
  `bug 1841481 <https://bugs.launchpad.net/nova/+bug/1841481>`_,
  this change allows Nova to have the latest state information, as opposed
  to state information which may be out of date due to the time which it may
  take to retrieve the status from Ironic. This issue was most observable
  on baremetal clusters with several thousand physical nodes.


