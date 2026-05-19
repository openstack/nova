===================================
 Ocata Series Release Notes
===================================

.. _Release Notes_15.1.5-28_ocata-eol:

15.1.5-28
=========

.. _Release Notes_15.1.5-28_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'02ea2c25eddebdc220d66e4a01d8deded7c77a57'

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


.. _Release Notes_15.1.5-28_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1801702-c8203d3d55007deb.yaml @ b'c77c3eb61ca7a0da64eed62dea084ee3df1d0722'

- When testing whether direct IO is possible on the backing storage
  for an instance, Nova now uses a block size of 4096 bytes instead
  of 512 bytes, avoiding issues when the underlying block device has
  sectors larger than 512 bytes. See bug
  https://launchpad.net/bugs/1801702 for details.


.. _Release Notes_15.1.5_ocata-eol:

15.1.5
======

.. _Release Notes_15.1.5_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/libvirt-cpu-model-extra-flags-amd-ssbd-1c0d0cec14073dec.yaml @ b'c85f5e22e1cb8afd756341517bd7284ffc8e505b'

- The 'AMD-SSBD' and 'AMD-NO-SSB' flags have been added to the list of available
  choices for the ``[libvirt]/cpu_model_extra_flags`` config option. These are
  important for proper mitigation of security issues in AMD CPUs. For more
  information see
  https://www.redhat.com/archives/libvir-list/2018-June/msg01111.html


.. _Release Notes_15.1.5_ocata-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1645175-b1ef3ad9a3e44ed6.yaml @ b'cbf3b7c70331fc2a7e7fcf3fa2551d806000b967'

- ``instance.shutdown.end`` versioned notification will
  have an empty ``ip_addresses`` field since the network
  resources associated with the instance are deallocated
  before this notification is sent, which is actually
  more accurate. Consumers should rely on the
  instance.shutdown.start notification if they need the
  network information for the instance when it is being
  deleted.


.. _Release Notes_15.1.4_ocata-eol:

15.1.4
======

.. _Release Notes_15.1.4_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739646-enforce_volume_backed_for_zero_disk_flavor-b36a6eb4fa8b2964.yaml @ b'8392c7f2656ae624877e3df539681c0a8f8b4926'

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


.. _Release Notes_15.1.3_ocata-eol:

15.1.3
======

.. _Release Notes_15.1.3_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/libvirt-cpu-model-extra-flags-ssbd-fdbda6e4da495915.yaml @ b'c18cd38d4d72524c55b4ad3bfa8d9ed5e6b44caf'

- The 'SSBD' and 'VIRT-SSBD' cpu flags have been added to the list
  of available choices for the ``[libvirt]/cpu_model_extra_flags``
  config option. These are important for proper mitigation of the
  Spectre 3a and 4 CVEs. Note that the use of either of these flags
  require updated packages below nova, including libvirt, qemu
  (specifically >=2.9.0 for virt-ssbd), linux, and system
  firmware. For more information see
  https://www.us-cert.gov/ncas/alerts/TA18-141A


.. _Release Notes_15.1.1_ocata-eol:

15.1.1
======

.. _Release Notes_15.1.1_ocata-eol_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1739593-cve-2017-18191-25fe48d336d8cf13.yaml @ b'0225a61fc4557c1257383a654f0741f7ef2ddeac'

This release includes fixes for security vulnerabilities.


.. _Release Notes_15.1.1_ocata-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/agg-resource-filters-6e24c92a69afa85f.yaml @ b'6c91a3d972060e42ab9c643e87aafa09f0bc573d'

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


.. _Release Notes_15.1.1_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739593-cve-2017-18191-25fe48d336d8cf13.yaml @ b'0225a61fc4557c1257383a654f0741f7ef2ddeac'

- [CVE-2017-18191] Swapping encrypted volumes can lead to data loss and a
  possible compute host DOS attack.

  * `Bug 1739593 <https://bugs.launchpad.net/nova/+bug/1739593>`_


.. _Release Notes_15.1.1_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1721179-87bc7b64215944c0.yaml @ b'd34222286b2a215744d225b24d1548f93bc8515a'

- The ``delete_host`` command has been added in ``nova-manage cell_v2``
  to delete a host from a cell (host mappings).
  The ``force`` option has been added in ``nova-manage cell_v2 delete_cell``.
  If the ``force`` option is specified, a cell can be deleted
  even if the cell has hosts.

.. releasenotes/notes/bug-1744325-rebuild-error-status-9e2da03f3f81fd6e.yaml @ b'83fd8ac0bfd3d9e5dd4ad48bfcb845d80095b845'

- If scheduling fails during rebuild the server instance will go to ERROR
  state and a fault will be recorded. `Bug 1744325`_

  .. _Bug 1744325: https://bugs.launchpad.net/nova/+bug/1744325

.. releasenotes/notes/libvirt-cpu-model-extra-flags-a23085f58bd22d27.yaml @ b'1c6b2fce289b68af92afeddf8d30efcda1903f06'

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


.. _Release Notes_15.1.0_ocata-eol:

15.1.0
======

.. _Release Notes_15.1.0_ocata-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1661360-wsgi-known-issue-ee439d193a4b56ad.yaml @ b'4d7acf3a0caa111f407ea7aac5dde95ff6ca49b6'

- Nova does not support running the nova-api service under mod_wsgi or uwsgi
  in Ocata. There are some experimental scripts that have been available
  for years which allow you do to this, but doing so in Ocata results in
  possible failures to list and show instance details in a cells v2 setup.
  See `bug 1661360`_ for details.

  .. _bug 1661360: https://bugs.launchpad.net/nova/+bug/1661360


.. _Release Notes_15.1.0_ocata-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1738094-request_specs.spec-migration-22d3421ea1536a37.yaml @ b'4f0ff43c79c02689a118dc8100187c19b5c21238'

- This release contains a schema migration for the ``nova_api`` database
  in order to address bug 1738094:

  https://bugs.launchpad.net/nova/+bug/1738094

  The migration is optional and can be postponed if you have not been
  affected by the bug. The bug manifests itself through "Data too long for
  column 'spec'" database errors.


.. _Release Notes_15.1.0_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1664931-refine-validate-image-rebuild-6d730042438eec10.yaml @ b'bbfc4230efe3299fa51f9451f54062f32590ed3d'

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

.. releasenotes/notes/bug-1695861-ebc8a0aa7a87f7e0.yaml @ b'c53df19bd4535c5a95cd1aa7e50f49e128f83b95'

- Fixes `bug 1695861`_ in which the aggregate API accepted requests that
  have availability zone names including ':'. With this fix, a creation
  of an availability zone whose name includes ':' results in a
  ``400 BadRequest`` error response.

  .. _bug 1695861: https://bugs.launchpad.net/nova/+bug/1695861

.. releasenotes/notes/bug-1733886-os-quota-sets-force-2.36-5866924621ecc857.yaml @ b'901377b22bb92747748b25058e31d1099904c8cc'

- This release includes a fix for `bug 1733886`_ which was a regression
  introduced in the 2.36 API microversion where the ``force`` parameter was
  missing from the ``PUT /os-quota-sets/{tenant_id}`` API request schema so
  users could not force quota updates with microversion 2.36 or later. The
  bug is now fixed so that the ``force`` parameter can once again be
  specified during quota updates. There is no new microversion for this
  change since it is an admin-only API.

  .. _bug 1733886: https://bugs.launchpad.net/nova/+bug/1733886


.. _Release Notes_15.0.8_ocata-eol:

15.0.8
======

.. _Release Notes_15.0.8_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1664931-validate-image-rebuild-9c5b05a001c94a4d.yaml @ b'ffd4f72d16dacd6ca1e703f9bab37b8917d253e7'

- `OSSA-2017-005`_: Nova Filter Scheduler bypass through rebuild action

  By rebuilding an instance, an authenticated user may be able to circumvent
  the FilterScheduler bypassing imposed filters (for example, the
  ImagePropertiesFilter or the IsolatedHostsFilter). All setups using the
  FilterScheduler (or CachingScheduler) are affected.

  The fix is in the ``nova-api`` and ``nova-conductor`` services.

  .. _OSSA-2017-005: https://security.openstack.org/ossa/OSSA-2017-005.html


.. _Release Notes_15.0.7_ocata-eol:

15.0.7
======

.. _Release Notes_15.0.7_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1704788-490797827bae9142.yaml @ b'3eefcce2553856a1635a62fecf73cd9a2d9097cb'

- Correctly allow the use of a custom scheduler driver by using the name of the custom driver entry point in the ``[scheduler]/driver`` config option. You must also update the entry point in ``setup.cfg``.

.. releasenotes/notes/retrieve_physical_network_from_multi-segment-eec5a490c1ed8739.yaml @ b'a0a9f418e7f03cd497051d83359c297ca0cfb609'

- Physical network name will be retrieved from a multi-segment network. The current implementation will retrieve the physical network name for the first segment that provides it. This is mostly intended to support a combination of vxlan and vlan segments. Additional work will be required to support a case of multiple vlan segments associated with different physical networks.


.. _Release Notes_15.0.5_ocata-eol:

15.0.5
======

.. _Release Notes_15.0.5_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1673613-7357d40ba9ab1fa6.yaml @ b'b501fa7a926943238ff5b88ef94aaaf642765e73'

