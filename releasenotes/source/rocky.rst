===================================
 Rocky Series Release Notes
===================================

.. _Release Notes_18.3.0-55_rocky-eol:

18.3.0-55
=========

.. _Release Notes_18.3.0-55_rocky-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/increase_glance_num_retries-ddfcd7053631882b.yaml @ b'11e391c31454272a56815a1eaec2b1c6b8b8c849'

- The default for ``[glance] num_retries`` has changed from ``0`` to ``3``.
  The option controls how many times to retry a Glance API call in response
  to a HTTP connection failure. When deploying Glance behind HAproxy it is
  possible for a response to arrive just after the HAproxy idle time. As a
  result, an exception will be raised when the connection is closed resulting
  in a failed request. By increasing the default value, Nova can be more
  resilient to this scenario were HAproxy is misconfigured by retrying the
  request.


.. _Release Notes_18.3.0-55_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841363-fallback-to-threaded-io-when-native-io-is-not-supported-fe56014e9648a518.yaml @ b'6e6440fe97c07489ab6b70029a22fa0b9b70bc02'

- Since Libvirt v.1.12.0 and the introduction of the `libvirt issue`_ ,
  there is a fact that if we set cache mode whose write semantic is not
  O_DIRECT (i.e. "unsafe", "writeback" or "writethrough"), there will
  be a problem with the volume drivers (i.e. LibvirtISCSIVolumeDriver,
  LibvirtNFSVolumeDriver and so on), which designate native io explicitly.

  When the driver_cache (default is none) has been configured as neither
  "none" nor "directsync", the libvirt driver will ensure the driver_io
  to be "threads" to avoid an instance spawning failure.

  .. _`libvirt issue`: https://bugzilla.redhat.com/show_bug.cgi?id=1086704

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'1fb4cc03e315f5b4dbebc521f0d1299273c7c396'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361

.. releasenotes/notes/cinder-detect-nonbootable-image-6fad7f865b45f879.yaml @ b'02551d6d6a3baee49309cffbc3bef2508fcafe72'

- The Compute service has never supported direct booting of an instance from
  an image that was created by the Block Storage service from an encrypted
  volume.  Previously, this operation would result in an ACTIVE instance that
  was unusable.  Beginning with this release, an attempt to boot from such an
  image will result in the Compute API returning a 400 (Bad Request)
  response.

.. releasenotes/notes/neutron-connection-retries-c276010afe238abc.yaml @ b'6bed39cd6e77744ca4bbad9dba3f68c78cdc1ec0'

- A new config option ``[neutron]http_retries`` is added which defaults to
  3. It controls how many times to retry a Neutron API call in response to a
  HTTP connection failure. An example scenario where it will help is when a
  deployment is using HAProxy and connections get closed after idle time. If
  an incoming request tries to reuse a connection that is simultaneously
  being torn down, a HTTP connection failure will occur and previously Nova
  would fail the entire request. With retries, Nova can be more resilient in
  this scenario and continue the request if a retry succeeds. Refer to
  https://launchpad.net/bugs/1866937 for more details.

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'84c63816602dcdf91885d20bb5d26cec336fb71e'

- An instance can be rebuilt in-place with the original image or a new
  image. Instance resource usage cannot be altered during a rebuild.
  Previously Nova would have ignored the NUMA topology of the new image
  continuing to use the NUMA topology of the existing instance until a move
  operation was performed. As Nova did not explicitly guard against
  inadvertent changes to resource requests contained in a new image,
  it was possible to rebuild with an image that would violate this
  requirement; see `bug #1763766`_ for details. This resulted in an
  inconsistent state as the instance that was running did not match the
  instance that was requested. Nova now explicitly checks if a rebuild would
  alter the requested NUMA topology of an instance and rejects the rebuild
  if so.

  ..  _`bug #1763766`: https://bugs.launchpad.net/nova/+bug/1763766

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'84c63816602dcdf91885d20bb5d26cec336fb71e'

- With the changes introduced to address `bug #1763766`_, Nova now guards
  against NUMA constraint changes on rebuild. As a result the
  ``NUMATopologyFilter`` is no longer required to run on rebuild since
  we already know the topology will not change and therefore the existing
  resource claim is still valid. As such it is now possible to do an in-place
  rebuild of an instance with a NUMA topology even if the image changes
  provided the new image does not alter the topology which addresses
  `bug #1804502`_.

  ..  _`bug #1804502`: https://bugs.launchpad.net/nova/+bug/1804502


.. _Release Notes_18.3.0_rocky-eol:

18.3.0
======

.. _Release Notes_18.3.0_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1852610-service-delete-with-migrations-ca0565fc0b503519.yaml @ b'30a635068512be558acf0f9c83185dc1aaad560f'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is involved in in-progress migrations. This is because doing
  so would not only orphan the compute node resource provider in the
  placement service on which those instances have resource allocations but
  can also break the ability to confirm/revert a pending resize properly.
  See https://bugs.launchpad.net/nova/+bug/1852610 for more details.


.. _Release Notes_18.3.0_rocky-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/heal-allocations-dry-run-1761fab00f7967d1.yaml @ b'07de847d7bdae22dd2a4a9e2c02113d4803d0883'

- A ``--dry-run`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command to get output without committing any changes to placement.

.. releasenotes/notes/heal-allocations-instance-uuid-9aa93fdef5015c64.yaml @ b'982c60dd0268232927cbed682fabe933923b9e8e'

- An ``--instance`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command on a specific instance given its UUID.


.. _Release Notes_18.2.3_rocky-eol:

18.2.3
======

.. _Release Notes_18.2.3_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/support-novnc-1.1.0-ce677fe3381b2a11.yaml @ b'd72f24569ea9da1f045927471b8d27c41837bf4a'

- Add support for noVNC >= v1.1.0 for VNC consoles. Prior to this fix, VNC
  console token validation always failed regardless of actual token validity
  with noVNC >= v1.1.0. See
  https://bugs.launchpad.net/nova/+bug/1822676 for more details.


.. _Release Notes_18.2.2_rocky-eol:

18.2.2
======

.. _Release Notes_18.2.2_rocky-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'e0b91a5b1e89bd0506dc6da86bc61f1708f0215a'

- `OSSA-2019-003`_: Nova Server Resource Faults Leak External Exception
  Details (CVE-2019-14433)

  This release contains a security fix for `bug 1837877`_ where users
  without the admin role can be exposed to sensitive error details in
  the server resource fault ``message``.

  There is a behavior change where non-nova exceptions will only record
  the exception class name in the fault ``message`` field which is exposed
  to all users, regardless of the admin role.

  The fault ``details``, which are only exposed to users with the admin role,
  will continue to include the traceback and also include the exception
  value which for non-nova exceptions is what used to be exposed in the
  fault ``message`` field. Meaning, the information that admins could see
  for server faults is still available, but the exception value may be in
  ``details`` rather than ``message`` now.

  .. _OSSA-2019-003: https://security.openstack.org/ossa/OSSA-2019-003.html
  .. _bug 1837877: https://bugs.launchpad.net/nova/+bug/1837877


.. _Release Notes_18.2.2_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1675791-snapshot-member-access-c40bba36606618f7.yaml @ b'6ca6f6fce691863901b01d37b8f6e3eadb2bcec4'

- `Bug 1675791`_ has been fixed by granting image membership access to
  snapshot images when the owner of the server is not performing the
  snapshot/backup/shelve operation on the server. For example, an admin
  shelves a user's server and the user needs to unshelve the server so the
  user needs access to the shelved snapshot image.

  Note that only the image owner may delete the image, so in the case of
  a shelved offloaded server, if the user unshelves or deletes the server,
  that operation will work but there will be a warning in the logs because
  the shelved snapshot image could not be deleted since the user does not
  own the image. Similarly, if an admin creates a snapshot of a server in
  another project, the admin owns the snapshot image and the non-admin
  project, while having shared image member access to see the image, cannot
  delete the snapshot.

  The bug fix applies to both the ``nova-osapi_compute`` and ``nova-compute``
  service so older compute services will need to be patched.

  Refer to the image API reference for details on image sharing:

  https://developer.openstack.org/api-ref/image/v2/index.html#sharing

  .. _Bug 1675791: https://launchpad.net/bugs/1675791

.. releasenotes/notes/bug-1811726-multi-node-delete-2ba17f02c6171fbb.yaml @ b'64d52788831f0e676f0b9bf9780eeadb38232def'

- `Bug 1811726`_ is fixed by deleting the resource provider (in placement)
  associated with each compute node record managed by a ``nova-compute``
  service when that service is deleted via the
  ``DELETE /os-services/{service_id}`` API. This is particularly important
  for compute services managing ironic baremetal nodes.

  .. _Bug 1811726: https://bugs.launchpad.net/nova/+bug/1811726


.. _Release Notes_18.2.1_rocky-eol:

18.2.1
======

.. _Release Notes_18.2.1_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1775418-754fc50261f5d7c3.yaml @ b'c19d602f9be536ee8412bac0f0951a995424f25e'

- The `os-volume_attachments`_ update API, commonly referred to as the swap
  volume API will now return a ``400`` (BadRequest) error when attempting to
  swap from a multi attached volume with more than one active read/write
  attachment resolving `bug #1775418`_.

  .. _os-volume_attachments: https://developer.openstack.org/api-ref/compute/?expanded=update-a-volume-attachment-detail
  .. _bug #1775418: https://launchpad.net/bugs/1775418

.. releasenotes/notes/qb-bug-1730933-6695470ebaee0fbd.yaml @ b'c958ad8a68ea9a8ea465d9e3dd889248d9f42481'

- Fixes a bug that caused Nova to fail on mounting Quobyte volumes
  whose volume URL contained multiple registries.


.. _Release Notes_18.2.0_rocky-eol:

18.2.0
======

.. _Release Notes_18.2.0_rocky-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1815791-f84a913eef9e3b21.yaml @ b'81b0e5a0680883d68d12253af64f8e10200df746'

- Adds a ``use_cache`` parameter to the virt driver ``get_info``
  method. Out of tree drivers should add support for this
  parameter.

.. releasenotes/notes/disable-live-migration-with-numa-bc710a1bcde25957.yaml @ b'52b89734426253f64b6d4797ba4d849c3020fb52'

- Live migration of instances with NUMA topologies is now disabled by default
  when using the libvirt driver. This includes live migration of instances
  with CPU pinning or hugepages. CPU pinning and huge page information for
  such instances is not currently re-calculated, as noted in `bug #1289064`_.
  This means that if instances were already present on the destination host,
  the migrated instance could be placed on the same dedicated cores as these
  instances or use hugepages allocated for another instance. Alternately, if
  the host platforms were not homogeneous, the instance could be assigned to
  non-existent cores or be inadvertently split across host NUMA nodes.

  The `long term solution`_ to these issues is to recalculate the XML on the
  destination node. When this work is completed, the restriction on live
  migration with NUMA topologies will be lifted.

  For operators that are aware of the issues and are able to manually work
  around them, the ``[workarounds] enable_numa_live_migration`` option can
  be used to allow the broken behavior.

  For more information, refer to `bug #1289064`_.

  .. _bug #1289064: https://bugs.launchpad.net/nova/+bug/1289064
  .. _long term solution: https://blueprints.launchpad.net/nova/+spec/numa-aware-live-migration


.. _Release Notes_18.2.0_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1378904-disable-az-rename-b22a558a20b12706.yaml @ b'1559db570452cd5502b8f5e9ba44fef54295537f'

- ``PUT /os-aggregates/{aggregate_id}`` and
  ``POST /os-aggregates/{aggregate_id}/action`` (for set_metadata action) will
  now return HTTP 400 for availability zone renaming if the hosts of
  the aggregate have any instances.

.. releasenotes/notes/bug-1815791-f84a913eef9e3b21.yaml @ b'81b0e5a0680883d68d12253af64f8e10200df746'

- Fixes a race condition that could allow a newly created Ironic
  instance to be powered off after deployment, without letting
  the user power it back on.

.. releasenotes/notes/set-endpoint-interface-for-ironicclient-a0b6b8f8dedc7341.yaml @ b'd4cea970c2d56ef8ff813473cd5ba0e38e3f04fd'

