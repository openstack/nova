===================================
 Pike Series Release Notes
===================================

.. _Release Notes_16.1.8-57_pike-eol:

16.1.8-57
=========

.. _Release Notes_16.1.8-57_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'6da28b0aa9b6a0ba67460f88dd2c397605b0679b'

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


.. _Release Notes_16.1.8-57_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1811726-multi-node-delete-2ba17f02c6171fbb.yaml @ b'bd2e0972993ffd732cde0a3a6154424e74d44f0a'

- `Bug 1811726`_ is fixed by deleting the resource provider (in placement)
  associated with each compute node record managed by a ``nova-compute``
  service when that service is deleted via the
  ``DELETE /os-services/{service_id}`` API. This is particularly important
  for compute services managing ironic baremetal nodes.

  .. _Bug 1811726: https://bugs.launchpad.net/nova/+bug/1811726

.. releasenotes/notes/fix-simple-tenant-usage-pagination-393ed6e7d0e31594.yaml @ b'f8a721ae85cab44754b8e64434e90f4c2afa89aa'

- The ``os-simple-tenant-usage`` pagination has been fixed. In some cases,
  nova usage-list would have returned incorrect results because of this.
  See bug https://launchpad.net/bugs/1796689 for details.


.. _Release Notes_16.1.8_pike-eol:

16.1.8
======

.. _Release Notes_16.1.8_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/config-cinder-admin-creds-b86038a3e87a1021.yaml @ b'4d7148709c5de098141fbee12ad2e78c61e3b174'

- It is now possible to configure the ``[cinder]`` section of nova.conf to
  allow setting admin-role credentials for scenarios where a user token is
  not available to perform actions on a volume. For example, when
  ``reclaim_instance_interval`` is a positive integer, instances are
  soft deleted until the nova-compute service periodic task removes them.
  If a soft deleted instance has volumes attached, the compute service needs
  to be able to detach and possibly delete the associated volumes, otherwise
  they will be orphaned in the block storage service. Similarly, if
  ``running_deleted_instance_poll_interval`` is set and
  ``running_deleted_instance_action = reap``, then the compute service will
  need to be able to detach and possibly delete volumes attached to
  instances that are reaped. See `bug 1733736`_ and `bug 1734025`_ for more
  details.

  .. _bug 1733736: https://bugs.launchpad.net/nova/+bug/1733736
  .. _bug 1734025: https://bugs.launchpad.net/nova/+bug/1734025

.. releasenotes/notes/fix-resize-instance-call-e987193c574c6486.yaml @ b'76f937b50a50dd43b97d62ebab8459bc98cfe554'

- Fixes an issue with cold migrating (resizing) an instance from
  ocata to pike compute by correcting parameters order in
  resize_instance rpcapi call to destination compute.


.. _Release Notes_16.1.7_pike-eol:

16.1.7
======

.. _Release Notes_16.1.7_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1801702-c8203d3d55007deb.yaml @ b'ba844f2a7c1d4602017bb0fc600a30b150c28dbc'

- When testing whether direct IO is possible on the backing storage
  for an instance, Nova now uses a block size of 4096 bytes instead
  of 512 bytes, avoiding issues when the underlying block device has
  sectors larger than 512 bytes. See bug
  https://launchpad.net/bugs/1801702 for details.


.. _Release Notes_16.1.5_pike-eol:

16.1.5
======

.. _Release Notes_16.1.5_pike-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1679750-local-delete-allocations-cb7bfbcb6c36b6a2.yaml @ b'cd50dcaf3e51722c9510d417c1724d8cdafe450b'

- The ``nova-api`` service now requires the ``[placement]`` section to be
  configured in nova.conf if you are using a separate config file just for
  that service. This is because the ``nova-api`` service now needs to talk
  to the placement service in order to delete resource provider allocations
  when deleting an instance and the ``nova-compute`` service on which that
  instance is running is down. This change is idempotent if
  ``[placement]`` is not configured in ``nova-api`` but it will result in
  new warnings in the logs until configured. See bug
  https://bugs.launchpad.net/nova/+bug/1679750 for more details.

.. releasenotes/notes/default-non-inheritable-image-properties-dfd13ba3b09278dd.yaml @ b'f8498c41cdfec2acde62a1da1abce917ac882c7d'

- The default list of non-inherited image properties to pop when creating a
  snapshot has been extended to include image signature properties. The
  properties ``img_signature_hash_method``, ``img_signature``,
  ``img_signature_key_type`` and ``img_signature_certificate_uuid`` are no
  longer inherited by the snapshot image as they would otherwise result in
  a Glance attempting to verify the snapshot image with the signature of the
  original.

.. releasenotes/notes/migration-tool-to-populate-inst.avz-29fed2fe57a9764d.yaml @ b'487c6dd778312780740d8cb9a0b51f3fa177c1c4'

- A new online data migration has been added to populate missing
  instance.availability_zone values for instances older than Pike whose
  availability_zone was not specified during boot time. This can be run
  during the normal ``nova-manage db online_data_migrations`` routine.
  This fixes `Bug 1768876`_

  .. _Bug 1768876: https://bugs.launchpad.net/nova/+bug/1768876


.. _Release Notes_16.1.5_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739646-enforce_volume_backed_for_zero_disk_flavor-b36a6eb4fa8b2964.yaml @ b'0bf75621bbd25d4ce8a3588f112cf714891556eb'

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

.. releasenotes/notes/libvirt-cpu-model-extra-flags-ssbd-fdbda6e4da495915.yaml @ b'27bacacdd8a3741cfbd7e14a4ea50713c5e1d9e5'

- The 'SSBD' and 'VIRT-SSBD' cpu flags have been added to the list
  of available choices for the ``[libvirt]/cpu_model_extra_flags``
  config option. These are important for proper mitigation of the
  Spectre 3a and 4 CVEs. Note that the use of either of these flags
  require updated packages below nova, including libvirt, qemu
  (specifically >=2.9.0 for virt-ssbd), linux, and system
  firmware. For more information see
  https://www.us-cert.gov/ncas/alerts/TA18-141A


.. _Release Notes_16.1.5_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1763183-service-delete-with-instances-d7c5c47e4ce31239.yaml @ b'8cd1204873287d9f0196cbc48d8c408448c67c43'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is still hosting instances. This is because doing so would
  orphan the compute node resource provider in the placement service on
  which those instances have resource allocations, which affects scheduling.
  See https://bugs.launchpad.net/nova/+bug/1763183 for more details.


.. _Release Notes_16.1.2_pike-eol:

16.1.2
======

.. _Release Notes_16.1.2_pike-eol_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1739593-cve-2017-18191-25fe48d336d8cf13.yaml @ b'5b64a1936122eeb35f37a09f9d38159e1a224c58'

This release includes fixes for security vulnerabilities.


.. _Release Notes_16.1.2_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739593-cve-2017-18191-25fe48d336d8cf13.yaml @ b'5b64a1936122eeb35f37a09f9d38159e1a224c58'

- [CVE-2017-18191] Swapping encrypted volumes can lead to data loss and a
  possible compute host DOS attack.

  * `Bug 1739593 <https://bugs.launchpad.net/nova/+bug/1739593>`_


.. _Release Notes_16.1.2_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/libvirt-cpu-model-extra-flags-a23085f58bd22d27.yaml @ b'56350b977e412d59da96a79290d80c6422fa44b1'

- The libvirt driver now allows specifying individual CPU feature
  flags for guests, via a new configuration attribute
  ``[libvirt]/cpu_model_extra_flags`` -- only with ``custom`` as the
  ``[libvirt]/cpu_model``.  Refer to its documentation in
  ``nova.conf`` for usage details.

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


.. _Release Notes_16.1.1_pike-eol:

16.1.1
======

.. _Release Notes_16.1.1_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/discover-hosts-by-service-06ee20365b895127.yaml @ b'76b9cbd12b1fcc3d92fd4b284a90c4238df5c485'

- The nova-manage discover_hosts command now has a ``--by-service`` option which
  allows discovering hosts in a cell purely by the presence of a nova-compute
  binary. At this point, there is no need to use this unless you're using ironic,
  as it is less efficient. However, if you are using ironic, this allows discovery
  and mapping of hosts even when no ironic nodes are present.

.. releasenotes/notes/update-swap-decorator-7622a265df55feaa.yaml @ b'7a51ffc551482ac28eaa493c408084d699a6dc8c'

- prevent swap_volume action if the instance is in state SUSPENDED, STOPPED or SOFT_DELETED. A conflict (409) will be raised now as previously it used to fail silently.


.. _Release Notes_16.1.0_pike-eol:

16.1.0
======

.. _Release Notes_16.1.0_pike-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/aarch64-set-proper-cpu-mode-8455bad7d69dc6fd.yaml @ b'50d8a07b3fa2fd8ee605691ee4f6148dd3a18a5f'

- On AArch64 architecture ``cpu_mode`` for libvirt is set to ``host-passthrough``
  by default.

  AArch64 currently lacks ``host-model`` support because neither libvirt nor
  QEMU are able to tell what the host CPU model exactly is and there is no
  CPU description code for ARM(64) at this point.

  .. warning:: ``host-passthrough`` mode will completely break live
     migration, *unless* all the Compute nodes (running libvirtd) have
     *identical* CPUs.

.. releasenotes/notes/agg-resource-filters-6e24c92a69afa85f.yaml @ b'cbd1402fb4fe0f7935e873e948e205aa752a8456'

- Starting in Ocata, there is a behavior change where aggregate-based
  overcommit ratios will no longer be honored during scheduling for the
  FilterScheduler. Instead, overcommit values must be set on a
  per-compute-node basis in the Nova configuration files.

  If you have been relying on per-aggregate overcommit, during your upgrade,
  you must change to using per-compute-node overcommit ratios in order for
  your scheduling behavior to stay consistent. Otherwise, you may notice
  increased NoValidHost scheduling failures as the aggregate-based overcommit
  is no longer being considered.

  You can safely remove the AggregateCoreFilter, AggregateRamFilter, and
  AggregateDiskFilter from your ``[filter_scheduler]enabled_filters`` and you
  do not need to replace them with any other core/ram/disk filters. The
  placement query in the FilterScheduler takes care of the core/ram/disk
  filtering, so CoreFilter, RamFilter, and DiskFilter are redundant.

  Please see the mailing list thread for more information:
  http://lists.openstack.org/pipermail/openstack-operators/2018-January/014748.html

.. releasenotes/notes/bug-1738094-request_specs.spec-migration-22d3421ea1536a37.yaml @ b'9adf97c0132c3e0d34bbb2e33b59c6e5b00bec57'

- This release contains a schema migration for the ``nova_api`` database
  in order to address bug 1738094:

  https://bugs.launchpad.net/nova/+bug/1738094

  The migration is optional and can be postponed if you have not been
  affected by the bug. The bug manifests itself through "Data too long for
  column 'spec'" database errors.


.. _Release Notes_16.1.0_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1721179-87bc7b64215944c0.yaml @ b'868ef987625d6867dc0e315af6245776fa2da18a'