- Includes the fix for `bug 1673613`_ which could cause issues when upgrading
  and running ``nova-manage cell_v2 simple_cell_setup`` or
  ``nova-manage cell_v2 map_cell0`` where the database connection is read
  from config and has special characters in the URL.

  .. _bug 1673613: https://launchpad.net/bugs/1673613

.. releasenotes/notes/bug-1691545-1acd6512effbdffb.yaml @ b'f4159d17552603b90912dba6fe5c604e8d0b8aa7'

- Fixes `bug 1691545`_ in which there was a significant increase in database
  connections because of the way connections to cell databases were being
  established. With this fix, objects related to database connections are
  cached in the API service and reused to prevent new connections being
  established for every communication with cell databases.

  .. _bug 1691545: https://bugs.launchpad.net/nova/+bug/1691545


.. _Release Notes_15.0.2_ocata-eol:

15.0.2
======

.. _Release Notes_15.0.2_ocata-eol_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'acb19160d4d348e29a21ad57c61c7369352c4d1c'

This release includes fixes for security vulnerabilities.


.. _Release Notes_15.0.2_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'acb19160d4d348e29a21ad57c61c7369352c4d1c'

- [CVE-2017-7214] Failed notification payload is dumped in logs with auth secrets

  * `Bug 1673569 <https://bugs.launchpad.net/nova/+bug/1673569>`_


.. _Release Notes_15.0.1_ocata-eol:

15.0.1
======

.. _Release Notes_15.0.1_ocata-eol_Prelude:

Prelude
-------

.. releasenotes/notes/ocata-15.0.1-fixes-d7f46a61a23d1566.yaml @ b'52666f40dbf2bfc2aa2109702503141fad7f4521'

The 15.0.1 Ocata release contains fixes for several high severity, high impact bugs. If you have not yet upgraded to 15.0.0, it is recommended to upgrade directly to 15.0.1.


.. _Release Notes_15.0.1_ocata-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/ocata-15.0.1-fixes-d7f46a61a23d1566.yaml @ b'52666f40dbf2bfc2aa2109702503141fad7f4521'

- There is a known regression in Ocata reported in `bug 1671648`_ where
  server build failures on a compute node are not retried on another compute
  node. The fix for this bug is being worked and will be provided shortly in
  a 15.0.2 release.

  .. _bug 1671648: https://launchpad.net/bugs/1671648


.. _Release Notes_15.0.1_ocata-eol_Critical Issues:

Critical Issues
---------------

.. releasenotes/notes/ocata-15.0.1-fixes-d7f46a61a23d1566.yaml @ b'52666f40dbf2bfc2aa2109702503141fad7f4521'

- `Bug 1670627`_ is fixed. This bug led to potential over-quota errors after
  several failed server build attempts, resulting in quota usage to reach the
  limit even though the servers were deleted.

  Unfortunately the ``nova-manage project quota_usage_refresh`` command will
  not reset the usages to fix this problem once encountered.

  If the project should not have any outstanding resource usage, then one
  possible workaround is to delete the existing quota usage for the project::

    ``nova quota-delete --tenant <tenant_id>``

  That will cleanup the ``project_user_quotas``, ``quota_usages`` and
  ``reservations`` tables for the given project in the ``nova`` database and
  reset the quota limits for the project back to the defaults defined in
  nova.conf.

  .. _Bug 1670627: https://launchpad.net/bugs/1670627


.. _Release Notes_15.0.1_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1670522-0a9f20e05e531c7a.yaml @ b'30e604f57faa8321679881bdf6113f9389e80271'

- Fixes `bug 1670522`_ which was a regression in the 15.0.0 Ocata release.
  For compute nodes running the libvirt driver with ``virt_type`` not set to
  "kvm" or "qemu", i.e. "xen", creating servers will fail by default if
  libvirt >= 1.3.3 and QEMU >= 2.7.0 without this fix.

  .. _bug 1670522: https://bugs.launchpad.net/nova/+bug/1670522

.. releasenotes/notes/ocata-15.0.1-fixes-d7f46a61a23d1566.yaml @ b'52666f40dbf2bfc2aa2109702503141fad7f4521'

- `Bug 1665263`_ is fixed. This was a regression where
  ``instance.delete.start`` and ``instance.delete.end`` notifications were
  not emitted when deleting an instance in ``ERROR`` state due to a failed
  build.

  .. _Bug 1665263: https://launchpad.net/bugs/1665263


.. _Release Notes_15.0.0_ocata-eol:

15.0.0
======

.. _Release Notes_15.0.0_ocata-eol_Prelude:

Prelude
-------

.. releasenotes/notes/ocata-use-neutron-by-default-7a836e65e1c3ccaf.yaml @ b'6627de4aa55110989b4b976ae794f3d8a3deb797'

Neutron is now the default configuration for new deployments.


.. releasenotes/notes/ocata_prelude-cfa8793d07f963e7.yaml @ b'9f1ffd665e20d705e9e4ff9613efc84f861fedf2'

The 15.0.0 release includes many new features and bug fixes. It is
difficult to cover all the changes that have been introduced. Please at
least read the upgrade section which describes the required actions to
upgrade your cloud from 14.0.0 (Newton) to 15.0.0 (Ocata).

That said, a few major changes are worth mentioning. This is not an
exhaustive list:

- The latest API microversion supported for Ocata is v2.42. Details on
  REST API microversions added since the 14.0.0 Newton release can be found
  in the `REST API Version History`_ page.
- The Nova FilterScheduler driver is now able to make scheduling
  decisions based on the new Placement RESTful API endpoint that becomes
  mandatory in Ocata. Accordingly, the compute nodes will
  refuse to start if you do not amend the configuration to add the
  ``[placement]`` section so they can provide their resource usage.
  For the moment, only CPU, RAM and disk resource usage are verified by
  the Placement API, but we plan to add more resource classes in the
  next release. You will find further details in the features and
  upgrade sections below, and the `Placement API`_ page.
- Ocata contains a lot of new CellsV2 functions, but not all of it is
  fully ready for production. All deployments must set up their existing
  nodes as a cell, with database connection and MQ transport_url config
  items matching that cell. In a subsequent release, additional cells
  will be fully supported, as will a migration path for CellsV1 users.
  By default, an Ocata deployment now needs to configure at least one new
  "Cell V2" (not to be confused with the first version of cells). In
  Newton, it was possible to deploy a single cell V2 and schedule on it
  but this was optional. Now in Ocata, single CellsV2 deployments are
  mandatory.
  More details to be found when reading the release notes below.
- There is a new nova-status command that gives operators a better
  view of their cloud. In particular, a new subcommand called "upgrade"
  allows operators to run a pre-flight check on their deployment before
  upgrading. This helps them to proactively identify potential upgrade
  issues that could occur.

.. _REST API Version History: http://docs.openstack.org/developer/nova/api_microversion_history.html
.. _Placement API: http://docs.openstack.org/developer/nova/placement.html


.. _Release Notes_15.0.0_ocata-eol_New Features:

New Features
------------

.. releasenotes/notes/add-ironic-configdrive-network-metadata-4e8f06dfd6d6d6d4.yaml @ b'8856ad31a01b044c79a2e4d488fab7cc9e576ca3'

- Updates the network metadata that is passed to configdrive by the Ironic
  virt driver. The metadata now includes network information about port
  groups and their associated ports. It will be used to configure port
  groups on the baremetal instance side.

.. releasenotes/notes/add-numa-hugepage-support-for-aarch64-14279c307e44b147.yaml @ b'50e0106d35ec1a3204c18f3912b0dc6cf6632305'

- Adding aarch64 to the list of supported architectures for NUMA and hugepage features. This requires libvirt>=1.2.7 for NUMA, libvirt>=1.2.8 for hugepage and qemu v2.1.0 for both.

.. releasenotes/notes/add-osprofiler-support-b04f1e4cfa550440.yaml @ b'ecc8de8d6cccb06d7f4c8ecc144d37612ae1e9cc'

- OSProfiler support was added. This cross-project profiling library allows to trace various OpenStack requests through all OpenStack services that support it. To initiate OpenStack request tracing ``--profile <HMAC_KEY>`` option needs to be added to the CLI command. This key needs to present one of the secret keys defined in nova.conf configuration file with ``hmac_keys`` option under the ``[profiler]`` configuration section. To enable or disable Nova profiling the appropriate ``enabled`` option under the same section needs to be set either to ``True`` or ``False``. By default Nova will trace all API and RPC requests, but there is an opportunity to trace DB requests as well. For this purpose ``trace_sqlalchemy`` option needs to be set to ``True``. As a prerequisite OSProfiler library and its storage backend needs to be installed to the environment. If so (and if profiling is enabled in nova.conf) the trace can be generated via following command, for instance - ``$ nova --profile SECRET_KEY boot --image <image> --flavor <flavor> <name>``. At the end of output there will be message with <trace_id>, and to plot nice HTML graphs the following command should be used - ``$ osprofiler trace show <trace_id> --html --out result.html``

.. releasenotes/notes/add-swap-volume-notifications-bb7e14230fccfd6e.yaml @ b'70b01c9c62c2c5467de7b6c119c3b49b603c40ad'

- The following versioned swap volume notifications have been added
  in the compute manager:

  * instance.volume_swap.start
  * instance.volume_swap.end
  * instance.volume_swap.error

.. releasenotes/notes/archive-all-db-aadf2ce0394c24fa.yaml @ b'6f00d3be95edcbcd6252af5ee42fb8f3b1dfd7d0'