- [`bug 1818295 <https://bugs.launchpad.net/nova/+bug/1818295>`_]
  Fixes the problem with endpoint lookup in Ironic driver where only public
  endpoint is possible, which breaks deployments where the controllers have
  no route to the public network per security requirement. Note that
  python-ironicclient fix I610836e5038774621690aca88b2aee25670f0262 must
  also be present to resolve the bug.


.. _Release Notes_18.2.0_rocky-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1414895-8f7d8da6499f8e94.yaml @ b'8c678ae57299076a5013f0be985621e064acfee0'

- The ``[workarounds]/ensure_libvirt_rbd_instance_dir_cleanup`` configuration
  option has been introduced. This can be used by operators to ensure that
  instance directories are always removed during cleanup within the Libvirt
  driver while using ``[libvirt]/images_type = rbd``. This works around known
  issues such as `bug 1414895`_ when cleaning up after an evacuation and
  `bug 1761062`_ when reverting from an instance resize.

  Operators should be aware that this workaround only applies when using the
  libvirt compute driver and rbd images_type as enabled by the following
  configuration options:

  * ``[DEFAULT]/compute_driver = libvirt``
  * ``[libvirt]/images_type = rbd``

  .. warning:: Operators will need to ensure that the instance directory
    itself, specified by ``[DEFAULT]/instances_path``, is not shared between
    computes before enabling this workaround, otherwise files associated with
    running instances may be removed.

  .. _bug 1414895: https://bugs.launchpad.net/nova/+bug/1414895
  .. _bug 1761062: https://bugs.launchpad.net/nova/+bug/1761062


.. _Release Notes_18.1.0_rocky-eol:

18.1.0
======

.. _Release Notes_18.1.0_rocky-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/nova-manage-online-migrations-exit-status-9de5ea7836d0e368.yaml @ b'dd8354efc1113ae9f35e404ef5ece00a78c378b4'

- The ``nova-manage db online_data_migrations`` command now returns exit
  status 2 in the case where some migrations failed (raised exceptions) and
  no others were completed successfully from the last batch attempted. This
  should be considered a fatal condition that requires intervention. Exit
  status 1 will be returned in the case where the ``--max-count`` option was
  used and some migrations failed but others succeeded (updated at least one
  row), because more work may remain for the non-failing migrations, and
  their completion may be a dependency for the failing ones. The command
  should be reiterated while it returns exit status 1, and considered
  completed successfully only when it returns exit status 0.


.. _Release Notes_18.1.0_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1795992-long_rpc_timeout-select_destinations-9712e8690160928f.yaml @ b'4b5a21b4ebcd3272ffdf6b42937acf348c5b045f'

- The ``long_rpc_timeout`` configuration option is now used for the RPC
  call to the scheduler to select a host. This is in order to avoid a
  timeout when scheduling multiple servers in a single request and/or when
  the scheduler needs to process a large number of hosts.

.. releasenotes/notes/bug-1796920-report_ironic_standard_resource_class_inventory-85c1fc629a08038d.yaml @ b'f7d0a7671fb73983a1853b0d2f3ce7552d752c31'

- A new ``[workarounds]/report_ironic_standard_resource_class_inventory``
  configuration option has been added.

  Starting in the 16.0.0 Pike release, ironic nodes can be scheduled using
  custom resource classes rather than the standard resource classes VCPU,
  MEMORY_MB and DISK_GB:

  https://docs.openstack.org/ironic/rocky/install/configure-nova-flavors.html

  However, existing ironic instances require a data migration which can be
  achieved either by restarting ``nova-compute`` services managing ironic
  nodes or running ``nova-manage db ironic_flavor_migration``. The completion
  of the data migration can be checked by running the
  ``nova-status upgrade check`` command and checking the
  "Ironic Flavor Migration" result.

  Once all data migrations are complete, you can set this option to False to
  stop reporting VCPU, MEMORY_MB and DISK_GB resource class inventory to the
  Placement service so that scheduling will only rely on the custom resource
  class for each ironic node, as described in the document above.

  Note that this option does not apply starting in the 19.0.0 Stein release
  since the ironic compute driver no longer reports standard resource class
  inventory regardless of configuration.

  Alternatives to this workaround would be unsetting ``memory_mb`` and/or
  ``vcpus`` properties from ironic nodes, or using host aggregates to
  segregate VM from BM compute hosts and restrict flavors to those
  aggregates, but those alternatives might not be feasible at large scale.

  See related bug https://bugs.launchpad.net/nova/+bug/1796920 for more
  details.

.. releasenotes/notes/bug-1801702-c8203d3d55007deb.yaml @ b'386e574f4ae6ead225edd65f2759e9aa14c4887b'

- When testing whether direct IO is possible on the backing storage
  for an instance, Nova now uses a block size of 4096 bytes instead
  of 512 bytes, avoiding issues when the underlying block device has
  sectors larger than 512 bytes. See bug
  https://launchpad.net/bugs/1801702 for details.

.. releasenotes/notes/fix-simple-tenant-usage-pagination-393ed6e7d0e31594.yaml @ b'133b194ba079abe84900d09a5c3c74ef9f464bab'

- The ``os-simple-tenant-usage`` pagination has been fixed. In some cases,
  nova usage-list would have returned incorrect results because of this.
  See bug https://launchpad.net/bugs/1796689 for details.


.. _Release Notes_18.0.3_rocky-eol:

18.0.3
======

.. _Release Notes_18.0.3_rocky-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/nova-status-check-consoleauths-618acb3a67f97418.yaml @ b'9fea5a2f34e7eb7b447ce3589fc578505d42891f'

- The ``nova-consoleauth`` service is deprecated and should no longer be
  deployed, however, if there is a requirement to maintain support for
  existing console sessions through a live/rolling upgrade, operators should
  set ``[workarounds]enable_consoleauth = True`` in their configuration and
  continue running ``nova-consoleauth`` for the duration of the live/rolling
  upgrade.
  A new check has been added to the ``nova-status upgrade check`` CLI to
  help with this and it will emit a warning and provide additional
  instructions to set ``[workarounds]enable_consoleauth = True`` while
  performing a live/rolling upgrade.


.. _Release Notes_18.0.1_rocky-eol:

18.0.1
======

.. _Release Notes_18.0.1_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/libvirt_fix_ipv6_live_migration-bbcde8f3b7d17921.yaml @ b'7ee5499e5507c45249945fa5baf7665bc2f1cc02'

- A change has been introduced in the libvirt driver to correctly handle IPv6 addresses for live migration.


.. _Release Notes_18.0.0_rocky-eol:

18.0.0
======

.. _Release Notes_18.0.0_rocky-eol_Prelude:

Prelude
-------

.. releasenotes/notes/rocky-prelude-b78b51b9026ed336.yaml @ b'7737d297318d91a7a3ed9ca009e60619ab7677ae'

The 18.0.0 release includes many new features and bug fixes. It is
difficult to cover all the changes that have been introduced. Please at
least read the upgrade section which describes the required actions to
upgrade your cloud from 17.0.0 (Queens) to 18.0.0 (Rocky).

That said, a few major changes are worth mentioning. This is not an
exhaustive list:

- The latest Compute API microversion supported for Rocky is v2.65. Details
  on REST API microversions added since the 17.0.0 Queens release can be
  found in the `REST API Version History`_ page.

- Nova is now using the new Neutron port binding API to minimize network
  downtime during live migrations. See the `related spec`_ for more
  details.

- Volume-backed instances will no longer report ``root_gb`` usage for new
  instances and existing instances will heal during move operations.

- Several REST APIs specific to nova-network were removed and the core
  functionality of nova-network is planned to be removed in the 19.0.0
  Stein release.

- A ``nova-manage db purge`` command to `purge archived shadow table data`_
  is now available. A new ``--purge`` option is also available for the
  ``nova-manage db archive_deleted_rows`` command.

- It is now possible to `disable a cell`_ to stop scheduling to a cell by
  using the ``nova-manage cell_v2 update_cell`` command.

- The libvirt compute driver now supports trusted image certificates when
  using the 2.63 compute API microversion. See the `image signature
  certificate validation`_ documentation for more details.

- It is now possible to configure a separate database for the placement
  service, which could help in easing the eventual placement service
  extraction from Nova and data migration associated with it.

- A ``nova-manage placement heal_allocations`` command is now available to
  allow users of the CachingScheduler to get the placement service
  populated for their eventual migration to the FilterScheduler. The
  CachingScheduler is deprecated and could be removed as early as Stein.

- The placement service now supports granular RBAC policy rules
  configuration. See the `placement policy`_ documentation for details.

- A new zVM virt driver is now available.

- The nova-consoleauth service has been deprecated.

.. _REST API Version History: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html
.. _related spec: https://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/neutron-new-port-binding-api.html
.. _purge archived shadow table data: https://docs.openstack.org/nova/latest/cli/nova-manage.html#nova-database
.. _disable a cell: https://docs.openstack.org/nova/latest/cli/nova-manage.html#nova-cells-v2
.. _image signature certificate validation: https://docs.openstack.org/nova/latest/user/certificate-validation.html
.. _placement policy: https://docs.openstack.org/nova/rocky/configuration/placement-policy.html


.. _Release Notes_18.0.0_rocky-eol_New Features:

New Features
------------

.. releasenotes/notes/aarch64-minimum-libvirt-version-86331e5282effbf0.yaml @ b'30b7a566aaeb3d9a1e8145cdbaa55b89c3946722'

- AArch64 architecture is supported by Nova with libvirt min version 3.6.0.
  See the Nova `support matrix`_ for more details.

  .. _`support matrix`: https://docs.openstack.org/nova/latest/user/support-matrix.html

.. releasenotes/notes/abort-live-migration-in-queue-0c917f415d6dac5a.yaml @ b'4cae503767857b90ce9ce609bca6f46575aae0b2'

- The support to abort live migrations with ``queued`` and ``preparing`` status using ``DELETE /servers/{server_id}/migrations/{migration_id}`` API has been added in microversion 2.65.

.. releasenotes/notes/add-action-initiator-to-instance-action-notifications-27e6a3031da274c5.yaml @ b'2bca6431e69bf2c6e657736b7fe11f5a2fbb9433'

- Instance action versioned notifications now contain
  ``action_initiator_user`` and ``action_initiator_project``
  fields to distinguish between the owner of the instance and
  who initiated the action upon the instance, for example an
  administrator or another user within the same project.

.. releasenotes/notes/add-cpu-weigher-2e982c9f9751d631.yaml @ b'67f52ab36df0f029d745851fc45607736c03e474'

- Add ``CPUWeigher`` weigher. This can be used to spread (default) or pack
  workloads on hosts based on their vCPU usage. This can be configured using
  the ``[filter_scheduler] cpu_weight_multiplier`` configuration option.

.. releasenotes/notes/add-disabled-to-create_cell-feb1643ec4716eb2.yaml @ b'cd01cbe65e797fddb8a6fb00fb867f9edf5909ad'

- A new option ``disabled`` has been added to nova-manage cell_v2 create_cell
  command by which users can create pre-disabled cells. Hence unless such cells
  are enabled, no VMs will be spawned on the hosts in these cells.

.. releasenotes/notes/add-disabled-to-create_cell-feb1643ec4716eb2.yaml @ b'cd01cbe65e797fddb8a6fb00fb867f9edf5909ad'

- Two new options ``--enable`` and ``--disable`` have been added to the
  ``nova-manage cell_v2 update_cell`` command. Using these flags users can enable
  or disable scheduling to a cell.

.. releasenotes/notes/add-extra-specs-to-flavor-list-362a4794c0871f2f.yaml @ b'0baba40b1b922a7b931f93cb164b9ba9a41ba31f'

- Exposes flavor extra_specs in the flavor representation since microversion
  2.61. Flavor extra_specs will be included in Response body of the
  following APIs:

  * ``GET /flavors/detail``
  * ``GET /flavors/{flavor_id}``
  * ``POST /flavors``
  * ``PUT /flavors/{flavor_id}``

  Now users can see the flavor extra-specs in flavor APIs response and do
  not need to call ``GET /flavors/{flavor_id}/os-extra_specs`` API. The
  visibility of the flavor extra_specs within the flavor resource will be
  controlled by the same policy rules as are used for showing the flavor
  extra_specs. If the user has no access to query extra_specs, the
  ``flavor.extra_specs`` will not be included.

.. releasenotes/notes/add-full-traceback-to-exceptionpayload-06cf8d55d2918eab.yaml @ b'2a0f2a0d270c6a5bb7c141e84a83d9d0e783ae3b'