- The ``delete_host`` command has been added in ``nova-manage cell_v2``
  to delete a host from a cell (host mappings).
  The ``force`` option has been added in ``nova-manage cell_v2 delete_cell``.
  If the ``force`` option is specified, a cell can be deleted
  even if the cell has hosts.

.. releasenotes/notes/bug-1744325-rebuild-error-status-9e2da03f3f81fd6e.yaml @ b'22a39b8f9b76d5f330a3f185e7d40f208a6a47f3'

- If scheduling fails during rebuild the server instance will go to ERROR
  state and a fault will be recorded. `Bug 1744325`_

  .. _Bug 1744325: https://bugs.launchpad.net/nova/+bug/1744325


.. _Release Notes_16.0.4_pike-eol:

16.0.4
======

.. _Release Notes_16.0.4_pike-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/over-quota-api-behavior-change-fc2cbbf7c79b5ae3.yaml @ b'43dbbf8d877124145b277129cbb8a12a7a0e7a0d'

- In 16.0.0 Pike release, quota limits are checked in a new fashion after change 5c90b25e49d47deb7dc6695333d9d5e46efe8665 and a new config option ``[quota]/recheck_quota`` has been added in change eab1d4b5cc6dd424c5c7dfd9989383a8e716cae5 to recheck quota after resource creation to prevent allowing quota to be exceeded as a result of racing requests. These changes could lead to requests blocked by over quota resulting in instances in the ``ERROR`` state, rather than no instance records as before. Refer to https://bugs.launchpad.net/nova/+bug/1716706 for detailed bug report.


.. _Release Notes_16.0.4_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1732976-doubled-allocations-rebuild-23e4d3b06eb4f43f.yaml @ b'fed660c1189fdf4159d97badfdc8c5b35ad14f23'

- `OSSA-2017-006`_: Nova FilterScheduler doubles resource allocations during
  rebuild with new image (CVE-2017-17051)

  By repeatedly rebuilding an instance with new images, an authenticated user
  may consume untracked resources on a hypervisor host leading to a denial of
  service. This regression was introduced with the fix for `OSSA-2017-005`_
  (CVE-2017-16239), however, only Nova stable/pike or later deployments with
  that fix applied and relying on the default FilterScheduler are affected.

  The fix is in the ``nova-api`` and ``nova-scheduler`` services.

  .. note:: The fix for errata in `OSSA-2017-005`_ (CVE-2017-16239) will
            need to be applied in addition to this fix.

  .. _OSSA-2017-006: https://security.openstack.org/ossa/OSSA-2017-006.html


.. _Release Notes_16.0.4_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1664931-refine-validate-image-rebuild-6d730042438eec10.yaml @ b'b29a461a8bc05c9b171c0574abb2e7e5b62a2ed7'

- The fix for `OSSA-2017-005`_ (CVE-2017-16239) was too far-reaching in that
  rebuilds can now fail based on scheduling filters that should not apply
  to rebuild. For example, a rebuild of an instance on a disabled compute
  host could fail whereas it would not before the fix for CVE-2017-16239.
  Similarly, rebuilding an instance on a host that is at capacity for vcpu,
  memory or disk could fail since the scheduler filters would treat it as a
  new build request even though the rebuild is not claiming *new* resources.

  Therefore this release contains a fix for those regressions in scheduling
  behavior on rebuild while maintaining the original fix for CVE-2017-16239.

  .. note:: The fix relies on a ``RUN_ON_REBUILD`` variable which is checked
            for all scheduler filters during a rebuild. The reasoning behind
            the value for that variable depends on each filter. If you have
            out-of-tree scheduler filters, you will likely need to assess
            whether or not they need to override the default value (False)
            for the new variable.

.. releasenotes/notes/bug-1733886-os-quota-sets-force-2.36-5866924621ecc857.yaml @ b'6f5b3123cc3e35af7d9054c299f4c2232c8c2a3f'

- This release includes a fix for `bug 1733886`_ which was a regression
  introduced in the 2.36 API microversion where the ``force`` parameter was
  missing from the ``PUT /os-quota-sets/{tenant_id}`` API request schema so
  users could not force quota updates with microversion 2.36 or later. The
  bug is now fixed so that the ``force`` parameter can once again be
  specified during quota updates. There is no new microversion for this
  change since it is an admin-only API.

  .. _bug 1733886: https://bugs.launchpad.net/nova/+bug/1733886


.. _Release Notes_16.0.3_pike-eol:

16.0.3
======

.. _Release Notes_16.0.3_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1664931-validate-image-rebuild-9c5b05a001c94a4d.yaml @ b'3f63d057a64b688b66ff1903c1afc4d97ba6df6d'

- `OSSA-2017-005`_: Nova Filter Scheduler bypass through rebuild action

  By rebuilding an instance, an authenticated user may be able to circumvent
  the FilterScheduler bypassing imposed filters (for example, the
  ImagePropertiesFilter or the IsolatedHostsFilter). All setups using the
  FilterScheduler (or CachingScheduler) are affected.

  The fix is in the ``nova-api`` and ``nova-conductor`` services.

  .. _OSSA-2017-005: https://security.openstack.org/ossa/OSSA-2017-005.html


.. _Release Notes_16.0.3_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1695861-ebc8a0aa7a87f7e0.yaml @ b'a33634e5558b20e4bd496fe476f6ceb1a2ba79f6'

- Fixes `bug 1695861`_ in which the aggregate API accepted requests that
  have availability zone names including ':'. With this fix, a creation
  of an availability zone whose name includes ':' results in a
  ``400 BadRequest`` error response.

  .. _bug 1695861: https://bugs.launchpad.net/nova/+bug/1695861

.. releasenotes/notes/ironic-empty-vcpus-66b4e1500ef8a34e.yaml @ b'd25feca90ec4bad6ec9ececedced63b9f00b4c87'

- Fixes a bug preventing ironic nodes without VCPUs, memory or disk in their
  properties from being picked by nova.


.. _Release Notes_16.0.2_pike-eol:

16.0.2
======

.. _Release Notes_16.0.2_pike-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add_keystone_option-138dff5efb9a53aa.yaml @ b'c0ff5b33ca42a417a5fa08e5133a27397af08c3d'

- A new ``keystone`` config section is added so that you can
  set session link attributes for communicating with keystone. This
  allows the use of custom certificates to secure the link between
  Nova and Keystone.


.. _Release Notes_16.0.2_pike-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/ironic_offline_flavor_migration-4845307799f0e24e.yaml @ b'f0c71321828bddb32ef05258f8aa2a6318f4f317'

- The ironic driver will automatically migrate instance flavors for resource classes
  at runtime. If you are not able to run the compute and ironic services at pike because
  you are automating an upgrade past this release, you can use the
  ``nova-manage db ironic_flavor_migration`` to push the migration manually. This is only
  for advanced users taking on the risk of automating the process of upgrading through
  pike and is not recommended for normal users.


.. _Release Notes_16.0.1_pike-eol:

16.0.1
======

.. _Release Notes_16.0.1_pike-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1712008-4ab2538211b8c3d9.yaml @ b'7d220b3dd7f9a52773604eab8160503b05f586b3'

- The ``nova-conductor`` service now needs access to the Placement service
  in the case of forcing a destination host during a live migration. Ensure
  the ``[placement]`` section of nova.conf for the ``nova-conductor`` service
  is filled in.


.. _Release Notes_16.0.1_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1712008-4ab2538211b8c3d9.yaml @ b'7d220b3dd7f9a52773604eab8160503b05f586b3'

- When forcing a specified destination host during live migration, the
  scheduler is bypassed but resource allocations will still be made in the
  Placement service against the forced destination host. If the resource
  allocation against the destination host fails, the live migration operation
  will fail, regardless of the ``force`` flag being specified in the API.
  The guest will be unchanged on the source host. For more details, see
  `bug 1712008`_.

  .. _bug 1712008: https://bugs.launchpad.net/nova/+bug/1712008

.. releasenotes/notes/bug-1713786-0ee9e543683dafa4.yaml @ b'21150948246d52060a38e93f98982c2e5c9b347d'

- When forcing a specified destination host during evacuate, the
  scheduler is bypassed but resource allocations will still be made in the
  Placement service against the forced destination host. If the resource
  allocation against the destination host fails, the evacuate operation
  will fail, regardless of the ``force`` flag being specified in the API.
  The guest will be unchanged on the source host. For more details, see
  `bug 1713786`_.

  .. _bug 1713786: https://bugs.launchpad.net/nova/+bug/1713786

.. releasenotes/notes/unsettable-keymap-settings-fa831c02e4158507.yaml @ b'ccfb46420d6ee186d6ec777ce6167bd138f2a285'

- It is now possible to unset the ``[vnc]keymap`` and ``[spice]keymap``
  configuration options. These were known to cause issues for some users
  with non-US keyboards and may be deprecated in the future.


.. _Release Notes_16.0.0_pike-eol:

16.0.0
======

.. _Release Notes_16.0.0_pike-eol_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'3f985f1eda6f29180878a3d21c20c5057179486a'

This release includes fixes for security vulnerabilities.


.. releasenotes/notes/pike_prelude-fedf9f27775d135f.yaml @ b'ebf4ad222587932baf95a62fd58a11284637a7dc'

The 16.0.0 release includes many new features and bug fixes. It is
difficult to cover all the changes that have been introduced. Please at
least read the upgrade section which describes the required actions to
upgrade your cloud from 15.0.0 (Ocata) to 16.0.0 (Pike).

That said, a few major changes are worth mentioning. This is not an
exhaustive list:

- The latest Compute API microversion supported for Pike is v2.53. Details
  on REST API microversions added since the 15.0.0 Ocata release can be
  found in the `REST API Version History`_ page.
- The FilterScheduler driver now provides allocations to the Placement API,
  which helps concurrent schedulers to verify resource consumptions
  directly without waiting for compute services to ask for a reschedule in
  case of a race condition. That is an important performance improvement
  that includes allowing one to use more than one scheduler worker if
  there are capacity concerns. For more details, see the
  `Pike Upgrade Notes for Placement`_.
- Nova now supports a Cells v2 multi-cell deployment. The default
  deployment is a single cell. There are known `limitations with
  multiple cells`_. Refer to the `Cells v2 Layout`_ page for more
  information about deploying multiple cells.
- Cells v1 is now deprecated in favor of Cells v2.
- The quota system has been reworked to `count resources`_ at the point of
  creation rather than using a reserve/commit/rollback approach. No
  operator impacts are expected.
- Compute-specific documentation is being migrated from
  http://docs.openstack.org to https://docs.openstack.org/nova/ and the
  layout for the Nova developer documentation is being re-organized. If you
  think anything is missing or you now have broken bookmarks, please
  `report a bug`_.

.. _Pike Upgrade Notes for Placement: https://docs.openstack.org/nova/latest/user/placement.html#pike-16-0-0

.. _limitations with multiple cells: https://docs.openstack.org/nova/latest/user/cellsv2_layout.html#caveats-of-a-multi-cell-deployment

.. _Cells v2 Layout: https://docs.openstack.org/nova/latest/user/cellsv2_layout.html

.. _count resources: https://specs.openstack.org/openstack/nova-specs/specs/pike/approved/cells-count-resources-to-check-quota-in-api.html