- Support for archiving all deleted rows from the database has
  been added to the ``nova-manage db archive_deleted_rows``
  command. The ``--until-complete`` option will continuously
  run the process until no more rows are available for archiving.

.. releasenotes/notes/bp-ephemeral-disk-ploop-a9b3af1f36ae42ed.yaml @ b'b1d575f2ad1c2accc8e54a2ea631ef21ac86ad97'

- Virtuozzo hypervisor now supports ephemeral disks for containers.

.. releasenotes/notes/bp-flavor-notifications-7b3a56509c3f138d.yaml @ b'e05f678e0a4d314f38780cd5e3c5b4def634df25'

- Support versioned notifications for flavor operations like create, delete, update access and update extra_specs.

.. releasenotes/notes/bp-hyperv-storage-qos-d559634e5df0f1d4.yaml @ b'802a0afa57fed3a098743abe7c0208416ad32a00'

- The Hyper-V driver now supports the following quota flavor extra
  specs, allowing to specify IO limits applied for each of the
  instance local disks, individually.

  - quota:disk_total_bytes_sec
  - quota:disk_total_iops_sec - those are normalized IOPS, thus each
    IO request is accounted for as 1 normalized IO if the size of the
    request is less than or equal to a predefined base size (8KB).

  Also, the following Cinder front-end QoS specs are now supported
  for SMB Cinder backends:

  - total_bytes_sec
  - total_iops_sec - normalized IOPS

.. releasenotes/notes/bp-hyperv-use-os-brick-bf576a5bc97f0ea2.yaml @ b'758a32f7cef6c675b35c04dd8d276c918be188dd'

- The Hyper-V driver now uses os-brick for volume related
  operations, introducing the following new features:

  - Attaching volumes over fibre channel on a passthrough
    basis.
  - Improved iSCSI MPIO support, by connecting to multiple
    iSCSI targets/portals when available and allowing using
    a predefined list of initiator HBAs.

.. releasenotes/notes/bp-inject-nmi-ironic-be5405065b6dd890.yaml @ b'b1556c2009f5388c6a53341a4601c783f1b0666a'

- Adds trigger crash dump support to ironic virt driver. This feature requires the Ironic service to support API version 1.29 or later. It also requires python-ironicclient >= 1.11.0.

.. releasenotes/notes/bp-soft-reboot-poweroff-203e0f33e3b8042e.yaml @ b'f3c774a96b963d66c5397069d12cf9eb2dcac4da'

- Adds soft reboot support to Ironic virt driver. If hardware driver in Ironic doesn't support soft reboot, hard reboot is tried. This feature requires the Ironic service to support API version 1.27 or later. It also requires python-ironicclient >= 1.10.0.

.. releasenotes/notes/bp-soft-reboot-poweroff-6215d216a6aedafa.yaml @ b'cf02e5161d8547395c40334ac8be43e377472867'

- Adds soft power off support to Ironic virt driver. This feature requires the Ironic service to support API version 1.27 or later. It also requires python-ironicclient >= 1.10.0.

.. releasenotes/notes/bp-virtuozzo-instance-admin-password-8278cad73f3be98d.yaml @ b'4445d4847111be4bfb7c1f3cea316d664add4dd6'

- Virtuozzo hypervisor now supports libvirt callback to set admin password. Requires libvirt>=2.0.0.

.. releasenotes/notes/bp-xenapi-vif-hotplug-2a2b913c49123fe0.yaml @ b'5dedd0b22a2ab929d65e91ae6df1ffa2feece5f1'

- The XenServer compute driver now supports hot-plugging virtual network interfaces.

.. releasenotes/notes/bug-1636157-2148ea3675969a5d.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- The same policy rule (os_compute_api:os-server-groups)
  was being used for all actions (show, index, delete, create)
  for server_groups REST APIs. It was thus impossible to provide
  different RBAC for specific actions based on roles. To address
  this changes were made to have separate policy rules for each
  action. The original rule (os_compute_api:os-server-groups) is
  left unchanged for backward compatibility.

.. releasenotes/notes/deprecate_live_migration_uri-8ae6656664db5ba0.yaml @ b'df334b4f414b8c341709df37ca10065d3b50fcef'

- The libvirt driver now has a ``live_migration_scheme`` configuration
  option which should be used where the ``live_migration_uri`` would
  previously have been configured with non-default scheme.

.. releasenotes/notes/hyper-v-ovs-vif-348fca68db4918fe.yaml @ b'07b6580a1648a860eefb5a949cb443c2a335a89a'

- The nova Hyper-V driver can now plug OVS VIFs. This means that neutron-ovs-agent can be used as an L2 agent instead of neutron-hyperv-agent. In order to plug OVS VIFs, the configuration option "vswitch_name" from the "hyperv" section must be set to the vSwitch which has the OVS extension enabled. Hot-plugging is only supported on Windows / Hyper-V Server 2016 + Generation 2 VMs. Older Hyper-V versions only support attaching vNICs while the VM is turned off.

.. releasenotes/notes/hyper-v-pci-passthrough-babf104d6bc2baa6.yaml @ b'9d6f9e9cd5dcb1dc9205ace9476dcb3a404ac497'

- The nova Hyper-V driver now supports adding PCI passthrough devices to
  Hyper-V instances (discrete device assignment). This feature has been
  introduced in Windows / Hyper-V Server 2016 and offers the possibility to
  attach some of the host's PCI devices (e.g.: GPU devices) directly to
  Hyper-V instances.
  In order to benefit from this feature, Hyper-V compute nodes must support
  SR-IOV and must have assignable PCI devices. This can easily be checked by
  running the following powershell commands::

      Start-BitsTransfer https://raw.githubusercontent.com/Microsoft/Virtualization-Documentation/master/hyperv-samples/benarm-powershell/DDA/survey-dda.ps1
      .\survey-dda.ps1

  The script above will print a list of assignable PCI devices available on
  the host, and if the host supports SR-IOV.

  If the host supports this feature and it has at least an assignable PCI
  device, the host must be configured to allow those PCI devices to be
  assigned to VMs. For information on how to do this, follow this guide [1].

  After the compute nodes have been configured, the nova-api, nova-scheduler,
  and the nova-compute services will have to be configured next [2].

  [1] https://blogs.technet.microsoft.com/heyscriptingguy/2016/07/14/passing-through-devices-to-hyper-v-vms-by-using-discrete-device-assignment/
  [2] http://docs.openstack.org/admin-guide/compute-pci-passthrough.html

.. releasenotes/notes/hyper-v-set-boot-order-1e76b08ca6783add.yaml @ b'd68c04299aa2c04aea16e881d93076236cc64d7b'

- Added boot order support in the Hyper-V driver.
  The HyperVDriver can now set the requested boot order for instances that are
  Generation 2 VMs (the given image has the property "hw_machine_type=hyperv-gen2").
  For Generation 1 VMs, the spawned VM's boot order is changed only if the given
  image is an ISO, booting from ISO first.

.. releasenotes/notes/hyper-v-vnuma-support-ffedfaadac91bbac.yaml @ b'2195e4d68486ed70e55d0b5f038b13bd35e3271c'

- The nova Hyper-V driver now supports symmetric NUMA topologies. This means that all the NUMA nodes in the NUMA topology must have the same amount of vCPUs and memory. It can easily be requested by having the flavor extra_spec "hw:numa_nodes", or the image property "hw_numa_nodes". An instance with NUMA topology cannot have dynamic memory enabled. Thus, if an instance requires a NUMA topology, it will be spawned without dynamic memory, regardless of the value set in the "dynamic_memory_ratio" config option in the compute node's "nova.conf" file. In order to benefit from this feature, the host's NUMA spanning must be disabled. Hyper-V does not guarantee CPU pinning, thus, the nova Hyper-V driver will not spawn instances with the flavor extra_spec "hw:cpu_policy" or image property "hw_cpu_policy" set to "dedicated".

.. releasenotes/notes/hyperv-uefi-secure-boot-a2a617ac2c313afd.yaml @ b'29dab997b4e7039cbf036edb5db35b6d18e6b6ca'

- Added support for Hyper-V VMs with UEFI Secure Boot enabled.
  In order to create such VMs, there are a couple of things to consider:

  * Images should be prepared for Generation 2 VMs. The image property
    "hw_machine_type=hyperv-gen2" is mandatory.
  * The guest OS type must be specified in order to properly spawn the VMs.
    It can be specified through the image property "os_type", and the
    acceptable values are "windows" or "linux".
  * The UEFI Secure Boot feature can be requested through the image property
    "os_secure_boot" (acceptable values: "disabled", "optional", "required")
    or flavor extra spec "os:secure_boot" (acceptable values: "disabled",
    "required"). The flavor extra spec will take precedence. If the image
    property and the flavor extra spec values are conflicting, then an
    exception is raised.
  * This feature is supported on Windows / Hyper-V Server 2012 R2 for
    Windows guests, and Windows / Hyper-V Server 2016 for both
    Windows and Linux guests.

.. releasenotes/notes/introduce-encryption-provider-constants-a7cd0ce58da2bae8.yaml @ b'5593d74435b441ef38b301b86b5b0642f9b0b85f'

- Encryption provider constants have been introduced detailing the supported
  encryption formats such as LUKs along with their associated in-tree
  provider implementations. These constants should now be used to identify an
  encryption provider implementation for a given encryption format.

.. releasenotes/notes/ironic-serial-console-support-82632bd4db6d1fda.yaml @ b'c9a64996ecc317b2c05d688e0f5d31c37122ca01'