- A new ``traceback`` field has been added to each versioned instance
  notification. In an error notification this field contains the full
  traceback string of the exception which caused the error notification.
  See the `notification dev ref`_ for the sample file of
  ``instance.create.error`` as an example.

  .. _notification dev ref: https://docs.openstack.org/nova/latest/reference/notifications.html#existing-versioned-notifications

.. releasenotes/notes/add-host-to-instance-action-events-aad2cc18fe191afa.yaml @ b'c2f7d6585818c04e626aa4b6c292e5c2660cb8b3'

- The microversion 2.62 adds ``host`` (hostname) and ``hostId`` (an
  obfuscated hashed host id string) fields to the instance action
  ``GET /servers/{server_id}/os-instance-actions/{req_id}`` API. The display
  of the newly added ``host`` field will be controlled via policy rule
  ``os_compute_api:os-instance-actions:events``, which is the same policy
  used for the ``events.traceback`` field. If the user is prevented by
  policy, only ``hostId`` will be displayed.

.. releasenotes/notes/add-req-id-to-versioned-notifications-fd0b525bd37b7e41.yaml @ b'94de8d75ff08bfc63d0d4a68083783b2a878508d'

- The ``request_id`` field has been added to all
  instance action and instance update versioned
  notification payloads. Note that notifications
  triggered by periodic tasks will have the
  ``request_id`` field set to be ``None``.

.. releasenotes/notes/allocation_candidates_support_member_of-92f7e1440ed63fe7.yaml @ b'a69e05d29a518e00f9a5b6d7e31fa7e4a0829023'

- Add support, in a new placement microversion 1.21, for the ``member_of``
  query parameter, representing one or more aggregate UUIDs. When supplied,
  it will filter the returned allocation candidates to only those
  resource_providers that are associated with ("members of") the specified
  aggregate(s). This parameter can have a value of either a single aggregate
  UUID, or a comma-separated list of aggregate UUIDs. When specifying more
  than one aggregate, a resource provider needs to be associated with at
  least one of the aggregates in order to be included; it does not have to be
  associated with all of them. Because of this, the list of UUIDs must be
  prefixed with ``in:`` to represent the logical ``OR`` of the selection.

.. releasenotes/notes/allow-reserved-equal-total-inventory-fe93584dd28c460d.yaml @ b'7f79758dd994675a0b90c35ae035d0c182290b83'

- Introduces new placement API version ``1.26``. Starting with this version
  it is allowed to define resource provider inventories with reserved value
  equal to total.

.. releasenotes/notes/availability-zone-placement-filter-0006c9895853c9bc.yaml @ b'96f10711667603e7fbad57b151c6438cdd9ae270'

- The scheduler can now use placement to more efficiently query for hosts within
  an availability zone. This requires that a host aggregate is created in nova
  with the ``availability_zone`` key set, and the same aggregate is created in
  placement with an identical UUID. The
  ``[scheduler]/query_placement_for_availability_zone`` config option enables
  this behavior and, if enabled, eliminates the need for the
  ``AvailabilityZoneFilter`` to be enabled.

.. releasenotes/notes/bp-granular-placement-policy-65722fc6d7cb1359.yaml @ b'0a461979df62cd1df2c807b3f4fb3593b3040d13'

- It is now possible to configure granular policy rules for placement
  REST API operations.

  By default, all operations continue to use the ``role:admin`` check string
  so there is no upgrade impact.

  A new configuration option is introduced, ``[placement]/policy_file``,
  which is used to configure the location of the placement policy file.
  By default, the ``placement-policy.yaml`` file may live alongside the
  nova policy file, e.g.:

  * /etc/nova/policy.yaml
  * /etc/nova/placement-policy.yaml

  However, if desired, ``[placement]/policy_file`` makes it possible to
  package and deploy the placement policy file separately to make the future
  split of placement and nova packages easier, e.g.:

  * /etc/placement/policy.yaml

  All placement policy rules are defined in code so by default no extra
  configuration is required and the default rules will be used on start of
  the placement service.

  For more information about placement policy including a sample file, see
  the configuration reference documentation:

  https://docs.openstack.org/nova/latest/configuration/index.html#placement-policy

.. releasenotes/notes/bp-ironic-rescue-mode-c305f37e20fba203.yaml @ b'a07b68ea9200863850d2dbd58e670bf06aafa9b9'

- Supports instance rescue and unrescue with ironic virt driver. This feature
  requires an ironic service supporting API version 1.38 or later, which is
  present in ironic releases >= 10.1. It also requires python-ironicclient >=
  2.3.0.

.. releasenotes/notes/bp-libvirt-virtio-set-queue-sizes-6c54a2ce3dc30d18.yaml @ b'a1eca36557d773123d1096edcbfaa55dba63de15'

- libvirt: add support for virtio-net rx/tx queue sizes

  Add support for configuring the ``rx_queue_size`` and
  ``tx_queue_size`` options in the QEMU virtio-net driver by way of
  nova.conf. Only supported for vhost/vhostuser interfaces

  Currently, valid values for the ring buffer sizes are 256, 512,
  and 1024.

  Adjustable RX queue sizes requires QEMU 2.7.0, and libvirt 2.3.0
  (or newer) Adjustable TX queue sizes requires QEMU 2.10.0, and
  libvirt 3.7.0 (or newer)

.. releasenotes/notes/bp-nvme-over-fabric-nova-ae1ef46fb5a7fc02.yaml @ b'a833bcd05f811325f40cb3c8cce7f94c93cd6b6e'

- Added support for ``nvmeof`` type volumes to the libvirt driver.

.. releasenotes/notes/bp-report-cpu-features-aff90db66837de7d.yaml @ b'7637026b90e2b060583fc17ff14a28ffc9774f74'

- Add support for reporting CPU traits to Placement in libvirt driver. For more detail, see https://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/report-cpu-features-as-traits.html and https://docs.openstack.org/nova/latest/user/support-matrix.html.

.. releasenotes/notes/cell-mapping-formatted-urls-4f5ee779a70960b8.yaml @ b'50658eee4fe26a55854642119beeff46c0d0108a'

- The URLs in cell mapping records may now include variables that are filled
  from the corresponding default URL specified in the host's configuration
  file. This allows per-host credentials, as well as other values to be set
  in the config file which will affect the URL of a cell, as calculated when
  loading the record. For ``database_connection``, the ``[database]/connection``
  URL is used as the base. For ``transport_url``, the ``[DEFAULT]/transport_url``
  is used. For more information, see the cells configuration docs:
  https://docs.openstack.org/nova/latest/user/cells.html

.. releasenotes/notes/complex-anti-affinity-policies-dcf4719e859093be.yaml @ b'd1ccea4dd79af064a363794b9071691c322a64bf'

- Microversion 2.64 is added and enables users to define rules on server
  group policy to meet more advanced policy requirements. This microversion
  brings the following changes in server group APIs:

  * Add ``policy`` and ``rules`` fields in the request of POST
    ``/os-server-groups``. The ``policy`` represents the name of policy. The
    ``rules`` field, which is a dict, can be applied to the policy, which
    currently only supports ``max_server_per_host`` for ``anti-affinity``
    policy.
  * The ``policy`` and ``rules`` fields will be returned in response
    body of POST, GET ``/os-server-groups`` API and GET
    ``/os-server-groups/{server_group_id}`` API.
  * The ``policies`` and ``metadata`` fields have been removed from the
    response body of POST, GET ``/os-server-groups`` API and GET
    ``/os-server-groups/{server_group_id}`` API.

.. releasenotes/notes/configure-amount-of-pcie-ports-486bfa44e9fbdd84.yaml @ b'a234bbf80c848fb23f613383e94b68bf336231a8'

- The amount of PCI Express ports (slots in virtual motherboard) can now be
  configured using ``num_pcie_ports`` option in ``libvirt`` section of
  ``nova.conf`` file.  This affects x86-64 with ``hw_machine_type`` set to
  'pc-q35' value and AArch64 instances of 'virt' ``hw_machine_type`` (which
  is default for that architecture). Due to QEMU's memory map limits on
  aarch64/virt maximum value is limited to 28.

.. releasenotes/notes/consumer_generation-f576ac2594b24e2e.yaml @ b'e60571aad097a35884c66322272980211fe3b460'

- Adds a new ``generation`` column to the consumers table. This value is
  incremented every time allocations are made for a consumer. The new
  placement microversion 1.28 requires that all ``POST /allocations`` and
  ``PUT /allocations/{consumer_uuid}`` requests now include the
  ``consumer_generation`` parameter to ensure that if two processes are
  allocating resources for the same consumer, the second one to complete
  doesn't overwrite the first. If there is a mismatch between the
  ``consumer_generation`` in the request and the current value in the
  database, the allocation will fail, and a 409 Conflict response will be
  returned. The calling process must then get the allocations for that
  consumer by calling ``GET /allocations/{consumer}``. That response will now
  contain, in addition to the allocations, the current generation value for
  that consumer. Depending on the use case, the calling process may error; or
  it may wish to combine or replace the existing allocations with the ones it
  is trying to post, and re-submit with the current consumer_generation.

.. releasenotes/notes/discover-hosts-by-service-06ee20365b895127.yaml @ b'005a66d7e0bb716e32d29a6b5c9d9f24192596e2'

- The nova-manage discover_hosts command now has a ``--by-service`` option which
  allows discovering hosts in a cell purely by the presence of a nova-compute
  binary. At this point, there is no need to use this unless you're using ironic,
  as it is less efficient. However, if you are using ironic, this allows discovery
  and mapping of hosts even when no ironic nodes are present.

.. releasenotes/notes/emulator-threads-policy-e5b57767104531b8.yaml @ b'9724ec118b880ca8713c69366f55df43494b8dbb'

- Introduces ``[compute]/cpu_shared_set`` option for compute nodes.
  Some workloads run best when the hypervisor overhead processes
  (emulator threads in libvirt/QEMU) can be placed on different
  physical host CPUs than other guest CPU resources. This allows
  those workloads to prevent latency spikes for guest vCPU threads.

  To place a workload's emulator threads on a set of isolated
  physical CPUs, set the ``[compute]/cpu_shared_set`` configuration
  option to the set of host CPUs that should be used for best-effort
  CPU resources. Then set a flavor extra spec to
  ``hw:emulator_threads_policy=share`` to instruct nova to place
  that workload's emulator threads on that set of host CPUs.

.. releasenotes/notes/enhanced-kvm-storage-qos-f8f67d404949c0b0.yaml @ b'37aea888459f090b27e53bf77e9daa46603473d8'

- The libvirt driver now supports additional Cinder front-end
  QoS specs, allowing the specification of additional IO
  burst limits applied for each attached disk, individually.

  - quota:read_bytes_sec_max
  - quota:write_bytes_sec_max
  - quota:total_bytes_sec_max
  - quota:read_iops_sec_max
  - quota:write_iops_sec_max
  - quota:total_iops_sec_max
  - quota:size_iops_sec

  For more information, see the Cinder admin guide:

  https://docs.openstack.org/cinder/latest/admin/blockstorage-basic-volume-qos.html

.. releasenotes/notes/expose-shutdown-retry-interval-d83724ade1b44e62.yaml @ b'197539d7a050042463802f6ece98473bbbf9743b'

- The shutdown retry interval in powering off instances can now be set using
  the configuration setting ``shutdown_retry_interval``, in the
  compute configuration group.

.. releasenotes/notes/forbidden-traits-in-nova-478f1884a06e50e7.yaml @ b'2c51688558504f2e8ce80bac06642772be67b2a9'

- Added support for forbidden traits to the scheduler. A flavor extra spec
  is extended to support specifying the forbidden traits. The syntax of
  extra spec is ``trait:<trait_name>=forbidden``, for example:

  - trait:HW_CPU_X86_AVX2=forbidden
  - trait:STORAGE_DISK_SSD=forbidden

  The scheduler will pass the forbidden traits to the
  ``GET /allocation_candidates`` endpoint in the Placement API to include
  only resource providers that do not include the forbidden traits. Currently
  the only valid values are ``required`` and ``forbidden``. Any other values
  will be considered invalid.

  This requires that the Placement API version 1.22 is available before
  the ``nova-scheduler`` service can use this feature.

  The FilterScheduler is currently the only scheduler driver that supports
  this feature.