.. _report a bug: https://bugs.launchpad.net/nova/


.. _Release Notes_16.0.0_pike-eol_New Features:

New Features
------------

.. releasenotes/notes/Make-versioned-notifications-topics-configurable-a4baad995a74a076.yaml @ b'5bc5e8440e7354b78caea37e077509695067bff5'

- The versioned_notifications_topic configuration option; This enables one to configure the topics used for versioned notifications.

.. releasenotes/notes/add-interface-attach-detach-support-in-ironic-cb2bf11f3875350a.yaml @ b'66f962d9b90d081fb029b455e12c625a9738ff92'

- Adds interface attach/detach support to baremetal nodes using ironic virt
  driver. Note that the instance info cache update relies on getting a
  ``network-changed`` event from neutron, or on the periodic task healing
  the instance info cache, both of which are asynchronous. This means that
  nova's cached network information (which is what is sent e.g. in the
  ``GET /servers`` responses) may not be up to date immediately after the
  attachment or detachment.

.. releasenotes/notes/add-lan9118-vif-property-qemu-fcc19774945d41f3.yaml @ b'af8d93fa9da749033575fe8c3ac58cfac134c355'

- Add support for LAN9118 as a valid nic for hw_vif_model property in qemu.

.. releasenotes/notes/add-new-fields-to-InstancePaylod-bc5ef2ecfed880a2.yaml @ b'bcdcc416a3a640c4f1a767421ed131002bf1a6f2'

- The fields ``locked`` and ``display_description`` have been added to
  InstancePayload. Versioned notifications for instance actions
  will include these fields.

  A few examples of versioned notifications that use InstancePayload:

  * ``instance.create``
  * ``instance.delete``
  * ``instance.resize``
  * ``instance.pause``

.. releasenotes/notes/add-pci-weigher-4a7e0a7b8e908975.yaml @ b'ec74cc688e1bbfc2f16cfe9473551fd261c6e78e'

- Add ``PCIWeigher`` weigher. This can be used to ensure non-PCI instances
  don't occupy resources on hosts with PCI devices. This can be configured
  using the ``[filter_scheduler] pci_weight_multiplier`` configuration
  option.

.. releasenotes/notes/added-network-metadata-7784295884f65c09.yaml @ b'ccebded0cbb654be18db5b4e0e7f8b8a3a7cacdb'

- The network.json metadata format has been amended for IPv6 networks
  under Neutron control. The type that is shown has been changed
  from being always set to ``ipv6_dhcp`` to correctly reflecting the
  ``ipv6_address_mode`` option in Neutron, so the type now will be
  ``ipv6_slaac``, ``ipv6_dhcpv6-stateless`` or ``ipv6_dhcpv6-stateful``.

.. releasenotes/notes/bp-ironic-boot-from-volume-cfb98c733cf09a92.yaml @ b'3e1a3c9f82089b6b37605fcf88bb685625f8632f'

- Enables to launch an instance from an iscsi volume with ironic virt
  driver. This feature requires an ironic service supporting API
  version 1.32 or later, which is present in ironic releases > 8.0.
  It also requires python-ironicclient >= 1.14.0.

.. releasenotes/notes/bp-opencontrail-nova-vif-plugin-b132102ad79ebf90.yaml @ b'1ba834c0e48c85bf84ff3ec62fce0d5cb5c39c6d'

- The model name vhostuser_vrouter_plug is set by the neutron contrail
  plugin during a VM (network port) creation.
  The libvirt compute driver now supports plugging virtual interfaces
  of type "contrail_vrouter" which are provided by
  the contrail-nova-vif-driver plugin [1].
  [1] https://github.com/Juniper/contrail-nova-vif-driver

.. releasenotes/notes/bp-restore-vm-diagnostics-544b56bbb0167071.yaml @ b'41d6d77897e2815a7a48220633ae8f5881f4b67a'

- Added microversion v2.48 which standardize VM diagnostics response. It has a set of fields which each hypervisor will try to fill. If a hypervisor driver is unable to provide a specific field then this field will be reported as 'None'.

.. releasenotes/notes/bp-service-hyper-uuid-in-api-cc7b9f21cc458e1b.yaml @ b'622bfb2e951c09845994b306e396c921801a0317'

- Microversion 2.53 changes service and hypervisor IDs to UUIDs to ensure
  uniqueness across cells. Prior to this, ID collisions were possible in
  multi-cell deployments. See the `REST API Version History`_ and
  `Compute API reference`_ for details.

  .. _REST API Version History: https://docs.openstack.org/developer/nova/api_microversion_history.html
  .. _Compute API reference: https://developer.openstack.org/api-ref/compute/

.. releasenotes/notes/compute-node-auto-disable-303eb9b0fdb4f3f1.yaml @ b'f93f675a8563c7c37fdcb0c685a8b491a7311361'

- The ``nova-compute`` worker can automatically disable itself in the
  service database if consecutive build failures exceed a set threshold. The
  ``[compute]/consecutive_build_service_disable_threshold`` configuration option
  allows setting the threshold for this behavior, or disabling it entirely if
  desired.
  The intent is that an admin will examine the issue before manually
  re-enabling the service, which will avoid that compute node becoming a
  black hole build magnet.

.. releasenotes/notes/delete-inventories-placement-api-13582910371308c4.yaml @ b'f903a6c56bf473fdc87de05544a460681d025e4f'

- Supports a new method for deleting all inventory for a
  resource provider

  * DELETE /resource-providers/{uuid}/inventories

  Return codes

  * 204 NoContent on success
  * 404 NotFound for missing resource provider
  * 405 MethodNotAllowed if a microversion is specified that is before
        this change (1.5)
  * 409 Conflict if inventory in use or if some other request concurrently
        updates this resource provider

  Requires OpenStack-API-Version placement 1.5

.. releasenotes/notes/discover-hosts-periodic-is-more-efficient-6c55b606a7831750.yaml @ b'95c190c23dda3206499ca240b10e39af7c4624b3'

- The ``discover_hosts_in_cells_interval`` periodic task in the scheduler is now more efficient in that it can specifically query unmapped compute nodes from the cell databases instead of having to query them all and compare against existing host mappings.

.. releasenotes/notes/display-flavor-dict-in-server-details-589c1db487f226cb.yaml @ b'90636e0f33e50857b7d3e6be3ae855918e2c199a'

- A new 2.47 microversion was added to the Compute API.  Users specifying this microversion or later will see the "flavor" information displayed as a dict when displaying server details via the ``servers`` REST API endpoint. If the user is prevented by policy from indexing extra-specs, then the "extra_specs" field will not be included in the flavor information.

.. releasenotes/notes/drbd-libvirt-volume-driver-d27c79e62c0beb64.yaml @ b'562a04091f398a1e8e5729bd3e30a23bec3edf27'

- The libvirt compute driver now supports attaching volumes of type "drbd".
  See the `DRBD documentation`_ for more information.

  .. _DRBD documentation: http://docs.linbit.com/docs/users-guide-9.0/p-apps/#s-openstack-transport-protocol

.. releasenotes/notes/flavor-api-policy-granularity-f563d621c615fd64.yaml @ b'a8fd8731d2e5562c5631d6847d4d781ed0a2e772'

- Add granularity to the ``os_compute_api:os-flavor-manage`` policy
  with the addition of distinct actions for create and delete:

  - ``os_compute_api:os-flavor-manage:create``
  - ``os_compute_api:os-flavor-manage:delete``

  To address backwards compatibility, the new rules added to the
  flavor_manage.py policy file, default to the existing rule,
  ``os_compute_api:os-flavor-manage``, if it is set to a non-default
  value.

.. releasenotes/notes/hide_hypervisor_id-6f93e7552336930d.yaml @ b'c7c08e590eb0ea2452a1a1d925297ba43fa609b0'

- Some hypervisors add a signature to their guests, e.g. KVM is adding
  ``KVMKVMKVM\0\0\0``, Xen: ``XenVMMXenVMM``.
  The existence of a hypervisor signature enables some paravirtualization
  features on the guest as well as disallowing certain drivers which test
  for the hypervisor to load e.g. Nvidia driver [1]:
  "The latest Nvidia driver (337.88) specifically checks
  for KVM as the hypervisor and reports Code 43 for the
  driver in a Windows guest when found.  Removing or
  changing the KVM signature is sufficient for the driver
  to load and work."

  The new ``img_hide_hypervisor_id`` image metadata property hides the
  hypervisor signature for the guest.

  Currently only the libvirt compute driver can hide hypervisor signature
  for the guest host.

  To verify if hiding hypervisor id is working on Linux based system::

    $ cpuid | grep -i hypervisor_id

  The result should not be (for KVM hypervisor)::

    $ hypervisor_id = KVMKVMKVM\0\0\0

  You can enable this feature by setting the ``img_hide_hypervisor_id=true``
  property in a Glance image.

  [1]: http://git.qemu.org/?p=qemu.git;a=commitdiff;h=f522d2a

.. releasenotes/notes/idempotent-put-resource-class-dc7a267c823b7995.yaml @ b'697c2d89ee5a4c2fc45f34ad28165f397c602399'

- The 1.7 version of the placement API changes handling of
  ``PUT /resource_classes/{name}`` to be a create or verification of the
  resource class with ``{name}``. If the resource class is a custom resource
  class and does not already exist it will be created and a ``201`` response
  code returned. If the class already exists the response code will be
  ``204``. This makes it possible to check or create a resource class in one
  request.

.. releasenotes/notes/netronome-smartnic-enablement-d3897fb294429282.yaml @ b'2bd008ef5c56b85c85b09ec94d7ed079116c8e3c'

- This release adds support for Netronome's Agilio OVS VIF type. In order to use the accelerated plugging modes, external Neutron and OS-VIF plugins are required. Consult https://github.com/Netronome/agilio-ovs-openstack-plugin for installation and operation instructions. Consult the Agilio documentation available at https://support.netronome.com/ for more information about the plugin compatibility and support matrix.

.. releasenotes/notes/netronome-smartnic-enablement-d3897fb294429282.yaml @ b'2bd008ef5c56b85c85b09ec94d7ed079116c8e3c'

- The ``virtio-forwarder`` VNIC type has been added to the list of VNICs. This VNIC type is intended to request a low-latency virtio port inside the instance, likely backed by hardware acceleration. Currently the Agilio OVS external Neutron and OS-VIF plugins provide support for this VNIC mode.

.. releasenotes/notes/nova-support-attached-volume-extend-88ce16ce41aa6d41.yaml @ b'bbe0f313bdfd30cc1c740709543b679567b42f0f'

- It is now possible to signal and perform an online volume size change
  as of the 2.51 microversion using the ``volume-extended`` external event.
  Nova will perform the volume extension so the host can detect its new size.
  It will also resize the device in QEMU so instance can detect
  the new disk size without rebooting.

  Currently only the libvirt compute driver with iSCSI and FC volumes
  supports the online volume size change.

.. releasenotes/notes/nova-support-attached-volume-extend-88ce16ce41aa6d41.yaml @ b'bbe0f313bdfd30cc1c740709543b679567b42f0f'