- Adds serial console support to Ironic driver. Nova now supports serial console to Ironic bare metals for Ironic ``socat`` console driver. In order to use this feature, serial console must be configured in Nova and the Ironic ``socat`` console driver must be used and configured in Ironic. Ironic serial console configuration is documented in http://docs.openstack.org/developer/ironic/deploy/console.html.

.. releasenotes/notes/live-migration-vz-3236af37a522e411.yaml @ b'd8d813800ce5799e42eeb9937553a29e725be4b1'

- Live migration is supported for both Virtuozzo containers and virtual machines when using virt_type=parallels.

.. releasenotes/notes/notification-transformation-ocata-ec42281e9df6019c.yaml @ b'4f05f06add8da51d149ee035e971b77c5fc02456'

-
  The following legacy notifications have been transformed to
  a new versioned payload:

  * aggregate.create
  * aggregate.delete
  * instance.create
  * instance.finish_resize
  * instance.power_off
  * instance.resume
  * instance.shelve_offload
  * instance.shutdown
  * instance.snapshot
  * instance.unpause
  * instance.unshelve

  Every versioned notification has a sample file stored under
  doc/notification_samples directory. Consult
  http://docs.openstack.org/developer/nova/notifications.html for more information.

.. releasenotes/notes/nova-status-upgrade-check-8190e6061680ff1f.yaml @ b'790313c0a065cda281e52be41d46b705a116eafa'

- A new ``nova-status upgrade check`` CLI is provided for checking the
  readiness of a deployment when preparing to upgrade to the latest release.
  The tool is written to handle both fresh installs and upgrades from an
  earlier release, for example upgrading from the 14.0.3 Newton release.
  There can be multiple checks performed with varying degrees of success.
  More details on the command and how to interpret results are in the
  `nova-status man page`_.

  .. _nova-status man page: http://docs.openstack.org/developer/nova/man/nova-status.html

.. releasenotes/notes/ocata-cellsv2-support-4b3b5e70e76bc756.yaml @ b'f6a419a49b891ec642a8422468eb3a1c719aaffb'

- All deployments will function as a single-cell
  environment. Multiple v2 cells are technically possible, but should
  only be used for testing as many other things will not work across
  cell boundaries yet. For details on cells v2 and the setup required for
  Nova with cells v2, see the cells documentation. [1]_

  .. [1] http://docs.openstack.org/developer/nova/cells.html

.. releasenotes/notes/pagination-for-usage-a313397f9a7e9a70.yaml @ b'83404013cb53aef16b97b5616c0627c50af76ac8'

- Added microversion v2.40 which introduces pagination support for usage
  with the help of new optional parameters 'limit' and 'marker'. If 'limit'
  isn't provided, it will default to the configurable max limit which is
  currently 1000.

  ::

      /os-simple-tenant-usage?limit={limit}&marker={instance_uuid}
      /os-simple-tenant-usage/{tenant}?limit={limit}&marker={instance_uuid}

  Older microversions will not accept these new paging query parameters,
  but they will start to silently limit by the max limit to encourage the
  adoption of this new microversion, and circumvent the existing possibility
  DoS-like usage requests on systems with thousands of instances.

.. releasenotes/notes/pci-passthrough-whitelist-regex-support-5004c5db4fbe09c8.yaml @ b'521cd72b1013278aa1cdadbe698d543be9683f7e'

- Enhance pci.passthrough_whitelist to support regular expression syntax. The
  'address' field can be regular expression syntax. The old
  pci.passthrough_whitelist, glob syntax, is still valid config.

.. releasenotes/notes/placement-api-member-of-d8a08d0d0c5700d7.yaml @ b'ea5d0576cce5574272c7d8d3acb2b6dbeaa8be50'

- A new Placement API microversion 1.3 is added with support for filtering
  the list of resource providers to include only those resource providers
  which are members of any of the aggregates listed by uuid in the ``member_of``
  query parameter. The parameter is used when making a
  ``GET /resource_providers`` request. The value of the parameter uses the
  ``in:`` syntax to provide a list of aggregate uuids as follows::

      /resource_providers?member_of=in:09c931b0-c0d7-4e80-8e01-9e6511db8259,f8ab4fa2-804f-402e-b675-7918bd04b173

  If other filtering query parameters are present, the results are a boolean
  AND of all the filters.

.. releasenotes/notes/placement-rest-api-filter-providers-by-resources-0ab51c9766fe654f.yaml @ b'a5dc7f1a11b14dcf9602de5dcd761b7ccce81711'

- A new Placement API microversion 1.4 is added. Users may now query the
  Placement REST API for resource providers that have the ability to meet a
  set of requested resource amounts. The ``GET /resource_providers`` API call
  can have a "resources" query string parameter supplied that indicates the
  requested amounts of various resources that a provider must have the
  capacity to serve. The "resources" query string parameter takes the form:

  ``?resources=$RESOURCE_CLASS_NAME:$AMOUNT,$RESOURCE_CLASS_NAME:$AMOUNT``

  For instance, if the user wishes to see resource providers that can service
  a request for 2 vCPUs, 1024 MB of RAM and 50 GB of disk space, the user can
  issue a request of::

  ``GET /resource_providers?resources=VCPU:2,MEMORY_MB:1024,DISK_GB:50``

  The placement API is only available to admin users.

.. releasenotes/notes/placement-rest-custom-resource-classes-a3f2175772983b0a.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- A new administrator-only resource endpoint was added to the OpenStack
  Placement REST API for managing custom resource classes. Custom resource
  classes are specific to a deployment and represent types of quantitative
  resources that are not interoperable between OpenStack clouds. See the
  `Placement REST API Version History`_ documentation for usage details.

  .. _Placement REST API Version History: http://docs.openstack.org/developer/nova/placement.html#id2

.. releasenotes/notes/resource_providers_scheduler_db_filters-16b2ed3da00c51dd.yaml @ b'4660333d0d97d8e00cf290ea1d4ed932f5edc1dc'

- nova-scheduler process is now calling the placement API in order to get a list of valid destinations before calling the filters. That works only if all your compute nodes are fully upgraded to Ocata. If some nodes are not upgraded, the scheduler will still lookup from the DB instead which is less performant.

.. releasenotes/notes/return-uuid-attribute-for-aggregates-70d9f733f86fb1a3.yaml @ b'03c2776e49e12ff7f877480a041626a654533f27'

- A new 2.41 microversion was added to the Compute API. Users specifying this microversion will now see the 'uuid' attribute of aggregates when calling the ``os-aggregates`` REST API endpoint.

.. releasenotes/notes/scheduler-can-discover-hosts-4b799cbd14dbc7dc.yaml @ b'9eb7bcea05ce2447496f6561caa1ae46b800f85d'

- As new hosts are added to Nova, the ``nova-manage cell_v2 discover_hosts`` command must be run in order to map them into their cell. For deployments with proper automation, this is a trivial extra step in that process. However, for smaller or non-automated deployments, there is a new configuration variable for the scheduler process which will perform this discovery periodically. By setting ``scheduler.discover_hosts_in_cells_interval`` to a positive value, the scheduler will handle this for you. Note that this process involves listing all hosts in all cells, and is likely to be too heavyweight for large deployments to run all the time.

.. releasenotes/notes/sriov-pf-passthrough-neutron-port-vlan-7d19df7ac6e2730a.yaml @ b'1a0778d280658a1da08b4cd903b8dbb6fbbd8d91'

- VLAN tags associated with instance network interfaces are now exposed via
  the metadata API and instance config drives and can be consumed by the
  instance. This is an extension of the device tagging mechanism added in
  past releases. This is useful for instances utilizing SR-IOV physical
  functions (PFs). The VLAN configuration for the guest's virtual interfaces
  associated with these devices cannot be configured inside the guest OS from
  the host, but nonetheless must be configured with the VLAN tags of the
  device to ensure packet delivery. This feature makes this possible.

  .. note:: VLAN tags are currently only supported via the Libvirt driver.

.. releasenotes/notes/validate-expired-user-tokens-57a265cb4ee4ba6f.yaml @ b'596e8de5ebd261b2b6610830641d23728b006f53'

- Added support for Keystone middleware feature where if service token is sent along with the user token, then it will ignore the expiration of user token. This helps deal with issues of user tokens expiring during long running operations, such as live-migration where nova tries to access Cinder and Neutron at the end of the operation using the user token that has expired. In order to use this functionality a service user needs to be created. Add service user configurations in ``nova.conf`` under ``service_user`` group and set ``send_service_user_token`` flag to ``True``. The minimum Keytone API version 3.8 and Keystone middleware version 4.12.0 is required to use this functionality. This only currently works with Nova - Cinder and Nova - Neutron API interactions.

.. releasenotes/notes/vendordata-reboot-cache-boot-roles-6051fabcd4981928.yaml @ b'6d8b58dc6f1cbda8d664b3487674f87049491c74'

- The vendordata metadata system now caches boot time roles.  Some external
  vendordata services want to provide metadata based on the role of the user
  who started the instance. It would be confusing if the metadata returned
  changed later if the role of the user changed, so we cache the boot time
  roles and then pass those to the external vendordata service.

.. releasenotes/notes/vendordata-reboot-hard-failure-42beeb1044680a50.yaml @ b'5ca61e4534075edcbfcf87c1bfa8a3a53be705b1'