.. releasenotes/notes/granular-extra-specs-50b26b8f63717942.yaml @ b'9ef4d7662e4a31e05d155982e25d3d35e2362e3e'

- Added support for granular resource and traits requests to the scheduler.
  A flavor extra spec is extended to support specifying numbered groupings of
  resources and required/forbidden traits.  A ``resources`` key with a
  positive integer suffix (e.g. ``resources42:VCPU``) will be logically
  associated with ``trait`` keys with the same suffix (e.g.
  ``trait42:HW_CPU_X86_AVX``). The resources and required/forbidden traits
  in that group will be satisfied by the same resource provider on the host
  selected by the scheduler. When more than one numbered grouping is
  supplied, the ``group_policy`` extra spec is required to indicate how the
  groups should interact. With ``group_policy=none``, separate groupings -
  numbered or unnumbered - may or may not be satisfied by the same provider.
  With ``group_policy=isolate``, numbered groups are guaranteed to be
  satisfied by *different* providers - though there may still be overlap with
  the unnumbered group.

  ``trait`` keys for a given group are optional.  That is, you may specify
  ``resources42:XXX`` without a corresponding ``trait42:YYY``. However, the
  reverse (specifying ``trait42:YYY`` without ``resources42:XXX``) will
  result in an error.

  The semantic of the (unnumbered) ``resources`` and ``trait`` keys is
  unchanged: the resources and traits specified thereby may be satisfied by
  any provider on the same host or associated via aggregate.

.. releasenotes/notes/hide_hypervisor_id-flavor-a7c16afeab553b01.yaml @ b'edf67cfda20b82c62a8c493c8daa1337841aba0a'

- Added a new flavor extra_spec, ``hide_hypervisor_id``, which hides
  the hypervisor signature for the guest when true ('kvm' won't appear
  in ``lscpu``). This acts exactly like and in parallel to the image
  property ``img_hide_hypervisor_id`` and is useful for running the
  nvidia drivers in the guest.
  Currently, this is only supported in the libvirt driver.

.. releasenotes/notes/libvirt-cpu-model-extra-flags-a23085f58bd22d27.yaml @ b'cc27a2007f314df18812d54a087f6192d6aed3fb'

- The libvirt driver now allows specifying individual CPU feature
  flags for guests, via a new configuration attribute
  ``[libvirt]/cpu_model_extra_flags`` -- this is valid in combination
  with all the three possible values for ``[libvirt]/cpu_mode``:
  ``custom``, ``host-model``, or ``host-passthrough``.  The
  ``cpu_model_extra_flags`` also allows specifying multiple CPU flags.
  Refer to its documentation in ``nova.conf`` for usage details.

  One of the motivations for this is to alleviate the performance
  degradation (caused as a result of applying the "Meltdown" CVE
  fixes) for guests running with certain Intel-based virtual CPU
  models.  This guest performance impact is reduced by exposing the
  CPU feature flag 'PCID' ("Process-Context ID") to the *guest* CPU,
  assuming that it is available in the physical hardware itself.

  Note that besides ``custom``, Nova's libvirt driver has two other
  CPU modes: ``host-model`` (which is the default), and
  ``host-passthrough``.  Refer to the
  ``[libvirt]/cpu_model_extra_flags`` documentation for what to do
  when you are using either of those CPU modes in context of 'PCID'.

.. releasenotes/notes/libvirt-file-backed-memory-ea2cd292200fc11c.yaml @ b'cbc28f0d15287dcf24a07f835210affa41c38993'

- The libvirt driver now allows utilizing file backed memory for qemu/KVM
  virtual machines, via a new configuration attribute
  ``[libvirt]/file_backed_memory``, defaulting to 0 (disabled).

  ``[libvirt]/file_backed_memory`` specifies the available capacity in MiB
  for file backed memory, at the directory configured for
  ``memory_backing_dir`` in libvirt's ``qemu.conf``. When enabled, the
  libvirt driver will report the configured value for the total memory
  capacity of the node, and will report used memory as the sum of all
  configured guest memory.

  Live migrations from nodes not compatible with file backed memory to nodes
  with file backed memory is not allowed, and will result in an error. It's
  recommended to upgrade all nodes before enabling file backed memory.

  Note that file backed memory is not compatible with hugepages, and is not
  compatible with memory overcommit. If file backed memory is enabled,
  ``ram_allocation_ratio`` must be configured to ``1.0``

  For more details, see the admin guide documentation:

  https://docs.openstack.org/nova/latest/admin/file-backed-memory.html

.. releasenotes/notes/mirror-host-aggregates-to-placement-597473efa94ee558.yaml @ b'5eda1fab85e907a59d3be36067bfe25250a7be56'

- We now attempt to mirror the association of compute host to host aggregate
  into the placement API. When administrators use the ``POST
  /os-aggregates/{aggregate_id}/action`` Compute API call to add or remove a
  host from an aggregate, the nova-api service will attempt to ensure that a
  corresponding record is created in the placement API for the resource
  provider (compute host) and host aggregate UUID.

  The nova-api service needs to understand how to connect to the placement
  service in order for this mirroring process to work. Administrators should
  ensure that there is a ``[placement]`` section in the nova.conf file which
  is used by the nova-api service, and that credentials for interacting with
  placement are contained in that section.

  If the ``[placement]`` section is missing from the nova-api's nova.conf
  file, nothing will break however there will be some warnings generated in
  the nova-api's log file when administrators associate a compute host with a
  host aggregate. However, this will become a failure starting in the 19.0.0
  Stein release.

.. releasenotes/notes/multi-member-of-4f9518a96652c0c6.yaml @ b'368b6d9293102696d7b208119e444127f638e0f1'

- A new 1.24 placement API microversion adds the ability to specify multiple
  ``member_of`` query parameters for the ``GET /resource_providers`` and `GET
  allocation_candidates` endpoints.
  When multiple ``member_of`` query parameters are received, the placement
  service will return resource providers that match all of the requested
  aggregate memberships. The ``member_of=in:<agg uuids>`` format is still
  supported and continues to indicate an IN() operation for aggregate
  membership. Some examples for using the new functionality:
  Get all providers that are associated with BOTH agg1 and agg2:
  ?member_of=agg1&member_of=agg2
  Get all providers that are associated with agg1 OR agg2:
  ?member_of=in:agg1,agg2
  Get all providers that are associated with agg1 and ANY OF (agg2, agg3):
  ?member_of=agg1&member_of=in:agg2,agg3
  Get all providers that are associated with ANY OF (agg1, agg2) AND are also
  associated with ANY OF (agg3, agg4):
  ?member_of=in:agg1,agg2&member_of=in:agg3,agg4

.. releasenotes/notes/multiple-scheduler-workers-3e5ac0d86f436338.yaml @ b'09898781656c987afe7019aaa63a68eda142f72e'

- It is now possible to configure multiple *nova-scheduler* workers via the
  ``[scheduler]workers`` configuration option. By default, the option runs
  ``ncpu`` workers if using the ``filter_scheduler`` scheduler driver,
  otherwise the default is 1.

  Since `blueprint placement-claims`_ in Pike, the FilterScheduler
  uses the Placement service to create resource allocations (claims)
  against a resource provider (i.e. compute node) chosen by the scheduler.
  That reduces the risk of scheduling collisions when running multiple
  schedulers.

  Since other scheduler drivers, like the CachingScheduler, do not
  use Placement, it is recommended to set workers=1 (default) for those
  other scheduler drivers.

  .. _blueprint placement-claims: https://specs.openstack.org/openstack/nova-specs/specs/pike/implemented/placement-claims.html

.. releasenotes/notes/nested-resource-providers-allocation-candidates-66c1c5b0a3e93513.yaml @ b'5b4aa7845901a6127ad7266596d9aca4442f7d48'

- From microversion 1.29, we support allocation candidates with nested
  resource providers. Namely, the following features are added.
  1) ``GET /allocation_candidates`` is aware of nested providers. Namely,
  when provider trees are present, ``allocation_requests`` in the response
  of ``GET /allocation_candidates`` can include allocations on combinations
  of multiple resource providers in the same tree.
  2) ``root_provider_uuid`` and ``parent_provider_uuid`` are added to
  ``provider_summaries`` in the response of ``GET /allocation_candidates``.

.. releasenotes/notes/notification-transformation-rocky-e541ba916e8e38fd.yaml @ b'198885522c3a4f63ec1b2a508d88c0d550ab3878'

- The following legacy notifications have been transformed to
  a new versioned payload:

  * ``aggregate.updatemetadata``
  * ``aggregate.updateprop``
  * ``instance.exists``
  * ``instance.live_migration._post``
  * ``instance.live.migration.force.complete``
  * ``instance.live_migration.post.dest``
  * ``instance.live_migration.rollback.dest``
  * ``instance.rebuild.scheduled``
  * ``metrics.update``
  * ``servergroup.addmember``

  Consult https://docs.openstack.org/nova/latest/reference/notifications.html
  for more information including payload samples.

.. releasenotes/notes/nova-manage-placement-sync-aggregates-1e6380eceda7dc9b.yaml @ b'aa6360d68385f36062034bdd1d982e918ea33c94'

- A ``nova-manage placement sync_aggregates`` command has been added which
  can be used to mirror nova host aggregates to resource provider aggregates
  in the placement service. This is a useful tool if you are using aggregates
  in placement to optimize scheduling:

  https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#aggregates-in-placement

  The ``os-aggregates`` compute API ``add_host`` and ``remove_host`` actions
  will automatically add/remove compute node resource providers from resource
  provider aggregates in the placement service if the ``nova-api`` service
  is configured to communicate with the placement service, so this command
  is mostly useful for existing deployments with host aggregates which are
  not yet mirrored in the placement service.

  For more details, see the command documentation:

  https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement

.. releasenotes/notes/numa-aware-vswitches-162132290dd6ef17.yaml @ b'803f85d7e638c7367db709a93f732f12d81e083a'

- It is now possible to configure NUMA affinity for most neutron networks.
  This is available for networks that use a ``provider:network_type`` of
  ``flat`` or ``vlan`` and a ``provider:physical_network`` (L2 networks) or
  networks that use a ``provider:network_type`` of ``vxlan``, ``gre`` or
  ``geneve`` (L3 networks).

  For more information, refer to the `spec`__ and `documentation`__.

  __ https://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/numa-aware-vswitches.html
  __ https://docs.openstack.org/nova/latest/admin/networking.html

.. releasenotes/notes/placement-aggregate-generation-9dad79fb0356fcc0.yaml @ b'3216f078d481d2b48b90b63c2d93082c86b9809d'

- Placement API microversion 1.19 enhances the payloads for the
  ``GET /resource_providers/{uuid}/aggregates`` response and the
  ``PUT /resource_providers/{uuid}/aggregates`` request and response to be
  identical, and to include the ``resource_provider_generation``. As with
  other generation-aware APIs, if the ``resource_provider_generation``
  specified in the ``PUT`` request does not match the generation known by the
  server, a 409 Conflict error is returned.

.. releasenotes/notes/placement-database-2e087f379273535d.yaml @ b'ae4285c837a65c2ebd918b68fefc720d79b15eb9'

- An optional configuration group ``placement_database`` can be used in
  nova.conf to configure a separate database for use with the placement
  API.

  If ``placement_database.connection`` has a value then the
  ``placement_database`` configuration group will be used to configure a
  separate placement database, including using ``connection`` to identify the
  target database. That database will have a schema that is a replica of all
  the tables used in the API database. The new database schema will be
  created and synchronized when the ``nova-manage api_db sync`` command is
  run.

  When the ``placement_database.connection`` setting is omitted the existing
  settings for the ``api_database`` will be used for hosting placement data.

  Setting ``placement_database.connection`` and calling
  ``nova-manage api_db sync`` will only create tables. No data will be
  migrated. In an existing OpenStack deployment, if there is existing
  placement data in the ``nova_api`` database this will not be copied. It is
  up to the deployment to manually replicate that data in a fashion that
  works best for the environment.

.. releasenotes/notes/placement-error-code-fcbbf5d45560984e.yaml @ b'bd9f24b7aa4284731f08e7970649d5e4998ee44b'