- The 2.51 microversion exposes the ``events`` field in the response body for
  the ``GET /servers/{server_id}/os-instance-actions/{request_id}`` API. This
  is useful for API users to monitor when a volume extend operation completes
  for the given server instance. By default only users with the administrator
  role will be able to see event ``traceback`` details.

.. releasenotes/notes/openstack-request-id-95f7bc7e960344a4.yaml @ b'99c690f57e92c9e157113b58ccb85d6b1f0f70f5'

- Nova now uses oslo.middleware for request_id processing. This
  means that there is now a new ``X-OpenStack-Request-ID`` header
  returned on every request which mirrors the content of the
  existing ``X-Compute-Request-ID``. The expected existence of this
  header is signaled by Microversion 2.46. If server version >= 2.46, you
  can expect to see this header in your results (regardless of
  microversion requested).

.. releasenotes/notes/placement-allocation-candidates-1114a843755b93c4.yaml @ b'1d01a8811a1674a36ebda809788d2e5d9f43beee'

- A new 1.10 API microversion is added to the Placement REST API. This
  microversion adds support for the GET /allocation_candidates resource
  endpoint. This endpoint returns information about possible allocation
  requests that callers can make which meet a set of resource constraints
  supplied as query string parameters. Also returned is some inventory and
  capacity information for the resource providers involved in the allocation
  candidates.

.. releasenotes/notes/placement-cors-c7a83e8c63787736.yaml @ b'a598af9de6536d8b66046fa329d9960edc706aed'

- The placement API service can now be configured to support
  `CORS <http://docs.openstack.org/developer/oslo.middleware/cors.html>`_.
  If a ``cors`` configuration group is present in the service's configuration
  file (currently ``nova.conf``), with ``allowed_origin`` configured, the values
  within will be used to configure the middleware. If ``cors.allowed_origin``
  is not set, the middleware will not be used.

.. releasenotes/notes/placement-traits-api-efa17d46ea1b616b.yaml @ b'9c975b6bd803ecca2e37082251247d356f4027fe'

- Traits are added to the placement with Microversion 1.6.

  * GET /traits: Returns all resource classes.
  * PUT /traits/{name}: To insert a single custom trait.
  * GET /traits/{name}: To check if a trait name exists.
  * DELETE /traits/{name}: To delete the specified trait.
  * GET /resource_providers/{uuid}/traits: a list of traits associated
    with a specific resource provider
  * PUT /resource_providers/{uuid}/traits: Set all the traits for a
    specific resource provider
  * DELETE /resource_providers/{uuid}/traits: Remove any existing trait
    associations for a specific resource provider

.. releasenotes/notes/recheck-quota-conf-043a5d6057b33282.yaml @ b'eab1d4b5cc6dd424c5c7dfd9989383a8e716cae5'

- A new configuration option ``[quota]/recheck_quota`` has been added to
  recheck quota after resource creation to prevent allowing quota to be
  exceeded as a result of racing requests. It defaults to True, which makes
  it impossible for a user to exceed their quota. However, it will be
  possible for a REST API user to be rejected with an over quota 403 error
  response in the event of a collision close to reaching their quota limit,
  even if the user has enough quota available when they made the request.
  Operators may want to set the option to False to avoid additional load on
  the system if allowing quota to be exceeded because of racing requests is
  considered acceptable.

.. releasenotes/notes/reserved_host_cpus-e7de4aa9b89bd947.yaml @ b'c102600d59ed6cd8751d8012c138cd318866910a'

- A new configuration option ``reserved_host_cpus`` has been added for compute services. It helps operators to provide how many physical CPUs they would like to reserve for the hypervisor separately from what the instances use.

.. releasenotes/notes/send-notification-when-instance-tag-changes-67c08000b6e0cd2a.yaml @ b'1590f18c633d076fc0b2a49ef24e3227c07d76b3'

- Versioned instance.update notification will be sent when server's tags field is updated.

.. releasenotes/notes/sriov-ovs-offload-1c3fe79e847f8c8f.yaml @ b'ccc1def0f5f6ec1cde48ca50c7e3e854e8cd112e'

- Adds support to OVS vif type with direct port (SR-IOV).
  In order to use this OVS acceleration mode, ``openvswitch`` 2.8.0
  and 'Linux Kernel' 4.8 are required. This feature allows control of
  an SR-IOV virtual function (VF) via OpenFlow control plane and gain
  improved performance of 'Open vSwitch'. Please note that in Pike
  release we can't differentiate between SR-IOV hardware and OVS offloaded
  on the same host. This limitation should be resolved when the
  enable-sriov-nic-features will be completed.
  Until then operators can use host aggregates to ensure that they can
  schedule instances on specific hosts based on hardware.

.. releasenotes/notes/support-tag-when-boot-4dd124371e3ef446.yaml @ b'b50b5a660efd5401490e9dbda853d7363d0568e3'

- Adds support for applying tags when creating a server. The tag schema is the same as in the 2.26 microversion.

.. releasenotes/notes/validate-expired-user-tokens-glance-440c36887286b52f.yaml @ b'6211009e557cf1c0addaf81e75e03939f8640a8a'

- Added support for Keystone middleware feature for interaction of Nova with
  the Glance API. With this support, if service token is sent along with the
  user token, then the expiration of user token will be ignored. In order to
  use this functionality a service user needs to be created first.
  Add the service user configurations in ``nova.conf`` under ``service_user``
  group and set ``send_service_user_token`` flag to ``True``.

  .. note:: This feature is already implemented for Nova interaction with the
    Cinder and Neutron APIs in Ocata.

.. releasenotes/notes/veritas_hyperscale_libvirt_driver-ba02bea54a9a99db.yaml @ b'1dc62d8f54486ca7cb514f006d40d38c2378f8cd'

- The libvirt compute driver now supports connecting to Veritas HyperScale volume backends.

.. releasenotes/notes/virt-device-tagged-attach-53e214d3b3fdd183.yaml @ b'125c17465f3d8d15fc87f8776e63aebbc516ef6a'

- Microversion 2.49 brings device role tagging to the attach operation of
  volumes and network interfaces. Both network interfaces and volumes can now
  be attached with an optional ``tag`` parameter. The tag is then exposed to
  the guest operating system through the metadata API. Unlike the original
  device role tagging feature, tagged attach does not support the config
  drive. Because the config drive was never designed to be dynamic, it only
  contains device tags that were set at boot time with API 2.32. Any changes
  made to tagged devices with API 2.49 while the server is running will only
  be reflected in the metadata obtained from the metadata API. Because of
  metadata caching, changes may take up to ``metadata_cache_expiration`` to
  appear in the metadata API. The default value for
  ``metadata_cache_expiration`` is 15 seconds.

  Tagged volume attachment is not supported for shelved-offloaded instances.
  Tagged device attachment (both volumes and network interfaces) is not
  supported for Cells V1 deployments.

.. releasenotes/notes/volume-attach-versioned-notifications-ef5afde3a5f6a749.yaml @ b'7fe677d71bc117245c52517e40218bfee8152312'

- The following volume attach and volume detach versioned notifications have
  been added to the nova-compute service:

  * instance.volume_attach.start
  * instance.volume_attach.end
  * instance.volume_attach.error
  * instance.volume_detach.start
  * instance.volume_detach.end

.. releasenotes/notes/xenapi-virt-device-role-tagging-5ffb440f75fae834.yaml @ b'85e94cef77dbf0b0e464f43f4f6de447a0274dd6'

- The ``XenAPI`` compute driver now supports creating servers with virtual
  interface and block device tags which was introduced in the ``2.32``
  microversion.

  Note that multiple paths will exist for a tagged disk for the following
  reasons:

  1. HVM guests may not have the paravirtualization (PV) drivers installed,
     in which case the disk will be accessible on the ``ide`` bus. When the
     PV drivers are installed the disk will be accessible on the ``xen`` bus.
  2. Windows guests with PV drivers installed expose devices in a different
     way to Linux guests with PV drivers. Linux systems will see disk paths
     under ``/sys/devices/``, but Windows guests will see them in the
     registry, for example ``HKLM\System\ControlSet001\Enum\SCSIDisk``. These
     two disks are both on the ``xen`` bus.

  See the following XenAPI documentation for details: http://xenbits.xen.org/docs/4.2-testing/misc/vbd-interface.txt


.. _Release Notes_16.0.0_pike-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1707256-shared-storage-placement-5f221e124500b999.yaml @ b'0d31698d9e97e98f599f6b7ee0f1533677deee97'

- Due to `bug 1707256`_, shared storage modeling in Placement is not
  supported by the scheduler. This means that in the Pike release series,
  an operator will be unable to model a shared storage pool between two or
  more compute hosts using the Placement service for scheduling and resource
  tracking.

  This is not a regression, just a note about functionality that is not yet
  available. Support for modeling shared storage providers will be worked on
  in the Queens release.

  .. _bug 1707256: https://bugs.launchpad.net/nova/+bug/1707256

.. releasenotes/notes/deprecate-live-migration-progress-timeout-b4640047dc5c8eed.yaml @ b'510fe1353d25affc3eee72e10b7756904f8748e9'

- The live-migration progress timeout controlled by the configuration option
  ``[libvirt]/live_migration_progress_timeout`` has been discovered to
  frequently cause live-migrations to fail with a progress timeout error,
  even though the live-migration is still making good progress.
  To minimize problems caused by these checks we have changed the default
  to 0, which means do not trigger a timeout.
  To modify when a live-migration will fail with a timeout error, please now
  look at ``[libvirt]/live_migration_completion_timeout`` and
  ``[libvirt]/live_migration_downtime``.

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'c92337bdf80fea4c0a8ebb433bacec4cc07f7a94'

- Due to the changes in scheduling of bare metal nodes, additional resources
  may be reported as free to Placement. This happens in two cases:

  * An instance is deployed with a flavor smaller than a node (only possible
    when exact filters are not used)
  * Node properties were modified in ironic for a deployed nodes

  When such instances were deployed without using a custom resource class,
  it is possible for the scheduler to try deploying another instance on
  the same node. It will cause a failure in the compute and a scheduling
  retry.

  The recommended work around is to assign a resource class to all ironic
  nodes, and use it for scheduling of bare metal instances.

.. releasenotes/notes/scheduler-upcalls-with-isolated-cells-0100eb5d1f212210.yaml @ b'ef1c539ad1f4b94b077f606502c8c53daf6620d2'

- In deployments with multiple (v2) cells, upcalls from the computes to the scheduler
  (or other control services) cannot occur. This prevents certain things from happening,
  such as the track_instance_changes updates, as well as the late affinity checks for
  server groups. See the related documentation on the ``scheduler.track_instance_changes``
  and ``workarounds.disable_group_policy_check_upcall`` configuration options for more
  details. Single-cell deployments without any MQ isolation will continue to operate as
  they have for the time being.


.. _Release Notes_16.0.0_pike-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-interface-attach-detach-support-in-ironic-cb2bf11f3875350a.yaml @ b'66f962d9b90d081fb029b455e12c625a9738ff92'

- Interface attachment/detachment for ironic virt driver was implemented in
  in-tree network interfaces in ironic version 8.0, and this release is
  required for nova's interface attachment feature to work. Prior to that
  release, calling VIF attach on an active ironic node using in-tree network
  interfaces would be basically a noop. It should not be an issue during the
  upgrade though, as it is required to upgrade ironic before nova.