- The vendordata metadata system now supports a hard failure mode. This can
  be enabled using the ``api.vendordata_dynamic_failure_fatal`` configuration
  option.  When enabled, an instance will fail to start if the instance
  cannot fetch dynamic vendordata.

.. releasenotes/notes/verbose-online-migrations-bd6f57e43328d554.yaml @ b'7e71a4e0a21ae2df92396edadd921ce1467a25c4'

- The nova-manage online_data_migrations command now prints a tabular summary of completed and remaining records. The goal here is to get all your numbers to zero. The previous execution return code behavior is retained for scripting.

.. releasenotes/notes/vif-vrouter-multiqueue-077785e1a2d242a0.yaml @ b'146accfada6429e91282a4de88188b016367421b'

- When using libvirt driver, vrouter VIFs (OpenContrail) now supports multiqueue mode, which allows to scale network performance across number of vCPUs. To use this feature one needs to create instance with more than 1 vCPU from an image with ``hw_vif_multiqueue_enabled`` property set to ``true``.

.. releasenotes/notes/virtuozzo_vif_types-6e50217b295a1589.yaml @ b'e5e4dfcfdb918b57dcbd3e3cfb171e3b70e3c701'

- A list of valid vif models is extended for Virtuozzo hypervisor (virt_type=parallels) with VIRTIO, RTL8139 and E1000 models.


.. _Release Notes_15.0.0_ocata-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bp-flavor-notifications-7b3a56509c3f138d.yaml @ b'e05f678e0a4d314f38780cd5e3c5b4def634df25'

- Flavor.projects (access) will not be present in the instance versioned
  notifications since notifications currently do not lazy-load fields. This
  limitation is being tracked with `bug 1653221`_.

  .. _bug 1653221: https://bugs.launchpad.net/nova/+bug/1653221

.. releasenotes/notes/bug-1661258-ee202843157f6a27.yaml @ b'965fffc09d6fffba7918117e170d5799c69fe99b'

- Ironic nodes that were deleted from ironic's database during Newton
  may result in orphaned resource providers causing incorrect scheduling
  decisions, leading to a reschedule. If this happens, the orphaned
  resource providers will need to be identified and removed.

  See also https://bugs.launchpad.net/nova/+bug/1661258

.. releasenotes/notes/deprecate-live-migration-progress-timeout-b4640047dc5c8eed.yaml @ b'679d78ab2baaf934dc6912096882613d55f2ea0c'

- The live-migration progress timeout controlled by the configuration option
  ``[libvirt]/live_migration_progress_timeout`` has been discovered to
  frequently cause live-migrations to fail with a progress timeout error,
  even though the live-migration is still making good progress.
  To minimize problems caused by these checks we have changed the default
  to 0, which means do not trigger a timeout.
  To modify when a live-migration will fail with a timeout error, please now
  look at ``[libvirt]/live_migration_completion_timeout`` and
  ``[libvirt]/live_migration_downtime``.

.. releasenotes/notes/libvirt-script-with-empty-path-2b49caa68b05278d.yaml @ b'847952927c60ed0577bc835adf607ed7b8f15240'

- When generating Libvirt XML to attach network interfaces for the ``tap``,
  ``ivs``, ``iovisor``, ``midonet``, and ``vrouter`` virtual interface types Nova
  previously generated an empty path attribute to the script element
  (``<script path=''/>``\) of the interface.

  As of Libvirt 1.3.3 (`commit`_) and later Libvirt no longer accepts an
  empty path attribute to the script element of the interface. Notably this
  includes Libvirt 2.0.0 as provided with RHEL 7.3 and CentOS 7.3-1611. The
  creation of virtual machines with offending interface definitions on a host
  with Libvirt 1.3.3 or later will result in an error "libvirtError: Cannot
  find '' in path: No such file or directory".

  Additionally, where virtual machines already exist that were created using
  earlier versions of Libvirt interactions with these virtual machines via
  Nova or other utilities (e.g. ``virsh``) may result in similar errors.

  To mitigate this issue Nova no longer generates an empty path attribute
  to the script element when defining an interface. This resolves the issue
  with regards to virtual machine creation. To resolve the issue with regards
  to existing virtual machines a change to Libvirt is required, this is being
  tracked in `Bugzilla 1412834`_

  .. _commit: https://libvirt.org/git/?p=libvirt.git;a=commit;h=9c17d665fdc5f0ab74500a14c30627014c11b2c0
  .. _Bugzilla 1412834: https://bugzilla.redhat.com/show_bug.cgi?id=1412834

.. releasenotes/notes/ocata-cellsv2-support-4b3b5e70e76bc756.yaml @ b'f6a419a49b891ec642a8422468eb3a1c719aaffb'

- Once fully upgraded, if you create multiple real cells with hosts, the scheduler will utilize them, but those instances will likely be unusable because not all API functions are cells-aware yet.

.. releasenotes/notes/ocata-cellsv2-support-4b3b5e70e76bc756.yaml @ b'f6a419a49b891ec642a8422468eb3a1c719aaffb'

- Listing instances across multiple cells with a sort order will result in barber-pole sorting, striped across the cell boundaries.


.. _Release Notes_15.0.0_ocata-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-api-config-to-api-group-af20a57a9e3e1b85.yaml @ b'b7b282ed084c74b36369ed915c92103c1595c7fb'

- API configuration options have been moved to the 'api' group. They
  should no longer be included in the 'DEFAULT' group. Options affected by
  this change:

  * ``auth_strategy``
  * ``use_forwarded_for``
  * ``config_drive_skip_versions``
  * ``vendordata_providers``
  * ``vendordata_dynamic_targets``
  * ``vendordata_dynamic_ssl_certfile``
  * ``vendordata_dynamic_connect_timeout``
  * ``vendordata_dynamic_read_timeout``
  * ``metadata_cache_expiration``
  * ``vendordata_jsonfile_path``
  * ``max_limit`` (was ``osapi_max_limit``)
  * ``compute_link_prefix`` (was ``osapi_compute_link_prefix``)
  * ``glance_link_prefix`` (was ``osapi_glance_link_prefix``)
  * ``allow_instance_snapshots``
  * ``hide_server_address_states`` (was ``osapi_hide_server_address_states``)
  * ``fping_path``
  * ``use_neutron_default_nets``
  * ``neutron_default_tenant_id``
  * ``enable_instance_password``

.. releasenotes/notes/add-consoleauth-config-to-consoleauth-group-aaa4d9ab8db7c78a.yaml @ b'2640f1f47e38846db49ea9636b9260392f724026'

- The ``console_token_ttl`` configuration option has been moved to the
  ``consoleauth`` group and renamed ``token_ttl``. It should no longer be
  included in the ``DEFAULT`` group.

.. releasenotes/notes/add-cors-to-versions-pipeline-56277ca66e796569.yaml @ b'87b9c2b9168553b68fffbdc2f499469a61335993'

- To allow access to the versions REST API from diverse origins, CORS support has been added to the 'oscomputeversions' pipeline in '/etc/nova/api-paste.ini'. Existing deployments that wish to enable support should add the 'cors' filter at the start of the 'oscomputeversions' pipeline.

.. releasenotes/notes/add-ivs-filter-to-compute-093734c1c5348e99.yaml @ b'58de26288cc51af8caaaafa86588b2e488aa0ca4'

- The ivs-ctl command has been added to the rootwrap filters in compute.filters. Deployments needing support for BigSwitch no longer need to add the filters manually nor include network.filters at installation.

.. releasenotes/notes/add-pci-config-to-pci-group-5648cc0f307f24f8.yaml @ b'4e5ed1c48916c2a76e4d7a1e640187dd3e555dc8'

- All pci configuration options have been added to the 'pci' group. They
  should no longer be included in the 'DEFAULT' group. These options are as
  below:

  - pci_alias (now pci.alias)
  - pci_passthrough_whitelist (now pci.passthrough_whitelist)

.. releasenotes/notes/add-scheduler-config-to-scheduler-group-c83bc770e67ac115.yaml @ b'7d0381c91a6ba8a45ae6527f046f382166eb158d'

- All general scheduler configuration options have been added to the
  ``scheduler`` group.

  - ``scheduler_driver`` (now ``driver``)
  - ``scheduler_host_manager`` (now ``host_manager``)
  - ``scheduler_driver_task_period`` (now ``periodic_task_interval``)
  - ``scheduler_max_attempts`` (now ``max_attempts``)

  In addition, all filter scheduler configuration options have been added to
  the ``filter_scheduler`` group.

  - ``scheduler_host_subset_size`` (now ``host_subset_size``)
  - ``scheduler_max_instances_per_host`` (now ``max_instances_per_host``)
  - ``scheduler_tracks_instance_changes`` (now ``track_instance_changes``)
  - ``scheduler_available_filters`` (now ``available_filters``)
  - ``scheduler_default_filters`` (now ``enabled_filters``)
  - ``baremetal_scheduler_default_filters`` (now
    ``baremetal_enabled_filters``)
  - ``scheduler_use_baremetal_filters`` (now ``use_baremetal_filters``)
  - ``scheduler_weight_classes`` (now ``weight_classes``)
  - ``ram_weight_multiplier``
  - ``disk_weight_multipler``
  - ``io_ops_weight_multipler``
  - ``soft_affinity_weight_multiplier``
  - ``soft_anti_affinity_weight_multiplier``
  - ``isolated_images``
  - ``isolated_hosts``
  - ``restrict_isolated_hosts_to_isolated_images``
  - ``aggregate_image_properties_isolation_namespace``
  - ``aggregate_image_properties_isolation_separator``

  These options should no longer be included in the ``DEFAULT`` group.