- In microversion 1.23 of the placement service, JSON formatted error
  responses gain a new attribute, ``code``, with a value that identifies the
  type of this error. This can be used to distinguish errors that are
  different but use the same HTTP status code. Any error response which does
  not specifically define a code will have the code
  ``placement.undefined_code``.

.. releasenotes/notes/placement-forbidden-traits-ace037856aa29a09.yaml @ b'4e07d81260a0747ef531e382f1fab97bb60d7798'

- Placement microversion '1.22' adds support for expressing traits which are
  forbidden when filtering ``GET /resource_providers`` or ``GET
  /allocation_candidates``. A forbidden trait is a properly formatted trait
  in the existing ``required`` parameter, prefixed by a ``!``. For example
  ``required=!STORAGE_DISK_SSD`` asks that the results not include any
  resource providers that provide solid state disk.

.. releasenotes/notes/placement-generation-from-create-provider-203a0ac1ebfe64d9.yaml @ b'388db7e6e2521bb66a19459f85adf1110a8d50ca'

- In placement API microversion 1.20, a successful ``POST /resource_providers``
  returns 200 with a payload representing the newly-created resource
  provider.  The format is the same format as the result of the corresponding
  ``GET /resource_providers/{uuid}`` call. This is to allow the caller to
  glean automatically-set fields, such as UUID and generation, without a
  subsequent GET.

.. releasenotes/notes/placement-granular-resource-requests-944f9b73f306429f.yaml @ b'9af073384cca305565e741c1dfbb359c1e562a4e'

- In version 1.25 of the Placement API, ``GET /allocation_candidates`` is
  enhanced to accept numbered groupings of resource, required/forbidden
  trait, and aggregate association requests. A ``resources`` query parameter
  key with a positive integer suffix (e.g. ``resources42``) will be logically
  associated with ``required`` and/or ``member_of`` query parameter keys with
  the same suffix (e.g. ``required42``, ``member_of42``). The resources,
  required/forbidden traits, and aggregate associations in that group will be
  satisfied by the same resource provider in the response. When more than one
  numbered grouping is supplied, the ``group_policy`` query parameter is
  required to indicate how the groups should interact. With
  ``group_policy=none``, separate groupings - numbered or unnumbered - may or
  may not be satisfied by the same provider. With ``group_policy=isolate``,
  numbered groups are guaranteed to be satisfied by *different* providers -
  though there may still be overlap with the unnumbered group.  In all cases,
  each ``allocation_request`` will be satisfied by providers in a single
  non-sharing provider tree and/or sharing providers associated via aggregate
  with any of the providers in that tree.

  The ``required`` and ``member_of`` query parameters for a given group are
  optional.  That is, you may specify ``resources42=XXX`` without a
  corresponding ``required42=YYY`` or ``member_of42=ZZZ``. However, the
  reverse (specifying ``required42=YYY`` or ``member_of42=ZZZ`` without
  ``resources42=XXX``) will result in an error.

  The semantic of the (unnumbered) ``resources``, ``required``, and
  ``member_of`` query parameters is unchanged: the resources, traits, and
  aggregate associations specified thereby may be satisfied by any provider
  in the same non-sharing tree or associated via the specified aggregate(s).

.. releasenotes/notes/placement-incomplete-consumer-configuration-b775dac1bcd34f9d.yaml @ b'03d80cf0de85099bf9d306578cd065af5bed7994'

- Prior to microversion 1.8 of the placement API, one could create
  allocations and not supply a project or user ID for the consumer of the
  allocated resources. While this is no longer allowed after placement API
  1.8, older allocations exist and we now ensure that a consumer record is
  created for these older allocations. Use the two new CONF options
  ``CONF.placement.incomplete_consumer_project_id`` and
  ``CONF.placement.incomplete_consumer_user_id`` to control the project and
  user identifiers that are written for these incomplete consumer records.

.. releasenotes/notes/placement-required-traits-on-list-resource-providers-fab11cdb36cd3502.yaml @ b'558540a27c01bf048d23dd7053d0601b5282d40d'

- Placement API microversion 1.18 adds support for the ``required`` query
  parameter to the ``GET /resource_providers`` API. It accepts a
  comma-separated list of string trait names. When specified, the API
  results will be filtered to include only resource providers marked with
  all the specified traits. This is in addition to (logical AND) any
  filtering based on other query parameters.

  Trait names which are empty, do not exist, or are otherwise invalid will
  result in a 400 error.

.. releasenotes/notes/placement-return-all-resources-bfc7e3f8b5151e28.yaml @ b'97530c2ca38228dcebeb231a187806f1e66d4570'

- From microversion 1.27, the ``provider_summaries`` field in the
  response of the ``GET /allocation_candidates`` API includes all
  the resource class inventories, while it had only requested
  resource class inventories with older microversions.
  Now callers can use this additional inventory information in
  making further sorting or filtering decisions.

.. releasenotes/notes/powervm-hotplug-interface-e54c84ebc039b18c.yaml @ b'ed525cc403d98e26d4c88fdc00d476ada1eb9ced'

- The PowerVM driver now supports hot plugging/unplugging of network
  interfaces.

.. releasenotes/notes/powervm-localdisk-ccdf2347226303a8.yaml @ b'026c2a61d08d6f2202e417a70313d182fdba3f45'

- The PowerVM virt driver now supports booting from local ephemeral disk.
  Two new configuration options have been introduced to the ``powervm``
  configuration group, ``disk_driver`` and ``volume_group_name``. The former
  allows the selection of either ssp or localdisk for the PowerVM disk
  driver. The latter specifies the name of the volume group when using the
  localdisk disk driver.

.. releasenotes/notes/powervm-snapshot-c44dc38bf69360f2.yaml @ b'3bb59e393f51eeef7299e331a033bd9385867e31'

- The PowerVM virt driver now supports instance snapshot.

.. releasenotes/notes/powervm-vscsi-46c82559f082d4ed.yaml @ b'e997ca68b38347b7ded34d1b6d77b9cbd4608438'

- The PowerVM virt driver now supports vSCSI Fibre Channel cinder volumes.
  PowerVM now supports attaching, detaching, and extending the size of vSCSI
  FC cinder volumes.

.. releasenotes/notes/purge-db-command-d4cd9ea5400f479c.yaml @ b'ff47787e11a0a1b6299298b25b4c982bcfae6e1c'

- The nova-manage command now has a 'db purge' command that will delete data
  from the shadow tables after 'db archive_deleted_rows' has been run. There
  is also now a ``--purge`` option for 'db archive_deleted_rows' that will
  automatically do a full purge after archiving.

.. releasenotes/notes/pvm_proc_units_factor-50d1e4ba079d7a6c.yaml @ b'8a67fcd1c20c85676ecb95c518aa5831204279ed'

- Introduces the ``powervm`` configuration group which contains the
  ``proc_units_factor`` configuration option. This allows the operator to
  specify the physical processing power to assign per vCPU.

.. releasenotes/notes/reset-marker-for-map_instances-0c841ef45e3adc7b.yaml @ b'98163f98b700840f50c689e4a3aed7e28dd0c1ef'

- Currently the ``nova-manage cell_v2 map_instances`` command uses a marker
  setup by which repeated runs of the command will start from where the last
  run finished, by default. A ``--reset`` option has been added to this command
  by which the marker can be reset and users can start the process from the
  beginning if needed, instead of the default behavior.

.. releasenotes/notes/rpc_timeout_changes-6b7e365bb44f7f3a.yaml @ b'fe26a52024416ed2d37c2d5027da4b23231dc515'

- Utilizing recent changes in oslo.messaging, the
  ``rpc_response_timeout`` value can now be increased significantly if
  needed or desired to solve issues with long-running RPC calls
  timing out before completing due to legitimate reasons (such as
  live migration prep). If ``rpc_response_timeout`` is increased
  beyond the default, nova will request active call monitoring from
  oslo.messaging, which will effectively heartbeat running
  activities to avoid a timeout, while still detecting failures
  related to service outages or message bus congestion in a
  reasonable amount of time. Further, the
  ``[DEFAULT]/long_rpc_timeout`` option has been added which allows
  setting an alternate timeout value for longer-running RPC calls
  which are known to take a long time. The default for this is 1800
  seconds, and the ``rpc_response_timeout`` value will be used for the
  heartbeat frequency interval, providing a similar
  failure-detection experience for these calls despite the longer
  overall timeout. Currently, only the live migration RPC call uses
  this longer timeout value.

.. releasenotes/notes/scaleio-extend-volume-d82c39a30e0a09ca.yaml @ b'ce90bec66f4844c17c2b1b63a0405d9ae20ebbbd'

- Added ability to extend an attached ScaleIO volume when using the libvirt compute driver.

.. releasenotes/notes/stop-scheduling-to-disabled-cells-eadbfe30d1f6be65.yaml @ b'ba083b0c9873edb12dbf5ec3216ea9ff1e83dd30'

- Support for filtering out disabled cells during scheduling for server
  create requests has been added. Firstly the concept of disabled
  cells has been introduced which means such disabled cells will not be
  candidates for the scheduler. Secondly changes have been made to the filter
  scheduler to ensure that it chooses only the enabled cells for scheduling
  and filters out the disabled ones. Note that operations on existing
  instances already inside a disabled cell like move operations will not be
  blocked.

.. releasenotes/notes/tenant_aggregate_placement_filter-c2fed8889f43b6e3.yaml @ b'a27da62d823447ad4c61d07914a6acd593082c87'

- The scheduler can now use placement to more efficiently query for hosts within a
  tenant-restricted aggregate. This requires that a host aggregate is created in
  nova with the ``filter_tenant_id`` key (optionally suffixed with any string for
  multiple tenants, like ``filter_tenant_id3=$tenantid``) and the same aggregate
  is created in placement with an identical UUID. The
  ``[scheduler]/limit_tenants_to_placement_aggregate`` config option enables this
  behavior and ``[scheduler]/placement_aggregate_required_for_tenants`` makes it
  either optional or mandatory, allowing only some tenants to be restricted. For
  more information, see the schedulers section__ of the administration guide.

  __ https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#aggregates-in-placement

.. releasenotes/notes/trigger-notifications-when-lock-unlock-instances-5c0bb9262c0b4f0b.yaml @ b'0b9b37fe9ad6ca7c15fdaabcf73afcda01fe6dc6'

- The versioned ``instance.lock`` and ``instance.unlock`` notifications have
  been added. These notifications are emitted as a result of the respective
  server ``lock`` and server ``unlock`` REST API calls.

  See https://docs.openstack.org/nova/latest/reference/notifications.html#existing-versioned-notifications
  for notification samples.

.. releasenotes/notes/trusted-certs-microversion-589b75f0180d4d51.yaml @ b'dc9fb5842cd302ec5e2fb9a68566a0214738badd'

- The 2.63 compute REST API microversion adds support for the
  ``trusted_image_certificates`` parameter, which is used to define a
  list of trusted certificate IDs that can be used during image
  signature verification and certificate validation. The list is
  restricted to a maximum of 50 IDs. Note that there is not support
  with volume-backed servers.

  The ``trusted_image_certificates`` request parameter can be passed to
  the server create and rebuild APIs (if allowed by policy):

  * ``POST /servers``
  * ``POST /servers/{server_id}/action (rebuild)``

  The following policy rules were added to restrict the usage of the
  ``trusted_image_certificates`` request parameter in the server create and
  rebuild APIs:

  * ``os_compute_api:servers:create:trusted_certs``
  * ``os_compute_api:servers:rebuild:trusted_certs``

  The ``trusted_image_certificates`` parameter will be in the response
  body of the following APIs (not restricted by policy):

  * ``GET /servers/detail``
  * ``GET /servers/{server_id}``
  * ``PUT /servers/{server_id}``
  * ``POST /servers/{server_id}/action (rebuild)``

  The payload of the ``instance.create.start`` and ``instance.create.end``
  and ``instance.create.error`` versioned notifications have been extended
  with the ``trusted_image_certificates`` field that contains the list of
  trusted certificate IDs used when the instance is created.

  The payload of the ``instance.rebuild.start`` and ``instance.rebuild.end``
  and ``instance.rebuild.error`` versioned notifications have been extended
  with the ``trusted_image_certificates`` field that contains the list of
  trusted certificate IDs used when the instance is rebuilt. This change also
  causes the type of the payload object to change from
  ``InstanceActionPayload`` version 1.6 to ``InstanceActionRebuildPayload``
  version 1.7. See the `notification dev reference`_ for the sample file of
  ``instance.rebuild.start`` as an example.

  .. _notification dev reference: https://docs.openstack.org/developer/nova/notifications.html