.. releasenotes/notes/add-neutron-floating_pool-option-cba402c2de407b78.yaml @ b'babb6f5f28c156a5f54af7434747a9848789b048'

- A ``default_floating_pool`` configuration option has been added in the
  ``[neutron]`` group. The existing ``default_floating_pool`` option in the
  ``[DEFAULT]`` group is retained and should be used by nova-network users.
  Neutron users meanwhile should migrate to the new option.

.. releasenotes/notes/added-network-metadata-7784295884f65c09.yaml @ b'ccebded0cbb654be18db5b4e0e7f8b8a3a7cacdb'

- The information in the network.json metadata has been amended,
  for IPv6 networks under Neutron control, the ``type`` field has been
  changed from being always set to ``ipv6_dhcp`` to correctly reflecting
  the ``ipv6_address_mode`` option in Neutron.

.. releasenotes/notes/bp-ironic-boot-from-volume-cfb98c733cf09a92.yaml @ b'3e1a3c9f82089b6b37605fcf88bb685625f8632f'

- The required ironic API version is updated to 1.32. The ironic service
  must be upgraded to an ironic release > 8.0 before nova is upgraded,
  otherwise all ironic integration will fail.

.. releasenotes/notes/bug-1599034-35ca4dea612d8fdb.yaml @ b'463fd7a11baa7618e14e355b162c06f3ccf2c2b2'

- The type of following config options have been changed
  from string to URI. They are checked whether they follow
  the URI format or not and its scheme.

  - ``api_endpoint`` in the ``ironic`` group
  - ``mksproxy_base_url`` in the ``mks`` group
  - ``html5_proxy_base_url`` in the ``rdp`` group
  - ``serial_port_proxy_uri`` in the ``vmware`` group

.. releasenotes/notes/bug-volume-attach-policy-1635358-671ce4d4ee8c211b.yaml @ b'4aa55f3edf453b3baba4efef4cca054f490f2d69'

- The os-volume_attachments APIs no longer check
  ``os_compute_api:os-volumes`` policy. They do still check
  ``os_compute_api:os-volumes-attachments`` policy rules. Deployers
  who have customized policy should confirm that their settings for
  os-volume_attachments policy checks are sufficient.

.. releasenotes/notes/compute-node-auto-disable-303eb9b0fdb4f3f1.yaml @ b'f93f675a8563c7c37fdcb0c685a8b491a7311361'

- The new configuration option
  ``[compute]/consecutive_build_service_disable_threshold``
  defaults to a nonzero value, which means multiple failed builds will
  result in a compute node auto-disabling itself.

.. releasenotes/notes/deprecate-nova-manage-commands-9de1abbc94e06d16.yaml @ b'0ace1a9b253b4e21d524535c0bbe92d82bcad1a3'

- The ``nova-manage project quota_usage_refresh`` and its alias ``nova-manage
  account quota_usage_refresh`` commands have been renamed ``nova-manage
  quota refresh``. Aliases are provided but these are marked as deprecated
  and will be removed in the next release of nova.

.. releasenotes/notes/deprecate-xenserver-vif-driver-option-12eb279c0c93c157.yaml @ b'7bc9b81699fb999e02a089edfeb7027c59726e0f'

- The default value for the ``[xenserver]/vif_driver`` configuration option
  has been changed to ``nova.virt.xenapi.vif.XenAPIOpenVswitchDriver`` to
  match the default configuration of ``[DEFAULT]/use_neutron=True``.

.. releasenotes/notes/libvirt-firewall-ignoreuse_ipv6-c555f95799f991fd.yaml @ b'e5080c733076f5098f85952051878f41d47f8181'

- The libvirt driver port filtering feature will now ignore the ``use_ipv6``
  config option.

  The libvirt driver provides port filtering capability. This capability
  is enabled when the following is true:

  - The ``nova.virt.libvirt.firewall.IptablesFirewallDriver`` firewall driver
    is enabled
  - Security groups are disabled
  - Neutron port filtering is disabled/unsupported
  - An IPTables-compatible interface is used, e.g. an OVS VIF in hybrid mode,
    where the VIF is a tap device connected to OVS with a bridge

  When enabled, libvirt applies IPTables rules to all interface ports that
  provide MAC, IP, and ARP spoofing protection.

  Previously, setting the ``use_ipv6`` config option to ``False`` prevented
  the generation of IPv6 rules even when there were IPv6 subnets available.
  This was fine when using nova-network, where the same config option was
  used to control generation of these subnets. However, a mismatch between
  this nova option and equivalent IPv6 options in neutron would have resulted
  in IPv6 packets being dropped.

  Seeing as there was no apparent reason for not allowing IPv6 traffic when
  the network is IPv6-capable, we now ignore this option. Instead, we use the
  availability of IPv6-capable subnets as an indicator that IPv6 rules should
  be added.

.. releasenotes/notes/libvirt-ignore-allow_same_net_traffic-fd88bb2801b81561.yaml @ b'0cae8d50fa3d039c601f3ee60840ff06fd4a3e45'

- The libvirt driver port filtering feature will now ignore the
  ``allow_same_net_traffic`` config option.

  The libvirt driver provides port filtering capability. This capability
  is enabled when the following is true:

  - The ``nova.virt.libvirt.firewall.IptablesFirewallDriver`` firewall driver
    is enabled
  - Security groups are disabled
  - Neutron port filtering is disabled/unsupported
  - An IPTables-compatible interface is used, e.g. an OVS VIF in hybrid mode,
    where the VIF is a tap device connected to OVS with a bridge

  When enabled, libvirt applies IPTables rules to all interface ports that
  provide MAC, IP, and ARP spoofing protection.

  Previously, setting the ``allow_same_net_traffic`` config option to ``True``
  allowed for same network traffic when using these port filters. This was
  the default case and was the only case tested. Setting this to ``False``
  disabled same network traffic *when using the libvirt driver port filtering
  functionality only*, however, this was neither tested nor documented.

  Given that there are other better documented and better tested ways to
  approach this, such as through use of neutron's native port filtering or
  security groups, this functionality has been removed.  Users should instead
  rely on one of these alternatives.

.. releasenotes/notes/live-migrate-config-option-force-minimum-value-c62ad8481614b146.yaml @ b'03711d264837ed59359073b76e6291ef14378014'

- Three live-migration related configuration options were restricted
  by minimum values since 16.0.0 and will now raise a ValueError if these
  configuration options' values less than minimum values, instead of
  logging warning before. These configuration options are:

  - ``live_migration_downtime`` with minimum value 100
  - ``live_migration_downtime_steps`` with minimum value 3
  - ``live_migration_downtime_delay`` with minimum value 10

.. releasenotes/notes/move-ssl-opts-to-glance-6553de9e773bccbc.yaml @ b'b277b10df6ebbb51cff13e65da7087a7bdc6ea97'

- The ``ssl`` options were only used by Nova code that interacts with
  Glance client. These options are now defined and read by Keystoneauth.
  ``api_insecure`` option from glance group is renamed to ``insecure``. The
  following ''ssl'' options are moved to ``glance`` group

  - ``ca_file`` now called ``cafile``
  - ``cert_file`` now called ``certfile``
  - ``key_file`` now called ``keyfile``

.. releasenotes/notes/network-templates-ignoreuse_ipv6-6d93c26f52a5b487.yaml @ b'c0aef97c49781f2ce0aa93fd33bfac7e68ea5b97'

- Injected network templates will now ignore the ``use_ipv6`` config option.

  Nova supports file injection of network templates. Putting these in a
  config drive is the only way to configure networking without DHCP.

  Previously, setting the ``use_ipv6`` config option to ``False`` prevented
  the generation of IPv6 network info, even if there were IPv6 networks
  available. This was fine when using nova-network, where the same config
  option is used to control generation of these subnets. However, a mismatch
  between this nova option and equivalent IPv6 options in neutron would
  have resulted in IPv6 packets being dropped.

  Seeing as there was no apparent reason for not including IPv6 network info
  when IPv6 capable networks are present, we now ignore this option.
  Instead, we include info for all available networks in the template, be
  they IPv4 or IPv6.

.. releasenotes/notes/no-placement-fallback-5db2d0645f51aca8.yaml @ b'a17851ab0ab1296e587c582523e9421a06e20597'

- In Ocata, the nova-scheduler would fall back to not calling the placement service during instance boot if old computes were running. That compatibility mode is no longer present in Pike, and as such, the scheduler fully depends on the placement service. This effectively means that in Pike Nova requires Placement API version 1.4 (Ocata).

.. releasenotes/notes/os-server-tags-default-policy-change-003a244908a67289.yaml @ b'f0c0621aa09a6f659e9080313962b99adbb63459'

- The default policy on os-server-tags has been changed from ``RULE_ANY`` (allow all) to ``RULE_ADMIN_OR_OWNER``. This is because server tags should only be manipulated on servers owned by the user or admin. This doesn't have any affect on how the API works.

.. releasenotes/notes/pike-fw-driver-noop-699d411b790035d4.yaml @ b'064da0853848c44a495f20912d835fbafa800515'

- The default value of the ``[DEFAULT]/firewall_driver`` configuration option
  has been changed to ``nova.virt.firewall.NoopFirewallDriver`` to coincide
  with the default value of ``[DEFAULT]/use_neutron=True``.

.. releasenotes/notes/pike-libvirt-min-version-bb7f43020995ac10.yaml @ b'b980df0d5423700719e3e6004de103a38886f070'

- The minimum required version of libvirt used by the ``nova-compute`` service
  is now 1.2.9. The minimum required version of QEMU used by the
  ``nova-compute`` service is now 2.1.0. Failing to meet these minimum versions
  when using the libvirt compute driver will result in the ``nova-compute``
  service not starting.

.. releasenotes/notes/pike-multicell-api-ae4fbebd711165ce.yaml @ b'9a5c3cd7da76a7340861d552718e7e46640f15be'

- Parts of the compute REST API are now relying on getting information from
  cells via their mappings in the ``nova_api`` database. This is to support
  multiple cells. For example, when listing compute hosts or services, all
  cells will be iterated in the API and the results will be returned.

  This change can have impacts, however, to deployment tooling that relies on
  parts of the API, like listing compute hosts, ``before`` the compute hosts
  are mapped using the ``nova-manage cell_v2 discover_hosts`` command.

  If you were using ``nova hypervisor-list`` after starting new nova-compute
  services to tell when to run ``nova-manage cell_v2 discover_hosts``, you
  should change your tooling to instead use one of the following commands::

    nova service-list --binary nova-compute [--host <hostname>]

    openstack compute service list --service nova-compute [--host <host>]

  As a reminder, there is also the
  ``[scheduler]/discover_hosts_in_cells_interval`` configuration option which
  can be used to automatically discover hosts from the nova-scheduler
  service.

.. releasenotes/notes/quota-limits-classes-api-db-88e5d0d2426d2dba.yaml @ b'b291061cb14b4a5048e071be01955d4ab2a32de1'