.. releasenotes/notes/add-whitelist-for-server-list-filter-sort-params-2ae766d03ba895e5.yaml @ b'd6691d17934b92046670bc9bb0f47eb3df6f3861'

- The filter and sort query parameters for server list API are
  now limited according to whitelists. The whitelists are different
  for admin and non-admin users.

  **Filtering**

  The whitelist for REST API filters for admin users:

  - access_ip_v4
  - access_ip_v6
  - all_tenants
  - auto_disk_config
  - availability_zone
  - config_drive
  - changes-since
  - created_at
  - deleted
  - description
  - display_description
  - display_name
  - flavor
  - host
  - hostname
  - image
  - image_ref
  - ip
  - ip6
  - kernel_id
  - key_name
  - launch_index
  - launched_at
  - limit
  - locked_by
  - marker
  - name
  - node
  - not-tags          (available in 2.26+)
  - not-tags-any      (available in 2.26+)
  - power_state
  - progress
  - project_id
  - ramdisk_id
  - reservation_id
  - root_device_name
  - sort_dir
  - sort_key
  - status
  - tags              (available in 2.26+)
  - tags-any          (available in 2.26+)
  - task_state
  - tenant_id
  - terminated_at
  - user_id
  - uuid
  - vm_state

  For non-admin users, there is a whitelist for filters already. That
  whitelist is unchanged.

  **Sorting**

  The whitelist for sort keys for admin users:

  - access_ip_v4
  - access_ip_v6
  - auto_disk_config
  - availability_zone
  - config_drive
  - created_at
  - display_description
  - display_name
  - host
  - hostname
  - image_ref
  - instance_type_id
  - kernel_id
  - key_name
  - launch_index
  - launched_at
  - locked_by
  - node
  - power_state
  - progress
  - project_id
  - ramdisk_id
  - root_device_name
  - task_state
  - terminated_at
  - updated_at
  - user_id
  - uuid
  - vm_state

  For non-admin users, the sort key ``host`` and ``node`` will be excluded.

  **Other**

  ``HTTP Bad Request 400`` will be returned for the filters/sort keys which
  are on joined tables or internal data model attributes. They would
  previously cause a ``HTTP Server Internal Error 500``, namely:

  - block_device_mapping
  - info_cache
  - metadata
  - pci_devices
  - security_groups
  - services
  - system_metadata

  In order to maintain backward compatibility, filter and sort parameters
  which are not mapped to the REST API ``servers`` resource representation are
  ignored.

.. releasenotes/notes/bug-1604116-87a823c3c165d057.yaml @ b'fcf2a644fbe6efc2bfd2810add36a099cadd959e'

- The three configuration options ``cpu_allocation_ratio``, ``ram_allocation_ratio`` and ``disk_allocation_ratio`` for the nova compute are now checked against negative values. If any of these three options is set to negative value then nova compute service will fail to start.

.. releasenotes/notes/deprecate-xenserver-vif-driver-option-12eb279c0c93c157.yaml @ b'babdb32beabb5e37e802a7b147f3649254f4283d'

- The default value for the ``[xenserver]/vif_driver`` configuration option
  has been changed to ``nova.virt.xenapi.vif.XenAPIOpenVswitchDriver`` to
  match the default configuration of ``[DEFAULT]/use_neutron=True``.

.. releasenotes/notes/flavor_hw_watchdog_action-512d79155c91cb84.yaml @ b'fa4ad0a2fef231e690059270d5b7070809b52a3e'

- Support for **hw_watchdog_action** as a flavor extra spec has been removed.
  The valid flavor extra spec is **hw:watchdog_action** and the image
  property, which takes precedence, is **hw_watchdog_action**.

.. releasenotes/notes/ironic-virt-driver-switch-to-vif-attach-detach-cc8583c604510f95.yaml @ b'c7b46c4778acdb05468b6cab4f3111b298609ed4'

- The Ironic driver now requires python-ironicclient>=1.9.0, and requires Ironic service to support API version 1.28 or higher. As usual, Ironic should be upgraded before Nova for a smooth upgrade process.

.. releasenotes/notes/minimum_vc_version-0695a79dc1df3caa.yaml @ b'2851ceaed3010c19f42e308be637b952edab092a'

- As of Ocata, the minimum version of VMware vCenter that nova compute will interoperate with will be 5.1.0. Deployments using older versions of vCenter should upgrade. Running with vCenter version less than 5.5.0 is also now deprecated and 5.5.0 will become the minimum version in the 16.0.0 Pike release of Nova.

.. releasenotes/notes/move-console-opt-to-console-group-de693ac26bc9b090.yaml @ b'ffcdb42ba17dadae5074ffb7315201410ec18eb7'

- ``console_public_hostname`` console options under the ``DEFAULT`` group
  have been moved to the ``xenserver`` group.

.. releasenotes/notes/move-notifications-opts-to-notifications-group-7dc9e76673472b8b.yaml @ b'c5cb7e459c04b54687c2373b44bf8de7ff02b584'

- Following Notifications related configuration options have been moved from
  the ``DEFAULT`` group to the ``notifications`` group:

  - ``notify_on_state_change``
  - ``notify_on_api_faults`` (was ``notify_api_faults``)
  - ``default_level`` (was ``default_notification_level``)
  - ``default_publisher_id``
  - ``notification_format``

.. releasenotes/notes/ocata-bug-1635008-rbd-vol-auth-83277b02ea87e16e.yaml @ b'b89efa3ef611a1932df0c2d6e6f30315b5111a57'

- When making connections to Ceph-backed volumes via the Libvirt driver, the
  auth values (rbd_user, rbd_secret_uuid) are now pulled from the backing
  cinder.conf rather than nova.conf. The nova.conf values are only used if
  set and the cinder.conf values are not set, but this fallback support is
  considered accidental and will be removed in the Nova 16.0.0 Pike release.
  See the Ceph documentation for `configuring Cinder`_ for RBD auth.

  .. _configuring Cinder: http://docs.ceph.com/docs/master/rbd/rbd-openstack/#configuring-cinder

.. releasenotes/notes/ocata-drop-cinder-v1-support-e383bc3623dbdb21.yaml @ b'84f5c6165bc94690d299ed4d025e421a651d1bb5'

- Nova no longer supports the deprecated Cinder v1 API.

.. releasenotes/notes/ocata-requires-cellv2-96bd243be874d77f.yaml @ b'5b44737e0c4627b796cfcf09bff5008ae06a95ff'

- Ocata requires that your deployment have created the cell and host mappings in Newton. If you have not done this, Ocata's ``db sync`` command will fail. Small deployments will want to run ``nova-manage cell_v2 simple_cell_setup`` on Newton before upgrading. Operators must create a new database for cell0 before running ``cell_v2 simple_cell_setup``. The simple cell setup command expects the name of the cell0 database to be ``<main database name>_cell0`` as it will create a cell mapping for cell0 based on the main database connection, sync the cell0 database, and associate existing hosts and instances with the single cell.

.. releasenotes/notes/ocata-use-neutron-by-default-7a836e65e1c3ccaf.yaml @ b'6627de4aa55110989b4b976ae794f3d8a3deb797'

- The nova-network service was deprecated in the 14.0.0 Newton release. In
  the 15.0.0 Ocata release, nova-network will only work in a Cells v1
  deployment. The Neutron networking service is now the default configuration
  for new deployments based on the ``use_neutron`` configuration option.

.. releasenotes/notes/quota-config-group-8028127074d43c48.yaml @ b'de0eff47f2cfa271735bb754637f979659a2d91a'

- Most quota options have been moved into their own
  configuration group. The exception is quota_networks
  as it is an API flag not a quota flag. These options are as
  below:

  - ``quota_instances`` (now ``instances``)
  - ``quota_cores`` (now ``cores``)
  - ``quota_ram`` (now ``ram``)
  - ``quota_floating_ips`` (now ``floating_ips``)
  - ``quota_fixed_ips`` (now ``fixed_ips``)
  - ``quota_metadata_items`` (now ``metadata_items``)
  - ``quota_injected_files`` (now ``injected_files``)
  - ``quota_injected_file_content_bytes`` (now ``injected_file_content_bytes``)
  - ``quota_injected_file_path_length`` (now ``injected_file_path_length``)
  - ``quota_security_groups`` (now ``security_groups``)
  - ``quota_security_group_rules`` (now ``security_group_rules``)
  - ``quota_key_pairs`` (now ``key_pairs``)
  - ``quota_server_groups`` (now ``server_groups``)
  - ``quota_server_group_members`` (now ``server_group_members``)
  - ``reservation_expire``
  - ``until_refresh``
  - ``max_age``
  - ``quota_driver`` (now ``driver``)

.. releasenotes/notes/remove-deprecated-cmd-all-c91c8fc2f3a56a97.yaml @ b'c07c0d4b8e2e32148a81683d6256efa8b6bd9dd4'

- The nova-all binary to launch all services has been removed after a deprecation period. It was only intended for testing purposes and not production use. Please use the individual Nova binaries to launch services.

.. releasenotes/notes/remove-deprecated-compute-options-dbf2be75d6bdbcc8.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- The ``compute_stats_class`` configuration option was deprecated since the
  13.0.0 Mitaka release and has been removed. Compute statistics are now always
  generated from the ``nova.compute.stats.Stats`` class within Nova.