.. releasenotes/notes/trusted-metatada-b999f1417f678c44.yaml @ b'f9ddddc3586193f4edd5f7bb2a05e91b7d15b494'

- As of the ``2018-08-27`` metadata API version, a boolean ``vf_trusted`` key
  appears for all network interface ``devices`` in ``meta_data.json``,
  indicating whether the device is a trusted virtual function or not.

.. releasenotes/notes/trusted-vfs-abee6dff7c9b6940.yaml @ b'88e21d8e5e9abf2c0aba42aabbac3d21e750140c'

- The libvirt compute driver now allows users to create instances
  with SR-IOV virtual functions which will be configured as trusted.

  The operator will have to create pools of devices with tag
  trusted=true.

  For example, modify ``/etc/nova/nova.conf`` and set:

  .. code-block:: ini

    [pci]
    passthrough_whitelist = {"devname": "eth0", "trusted": "true",
                             "physical_network":"sriovnet1"}

  Where "eth0" is the interface name related to the physical
  function.

  Ensure that the version of ``ip-link`` on the compute host supports setting
  the trust mode on the device.

  Ports from the physical network will have to be created with a
  binding profile to match the trusted tag. Only ports with
  ``binding:vif_type=hw_veb`` and ``binding:vnic_type=direct`` are supported.

  .. code-block:: ini

    $ neutron port-create <net-id> \
                          --name sriov_port \
                          --vnic-type direct \
                          --binding:profile type=dict trusted=true

.. releasenotes/notes/use-new-style-policy-in-notifications-3c6eefbb56224be2.yaml @ b'd1ccea4dd79af064a363794b9071691c322a64bf'

- The new style ``policy`` field has been added to ``ServerGroupPayload``.
  The ``server_group.create``, ``server_group.delete`` and
  ``server_group.add_member`` versioned notifications will be updated to
  include the new ``policy`` and ``rules`` field. The ``policies`` field is
  deprecated for removal but still put into the notification payload for
  backward compatibility.

.. releasenotes/notes/xenapi-image-handler-7628a7221b7323e2.yaml @ b'f7593ded8f2e5b768b868914d211163c8b9508ea'

- Add a new option of ``image_handler`` in the ``xenapi`` section for
  configuring the image handler plugin which will be used by XenServer
  to download or upload images. The value for this option should be a
  short name representing a supported handler.

  The following are the short names and description of the plugins which
  they represent:

  * ``direct_vhd``

    This plugin directly processes the VHD files in XenServer SR(Storage
    Repository). So this plugin only works when the host's SR type is
    file system based e.g. ext, nfs.  This is the default plugin.

  * ``vdi_local_dev``

    This plugin implements an image upload method which attaches the VDI
    as a local disk in the VM in which the OpenStack Compute service runs.
    It uploads the raw disk to glance when creating an image; When booting
    an instance from a glance image, it downloads the image and streams it
    into the disk which is attached to the compute VM.

  * ``vdi_remote_stream``

    This plugin implements an image proxy in nova compute service.

    For image upload, the proxy will export a data stream for a VDI from
    XenServer via the remote API supplied by XAPI; convert the stream
    to the image format supported by glance; and upload the image to glance.

    For image download, the proxy downloads an image stream from glance;
    extracts the data stream from the image stream; and then remotely
    imports the data stream to XenServer's VDI via the remote API supplied
    by XAPI.

    Note: Under this implementation, the image data may reside in one or
    more pieces of storage of various formats on the host, but the import
    and export operations interact with a single, proxied VDI object
    independent of the underlying structure.


.. _Release Notes_18.0.0_rocky-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1778044-f498ee2f2cfb35ea.yaml @ b'78891c2305bff6e16706339a9c5eca99a84e409c'

- The initial implementation of native LUKS decryption within Libvirt 2.2.0
  had a `known issue`_ with the use of passphrases that were a multiple of 16
  bytes in size. This was `resolved`_ in the upstream 3.3.0 release of
  Libvirt and has been backported to various downstream distribution specific
  versions.

  A simple warning will reference the above if this issue is encountered by
  Nova however operators of the environment will still need to update
  Libvirt to a version where this issue has been fixed to resolve the issue.

  .. _known issue: https://bugzilla.redhat.com/show_bug.cgi?id=1447297
  .. _resolved: https://libvirt.org/git/?p=libvirt.git;a=commit;h=7189099


.. _Release Notes_18.0.0_rocky-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/aarch64-minimum-libvirt-version-86331e5282effbf0.yaml @ b'30b7a566aaeb3d9a1e8145cdbaa55b89c3946722'

- The minimum version of libvirt on AArch64 architecture that nova compute will interoperate with is now 3.6.0. Deployments using older versions of libvirt on AArch64 should upgrade.

.. releasenotes/notes/bp-remove-nova-network-api-removals-931ad60364f6f2a8.yaml @ b'db294b1e33f18e01a3e4a20d537880ffd1b110fe'

- The *nova-network* service has been deprecated since the 14.0.0 Newton
  release and now the following *nova-network* specific REST APIs have been
  removed along with their related policy rules. Calling these APIs will now
  result in a ``410 HTTPGone`` error response.

  * ``GET /os-fping``
  * ``GET /os-fping/{server_id}``
  * ``GET /servers/{server_id}/os-virtual-interfaces``
  * ``GET /os-fixed-ips/{fixed_ip}``
  * ``POST /os-fixed-ips/{fixed_ip}/action (reserve)``
  * ``POST /os-fixed-ips/{fixed_ip}/action (unreserve)``
  * ``GET /os-floating-ips-bulk``
  * ``GET /os-floating-ips-bulk/{host_name}``
  * ``POST /os-floating-ips-bulk``
  * ``PUT /os-floating-ips-bulk/delete``
  * ``GET /os-floating-ip-dns``
  * ``PUT /os-floating-ip-dns/{domain}``
  * ``DELETE /os-floating-ip-dns/{domain}``
  * ``GET /os-floating-ip-dns/{domain}/entries/{ip}``
  * ``GET /os-floating-ip-dns/{domain}/entries/{name}``
  * ``PUT /os-floating-ip-dns/{domain}/entries/{name}``
  * ``DELETE /os-floating-ip-dns/{domain}/entries/{name}``

  In addition, the following configuration options have been removed.

  * ``[api]/fping_path``

.. releasenotes/notes/bug-1679750-local-delete-allocations-cb7bfbcb6c36b6a2.yaml @ b'ea9d0af31395fbe1686fa681cd91226ee580796e'

- The ``nova-api`` service now requires the ``[placement]`` section to be
  configured in nova.conf if you are using a separate config file just for
  that service. This is because the ``nova-api`` service now needs to talk
  to the placement service in order to delete resource provider allocations
  when deleting an instance and the ``nova-compute`` service on which that
  instance is running is down. This change is idempotent if
  ``[placement]`` is not configured in ``nova-api`` but it will result in
  new warnings in the logs until configured. See bug
  https://bugs.launchpad.net/nova/+bug/1679750 for more details.

.. releasenotes/notes/bug-1753550-image-ref-url-notifications-42df5911a46b7de7.yaml @ b'6482165bb1f44f5c98d9361153d737c22c92112d'

- The ``image_ref_url`` entry in legacy instance notification payloads will
  be just the instance image id if ``[glance]/api_servers`` is not set
  and the notification is being sent from a periodic task. In this case the
  periodic task does not have a token to get the image service endpoint URL
  from the identity service so only the image id is in the payload. This
  does not affect versioned notifications.

.. releasenotes/notes/bug-1759316-nova-status-api-version-check-183fac0525bfd68c.yaml @ b'eaf6340847c35ace3b4b681a95b8a79a7a3f2491'

- A new check is added to ``nova-status upgrade check`` which will scan
  all cells looking for ``nova-osapi_compute`` service versions which are
  from before Ocata and which may cause issues with how the compute API
  finds instances. This will result in a warning if:

  * No cell mappings are found
  * The minimum ``nova-osapi_compute`` service version is less than 15 in
    any given cell

  See https://bugs.launchpad.net/nova/+bug/1759316 for more details.

.. releasenotes/notes/deprecate-keymap-options-b41ad9f33a5923e1.yaml @ b'cab8139498c7ea6b05cfdc8b4997276051b943fc'

- noVNC 1.0.0 introduced a breaking change in the URLs used to access the
  console. Previously, the ``vnc_auto.html`` path was used but it is now
  necessary to use the ``vnc_lite.html`` path. When noVNC is updated to
  1.0.0, ``[vnc] novncproxy_base_url`` configuration value must be updated on
  each compute node to reflect this change.

.. releasenotes/notes/full_host_state_instances-6fbc828564a000ec.yaml @ b'91f5af7ee7f7140eafb7237875f6cd6ea1abcd38'

- Deployments with custom scheduler filters (or weighers) that rely on
  the ``HostState.instances`` dict to contain full Instance objects will
  now hit a performance penalty because the Instance values in that dict
  are no longer fully populated objects. The in-tree filters that do rely
  on ``HostState.instances`` only care about the (1) uuids of the instances
  per host, which is the keys in the dict and (2) the number of instances
  per host, which can be determined via ``len(host_state.instances)``.

  Custom scheduler filters and weighers should continue to function since
  the Instance objects will lazy-load any accessed fields, but this means
  a round-trip to the database to re-load the object per instance, per host.

  If this is an issue for you, you have three options:

  * Accept this change along with the performance penalty
  * Revert change I766bb5645e3b598468d092fb9e4f18e720617c52 and carry
    the fork in the scheduler code
  * Contribute your custom filter/weigher upstream (this is the best option)

.. releasenotes/notes/migration-tool-to-populate-inst.avz-29fed2fe57a9764d.yaml @ b'6b4c38c04177ff194d05368cd4aff69958075167'

- A new online data migration has been added to populate missing
  instance.availability_zone values for instances older than Pike whose
  availability_zone was not specified during boot time. This can be run
  during the normal ``nova-manage db online_data_migrations`` routine.
  This fixes `Bug 1768876`_

  .. _Bug 1768876: https://bugs.launchpad.net/nova/+bug/1768876

.. releasenotes/notes/move-ivs-plug-unplug-to-separate-os-vif-plugin-f7ee42da4ed9739b.yaml @ b'92323586b5d03b31c18657ad64646a8ce3b8a742'

- This release moves the livirt driver ``IVS`` VIF plug-unplug to a separate
  package called ``os-vif-bigswitch``. This package is a requirement on
  compute nodes when using ``networking-bigswitch`` as neutron ML2 and L3
  driver.
  Releases are available on https://pypi.org/project/os-vif-bigswitch/. Major
  version for the package matches upstream neutron version number. Minor
  version tracks compatibility with Big Cloud Fabric (BCF) releases, and
  typically is set to the lowest supported BCF release.

.. releasenotes/notes/multiple-scheduler-workers-3e5ac0d86f436338.yaml @ b'09898781656c987afe7019aaa63a68eda142f72e'

- The new ``[scheduler]workers`` configuration option defaults to ``ncpu``
  workers if using the ``filter_scheduler`` scheduler driver. If you are
  running *nova-scheduler* on the same host as other services, you may want
  to change this default value, or to otherwise account for running other
  instances of the *nova-scheduler* service.

.. releasenotes/notes/nova-status-check-ironic-flavor-migration-4c78314bf4e74ff6.yaml @ b'7eb670352126ed8d30426eb422fe5aed9cb21e7f'

- A new check is added to the ``nova-status upgrade check`` CLI which can
  assist with determining if ironic instances have had their embedded flavor
  migrated to use the corresponding ironic node custom resource class.

.. releasenotes/notes/nova-status-check-requestspec-migration-2a3b50b98fff9324.yaml @ b'e73f828057f8ec3d0693f1c498e59600caf1eeb6'

- A new check is added to the ``nova-status upgrade check`` CLI to make sure
  request spec online migrations have been run per-cell. Missing request spec
  compatibility code is planned to be removed in the Stein release.

.. releasenotes/notes/powervm-localdisk-ccdf2347226303a8.yaml @ b'026c2a61d08d6f2202e417a70313d182fdba3f45'