- Quota limits and classes are being moved to the API database for Cells v2.
  In this release, the online data migrations will move any quota limits and
  classes you have in your main database to the API database, retaining all
  attributes.

  .. note:: Quota limits and classes can no longer be soft-deleted as the API
    database does not replicate the legacy soft-delete functionality from the
    main database. As such, deleted quota limits and classes are not migrated
    and the behavior users will experience will be the same as if a purge of
    deleted records was performed.

.. releasenotes/notes/quota-show-detail-access-d6f37282d288fa33.yaml @ b'dcc2934921c5b2770878eee5afd088a1a8dbf645'

- The default policy for os_compute_api:os-quota-sets:detail has been changed to permit listing of quotas with details to project users, not only to admins.

.. releasenotes/notes/remove-cert-becab1c042700f80.yaml @ b'2bcee77e3baa0d338685915fa2456175f6eaa2ad'

- The deprecated nova cert daemon is now removed. The /os-certificates API endpoint that depended on this service now returns 410 whenever it is called.

.. releasenotes/notes/remove-cloudpipe-api-f7aea9372046ecfc.yaml @ b'acdc2da0e3b0255e9884c8a8f1bfe38367c2094c'

- The deprecated /os-cloudpipe API endpoint has been removed. Whenever calls are made to that endpoint it now returns a 410 response.

.. releasenotes/notes/remove-console-driver-opt-07344dbc02badaa4.yaml @ b'f71e5687f545a3b3b981b851d719bbab1cf49ddd'

- Configuration option ``console_driver`` in the ``DEFAULT`` group has
  been deprecated since the Ocata release and is now removed.

.. releasenotes/notes/remove-deprecated-extensions-enable-config-options-d6b3d62a6cc1cbe5.yaml @ b'de0a8440c86e180f39e2eed421e1a413844e4dac'

- Deprecated config options to enable/disable extensions
  ``extensions_blacklist`` and ``extensions_whitelist`` have been removed.
  This means all API extensions are always enabled. If you modified policy,
  please double check you have the correct policy settings for all APIs.

.. releasenotes/notes/remove-discoverable-policy-rules-4a2c87e1c88a3228.yaml @ b'd3b647a0009643e53d0178af909d0b7b5320d896'

- All policy rules with the following naming scheme have been
  removed: ``os_compute_api:{extension_alias}:discoverable``
  These policy rules were used to hide an enabled extension from the
  list active API extensions API. Given it is no longer possible to
  disable any API extensions, it makes no sense to have the option
  to hide the fact an API extension is active. As such, all these policy
  rules have been removed.

.. releasenotes/notes/remove-glusterfs-volume-driver-dd211308bca4ad01.yaml @ b'5c5bc57d2bea9b860d2641fd2a3410d1c835b1f8'

- The ``nova.virt.libvirt.volume.glusterfs.LibvirtGlusterfsVolumeDriver``
  volume driver has been removed. The GlusterFS volume driver in Cinder was
  deprecated during the Newton release and was removed from Cinder in the
  Ocata release so it is effectively not maintained and therefore no longer
  supported.

  The following configuration options, previously found in the ``libvirt``
  group, have been removed:

  - ``glusterfs_mount_point_base``
  - ``qemu_allowed_storage_drivers``

  These were used by the now-removed ``LibvirtGlusterfsVolumeDriver`` volume
  driver and therefore no longer had any effect.

.. releasenotes/notes/remove-nova-cells-topic-config-a7cd4d1a3e2d7d5b.yaml @ b'7815108d4892525b0047c787cbd2fe2f26c204c2'

- The cells topic configuration option has been removed. Please make sure
  your cells related message queue topic is 'cells'.

.. releasenotes/notes/remove-scality-volume-driver-21ff4832d0d3f28e.yaml @ b'9e5b91568743178f9fbc251f02ea93e77a7da01e'

- The ``nova.virt.libvirt.volume.scality.LibvirtScalityVolumeDriver`` volume
  driver has been removed. The Scality volume driver in Cinder was deprecated
  during the Newton release and was removed from Cinder in the Ocata release
  so it is effectively not maintained and therefore no longer supported.

.. releasenotes/notes/remove-scality-volume-driver-21ff4832d0d3f28e.yaml @ b'9e5b91568743178f9fbc251f02ea93e77a7da01e'

- The following configuration options, previously found in the ``libvirt``
  group, have been removed:

  - ``scality_sofs_config``
  - ``scality_sofs_mount_point``

  These were used by the now-removed ``LibvirtScalityVolumeDriver`` volume
  driver and therefore no longer had any effect.

.. releasenotes/notes/remove-topic-config-opts-336f72bebf4e9141.yaml @ b'6ef30d5078595108c1c0f2b5c258ae6ef2db1eeb'

- Configuration options related to RPC topics were deprecated in the past
  releases and are now completely removed from nova. There was no need to
  let users choose the RPC topics for all services. There was little
  benefit from this and it made it really easy to break Nova by changing
  the value of topic options.

  The following options are removed:

  - ``compute_topic``
  - ``console_topic``
  - ``consoleauth_topic``
  - ``scheduler_topic``
  - ``network_topic``

.. releasenotes/notes/remove-unused-admin_actions_policy-rule-c868436ac6fad50d.yaml @ b'353fb80d4d8464037f475549fd2653b423ffd2b3'

- Policy rule with name os_compute_api:os-admin-actions has been removed
  as it was never used by any API.

.. releasenotes/notes/remove-wsdl-location-config-33d439f7fb7036a2.yaml @ b'55d07cf643971d41747f735595134673ab15c9d5'

- The ``[vmware] wsdl_location`` configuration option has been removed after
  being deprecated in 15.0.0. It was unused and should have no impact.

.. releasenotes/notes/remove_deprecated_image_file_config_opts-d7bf437f518b6eca.yaml @ b'ff8dcf6dcd979ea16cc188d522ae00ad645a4337'

- Configuration options related to image file have been removed. They were
  marked as deprecated because the feature to download images from glance
  via filesystem is not used. Below are the removed options:

  - ``image_file_url.filesystems``
  - ``image_file_url.FS.id``
  - ``image_file_url.FS.mountpoint``

.. releasenotes/notes/rename-libvirt-num-iscsi-scan-tries-opt-8329385f84d2518e.yaml @ b'3f95d65a61fbc821c0ea106786058d9954f4dc57'

- ``libvirt.num_iscsi_scan_tries`` option has been renamed to
  ``libvirt.num_volume_scan_tries``, as the previous name was suggesting
  that this option only concerns devices connected using iSCSI interface.
  It also concerns devices connected using fibrechannel, scaleio and disco.

.. releasenotes/notes/request_log-e7680b3276910743.yaml @ b'aa45a6f3ab7ae870f99365b14b276cceff51ec8d'

- A new request_log middleware is created to log REST HTTP requests
  even if Nova API is not running under eventlet.wsgi. Because this
  is an api-paste.ini change, you will need to manually update your
  api-paste.ini with the one from the release to get this
  functionality. The new request logs will only emit when it is
  detected that nova-api is not running under eventlet, and will
  include the microversion of the request in addition to all the
  previously logged information.

.. releasenotes/notes/reworked-nova-manage-db-commands-b958b0a41a4004a6.yaml @ b'59dd49978c04bb19dd7f56e1e97a2bb75a0da759'

- The ``nova-manage api_db sync`` and ``nova-manage db sync`` commands
  previously took an optional ``--version`` parameter to determine which
  version to sync to. For example::

      $ nova-manage api_db sync --version some-version

  This is now an optional positional argument. For example::

      $ nova-manage api_db sync some-version

  Aliases are provided but these are marked as deprecated and will be removed
  in the next release of nova.

.. releasenotes/notes/scheduler-placement-allocation-candidates-a6221e1819ea1c2d.yaml @ b'48268c73e3f43fa763d071422816942942987f4a'

- The scheduler now requests allocation candidates from the Placement
  service during scheduling. The allocation candidates information
  was introduced in the Placement API 1.10 microversion, so you should
  upgrade the placement service before the Nova scheduler service so that
  the scheduler can take advantage of the allocation candidate
  information.

.. releasenotes/notes/service-uuid-online-migration-17d48f198a6d4deb.yaml @ b'3a01e33d7e4426426d913b480d202e21cdc83ae3'

- An online data migration has been added to populate the ``services.uuid``
  column in the nova database for non-deleted services records. Listing or
  showing services out of the ``os-services`` API will have the same effect.

.. releasenotes/notes/switch-to-cinder-v3-00bdf83e0937dbe5.yaml @ b'6dc3d7beaf9a41be766a2e6787593ef6a5644097'

- Nova is now configured to use the v3 version of the Cinder API. You need to
  ensure that the v3 version of the Cinder API is available and listed in the
  service catalog in order to use Nova with the default configuration option.

  The base ``3.0`` version is identical to v2 and it was introduced in the
  Newton release of OpenStack. In case you need Nova to continue using the v2
  version you can point it towards that by setting the ``catalog_info``
  option in the ``nova.conf`` file under the ``cinder`` section, like::

      [cinder]
      catalog_info = volumev2:cinderv2:publicURL

.. releasenotes/notes/trim-default-sched-filters-e70de3bb4c7b1a1b.yaml @ b'2fe96819c24eff5a9493a6559f3e8d5b4624a8c9'

- Since we now use Placement to verify basic CPU/RAM/disk resources when
  using the FilterScheduler, the ``RamFilter`` and ``DiskFilter`` entries are
  being removed from the default value for the ``enabled_filters`` config
  option in the ``[filter_scheduler]`` group.  If you are overriding this
  option, you probably should remove them from your version.  If you are
  using CachingScheduler you may wish to enable these filters as we will
  not use Placement in that case.

.. releasenotes/notes/wsgi-applications-8017c3192d2b143e.yaml @ b'9e8ec982ac4c382f132b0d0070ba046026c0dc9a'

- WSGI application scripts ``nova-api-wsgi`` and ``nova-metadata-wsgi`` are
  now available. They allow running the compute and metadata APIs using a WSGI
  server of choice (for example nginx and uwsgi, apache2 with mod_proxy_uwsgi
  or gunicorn). The eventlet-based servers are still available, but the WSGI
  options will allow greater deployment flexibility.


.. _Release Notes_16.0.0_pike-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-TypeAffinityFilter-465c47a6b2a7bd77.yaml @ b'46ba7e8df5a2d11fbca72f9b8a0b7d8cc1bbe06f'

- TypeAffinityFilter is deprecated for removal in the
  17.0.0 Queens release. There is no replacement planned for this
  filter. It is fundamentally flawed in that it relies on the
  ``flavors.id`` primary key and if a flavor "changed", i.e. deleted
  and re-created with new values, it will result in this filter
  thinking it is a different flavor, thus breaking the usefulness of
  this filter.

.. releasenotes/notes/deprecate-allow_instance_snapshots-c63c45856c902e1e.yaml @ b'43fe032a1583ab08a32d8efbe470de754a374607'

- The ``[api]/allow_instance_snapshots`` configuration option is now
  deprecated for removal. To disable snapshots in the ``createImage`` server
  action API, change the ``os_compute_api:servers:create_image`` and
  ``os_compute_api:servers:create_image:allow_volume_backed`` policies.