.. releasenotes/notes/remove-deprecated-glance-v1-opt-976e680457f8b2c7.yaml @ b'97e7b97210139a7f7888f0d6901e499664de02a3'

- ``use_glance_v1`` option was removed due to plans to remove Glance V1
  support during Ocata development.

.. releasenotes/notes/remove-image-s3-ae6164a0d524602f.yaml @ b'8a215843dd3030e8a4f10dd22031be2b26ac66f0'

- The deprecated S3 image backend has been removed.

.. releasenotes/notes/remove-ovs-integration-bridge-default-0b838f0816829b68.yaml @ b'c4a88d597e9dae2e9fa77d30ea91349a955b0839'

- XenServer users must now set the value of xenserver.ovs_integration_bridge before they can use the system. Previously this had a default of "xapi1", which has now been removed, because it is dependent on the environment. The xapi<n> are internal bridges that are incrementally defined from zero and "xapi1" may not be the correct bridge. Operators should set this config value to the integration bridge used between all guests and the compute host in their environment.

.. releasenotes/notes/remove-scheduler_json_config_location-option-c669e8c9867ce0fb.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- The ``scheduler_json_config_location`` configuration option has not been
  used since the 13.0.0 Mitaka release and has been removed.

.. releasenotes/notes/remove_deprecated_barbican_config_opts-7eb4e801d0ac252f.yaml @ b'a63aef8fba55171e4e598b36932e46c379bf1ec7'

- Configuration options related to the Barbican were deprecated and now
  completely removed from ``barbican`` group. These options are available in
  the Castellan library. Following are the affected options:

  - ``barbican.catalog_info``
  - ``barbican.endpoint_template``
  - ``barbican.os_region_name``

.. releasenotes/notes/remove_deprecated_cells_driver_conf_opt-dbb80137b3632500.yaml @ b'f8c69efdf19c73f04f2ee1d9dfc3f7c4e142d616'

- ``driver`` configuration option has been removed from ``cells``
  group. There is only one possible driver for cells (CellsRPCDriver), which
  makes this option redundant.

.. releasenotes/notes/remove_deprecated_cert_topic_conf_opt-6402aeca8629da95.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- The deprecated ``cert_topic`` configuration option has been removed.

.. releasenotes/notes/remove_deprecated_exception_conf_opt-94bfea599c2ebf5c.yaml @ b'4bac18b28c5ada7735b87caebd9f4ee86edc9c65'

- ``fatal_exception_format_errors`` configuration option has been removed,
  as it was only used for internal testing.

.. releasenotes/notes/remove_deprecated_ironic_conf_opt-0bff87f16412d4b8.yaml @ b'05c0d472d87e3140241cdb511b40a65076266c24'

- Ironic configuration options that were used for a deprecated Identity v2
  API have been removed from ``ironic`` group. Below is the detailed list of
  removed options:

  - admin_usernale
  - admin_password
  - admin_url
  - admin_tenant_name

.. releasenotes/notes/remove_service_manager_config_options-2e1eaae92ea82d84.yaml @ b'd9a7c16c305cd7016195cada883867411d3a5eb9'

- The concept that ``service manager`` were replaceable
  components was deprecated in Mitaka, so following config
  options are removed.

  - ``metadata_manager``
  - ``compute_manager``
  - ``console_manager``
  - ``consoleauth_manager``
  - ``cert_manager``
  - ``scheduler_manager``
  - ``conductor.manager``

.. releasenotes/notes/removing-pci-parent_addr-migration-f7dfa2b441cf30e8.yaml @ b'15cda7141ba88d2170f438eae5f7fba60f27fb2e'

- In mitaka, an online migration was added to migrate older SRIOV parent device information from extra_info to a new column. Since two releases have gone out with that migration, it is removed in Ocata and operators are expected to have run it as part of either of the previous two releases, if applicable.

.. releasenotes/notes/resource_providers_scheduler_db_filters-16b2ed3da00c51dd.yaml @ b'4660333d0d97d8e00cf290ea1d4ed932f5edc1dc'

- Since the Placement service is now mandatory in Ocata, you need to deploy it and amend your compute node configuration with correct placement instructions before restarting nova-compute or the compute node will refuse to start.

.. releasenotes/notes/resource_providers_scheduler_db_filters-16b2ed3da00c51dd.yaml @ b'4660333d0d97d8e00cf290ea1d4ed932f5edc1dc'