- The PowerVM virt driver previously used the PowerVM Shared Storage Pool
  disk driver by default. The default disk driver for PowerVM is now
  localdisk. See configuration option ``[powervm]/disk_driver`` for usage
  details.

.. releasenotes/notes/privsep-rocky-rootwrap-adds-644c43fbd86f9f8a.yaml @ b'7b43fb4ebda7eb1dac74d1aaac1d347a3b611a96'

- The following commands are no longer required to be listed in your rootwrap
  configuration: e2fsck; mkfs; tune2fs; xenstore_read.

.. releasenotes/notes/pvm_proc_units_factor-50d1e4ba079d7a6c.yaml @ b'8a67fcd1c20c85676ecb95c518aa5831204279ed'

- Previously the PowerVM driver would default to 0.5 physical processors per
  vCPU, which is the default from the pypowervm library. The default will now
  be 0.1 physical processors per vCPU, from the ``proc_units_factor``
  configuration option in the ``powervm`` configuration group.

.. releasenotes/notes/remove-baremetal-filters-52db06d597645d00.yaml @ b'4a55e260a4e779287a9af85d2c04e9d7dafdb4d2'

- The ``[filter_scheduler]/use_baremetal_filters`` and
  ``[filter_scheduler]/baremetal_enabled_filters`` configuration options
  were deprecated in the 16.0.0 Pike release since deployments serving
  baremetal instances should be `scheduling based on resource classes`_.
  Those options have now been removed.

  Similarly, the ``ironic_host_manager`` choice for the
  ``[scheduler]/host_manager`` configuration option was deprecated in the
  17.0.0 Queens release because ``ironic_host_manager`` is only useful when
  using ``use_baremetal_filters=True`` and ``baremetal_enabled_filters``.
  Now that those options are gone, the deprecated ``ironic_host_manager``
  host manager choice has also been removed. As a result, the
  ``[scheduler]/host_manager`` configuration option has also been removed
  since there is only one host manager now and no need for an option.

  Remember to run ``nova-status upgrade check`` before upgrading to
  18.0.0 Rocky to ensure baremetal instances have had their embedded
  flavor migrated to use the corresponding ironic node custom resource class.

  .. _scheduling based on resource classes: https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-based-on-resource-classes

.. releasenotes/notes/remove-crypt-opts-67a1f304ae09aaeb.yaml @ b'a869b9c7909737d7eb6de94da8c101c3a41faa73'

- The following options, previously found in the ``[crypto]`` group, have
  been removed:

  - ``ca_file``
  - ``key_file``
  - ``crl_file``
  - ``keys_path``
  - ``ca_path``
  - ``use_project_ca``
  - ``user_cert_subject``
  - ``project_cert_subject``

  These have not been used in recent releases.

.. releasenotes/notes/remove-db_driver-config-opt-50110843b3221fc4.yaml @ b'a3e9530fe96114eb0facf535e868c534498bae18'

- The ``db_driver`` configuration option was deprecated in a previous release
  and has now been removed. This option allowed you to replace the SQLAlchemy
  database layer with one of your own. The approach was deprecated and
  unsupported, and it is now time to remove it completely.

.. releasenotes/notes/remove-deprecated-api-opts-d01d97fa19330e06.yaml @ b'1b112acb344bce835c98759fea2e89ffdfdd967b'

- The following deprecated configuration options have been removed from the
  ``api`` section of ``nova.conf``:

  - ``allow_instance_snapshots``

  These were deprecated in the 16.0.0 release as they allowed inconsistent
  API behavior across deployments. To disable snapshots in the
  ``createImage`` server action API, change the
  ``os_compute_api:servers:create_image`` and
  ``os_compute_api:servers:create_image:allow_volume_backed`` policies.

.. releasenotes/notes/remove-deprecated-compute-opts-b640061349806d9e.yaml @ b'0e43002c90cdad6286bbf41295f3b5d5b6874cbc'

- The following deprecated configuration options have been removed from the
  ``compute`` section of ``nova.conf``:

  - ``multi_instance_display_name_template``

  These were deprecated in the 15.0.0 release as they allowed for
  inconsistent API behavior across deployments.

.. releasenotes/notes/remove-deprecated-placement-opts-aeffb090a2e94bdc.yaml @ b'3db815957324f4bd6912238a960a90624d97c518'

- The following deprecated options have been removed from the ``placement``
  group of ``nova.conf``:

  - ``os_region_name`` (use ``region_name`` instead)
  - ``os_interface`` (use ``valid_interfaces`` instead)

  These were deprecated in 17.0.0 as they have been superseded by their
  respective keystoneauth1 Adapter configuration options.

.. releasenotes/notes/remove-monkey-patch-conf-220ea611d4ff348e.yaml @ b'9f48aee9b0ea68f7c8eba6a1f3d076e4194d804d'

- The following configuration options were deprecated for removal in the
  17.0.0 Queens release and have now been removed:

  - ``[DEFAULT]/monkey_patch``
  - ``[DEFAULT]/monkey_patch_modules``
  - ``[notifications]/default_publisher_id``

  Monkey patching nova is not tested, not supported, and is a barrier to
  interoperability. If you have code which relies on monkey patching
  decorators, for example, for notifications, please propose those changes
  upstream.

.. releasenotes/notes/remove-scheduler_driver_task_period-3d13293428db905d.yaml @ b'537155a982f8572d7668a841c12730a5602d039c'

- The ``[DEFAULT]/scheduler_driver_task_period`` configuration option,
  which was deprecated in the 15.0.0 Ocata release, has now been removed.
  Use the ``[scheduler]/periodic_task_interval`` option instead.

.. releasenotes/notes/remove-topic-config-opts-705ebd829a6e80b6.yaml @ b'af703e7376aba2c471389ae736f7d32ea7fa23a6'

- The ``[conductor] topic`` configuration option was previously deprecated
  and is now removed from nova.  There was no need to let users choose the
  RPC topics for all services. There was little benefit from this and it made
  it really easy to break nova by changing the value of topic options.

.. releasenotes/notes/remove-xenserver-vif-driver-option-850f8dcfe54bca7c.yaml @ b'c791cc4e04c4c8061ce0bf7c9a57e90de3001f56'

- The ``[xenserver]/vif_driver`` configuration option was deprecated in
  the 15.0.0 Ocata release and has now been removed. The only supported
  vif driver is now ``XenAPIOpenVswitchDriver`` used with Neutron as the
  backend networking service configured to run the
  ``neutron-openvswitch-agent`` service. See the `XenServer configuration
  guide`_ for more details on networking setup.

  .. _XenServer configuration guide: https://docs.openstack.org/nova/latest/admin/configuration/hypervisor-xen-api.html

.. releasenotes/notes/remove_exact_filters-2fd96171b93d7413.yaml @ b'3c756ac6597755b537cf6f7d27a5dcae2f3ed8c9'

- ExactCoreFilter, ExactDiskFilter and ExactRamFilter were deprecated for
  removal in the 16.0.0 Pike release and have now been removed.

  Baremetal scheduling will use the custom resource class defined for
  each baremetal node to make its selection. Refer to the ironic
  documentation for more details:

  https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-resource-classes

.. releasenotes/notes/rocky-libvirt-qemu-min-versions-56412048c12f1f52.yaml @ b'403320bc9991618b09ab55c5f650916f5c46dd75'

- The minimum required version of libvirt used by the ``nova-compute``
  service is now 1.3.1.  And the minimum required version of QEMU used
  by the ``nova-compute`` service is now 2.5.0. Failing to meet these
  minimum versions when using the libvirt compute driver will result
  in the ``nova-compute`` service not starting.

.. releasenotes/notes/rocky-quota-driver-config-6459e19ef2b43aa2.yaml @ b'1bbd144f5e201a19531f25177ed39fe52cc912dd'

- The ``[quota]/driver`` configuration option is no longer deprecated
  but now only allows one of two possible values:

  * ``nova.quota.DbQuotaDriver``
  * ``nova.quota.NoopQuotaDriver``

  This means it is no longer possible to class-load custom out-of-tree
  quota drivers.

.. releasenotes/notes/stop-scheduling-to-disabled-cells-eadbfe30d1f6be65.yaml @ b'ba083b0c9873edb12dbf5ec3216ea9ff1e83dd30'

- If the scheduler service is started before the cell mappings are created or
  setup, nova-scheduler needs to be restarted or SIGHUP-ed for the newly
  added cells to get registered in the scheduler cache.

.. releasenotes/notes/urandom-as-default-for-rng_dev_path-150a76b0ea74cbc2.yaml @ b'814bfd937238cbd211ea30805c36ae682cfd7b48'

- The default value of the configuration attribute
  ``[libvirt]/rng_dev_path`` is now set to ``/dev/urandom``.  Refer to
  the documentation of ``rng_dev_path`` for details.

.. releasenotes/notes/workarounds-enable-consoleauth-71d68c3879dc2c8a.yaml @ b'd362e4285137de63e14f0fe8e24fa874a975660b'

- The ``nova-consoleauth`` service has been deprecated and new consoles will
  have their token authorizations stored in cell databases. With this,
  console proxies are required to be deployed per cell. All existing consoles
  will be reset. For most operators, this should be a minimal disruption as
  the default TTL of a console token is 10 minutes.

  There is a new configuration option ``[workarounds]/enable_consoleauth``
  for use by operators who:

  * Are performing a live, rolling upgrade and all compute hosts are not
    currently running Rocky code
  * Have not yet deployed console proxies per cell
  * Have configured a much longer token TTL
  * Otherwise wish to avoid immediately resetting all existing consoles

  When the option is set to True, the console proxy will fall back on the
  ``nova-consoleauth`` service to locate existing console authorizations.
  The option defaults to False.

  Operators may unset the configuration option when:

  * The live, rolling upgrade has all compute hosts running Rocky code
  * Console proxies have been deployed per cell
  * All of the existing consoles have expired. For example, if a deployment
    has configured a token TTL of one hour, the operator may disable the
    ``[workarounds]/enable_consoleauth`` option, one hour after deploying the
    new code.

  .. note:: Cells v1 was not converted to use the database backend for
    console token authorizations. Cells v1 console token authorizations will
    continue to be supported by the ``nova-consoleauth`` service and use of
    the ``[workarounds]/enable_consoleauth`` option does not apply to
    Cells v1 users.


.. _Release Notes_18.0.0_rocky-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/Deprecate-support-for-Intel-CMT-events-017fbb890b631d70.yaml @ b'fc4794acc6b13afade1bb72a1ae9f574707d2f0d'

- Support to monitor performance events for Intel CMT (Cache
  Monitoring Technology, or "CQM" in Linux kernel parlance) -- namely
  ``cmt``, ``mbm_local`` and ``mbm_total`` -- via the config attribute
  ``[libvirt]/enabled_perf_events`` is now *deprecated* from Nova, and
  will be *removed* in the "Stein" release.  Otherwise, if you have
  enabled those events, and upgraded to Linux kernel 4.14 (or suitable
  downstream version), it will result in instances failing to boot.

  That is because the Linux kernel has deleted the ``perf`` framework
  integration with Intel CMT, as the feature was broken by design --
  an incompatibility between Linux's ``perf`` infrastructure and Intel
  CMT.  It was removed in upstream Linux version v4.14; but bear in
  mind that downstream Linux distributions with lower kernel versions
  than 4.14 have backported the said change.

.. releasenotes/notes/deprecate-api-eventlet-1a0279f1f2333082.yaml @ b'b53d81b03cad73fac7f558d287db0354f0a46ec1'

- Running API services (nova-osapi_compute or nova-metadata) with eventlet
  is now deprecated. Deploy with a WSGI server such as uwsgi or mod_wsgi.

.. releasenotes/notes/deprecate-keymap-options-b41ad9f33a5923e1.yaml @ b'cab8139498c7ea6b05cfdc8b4997276051b943fc'

- Two keymap-related configuration options have been deprecated:

  - ``[vnc] keymap``
  - ``[spice] keymap``

  The VNC option affects the libvirt and VMWare virt drivers, while the SPICE
  option only affects libvirt. For the libvirt driver, configuring these
  options resulted in lossy keymap conversions for the given graphics method.
  It is recommended that users should unset these options and configure their
  guests as necessary instead. In the case of noVNC, noVNC 1.0.0 should be
  used as this provides support for QEMU's Extended Key Event messages. Refer
  to `bug #1682020`__ and the `QEMU RFB pull request`__ for more information.

  For the VMWare driver, only the VNC option applies. However, this option is
  deprecated and will not affect any other driver in the future. A new option
  has been added to the ``[vmware]`` group to replace this:

  - ``[vmware] vnc_keymap``

  The ``[vnc] keymap`` and ``[spice] keymap`` options will be removed in a
  future release.

  __ https://bugs.launchpad.net/nova/+bug/1682020
  __ https://github.com/novnc/noVNC/pull/596