.. releasenotes/notes/deprecate-baremetal-filters-618249af65115bf6.yaml @ b'7e3c4dbf3a1273fdfce7667d986975cc7f13c7a3'

- The configuration options ``baremetal_enabled_filters`` and
  ``use_baremetal_filters`` are deprecated in Pike and should only be used if
  your deployment still contains nodes that have not had their resource_class
  attribute set. See `Ironic release notes <https://docs.openstack.org/releasenotes/ironic/>`_
  for upgrade concerns.

.. releasenotes/notes/deprecate-baremetal-filters-618249af65115bf6.yaml @ b'7e3c4dbf3a1273fdfce7667d986975cc7f13c7a3'

- The following scheduler filters are deprecated in Pike: ``ExactRamFilter``,
  ``ExactCoreFilter`` and ``ExactDiskFilter`` and should only be used if your
  deployment still contains nodes that have not had their resource_class
  attribute set. See `Ironic release notes <https://docs.openstack.org/releasenotes/ironic/>`_
  for upgrade concerns.

.. releasenotes/notes/deprecate-cellsv1-592b3c3612a9dfa5.yaml @ b'3414ab14cacc6e855bbdc3381f3d6c8bdccbdec0'

- Cells v1, which includes the ``[cells]`` configuration options and
  ``nova-cells`` service, is deprecated in favor of Cells v2. For information
  on Cells v2, see: https://docs.openstack.org/nova/latest/user/cells.html

.. releasenotes/notes/deprecate-live-migration-progress-timeout-b4640047dc5c8eed.yaml @ b'510fe1353d25affc3eee72e10b7756904f8748e9'

- ``[libvirt]/live_migration_progress_timeout`` has been deprecated as this
  feature has been found not to work. See bug 1644248 for more details.

.. releasenotes/notes/deprecate-more-nova-network-opts-a9f87c79f7d26438.yaml @ b'1c1a4b18f83d58786714077762ab981c27f23c90'

- The following options, found in ``DEFAULT``, were only used for configuring
  nova-network and are, like nova-network itself, now deprecated.

  - ``default_floating_pool`` (neutron users should use the
    ``neutron.default_floating_pool``)
  - ``ipv6_backend``
  - ``firewall_driver``
  - ``metadata_host``
  - ``metadata_port``
  - ``iptables_top_regex``
  - ``iptables_bottom_regex``
  - ``iptables_drop_action``
  - ``ldap_dns_url``
  - ``ldap_dns_user``
  - ``ldap_dns_password``
  - ``ldap_dns_soa_hostmaster``
  - ``ldap_dns_servers``
  - ``ldap_dns_base_dn``
  - ``ldap_dns_soa_refresh``
  - ``ldap_dns_soa_retry``
  - ``ldap_dns_soa_expiry``
  - ``ldap_dns_soa_minimum``
  - ``dhcpbridge_flagfile``
  - ``dhcpbridge``
  - ``dhcp_lease_time``
  - ``dns_server``
  - ``use_network_dns_servers``
  - ``dnsmasq_config_file``
  - ``ebtables_exec_attempts``
  - ``ebtables_retry_interval``
  - ``fake_network``
  - ``send_arp_for_ha``
  - ``send_arp_for_ha_count``
  - ``dmz_cidr``
  - ``force_snat_range``
  - ``linuxnet_interface_driver``
  - ``linuxnet_ovs_integration_bridge``
  - ``use_single_default_gateway``
  - ``forward_bridge_interface``
  - ``ovs_vsctl_timeout``
  - ``networks_path``
  - ``public_interface``
  - ``routing_source_ip``
  - ``use_ipv6``
  - ``allow_same_net_traffic``

.. releasenotes/notes/deprecate-nicira-iface-id-in-xenserver-dc3c147aef1bc2c8.yaml @ b'd0d546ce8e18adb0eeb9f3aa502e726be7979582'

- When using neutron polling mode with XenAPI driver, booting a VM will
  timeout because ``nova-compute`` cannot receive network-vif-plugged event.
  This is because it set vif['id'](i.e. neutron port uuid) to two different
  OVS ports. One is XenServer VIF, the other is tap device qvo-XXXX, but
  setting 'nicira-iface-id' to XenServer VIF isn't correct, so deprecate it.

.. releasenotes/notes/deprecate-nova-manage-commands-9de1abbc94e06d16.yaml @ b'0ace1a9b253b4e21d524535c0bbe92d82bcad1a3'

- A number of ``nova-manage`` commands have been deprecated. The commands,
  along with the reasons for their deprecation, are listed below:

  ``account``

    This allows for the creation, deletion, update and listing of user and
    project quotas. Operators should use the equivalent resources in the
    `REST API`__ instead.

    The ``quota_usage_refresh`` sub-command has been renamed to ``nova-manage
    quota refresh``. This new command should be used instead.

  ``agent``

    This allows for the creation, deletion, update and listing of "agent
    builds". Operators should use the equivalent resources in the `REST
    API`__ instead.

  ``host``

    This allows for the listing of compute hosts. Operators should use the
    equivalent resources in the `REST API`__ instead.

  ``log``

    This allows for the filtering of errors from nova's logs and extraction
    of all logs from syslog. This command has not been actively maintained in
    a long time, is not tested, and can be achieved using ``journalctl`` or by
    simply grepping through ``/var/log``. It will simply be removed.

  ``project``

    This is an alias for ``account`` and has been deprecated for the same
    reasons.

  ``shell``

    This starts the Python interactive interpreter. It is a clone of the same
    functionality found in Django's ``django-manage`` command. This command
    hasn't been actively maintained in a long time and is not tested. It will
    simply be removed.

  These commands will be removed in their entirety during the Queens cycle.

  __ https://developer.openstack.org/api-ref/compute/#quota-sets-os-quota-sets
  __ https://developer.openstack.org/api-ref/compute/#guest-agents-os-agents
  __ https://developer.openstack.org/api-ref/compute/#compute-services-os-services

.. releasenotes/notes/deprecate-the-cinder-v2-support-0cebc90580a3e80f.yaml @ b'89f984d02864db4a821712a6deabd49c95b6c314'

- Nova support for using the Block Storage (Cinder) v2 API is now deprecated
  and will be removed in the 17.0.0 Queens release. The v3 API is now the
  default and is backward compatible with the v2 API.

.. releasenotes/notes/deprecate-xenserver-vif-driver-option-12eb279c0c93c157.yaml @ b'7bc9b81699fb999e02a089edfeb7027c59726e0f'

- The ``[xenserver]/vif_driver`` configuration option is deprecated for
  removal. The ``XenAPIOpenVswitchDriver`` vif driver is used for Neutron and
  the ``XenAPIBridgeDriver`` vif driver is used for nova-network, which
  itself is deprecated. In the future, the ``use_neutron`` configuration
  option will be used to determine which vif driver to load.

.. releasenotes/notes/deprecate_trustedfilter-d733a4b482967b00.yaml @ b'82f16b88f33316bd5912081c4a6b2524e13437ac'

- The ``TrustedFilter`` scheduler filter has been experimental since its existence on
  May 18, 2012. Due to the lack of tests and activity with it, it's now
  deprecated and set for removal in the 17.0.0 Queens release.

.. releasenotes/notes/deprecate_unused_policy-d3bf8589aee63eb6.yaml @ b'a7022af2b5a3e67c46786ea0ffc74185f55dc566'

- Some unused policies have been deprecated. These are:

  * ``os_compute_api:os-server-groups``
  * ``os_compute_api:flavors``

  Please note you should remove these from your policy file(s).

.. releasenotes/notes/deprecate_wsgi_log_format-43a10b7a608ea8f3.yaml @ b'27c341c1bf7c44199df49edd63e89cd0c96c094f'

- Configuration option ``wsgi_log_format`` is deprecated. This only
  applies when running nova-api under eventlet, which is no longer
  the preferred deployment mode.

.. releasenotes/notes/deprecates-multinic-floatingipaction-osvirtualinterface-api-73b24e5304635e9d.yaml @ b'03ce16988463c08761e9dbe90579792dcdf94c68'

- The following APIs which are considered as proxies of Neutron networking
  API, are deprecated and will result in a 404 error response in microversion
  ``2.44``::

       POST /servers/{server_uuid}/action
       {
           "addFixedIp": {...}
       }
       POST /servers/{server_uuid}/action
       {
           "removeFixedIp": {...}
       }
       POST /servers/{server_uuid}/action
       {
           "addFloatingIp": {...}
       }
       POST /servers/{server_uuid}/action
       {
           "removeFloatingIp": {...}
       }

  Those server actions can be replaced by calling the Neutron API directly.

  The nova-network specific API to query the server's interfaces is
  deprecated::

       GET /servers/{server_uuid}/os-virtual-interfaces

  To query attached neutron interfaces for a specific server, the API
  ``GET /servers/{server_uuid}/os-interface`` can be used.

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'c92337bdf80fea4c0a8ebb433bacec4cc07f7a94'

- Scheduling bare metal (ironic) instances using standard resource classes
  (VCPU, memory, disk) is deprecated and will no longer be supported in
  Queens.  Custom resource classes should be used instead.
  Please refer to the `ironic documentation
  <https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-based-on-resource-classes>`_
  for a detailed explanation.

.. releasenotes/notes/microversion-2.43-77d63cae38695fd1.yaml @ b'aad4be2e3d071aa402d53178689b350436ae4b34'

- The ``os-hosts`` API is deprecated as of the 2.43 microversion. Requests
  made with microversion >= 2.43 will result in a 404 error. To list and show
  host details, use the ``os-hypervisors`` API. To enable or disable a
  service, use the ``os-services`` API. There is no replacement for the
  ``shutdown``, ``startup``, ``reboot``, or ``maintenance_mode`` actions as those are
  system-level operations which should be outside of the control of the
  compute service.

.. releasenotes/notes/quota-refresh-deprecated-08040cb2e62fdc6b.yaml @ b'f2606322f72d94a80941d00f19c7c01d81966cab'

- The ``nova-manage quota refresh`` command has been deprecated and is now a
  no-op since quota usage is counted from resources instead of being tracked
  separately. The command will be removed during the Queens cycle.

.. releasenotes/notes/reworked-nova-manage-db-commands-b958b0a41a4004a6.yaml @ b'59dd49978c04bb19dd7f56e1e97a2bb75a0da759'

- The ``--version`` parameters of the ``nova-manage api_db sync`` and
  ``nova-manage db sync`` commands has been deprecated in favor of
  positional arguments.

.. releasenotes/notes/scheduler-deprecation-20d035193c7392e4.yaml @ b'd48bba18a7cebc57e63f5b2c5a1e939654de0883'

- The CachingScheduler and ChanceScheduler drivers are deprecated in Pike.
  These are not integrated with the placement service, and their primary
  purpose (speed over correctness) should be addressed by the default
  FilterScheduler going forward. If ChanceScheduler behavior is desired
  (i.e. speed trumps correctness) then configuring the FilterScheduler with
  no enabled filters should approximate that behavior.


.. _Release Notes_16.0.0_pike-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'3f985f1eda6f29180878a3d21c20c5057179486a'

- [CVE-2017-7214] Failed notification payload is dumped in logs with auth secrets

  * `Bug 1673569 <https://bugs.launchpad.net/nova/+bug/1673569>`_


.. _Release Notes_16.0.0_pike-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/add-server-groups-keys-in-quota-class-set-response-4a91ef4b2683e31c.yaml @ b'd0f91817eb79e0ab09b106f501214f55df6d0921'

- In the 2.50 microversion, the following fields are added to the
  ``GET /os-quota-class-sets`` and ``PUT /os-quota-class-sets/{id}`` API
  response:

  - ``server_groups``
  - ``server_group_members``

  And the following fields are removed from the same APIs in the same
  microversion:

  - ``fixed_ips``
  - ``floating_ips``
  - ``security_groups``
  - ``security_group_rules``
  - ``networks``

.. releasenotes/notes/bug-1657585-99b7eddc40c71e5a.yaml @ b'70afc0d5408aaae8beb587682fe26c124c0cacee'

- The ``POST`` and ``DELETE`` operations on the
  ``os-assisted-volume-snapshots`` API will now fail with a 400 error if the
  related instance is undergoing a task state transition or does not have a
  host, i.e. is shelved offloaded.

.. releasenotes/notes/bug-1662699-06203e7262e02aa6.yaml @ b'e34f05edb2efc79bfdd8e73cca8fa02ea6ef2d60'

- Fixes `bug 1662699`_ which was a regression in the v2.1 API from the
  ``block_device_mapping_v2.boot_index`` validation that was performed in the
  legacy v2 API. With this fix, requests to create a server with
  ``boot_index=None`` will be treated as if ``boot_index`` was not specified,
  which defaults to meaning a non-bootable block device.

  .. _bug 1662699: https://bugs.launchpad.net/nova/+bug/1662699

.. releasenotes/notes/bug-1670522-0a9f20e05e531c7a.yaml @ b'ac61abb7c74f1a8e3e9134bc045455fd9fdac0fa'

- Fixes `bug 1670522`_ which was a regression in the 15.0.0 Ocata release.
  For compute nodes running the libvirt driver with ``virt_type`` not set to
  "kvm" or "qemu", i.e. "xen", creating servers will fail by default if
  libvirt >= 1.3.3 and QEMU >= 2.7.0 without this fix.

  .. _bug 1670522: https://bugs.launchpad.net/nova/+bug/1670522

.. releasenotes/notes/bug-1673613-7357d40ba9ab1fa6.yaml @ b'9a9a620ea2d06e51c01b0864d7275b57d7203e5a'

- Includes the fix for `bug 1673613`_ which could cause issues when upgrading
  and running ``nova-manage cell_v2 simple_cell_setup`` or
  ``nova-manage cell_v2 map_cell0`` where the database connection is read
  from config and has special characters in the URL.

  .. _bug 1673613: https://launchpad.net/bugs/1673613

.. releasenotes/notes/bug-1691545-1acd6512effbdffb.yaml @ b'47fa88d94754fcdad6bb132b45196b4d44c0f4cd'

- Fixes `bug 1691545`_ in which there was a significant increase in database
  connections because of the way connections to cell databases were being
  established. With this fix, objects related to database connections are
  cached in the API service and reused to prevent new connections being
  established for every communication with cell databases.

  .. _bug 1691545: https://bugs.launchpad.net/nova/+bug/1691545

.. releasenotes/notes/bug-1704788-490797827bae9142.yaml @ b'1e5c7b52a403e708dba5a069dd86b628a4cb952c'

- Correctly allow the use of a custom scheduler driver by using the name of the custom driver entry point in the ``[scheduler]/driver`` config option. You must also update the entry point in ``setup.cfg``.

.. releasenotes/notes/bug_1659328-73686be497f5f85a.yaml @ b'f2d5af0b38334ebc33bb549c734bb4d37ca11241'

- The i/o performance for Quobyte volumes has been increased significantly
  by disabling xattrs.

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'c92337bdf80fea4c0a8ebb433bacec4cc07f7a94'

- The ironic virt driver no longer reports an empty inventory for bare metal
  nodes that have instances on them. Instead the custom resource class, VCPU,
  memory and disk are reported as they are configured on the node.

.. releasenotes/notes/project_id_validation-568d31c13c3ef735.yaml @ b'1f120b5649ba03aa5b2490a82c08b77c580f12d7'

- API calls to ``/os-quota-sets`` and flavor access will now attempt
  to validate the project_id being operated on with Keystone. If
  the user token has enough permissions to perform
  ``GET /v3/projects/{project_id}``, and the Keystone project
  does not exist, a 400 BadRequest will be returned to prevent invalid
  project data from being put in the Nova database. This fixes an effective
  silent error where the project_id would be stored even if it was not a
  valid project_id in the system.

.. releasenotes/notes/remove-check-attach-68b9ec781ad184ff.yaml @ b'63805735c25a54ad1b9b97e05080c1a6153d8e22'

- Fixes `bug 1581230`_ by removing the internal ``check_attach`` call from
  the Nova code as it can cause race conditions and the checks are handled by
  ``reserve_volume`` in Cinder. ``reserve_volume`` is called in every volume
  attach scenario to provide the necessary checks and volume state validation
  on the Cinder side.

.. releasenotes/notes/retrieve_physical_network_from_multi-segment-eec5a490c1ed8739.yaml @ b'b9d9d96a407db5a2adde3aed81e61cc9589c291a'

- Physical network name will be retrieved from a multi-segement network. The current implementation will retrieve the physical network name for the first segment that provides it. This is mostly intended to support a combination of vxlan and vlan segments. Additional work will be required to support a case of multiple vlan segments associated with different physical networks.


.. _Release Notes_16.0.0_pike-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1645175-b1ef3ad9a3e44ed6.yaml @ b'115cf068a6d48cdf8b0d20a3c5a779bb8120aa9b'

- ``instance.shutdown.end`` versioned notification will
  have an empty ``ip_addresses`` field since the network
  resources associated with the instance are deallocated
  before this notification is sent, which is actually
  more accurate. Consumers should rely on the
  instance.shutdown.start notification if they need the
  network information for the instance when it is being
  deleted.

.. releasenotes/notes/bug-1700359-b123208d51d73ae3.yaml @ b'598314a4bb53ffff2a8872bd6b290ef8d1d6c532'

- The ``PUT /os-services/disable``, ``PUT /os-services/enable`` and
  ``PUT /os-services/force-down`` APIs to enable, disable, or force-down a
  service will now only work with *nova-compute* services. If you are using
  those APIs to try and disable a non-compute service, like nova-scheduler or
  nova-conductor, those APIs will result in a 404 response.

  There really never was a good reason to disable or enable non-compute
  services anyway since that would not do anything. The nova-scheduler and
  nova-api services are checking the ``status`` and ``forced_down`` fields to
  see if instance builds can be scheduled to a compute host or if instances
  can be evacuated from a downed compute host. There is nothing that relies
  on a disabled or downed nova-conductor or nova-scheduler service.

.. releasenotes/notes/enable_new_services-compute-only-0abf5d3cbec40eb2.yaml @ b'38cca9d90506a577025a4bc2c9b023f54123a252'

- The ``[DEFAULT]/enable_new_services`` configuration option will now only be
  used to auto-disable new nova-compute services. Other services like
  nova-conductor, nova-scheduler and nova-osapi_compute will not be
  auto-disabled since disabling them does nothing functionally, and starting
  in Pike the ``PUT /os-services/enable`` REST API will not be able to find
  non-compute services to enable them.

.. releasenotes/notes/microversion-2.45-608ba80a84c8aec8.yaml @ b'66b0cf333758b5793208c2a734959aa192bbc39b'

- The 2.45 microversion is introduced which changes the response for the
  ``createImage`` and ``createBackup`` server action APIs to no longer
  return a ``Location`` response header. With microversion 2.45 those APIs
  now return a json dict in the response body with a single ``image_id`` key
  whose value is the snapshot image ID (a uuid). The old ``Location`` header
  in the response before microversion 2.45 is most likely broken and
  inaccessible by end users since it relies on the internal Glance API
  server configuration and does not take into account Glance API versions.

.. releasenotes/notes/placement-api-endpoint-interface-set-29af8b9400ce7775.yaml @ b'2c1e1341214356808936c4a812c89d4008cdb284'

- The Placement API can be set to connect to a specific keystone endpoint interface using the ``os_interface`` option in the ``[placement]`` section inside ``nova.conf``. This value is not required but can be used if a non-default endpoint interface is desired for connecting to the Placement service. By default, keystoneauth will connect to the "public" endpoint.

.. releasenotes/notes/placement-claims-844540aa7bf52b33.yaml @ b'23c4eb34380bdf3eece11abbe0f6ccb68c060f47'

- The filter scheduler will now attempt to claim a number of
  resources in the placement API after determining a list of
  potential hosts. We attempt to claim these resources for each instance
  in the build request, and if a claim does not succeed, we try this
  claim against the next potential host the scheduler selected. This
  claim retry process can potentially attempt claims against a large
  number of hosts, and we do not limit the number of hosts to attempt
  claims against. Claims for resources may fail due to another scheduler
  process concurrently claiming resources against the same compute node.
  This concurrent resource claim is normal and the retry of a claim
  request should be unusual but harmless.

.. releasenotes/notes/remove-bittorent-in-xenapi-driver-7b03447b8a1760fe.yaml @ b'812cfc14f8f5c069cc413ff6aa5c0326164a4415'

- With XenAPI driver, we have deprecated bittorrent since '15.0.0', so we
  decide to remove all bittorrent related files and unit tests.

.. releasenotes/notes/remove-check-attach-68b9ec781ad184ff.yaml @ b'63805735c25a54ad1b9b97e05080c1a6153d8e22'

- By removing the ``check_attach`` internal call from Nova, small behavioral
  changes were introduced.

  ``reserve_volume`` call was added to the boot from volume scenario. In case
  a failure occurs while building the instance, the instance goes into ERROR
  state while the volume stays in ``attaching`` state. The volume state will
  be set back to ``available`` when the instance gets deleted.

  Additional availability zone check is added to the volume attach flow,
  which results in an availability zone check when an instance gets
  unshelved. In case the deployment is not sensitive to availability zones
  and not using the AvailabilityZoneFilter scheduler filter the current
  default settings (cross_az_attach=True) are allowing to perform unshelve
  the same way as before this change without additional configuration.

  .. _`bug 1581230`: https://bugs.launchpad.net/nova/+bug/1581230

.. releasenotes/notes/remove-os-pci-api-4fcbf5fdf11c4c63.yaml @ b'75a7e6fc7d02608bf128ad72b2b8945515b12c21'

- The disabled ``os-pci`` API has been removed. This API was originally added
  to the v3 API which over time finally became the v2.1 API and the initial
  microversion is backward compatible with the v2.0 API, where the
  ``os-pci`` extension did not exist. The ``os-pci`` API was never enabled
  as a microversion in the v2.1 API and at this time no longer aligns with
  Nova strategically and is therefore just technical debt, so it has been
  removed. Since it was never enabled or exposed out of the compute REST API
  endpoint there was no deprecation period for this.