- If by Newton (14.0.0), you don't use any of the CoreFilter, RamFilter or DiskFilter, then please modify all your compute node's configuration by amending either ``cpu_allocation_ratio`` (if you don't use CoreFilter) or ``ram_allocation_ratio`` (if you don't use RamFilter) or ``disk_allocation_ratio`` (if you don't use DiskFilter) by putting a 9999.0 value for the ratio before upgrading the nova-scheduler to Ocata.

.. releasenotes/notes/rm-conductor-local-apis-f121afaee99f6fa4.yaml @ b'c36dbe1f721ea6ca6b083932c8f27022a03ddf53'

- The ''use_local'' option, which made it possible to
  perform nova-conductor operations locally, has been
  removed. This legacy mode was introduced to bridge a
  gap during the transition to the conductor service.
  It no longer represents a reasonable alternative for
  deployers.

.. releasenotes/notes/rm-config-option-snapshot_name_template-1d8b1ee431d30e4d.yaml @ b'a05c4a924048510ff378acd8091a1145c85b884c'

- The deprecated compute config option ``snapshot_name_template``
  has been removed. It is not used anywhere and has no effect
  on any code, so there is no impact.

.. releasenotes/notes/rm-deprecated-compute_available_monitors-option-c8d0b81304452786.yaml @ b'9281164e00ff9613b204f6fc6f689f715f0ca301'

- The deprecated config option ``compute_available_monitors`` has been removed
  from the ``DEFAULT`` config section. Use setuptools entry points to list
  available monitor plugins.

.. releasenotes/notes/rm-deprecated-nova-manage-cmds-ocata-b3-813d3bcecfb939e2.yaml @ b'15e962b3a0eaae0091a1e79ee9701410e61517ca'

- The following deprecated nova-manage commands have been removed:

  * ``nova-manage account scrub``
  * ``nova-manage fixed *``
  * ``nova-manage project scrub``
  * ``nova-manage vpn *``

.. releasenotes/notes/rm-deprecated-nova-manage-cmds-ocata-bada0a4dbbc50eb6.yaml @ b'94a28d346a5a65a653d1ea7ca9ec158724a1961d'

- The following deprecated nova-manage commands have been removed:

  * nova-manage vm list

.. releasenotes/notes/supported-virtuozzo-version-569db9259a7ee579.yaml @ b'646151ff1b8d481b70884d201a1b395d904e35b0'

- As of Ocata, the minimum version of Virtuozzo that nova compute will interoperate with will be 7.0.0. Deployments using older versions of Virtuozzo should upgrade.

.. releasenotes/notes/xenserver-plugin-extensions-57e01c9473073d0a.yaml @ b'6bb1fd776feb7efd36a8c622ded37b67a21754cc'

- XenServer plugins have been renamed to include a '.py' extension. Code has been included to handle plugins with and without the extension, but this will be removed in the next release. The plugins with the extension should be deployed on all compute nodes to mitigate any upgrade issues.


.. _Release Notes_15.0.0_ocata-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/bp-deprecate-image-meta-proxy-api-7f21e1e6a94944ee.yaml @ b'df6e2d37f2c4b4c4dcccf870bc236ca5adc7770e'

- Implemented microversion v2.39 that deprecates ``image-metadata`` proxy API, removes image metadata quota checks for 'createImage' and 'createBackup' actions.
  After this version Glance configuration option ``image_property_quota`` should be used to control the quota of image metadatas. Also, removes the ``maxImageMeta`` field from ``os-limits`` API response.

.. releasenotes/notes/deprecate-compute-options-011c9a454182a8bf.yaml @ b'6a8924a7b6dfa55e24c9bc1e0e96456eb0226e42'

- The config options ``multi_instance_display_name_template`` and
  ``null_kernel`` in the ``DEFAULT`` group are now deprecated and may be
  removed as early as the 16.0.0 release. These options are deprecated to
  keep API behaviour consistent across deployments.

.. releasenotes/notes/deprecate-console_driver-opt-26475263aad3b655.yaml @ b'582321c54d7cd24fa61623f29a87f74df57f9bb9'

- The ``console_driver`` config opt in the ``DEFAULT`` group has been
  deprecated and will be removed in a future release. This option no longer
  does anything. Previously this option had only two valid, in-tree values:
  ``nova.console.xvp.XVPConsoleProxy`` and
  ``nova.console.fake.FakeConsoleProxy``. The latter of these was only used
  in tests and has since been replaced.

.. releasenotes/notes/deprecate-live-migration-progress-timeout-b4640047dc5c8eed.yaml @ b'679d78ab2baaf934dc6912096882613d55f2ea0c'

- ``[libvirt]/live_migration_progress_timeout`` has been deprecated as this
  feature has been found not to work. See bug 1644248 for more details.

.. releasenotes/notes/deprecate-nova-network-opts-b6da6af4497ef4ca.yaml @ b'0e1734b9c2685c39bdd5a8b0f6636f34e2683d83'

- The following options, found in ``DEFAULT``, were only used for configuring
  nova-network and are, like nova-network itself, now deprecated.

  - ``flat_network_bridge``
  - ``flat_network_dns``
  - ``flat_interface``
  - ``vlan_interface``
  - ``vlan_start``
  - ``num_networks``
  - ``vpn_ip``
  - ``vpn_start``
  - ``network_size``
  - ``fixed_range_v6``
  - ``gateway``
  - ``gateway_v6``
  - ``cnt_vpn_clients``
  - ``fixed_ip_disassociate_timeout``
  - ``create_unique_mac_address_attempts``
  - ``teardown_unused_network_gateway``
  - ``l3_lib``
  - ``network_driver``
  - ``multi_host``
  - ``force_dhcp_release``
  - ``update_dns_entries``
  - ``dns_update_periodic_interval``
  - ``dhcp_domain``
  - ``use_neutron``
  - ``auto_assign_floating_ip``
  - ``floating_ip_dns_manager``
  - ``instance_dns_manager``
  - ``instance_dns_domain``

  The following options, found in ``quota``, are also deprecated.

  - ``floating_ips``
  - ``fixed_ips``
  - ``security_groups``
  - ``security_group_rules``

.. releasenotes/notes/deprecate-remap_vbd_dev-opt-c1690c5b447f0053.yaml @ b'310562f52f610623ba6b0f8d1aad465b884e8515'

- The ``remap_vbd_dev`` option is deprecated and will be removed in a future
  release.

.. releasenotes/notes/deprecate-topic-opts-68b1a752dba1eb24.yaml @ b'64603034446a8c5d73af111fbedc52e1c44232aa'

- The ``topic`` config options are now deprecated and will be removed
  in the next release. The deprecated options are as below:

  * cells.topic
  * compute_topic
  * conductor.topic
  * console_topic
  * consoleauth_topic
  * network_topic
  * scheduler_topic

.. releasenotes/notes/deprecate-vmware-wsdl-location-97af576f53fef771.yaml @ b'fe98f68f5be9cabd9acbba4510a072dcf5c2e0a2'

- Deprecate the VMware driver's ``wsdl_location`` config option. This option pointed to the location of the WSDL files required when using vCenter versions earlier than 5.1. Since the minimum supported version of vCenter is 5.1, there is no longer a need for this option and its value is ignored.

.. releasenotes/notes/deprecate-xenserver-vif-driver-option-12eb279c0c93c157.yaml @ b'babdb32beabb5e37e802a7b147f3649254f4283d'

- The ``[xenserver]/vif_driver`` configuration option is deprecated for
  removal. The ``XenAPIOpenVswitchDriver`` vif driver is used for Neutron and
  the ``XenAPIBridgeDriver`` vif driver is used for nova-network, which
  itself is deprecated. In the future, the ``use_neutron`` configuration
  option will be used to determine which vif driver to load.

.. releasenotes/notes/deprecate_live_migration_uri-8ae6656664db5ba0.yaml @ b'df334b4f414b8c341709df37ca10065d3b50fcef'

- The ``live_migration_uri`` option in the [libvirt] configuration section
  is deprecated, and will be removed in a future release. The
  ``live_migration_scheme`` should be used to change scheme used for live
  migration, and ``live_migration_inbound_addr`` should be used to change
  target URI.

.. releasenotes/notes/deprecate_xenapi_torrent_downloader-ebcbb3d5f929d893.yaml @ b'bee269cf3debdac80dd6891ab4ae7439b6941c83'

- The XenServer driver provides support for downloading images via torrents.
  This feature has not been tested, and it's not clear whether there's a
  clear use case for such a feature. As a result, this feature is now
  deprecated as are the following config options.

  * ``torrent_base_url``
  * ``torrent_seed_chance``
  * ``torrent_seed_duration``
  * ``torrent_max_last_accessed``
  * ``torrent_listen_port_start``
  * ``torrent_listen_port_end``
  * ``torrent_download_stall_cutoff``
  * ``torrent_max_seeder_processes_per_host``

.. releasenotes/notes/introduce-encryption-provider-constants-a7cd0ce58da2bae8.yaml @ b'5593d74435b441ef38b301b86b5b0642f9b0b85f'

- The direct use of the encryption provider classes such as
  nova.volume.encryptors.luks.LuksEncryptor is now deprecated and will be
  blocked in the Pike release of Nova. The use of out of tree encryption
  provider classes is also deprecated and will be blocked in the Pike release
  of Nova.

.. releasenotes/notes/nova-network-only-for-cellsv1-dfb72fb1d3339bb3.yaml @ b'cf72bb8f902c0bbdfb0efff4402ad24d656de399'

- Nova network was deprecated in Newton and is no longer supported for regular deployments in Ocata. The network service binary will now refuse to start, except in the special case of CellsV1 where it is still required to function.


.. _Release Notes_15.0.0_ocata-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/add-osprofiler-support-b04f1e4cfa550440.yaml @ b'ecc8de8d6cccb06d7f4c8ecc144d37612ae1e9cc'

- OSProfiler support requires passing of trace information between various OpenStack services. This information is securely signed by one of HMAC keys, defined in nova.conf configuration file. To allow cross-project tracing user should use the key, that is common among all OpenStack services he or she wants to trace.


.. _Release Notes_15.0.0_ocata-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1633518-0646722faac1a4b9.yaml @ b'7d77fe09e86ef286ab3419282dc7afbb77d5ffd2'

- Prior to Newton, volumes encrypted by the CryptsetupEncryptor and LuksEncryptor encryption providers used a mangled passphrase stripped of leading zeros per hexadecimal. When opening encrypted volumes, LuksEncryptor now attempts to replace these mangled passphrases if detected while CryptsetupEncryptor simply uses the mangled passphrase.

.. releasenotes/notes/bug-1662699-06203e7262e02aa6.yaml @ b'ff1925ae47245f056690889a6e063ebce1bb7a80'

- Fixes `bug 1662699`_ which was a regression in the v2.1 API from the
  ``block_device_mapping_v2.boot_index`` validation that was performed in the
  legacy v2 API. With this fix, requests to create a server with
  ``boot_index=None`` will be treated as if ``boot_index`` was not specified,
  which defaults to meaning a non-bootable block device.

  .. _bug 1662699: https://bugs.launchpad.net/nova/+bug/1662699

.. releasenotes/notes/bug-hyperv-1629040-e1eb35a7b31d9af8.yaml @ b'e60e95f4997a8108de0d861e15775ea5e57ef759'

- The Hyper-V driver no longer accepts cold migrating instances to the same host. Note that this does not apply to resizes, in which case this is still allowed.

.. releasenotes/notes/fix-default-cell0-db-connection-f9717053cc34778e.yaml @ b'5b44737e0c4627b796cfcf09bff5008ae06a95ff'

- The ``nova-manage cell_v2 simple_cell_setup`` command now creates the
  default cell0 database connection using the ``[database]`` connection
  configuration option rather than the ``[api_database]`` connection. The
  cell0 database schema is the ``main`` database, i.e. the ``instances`` table,
  rather than the ``api`` database schema. In other words, the cell0 database
  would be called something like ``nova_cell0`` rather than
  ``nova_api_cell0``.

.. releasenotes/notes/fix-virtual-device-role-tagging-7cfdb14f2ba4fbcf.yaml @ b'e80e2511cf825671a479053cc8d41463aab1caaa'

- In the context of virtual device role tagging at server create time, the
  2.42 microversion restores the tag attribute to networks and
  block_device_mapping_v2. A bug has caused the tag attribute to no longer be
  accepted starting with version 2.33 for block_device_mapping_v2 and
  starting with version 2.37 for networks. In other words, block devices
  could only be tagged in version 2.32 and network interfaces between
  versions 2.32 and 2.36 inclusively. Starting with 2.42, both network
  interfaces and block devices can be tagged again.

.. releasenotes/notes/set_migration_status_to_error_on_live-migration_failure-d1f6f29ceafdd598.yaml @ b'a7c0a84a1e50a9f83acd27ece64f393ac454cf7f'

- To make live-migration consistent with resize, confirm-resize and revert-resize operations, the migration status is changed to 'error' instead of 'failed' in case of live-migration failure. With this change the periodic task '_cleanup_incomplete_migrations' is now able to remove orphaned instance files from compute nodes in case of live-migration failures. There is no impact since migration status 'error' and 'failed' refer to the same failed state.

.. releasenotes/notes/vendordata-service-tokens-876505167395a56d.yaml @ b'1f53bfcc7998f63f130a2cedaf15b41a4506c568'

- The nova metadata service will now pass a nove service token to the
  external vendordata server. These options can be configured using various
  Keystone-related options available in the ``vendordata_dynamic_auth``
  group. A new service token has been created for this purpose. Previously,
  the requesting user's keystone token was passed through to the external
  vendordata server if available, otherwise no token is passed. This resolves
  issues with scenarios such as cloud-init's use of the metadata server on
  first boot to determine configuration information.  Refer to the blueprints
  at
  http://specs.openstack.org/openstack/nova-specs/specs/ocata/approved/vendordata-reboot-ocata.html
  for more information.


.. _Release Notes_15.0.0_ocata-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/placement-api-endpoint-interface-set-29af8b9400ce7775.yaml @ b'a3089b41f6bfb10ce34581f72bc5fb029c836cd7'

- The Placement API can be set to connect to a specific keystone endpoint interface using the ``os_interface`` option in the ``[placement]`` section inside ``nova.conf``. This value is not required but can be used if a non-default endpoint interface is desired for connecting to the Placement service. By default, keystoneauth will connect to the "public" endpoint.