.. releasenotes/notes/deprecate-more-nova-network-opts-38a69fb87f10bb9c.yaml @ b'44181a5a20abd984e9aad976dad533e03f44cb10'

- The following options, found in ``DEFAULT``, were only used for configuring
  nova-network and are, like nova-network itself, now deprecated.

  - ``network_manager``

.. releasenotes/notes/deprecate-nova-consoleauth-ed6ccbc324a0fb10.yaml @ b'212a2c5fee389b413b69050d93a06831326b9192'

- The ``nova-consoleauth`` service has been deprecated. Console token
  authorization storage is moving from the ``nova-consoleauth`` service
  backend to the database backend, with storage happening in both, in Rocky.
  In Stein, only the database backend will be used for console token
  authorization storage.

  .. note:: Cells v1 was not converted to use the database backend for
    console token authorizations. Cells v1 console token authorizations will
    continue to be supported by the ``nova-consoleauth`` service.

.. releasenotes/notes/deprecate_fping_path-87d192cf0e6a5930.yaml @ b'497e0321f1ab4412a1940e2d885768fec5c23b46'

- The ``fping_path`` configuration option has been deprecated.
  /os-fping is used by nova-network and nova-network itself is
  deprecated and will be removed in the future.

.. releasenotes/notes/deprecate_sparse_lvs-99f30d70a68a028d.yaml @ b'0b11a09327b0890051627f307fba1c5667c1dcbc'

- The ``[libvirt]/sparse_logical_volumes`` configuration option is now
  deprecated. Sparse logical volumes were never verified by tests in Nova
  and some bugs were found without having fixes so we prefer to deprecate
  that feature.
  By default, the LVM image backend allocates all the disk size to a logical
  volume. If you want to have the volume group having thin-provisioned
  logical volumes, use Cinder with volume-backed instances.

.. releasenotes/notes/rocky-deprecate-some-upgrade-levels-options-bbe19bb2256e25ad.yaml @ b'f0d2925bc71d0649f75fd3d281742f2e56e7e3b6'

- The following configuration options in the ``[upgrade_levels]`` group
  have been deprecated:

  * ``network`` - The ``nova-network`` service was deprecated in the 14.0.0
    Newton release and will be removed in an upcoming release.
  * ``cert`` - The ``nova-cert`` service was removed in the 16.0.0 Pike
    release so this option is no longer used.
  * ``consoleauth`` - The ``nova-consoleauth`` service was deprecated in the
    18.0.0 Rocky release and will be removed in an upcoming release.

.. releasenotes/notes/xenapi-image-handler-7628a7221b7323e2.yaml @ b'f7593ded8f2e5b768b868914d211163c8b9508ea'

- The ``image_upload_handler`` option in the ``xenserver`` conf section
  has been deprecated. Please use the new option of ``image_handler`` to
  configure the image handler which is used to download or upload images.


.. _Release Notes_18.0.0_rocky-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739646-enforce_volume_backed_for_zero_disk_flavor-b36a6eb4fa8b2964.yaml @ b'763fd62464e9a0753e061171cc1fd826055bbc01'

- A new policy rule, ``os_compute_api:servers:create:zero_disk_flavor``, has
  been introduced which defaults to ``rule:admin_or_owner`` for backward
  compatibility, but can be configured to make the compute
  API enforce that server create requests using a flavor with zero root disk
  must be volume-backed or fail with a ``403 HTTPForbidden`` error.

  Allowing image-backed servers with a zero root disk flavor can be
  potentially hazardous if users are allowed to upload their own images,
  since an instance created with a zero root disk flavor gets its size
  from the image, which can be unexpectedly large and exhaust local disk
  on the compute host. See https://bugs.launchpad.net/nova/+bug/1739646 for
  more details.

  While this is introduced in a backward-compatible way, the default will
  be changed to ``rule:admin_api`` in a subsequent release. It is advised
  that you communicate this change to your users before turning on
  enforcement since it will result in a compute API behavior change.

.. releasenotes/notes/change-consecutive-boot-failure-counter-to-weigher-428de7da0ed2033a.yaml @ b'91e29079a0eac825c5f4fe793cf607cb1771467d'

- To mitigate potential issues with compute nodes disabling
  themselves in response to failures that were either non-fatal or
  user-generated, the consecutive build failure counter
  functionality in the compute service has been changed to advise
  the scheduler of the count instead of self-disabling the service
  upon exceeding the threshold. The
  ``[compute]/consecutive_build_service_disable_threshold``
  configuration option still controls whether the count is tracked,
  but the action taken on this value has been changed to a scheduler
  weigher. This allows the scheduler to be configured to weigh hosts
  with consecutive failures lower than other hosts, configured by the
  ``[filter_scheduler]/build_failure_weight_multiplier`` option. If
  the compute threshold option is nonzero, computes will report their
  failure count for the scheduler to consider. If the threshold
  value is zero, then computes will not report this value
  and the scheduler will assume the number of failures for
  non-reporting compute nodes to be zero. By default, the scheduler
  weigher is enabled and configured with a very large multiplier to
  ensure that hosts with consecutive failures are scored low by
  default.


.. _Release Notes_18.0.0_rocky-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/add-association-refresh-config-opt-d1ca1af238d10c9a.yaml @ b'41d6b479fe8baf66578044b8773c3b892d64a2c4'

- The nova-compute service now allows specifying the interval for updating
  nova-compute-side cache of the compute node resource provider's aggregates
  and traits info via a new config option called
  ``[compute]/resource_provider_association_refresh`` which defaults to 300.
  This was previously hard-coded to run every 300 seconds which may be too
  often in a large deployment.

.. releasenotes/notes/bfv-instances-no-longer-allocate-from-compute-95d048fbe9867c34.yaml @ b'03c596a9f4324e572bc04d4bbad09a6d3d47366c'

- Booting volume-backed instances no longer includes an incorrect allocation
  against the compute node for the root disk. Historically, this has been
  quite broken behavior in Nova, where volume-backed instances would count
  against available space on the compute node, even though their storage
  was provided by the volume service. Now, newly-booted volume-backed
  instances will not create allocations of ``DISK_GB`` against the compute
  node for the ``root_gb`` quantity in the flavor. Note that if you are
  still using a scheduler configured with the (now deprecated)
  DiskFilter (including deployments using CachingScheduler), the
  above change will not apply to you.

.. releasenotes/notes/bug-1726301-list-across-down-cells-82726cac592e9728.yaml @ b'ee461b5bf6c4aa1b66be458776f478f718ef809b'

- Listing server and migration records used to give a 500 to users
  when a cell database was unreachable. Now only records from available
  cells are included to avoid the 500 error. The down cells are basically
  skipped when forming the results and this solution is planned to be
  further enhanced through the `blueprint handling-down-cell`_.

  .. _blueprint handling-down-cell: https://blueprints.launchpad.net/nova/+spec/handling-down-cell

.. releasenotes/notes/bug-1734625-419fd0e21bd332f6.yaml @ b'ab4efbba61fb0dd0266e42e48555f80ddde72efd'

- The SchedulerReportClient
  (``nova.scheduler.client.report.SchedulerReportClient``) sends requests
  with the global request ID in the ``X-Openstack-Request-Id`` header
  to the placement service. `Bug 1734625`_

  .. _Bug 1734625: https://bugs.launchpad.net/nova/+bug/1734625

.. releasenotes/notes/bug-1763183-service-delete-with-instances-d7c5c47e4ce31239.yaml @ b'42f62f1ed2ad76829eb9d40a8b9646a523f6381f'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is still hosting instances. This is because doing so would
  orphan the compute node resource provider in the placement service on
  which those instances have resource allocations, which affects scheduling.
  See https://bugs.launchpad.net/nova/+bug/1763183 for more details.

.. releasenotes/notes/fix-multiarch-image-props-filter-f2e885aa53d585ea.yaml @ b'aa5b1326c86c408ce9cc4546e1c7a310fbce3136'

- The behaviour of ImagePropertiesFilter when using multiple architectures in a cloud can be unpredictable for a user if they forget to set the architecture property in their image.  Nova now allows the deployer to specify a fallback in ``[filter_scheduler]image_properties_default_architecture`` to use a default architecture if none is specified.  Without this, it is possible that a VM would get scheduled on a compute node that does not support the image.

.. releasenotes/notes/libvirt-live-migration-speed-limit-revert-81a9d29d60b0df4b.yaml @ b'afd1c1e6e152b6337d6e71af1c908c73c847b6f3'

- Note that the original fix for `bug 1414559`_ committed early in rocky was automatic and always
  enabled. Because of `bug 1786346`_ that fix has since been reverted and superseded by an opt-in
  mechanism which must be enabled. Setting ``[compute]/live_migration_wait_for_vif_plug=True``
  will restore the behavior of `waiting for neutron events`_ during the live migration process.

  .. _bug 1414559: https://bugs.launchpad.net/neutron/+bug/1414559
  .. _bug 1786346: https://bugs.launchpad.net/nova/+bug/1786346
  .. _waiting for neutron events: https://docs.openstack.org/nova/latest/configuration/config.html#compute.live_migration_wait_for_vif_plug


.. _Release Notes_18.0.0_rocky-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/instance-list-limit-to-cells-config-f72701ac68444e95.yaml @ b'eb3da9f5a1c212ed36c0594c91f24f3a18cec8f0'

- The ``[api]/instance_list_per_project_cells`` configuration option
  was added, which controls whether or not an instance list for
  non-admin users checks all cell databases for results.  If
  disabled (the default), then a list will always contact each cell
  database looking for instances. This is appropriate if you have a
  small number of cells, and/or if you spread instances from tenants
  evenly across cells. If you confine tenants to a subset of cells,
  then enabling this will result in fewer cell database calls, as
  nova will only query the cells for which the tenant has instances
  mapped. Doing this requires one more (fast) call to the API
  database to get the relevant subset of cells, so if that is likely
  to always be the same, disabling this feature will provide better
  performance.

.. releasenotes/notes/live_migration_wait_for_vif_plug-c9dcb034067890d8.yaml @ b'5aadff75c3ac4f2019838600df6580481a96db0f'

- A new configuration option, ``[compute]/live_migration_wait_for_vif_plug``,
  has been added which can be used to configure compute services to wait
  for network interface plugging to complete on the destination host before
  starting the guest transfer on the source host during live migration.

  Note that this option is read on the destination host of a live migration.
  If you set this option the same on all of your compute hosts, which you
  should do if you use the same networking backend universally, you do not
  have to worry about this.

  This is disabled by default for backward compatibility and because the
  compute service cannot reliably determine which types of virtual
  interfaces (``port.binding:vif_type``) will send ``network-vif-plugged``
  events without an accompanying port ``binding:host_id`` change.
  Open vSwitch and linuxbridge should be OK, but OpenDaylight is at least
  one known backend that will not currently work in this case, see bug
  https://launchpad.net/bugs/1755890 for more details.

.. releasenotes/notes/nova-manage-placement-heal-allocations-13a9a0a3df910e0b.yaml @ b'95106d2fa1ab86607231c338fa0abc0c3488f0f8'

- A new ``nova-manage placement heal_allocations`` CLI has been added to
  help migrate users from the deprecated CachingScheduler. Starting in
  16.0.0 (Pike), the nova-compute service no longer reports instance
  allocations to the Placement service because the FilterScheduler does
  that as part of scheduling. However, the CachingScheduler does not create
  the allocations in the Placement service, so any instances created using
  the CachingScheduler after Ocata will not have allocations in Placement.
  The new CLI allows operators using the CachingScheduler to find all
  instances in all cells which do not have allocations in Placement and
  create those allocations. The CLI will skip any instances that are
  undergoing a task state transition, so ideally this would be run when
  the API is down but it can be run, if necessary, while the API is up.
  For more details on CLI usage, see the man page entry:

  https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement


