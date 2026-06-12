===================================
 Queens Series Release Notes
===================================

.. _Release Notes_17.0.13-73_queens-eol:

17.0.13-73
==========

.. _Release Notes_17.0.13-73_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1852610-service-delete-with-migrations-ca0565fc0b503519.yaml @ b'd88f353796813bf0ad5ec79ba4714af35e04e591'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is involved in in-progress migrations. This is because doing
  so would not only orphan the compute node resource provider in the
  placement service on which those instances have resource allocations but
  can also break the ability to confirm/revert a pending resize properly.
  See https://bugs.launchpad.net/nova/+bug/1852610 for more details.

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'420df86e23acf050e78b64315f1058ae9704c6d0'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361

.. releasenotes/notes/cinder-detect-nonbootable-image-6fad7f865b45f879.yaml @ b'418b9450e4b9bab15a4a0f92d013e53d18de3342'

- The Compute service has never supported direct booting of an instance from
  an image that was created by the Block Storage service from an encrypted
  volume.  Previously, this operation would result in an ACTIVE instance that
  was unusable.  Beginning with this release, an attempt to boot from such an
  image will result in the Compute API returning a 400 (Bad Request)
  response.

.. releasenotes/notes/neutron-connection-retries-c276010afe238abc.yaml @ b'11daac03bf4d33c77c7bc6f037bc16972ad64ea4'

- A new config option ``[neutron]http_retries`` is added which defaults to
  3. It controls how many times to retry a Neutron API call in response to a
  HTTP connection failure. An example scenario where it will help is when a
  deployment is using HAProxy and connections get closed after idle time. If
  an incoming request tries to reuse a connection that is simultaneously
  being torn down, a HTTP connection failure will occur and previously Nova
  would fail the entire request. With retries, Nova can be more resilient in
  this scenario and continue the request if a retry succeeds. Refer to
  https://launchpad.net/bugs/1866937 for more details.


.. _Release Notes_17.0.13_queens-eol:

17.0.13
=======

.. _Release Notes_17.0.13_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/qb-bug-1730933-6695470ebaee0fbd.yaml @ b'37e45ad44c22a5b9346bece8279cde3691562e52'

- Fixes a bug that caused Nova to fail on mounting Quobyte volumes
  whose volume URL contained multiple registries.


.. _Release Notes_17.0.12_queens-eol:

17.0.12
=======

.. _Release Notes_17.0.12_queens-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'3dcefba60a4f4553888a9dfda9fe3bee094d617a'

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


.. _Release Notes_17.0.12_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1811726-multi-node-delete-2ba17f02c6171fbb.yaml @ b'b2f438bab4a0fdaa37b1a57cff0b27fb2a3f3437'

- `Bug 1811726`_ is fixed by deleting the resource provider (in placement)
  associated with each compute node record managed by a ``nova-compute``
  service when that service is deleted via the
  ``DELETE /os-services/{service_id}`` API. This is particularly important
  for compute services managing ironic baremetal nodes.

  .. _Bug 1811726: https://bugs.launchpad.net/nova/+bug/1811726


.. _Release Notes_17.0.11_queens-eol:

17.0.11
=======

.. _Release Notes_17.0.11_queens-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/disable-live-migration-with-numa-bc710a1bcde25957.yaml @ b'9999bce00f5bea5f3e90ab9e16625d4237504bcb'

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


.. _Release Notes_17.0.11_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1775418-754fc50261f5d7c3.yaml @ b'58a140487c8127da727fa7e4fb56892f8c162536'

- The `os-volume_attachments`_ update API, commonly referred to as the swap
  volume API will now return a ``400`` (BadRequest) error when attempting to
  swap from a multi attached volume with more than one active read/write
  attachment resolving `bug #1775418`_.

  .. _os-volume_attachments: https://developer.openstack.org/api-ref/compute/?expanded=update-a-volume-attachment-detail
  .. _bug #1775418: https://launchpad.net/bugs/1775418


.. _Release Notes_17.0.10_queens-eol:

17.0.10
=======

.. _Release Notes_17.0.10_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-simple-tenant-usage-pagination-393ed6e7d0e31594.yaml @ b'70b4cdce68f9b1543c032aa700e4f0f4289d90a6'

- The ``os-simple-tenant-usage`` pagination has been fixed. In some cases,
  nova usage-list would have returned incorrect results because of this.
  See bug https://launchpad.net/bugs/1796689 for details.


.. _Release Notes_17.0.10_queens-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1414895-8f7d8da6499f8e94.yaml @ b'b7bf1fbe4917c285f7bb635e791204d67b809049'

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


.. _Release Notes_17.0.9_queens-eol:

17.0.9
======

.. _Release Notes_17.0.9_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1801702-c8203d3d55007deb.yaml @ b'f8eb8a7bc52448ede25cb8ac67fcb1818d3fdd2e'

- When testing whether direct IO is possible on the backing storage
  for an instance, Nova now uses a block size of 4096 bytes instead
  of 512 bytes, avoiding issues when the underlying block device has
  sectors larger than 512 bytes. See bug
  https://launchpad.net/bugs/1801702 for details.


.. _Release Notes_17.0.8_queens-eol:

17.0.8
======

.. _Release Notes_17.0.8_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/libvirt_fix_ipv6_live_migration-bbcde8f3b7d17921.yaml @ b'551a7a459c6503158cb4512fec8b2dc9c0641abe'

- A change has been introduced in the libvirt driver to correctly handle IPv6 addresses for live migration.


.. _Release Notes_17.0.6_queens-eol:

17.0.6
======

.. _Release Notes_17.0.6_queens-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1778044-f498ee2f2cfb35ea.yaml @ b'875afe92086cf60a701abeb45574802feed9329e'

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


.. _Release Notes_17.0.6_queens-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/migration-tool-to-populate-inst.avz-29fed2fe57a9764d.yaml @ b'0a481a52929626c5fab8fd6fd50cca6882db3bd9'

- A new online data migration has been added to populate missing
  instance.availability_zone values for instances older than Pike whose
  availability_zone was not specified during boot time. This can be run
  during the normal ``nova-manage db online_data_migrations`` routine.
  This fixes `Bug 1768876`_

  .. _Bug 1768876: https://bugs.launchpad.net/nova/+bug/1768876


.. _Release Notes_17.0.6_queens-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1739646-enforce_volume_backed_for_zero_disk_flavor-b36a6eb4fa8b2964.yaml @ b'7bcd581c78bb5916bf4b52e213322e7b56283572'

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

.. releasenotes/notes/change-consecutive-boot-failure-counter-to-weigher-428de7da0ed2033a.yaml @ b'43a84dbc1ebf147d43451610b76c700a31e08f4b'

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

.. releasenotes/notes/libvirt-cpu-model-extra-flags-amd-ssbd-1c0d0cec14073dec.yaml @ b'f8aca778f704983bc7ebb0a75d42914fee2dac06'

- The 'AMD-SSBD' and 'AMD-NO-SSB' flags have been added to the list of available
  choices for the ``[libvirt]/cpu_model_extra_flags`` config option. These are
  important for proper mitigation of security issues in AMD CPUs. For more
  information see
  https://www.redhat.com/archives/libvir-list/2018-June/msg01111.html


.. _Release Notes_17.0.6_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1726301-list-across-down-cells-82726cac592e9728.yaml @ b'0626dd0f5bbafdfd38b85a074513894d3dc724af'

- Listing server and migration records used to give a 500 to users
  when a cell database was unreachable. Now only records from available
  cells are included to avoid the 500 error. The down cells are basically
  skipped when forming the results and this solution is planned to be
  further enhanced through the `blueprint handling-down-cell`_.

  .. _blueprint handling-down-cell: https://blueprints.launchpad.net/nova/+spec/handling-down-cell

.. releasenotes/notes/libvirt-mtu-configuration-0a3e9129dd33b0bc.yaml @ b'127dd738c0ec67f3559774bae83dd8872e616991'

- For libvirt driver. Now when creating tap devices the MTU will be
  configured. Requires libvirt 3.3.0 at least.


.. _Release Notes_17.0.6_queens-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/live_migration_wait_for_vif_plug-c9dcb034067890d8.yaml @ b'bfe89fec4669df6f4ac48dbb56fde3db0a24cbac'

- A new configuration option, ``[compute]/live_migration_wait_for_vif_plug``,
  has been added which can be used to configure compute services to wait
  for network interface plugging to complete on the destination host before
  starting the guest transfer on the source host during live migration.

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


.. _Release Notes_17.0.5_queens-eol:

17.0.5
======

.. _Release Notes_17.0.5_queens-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1679750-local-delete-allocations-cb7bfbcb6c36b6a2.yaml @ b'cba1a3e2c1b161204a3662a0d9fbf33da38aa7d3'

- The ``nova-api`` service now requires the ``[placement]`` section to be
  configured in nova.conf if you are using a separate config file just for
  that service. This is because the ``nova-api`` service now needs to talk
  to the placement service in order to delete resource provider allocations
  when deleting an instance and the ``nova-compute`` service on which that
  instance is running is down. This change is idempotent if
  ``[placement]`` is not configured in ``nova-api`` but it will result in
  new warnings in the logs until configured. See bug
  https://bugs.launchpad.net/nova/+bug/1679750 for more details.

.. releasenotes/notes/bug-1759316-nova-status-api-version-check-183fac0525bfd68c.yaml @ b'aaa259d9d34bab4fd168111b7393c000f7b82077'

- A new check is added to ``nova-status upgrade check`` which will scan
  all cells looking for ``nova-osapi_compute`` service versions which are
  from before Ocata and which may cause issues with how the compute API
  finds instances. This will result in a warning if:

  * No cell mappings are found
  * The minimum ``nova-osapi_compute`` service version is less than 15 in
    any given cell

  See https://bugs.launchpad.net/nova/+bug/1759316 for more details.

.. releasenotes/notes/nova-status-check-ironic-flavor-migration-4c78314bf4e74ff6.yaml @ b'daac9a69500c318b5e9d94be0031a1c9506d0340'

- A new check is added to the ``nova-status upgrade check`` CLI which can
  assist with determining if ironic instances have had their embedded flavor
  migrated to use the corresponding ironic node custom resource class.


.. _Release Notes_17.0.5_queens-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/libvirt-cpu-model-extra-flags-ssbd-fdbda6e4da495915.yaml @ b'a27ea0f9100d0061c1cf3b20407095d3cd04df26'

- The 'SSBD' and 'VIRT-SSBD' cpu flags have been added to the list
  of available choices for the ``[libvirt]/cpu_model_extra_flags``
  config option. These are important for proper mitigation of the
  Spectre 3a and 4 CVEs. Note that the use of either of these flags
  require updated packages below nova, including libvirt, qemu
  (specifically >=2.9.0 for virt-ssbd), linux, and system
  firmware. For more information see
  https://www.us-cert.gov/ncas/alerts/TA18-141A


.. _Release Notes_17.0.5_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1763183-service-delete-with-instances-d7c5c47e4ce31239.yaml @ b'a817b78dc44cf2cb4157531b2d92b03a4d0ca7d1'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is still hosting instances. This is because doing so would
  orphan the compute node resource provider in the placement service on
  which those instances have resource allocations, which affects scheduling.
  See https://bugs.launchpad.net/nova/+bug/1763183 for more details.

.. releasenotes/notes/fix-multiarch-image-props-filter-f2e885aa53d585ea.yaml @ b'ad332f3c635d887b163a8abe640d2a1b0da547fc'

- The behaviour of ImagePropertiesFilter when using multiple architectures in a cloud can be unpredictable for a user if they forget to set the architecture property in their image.  Nova now allows the deployer to specify a fallback in ``[filter_scheduler]image_properties_default_architecture`` to use a default architecture if none is specified.  Without this, it is possible that a VM would get scheduled on a compute node that does not support the image.


.. _Release Notes_17.0.4_queens-eol:

17.0.4
======

.. _Release Notes_17.0.4_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/add-association-refresh-config-opt-d1ca1af238d10c9a.yaml @ b'3a39cfc471953f95b692c15ce2175bf92035a2da'

- The nova-compute service now allows specifying the interval for updating
  nova-compute-side cache of the compute node resource provider's aggregates
  and traits info via a new config option called
  ``[compute]/resource_provider_association_refresh`` which defaults to 300.
  This was previously hard-coded to run every 300 seconds which may be too
  often in a large deployment.


.. _Release Notes_17.0.3_queens-eol:

17.0.3
======

.. _Release Notes_17.0.3_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/libvirt-cpu-model-extra-flags-a23085f58bd22d27.yaml @ b'98eb85f29c5f0775de480d5ea2946dcbba85fe8a'

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


.. _Release Notes_17.0.2_queens-eol:

17.0.2
======

.. _Release Notes_17.0.2_queens-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1753550-image-ref-url-notifications-42df5911a46b7de7.yaml @ b'e55a5f412bf6bc343eb8bb11348afe57c2012066'

- The ``image_ref_url`` entry in legacy instance notification payloads will
  be just the instance image id if ``[glance]/api_servers`` is not set
  and the notification is being sent from a periodic task. In this case the
  periodic task does not have a token to get the image service endpoint URL
  from the identity service so only the image id is in the payload. This
  does not affect versioned notifications.


.. _Release Notes_17.0.2_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1734625-419fd0e21bd332f6.yaml @ b'd49a6b8999c4b4986ea0ac0ce9f1dca2c076ee17'

- The SchedulerReportClient
  (``nova.scheduler.client.report.SchedulerReportClient``) sends requests
  with the global request ID in the ``X-Openstack-Request-Id`` header
  to the placement service. `Bug 1734625`_

  .. _Bug 1734625: https://bugs.launchpad.net/nova/+bug/1734625

.. releasenotes/notes/discover-hosts-by-service-06ee20365b895127.yaml @ b'dd90b5dbf31ba28ff3e6d54182a8badac4548313'

- The nova-manage discover_hosts command now has a ``--by-service`` option which
  allows discovering hosts in a cell purely by the presence of a nova-compute
  binary. At this point, there is no need to use this unless you're using ironic,
  as it is less efficient. However, if you are using ironic, this allows discovery
  and mapping of hosts even when no ironic nodes are present.


.. _Release Notes_17.0.0_queens-eol:

17.0.0
======

.. _Release Notes_17.0.0_queens-eol_Prelude:

Prelude
-------

.. releasenotes/notes/queens_prelude-4bdf895167f979b2.yaml @ b'b44a8069e846c7a251e1b607bd0903ad6b2d8620'

The 17.0.0 release includes many new features and bug fixes. It is
difficult to cover all the changes that have been introduced. Please at
least read the upgrade section which describes the required actions to
upgrade your cloud from 16.0.0 (Pike) to 17.0.0 (Queens).

That said, a few major changes are worth mentioning. This is not an
exhaustive list:

- The latest Compute API microversion supported for Queens is v2.60. Details
  on REST API microversions added since the 16.0.0 Pike release can be
  found in the `REST API Version History`_ page.
- The placement service should be upgraded before the nova controller and
  compute services. See the `Pike Upgrade Notes for Queens`_ for more
  details.
- Some of the `multi-cell cells v2 caveats`_ have been resolved.
- Cells v1 and nova-network continue to be deprecated, and plan to be
  removed in the 18.0.0 Rocky release.
- The libvirt and xenapi compute drivers now have (experimental) native
  support for virtual GPU devices. See the `virtual GPU`_ admin guide for
  more details.
- The libvirt compute driver now supports volume multi-attach when using
  the 2.60 compute API microversion. See the cinder admin guide for more
  details about volume multi-attach support in OpenStack.
- Version 1.0.0 of the `osc-placement plugin`_ has been released which
  provides CLI support for interacting directly with the Placement API.
- Traits-based scheduling is now available for the ironic compute driver.
  For more details, see the `ironic docs for scheduling based on traits`_.

.. _REST API Version History: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html

.. _Pike Upgrade Notes for Queens: https://docs.openstack.org/nova/latest/user/placement.html#queens-17-0-0

.. _multi-cell cells v2 caveats: https://docs.openstack.org/nova/latest/user/cellsv2-layout.html#caveats-of-a-multi-cell-deployment

.. _virtual GPU: https://docs.openstack.org/nova/latest/admin/virtual-gpu.html

.. _osc-placement plugin: https://docs.openstack.org/osc-placement/latest/index.html

.. _ironic docs for scheduling based on traits: https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-based-on-traits


.. _Release Notes_17.0.0_queens-eol_New Features:

New Features
------------

.. releasenotes/notes/add-storpool-libvirt-driver-8dfa78f46f58b034.yaml @ b'b100eb05ab5f69576f3588d646158cbf5a7dad19'

- Added the StorPool libvirt volume attachment driver.

.. releasenotes/notes/add-support-for-vgpu-libvirt-91d2983e643f5ff1.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- The libvirt driver now supports booting instances by asking for virtual
  GPUs.
  In order to support that, the operators should specify the enabled vGPU
  types in the nova-compute configuration file by using the configuration
  option ``[devices]/enabled_vgpu_types``. Only the enabled vGPU types can be
  used by instances.

  For knowing which types the physical GPU driver supports for libvirt, the
  operator can look at the sysfs by doing::

    ls /sys/class/mdev_bus/<device>/mdev_supported_types

  Operators can specify a VGPU resource in a flavor by adding in the flavor's
  extra specs::

    nova flavor-key <flavor-id> set resources:VGPU=1

  That said, Nova currently has some caveats for using vGPUs.

  * For the moment, only a single type can be supported across one compute
    node, which means that libvirt will create the vGPU by using that
    specific type only. It's also possible to have two compute nodes having
    different types but there is no possibility yet to specify in the flavor
    which specific type we want to use for that instance.

  * Suspending a guest having vGPUs doesn't work yet given a libvirt concern
    (it can't hot-unplug mediated devices from a guest). Workarounds using
    other instance actions (like snapshotting the instance or shelving it)
    are recommended until libvirt supports that. If a user asks to suspend
    the instance, Nova will get an exception that will set the instance state
    back to ``ACTIVE``, and you can see the suspend action in
    ``os-instance-action`` API will be Error.

  * Resizing an instance with a new flavor that has vGPU resources doesn't
    allocate those vGPUs to the instance (the instance is created without
    vGPU resources). We propose to work around this problem by rebuilding the
    instance once it has been resized so then it will have allocated vGPUs.

  * Migrating an instance to another host will have the same problem as
    resize. In case you want to migrate an instance, make sure to rebuild
    it.

  * Rescuing an instance having vGPUs will mean that the rescue image won't
    use the existing vGPUs. When unrescuing, it will use again the existing
    vGPUs that were allocated to the instance. That said, given Nova looks
    at all the allocated vGPUs when trying to find unallocated ones, there
    could be a race condition if an instance is rescued at the moment a new
    instance asking for vGPUs is created, because both instances could use
    the same vGPUs. If you want to rescue an instance, make sure to disable
    the host until we fix that in Nova.

  * Mediated devices that are created by the libvirt driver are not persisted
    upon reboot. Consequently, a guest startup would fail since the virtual
    device wouldn't exist. In order to prevent that issue, when restarting
    the compute service, the libvirt driver now looks at all the guest XMLs
    to check if they have mediated devices, and if the mediated device no
    longer exists, then Nova recreates it by using the same UUID.

  * If you use NVIDIA GRID cards, please know that there is a limitation with
    the NVIDIA driver that prevents one guest to have more than one virtual
    GPU from the same physical card. One guest can have two or more virtual
    GPUs but then it requires each vGPU to be hosted by a separate physical
    card. Until that limitation is removed, please avoid creating flavors
    asking for more than one vGPU.

  We are working actively to remove or workaround those caveats, but please
  understand that for the moment this feature is experimental given all the
  above.

.. releasenotes/notes/allocation-candidates-limit-37fe5c2ce57daf7f.yaml @ b'4a97bbd8248d9db7936404b66c133331316ee4b5'

- Add support, in new placement microversion 1.16, for a ``limit`` query
  parameter when making a ``GET /allocation_candidates`` request. The
  parameter accepts an integer value, ``N``, which limits the number of
  candidates returned. A new configuration item
  ``[placement]/randomize_allocation_candidates``, defaulting to ``False``,
  controls how the limited results are chosen. If ``True``, a random sampling
  of the entire result set is taken, otherwise the first N results are
  returned.

.. releasenotes/notes/allocation-candidates-traits-1adf079ed0c6563c.yaml @ b'284ba35c33053f9ef2786eacf81d6c8cdcf8e24a'

- Add ``required`` query parameter to the ``GET /allocation_candidates`` API
  in new placement microversion 1.17. The parameter accepts a list of traits
  separated by ``,``, which is used to further limit the list of allocation
  requests to resource providers that have the capacity to fulfill the
  requested resources AND *collectively* have all of the required traits
  associated with them. In the same microversion, the provider summary
  includes the traits associated with each provider.

.. releasenotes/notes/bp-add-pagination-for-instance-actions-1c14cb3fc9887d2a.yaml @ b'0c480d795f850b1eb940508823d68f67708bde90'

- Add pagination support and ``changes-since`` filter for os-instance-actions
  API. Users can now use ``limit`` and ``marker`` to perform paginated query
  when listing instance actions. Users can also use ``changes-since`` filter
  to filter the results based on the last time the instance action was
  updated.

.. releasenotes/notes/bp-add-pagination-for-os-migrations-2f8d5d257b0c5658.yaml @ b'92a0fc0b9f89f2472a574ef86c007d209a516a41'

- Added pagination support for migrations, there are four changes:

  - Add pagination support and ``changes-since`` filter for os-migrations
    API. Users can now use ``limit`` and ``marker`` to perform paginate query
    when listing migrations.
  - Users can also use ``changes-since`` filter to filter the results based
    on the last time the migration record was updated.
  - ``GET /os-migrations``,
    ``GET /servers/{server_id}/migrations/{migration_id}`` and
    ``GET /servers/{server_id}/migrations`` will now return a uuid value in
    addition to the migrations id in the response.
  - The query parameter schema of the ``GET /os-migrations`` API no longer
    allows additional properties.

.. releasenotes/notes/bp-deprecate-file-injection-feaf490524d10b3d.yaml @ b'126c3d4c78d937888213979272534e1cb706a4d4'

- The 2.57 microversion makes the following changes:

  * The ``user_data`` parameter is added to the server rebuild API.
  * The ``personality`` parameter is removed from the server create and
    rebuild APIs. Use the ``user_data`` parameter instead.
  * The ``maxPersonality`` and ``maxPersonalitySize`` limits are excluded
    from the ``GET /limits`` API response.
  * The ``injected_files``, ``injected_file_content_bytes`` and
    ``injected_file_path_bytes`` quotas are removed from the
    ``os-quota-sets`` and ``os-quota-class-sets`` APIs.

  See the `spec`_ for more details and reasoning.

  .. _spec: https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/deprecate-file-injection.html

.. releasenotes/notes/bp-ironic-volume-connector-ip-467396a516dc668a.yaml @ b'23d935b3a60741ddb52f076ffeacde9c37f17c8c'

- When creating a baremetal instance with volumes, the ironic driver will
  now pass an IP address of an iSCSI initiator to the block storage service
  because the volume backend may require the IP address for access control.
  If an IP address is set to an ironic node as a volume connector resource,
  the address is used. If a node has MAC addresses as volume connector
  resources, an IP address is retrieved from VIFs associated with the MAC
  addresses. IPv4 addresses are given priority over IPv6 addresses if both
  are available.

.. releasenotes/notes/bp-rebuild-keypair-reset-9ed45744bd85e358.yaml @ b'751f5dec112898bb4903848d5efc347fe48d8750'

- A new param ``key_name`` was added to the instance rebuild API (v2.54),
  then it is able to reset instance key pair. It is worth noting that
  users within the same project are able to rebuild other user's instances
  in that project with a new keypair.
  If set ``key_name`` to None in API body, nova will unset the keypair of
  instance during rebuild.

.. releasenotes/notes/bp-service-create-destroy-notification-f2f340903eed8f84.yaml @ b'8e793a6c6fe9cc533cb786cdb995c33160e4c986'

- Added support for service create and destroy versioned notifications.
  The ``service.create`` notification will be emitted after the service is
  created (so the uuid is available) and also send the ``service.delete``
  notification after the service is deleted.

.. releasenotes/notes/bp-symmetric-allocations-6ff7b270c32dcb7d.yaml @ b'453fd67da154bf2dd1a567702059645efb184812'

- The 1.12 version of the placement API changes handling of the `PUT
  /allocations/{consumer_uuid}` request to use a dict-based structure for
  the JSON request body to make it more aligned with the response body of
  ``GET /allocations/{consumer_uuid}``. Because ``PUT`` requires ``user_id``
  and ``project_id`` in the request body, these fields are added to the
  ``GET`` response. In addition, the response body for
  ``GET /allocation_candidates`` is updated so the allocations in the
  ``allocation_requests`` object work with the new ``PUT`` format.

.. releasenotes/notes/bug-1377781-c91d5319862bb9d8.yaml @ b'24aaf8752db25e1e71f4a14502f0ea3b1ab1b7de'

- Add support for graceful shutdown of VMware instances. The timeout parameter of the power_off
  method is now considered by the VMware driver. If you specify a timeout greater than 0, the
  driver calls the appropriate soft shutdown method of the VMware API and only forces a hard
  shutdown if the soft shutdown did not succeed before the timeout is reached.

.. releasenotes/notes/bug-1721179-87bc7b64215944c0.yaml @ b'f4f17b364e28389f22bf9c6017dd7aef918c7104'

- The ``delete_host`` command has been added in ``nova-manage cell_v2``
  to delete a host from a cell (host mappings).
  The ``force`` option has been added in ``nova-manage cell_v2 delete_cell``.
  If the ``force`` option is specified, a cell can be deleted
  even if the cell has hosts.

.. releasenotes/notes/bug-1725331-fcf93514045a557a.yaml @ b'52e7e6e3e47c66b362d62d8e277e85f65714285a'

- The ``nova-manage cell_v2 delete_cell`` command returns an exit code 4
  when there are instance mappings to a cell to delete but all instances
  have been deleted in the cell.

.. releasenotes/notes/bug-1735687-add-list-hosts-in-cellv2-7afa67ce0d48b6a2.yaml @ b'c7b51a63b0c3b5ad80979060bbfe49287e6da847'

- Add a ``nova-manage cell_v2 list_hosts`` command for listing hosts
  in one or all v2 cells.

.. releasenotes/notes/cold-migration-with-target-queens-2dcd09c3a3414302.yaml @ b'd2ce4ca9ec7501c4ecb1edfacf421d2231c6edef'

- When cold migrating a server, the ``host`` parameter is available as of microversion 2.56. The target host is checked by the scheduler.

.. releasenotes/notes/fill-instance-action-record-gaps-14b36eba313d6d87.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- The following instance action records have been added:

  * ``attach_interface``
  * ``detach_interface``
  * ``attach_volume``
  * ``detach_volume``
  * ``swap_volume``
  * ``lock``
  * ``unlock``
  * ``shelveOffload``
  * ``createBackup``
  * ``createImage``

.. releasenotes/notes/flavor-description-02f8b8626da71a25.yaml @ b'034d7f37954e8bb46bb18df261adea51a0e3981f'

- Microversion 2.55 adds a ``description`` field to the flavor resource in
  the following APIs:

  * ``GET /flavors``
  * ``GET /flavors/detail``
  * ``GET /flavors/{flavor_id}``
  * ``POST /flavors``
  * ``PUT /flavors/{flavor_id}``

  The embedded flavor description will not be included in server
  representations.

  A new policy rule ``os_compute_api:os-flavor-manage:update`` is added
  to control access to the ``PUT /flavors/{flavor_id}`` API.

.. releasenotes/notes/image-id-in-snapshot-notification-7e1e10435475a1af.yaml @ b'581c537cf530f6f3d3e5330404e14f6dc48b2ff5'

- The payload of the ``instance.snapshot.start`` and
  ``instance.snapshot.end`` notifications have been extended with the
  ``snapshot_image_id`` field that contains the image id of the snapshot
  created. This change also causes that the type of the payload object has
  been changed from ``InstanceActionPayload`` version 1.5 to
  ``InstanceActionSnapshotPayload`` version 1.6. See the
  `notification dev reference`_ for the sample file of
  ``instance.snapshot.start`` as an example.

  .. _notification dev reference: https://docs.openstack.org/developer/nova/notifications.html

.. releasenotes/notes/notification-transformation-queens-c360f10c7516cae4.yaml @ b'43cafb684c56a5c730988ee208f141c8557323ea'

- The following legacy notifications have been transformed to
  a new versioned payload:

  * aggregate.add_host
  * aggregate.remove_host
  * instance.evacuate
  * instance.interface_attach
  * instance.interface_detach
  * instance.live_migration_abort
  * instance.live_migration_pre
  * instance.rescue
  * instance.resize_confirm
  * instance.resize_prep
  * instance.resize_revert
  * instance.resize.error
  * instance.trigger_crash_dump
  * instance.unrescue
  * keypair.delete
  * keypair.import
  * server_group.create
  * server_group.delete

  Every versioned notification has a sample file stored under
  doc/notification_samples directory. Consult
  https://docs.openstack.org/nova/latest/reference/notifications.html for
  more information.

.. releasenotes/notes/oslo_reports_config-23d89ab202937d25.yaml @ b'f1de38c26fcd88eb88b8792eaa1651c07fc40485'

- Configuration options for ``oslo.reports``, found in the ``oslo_reports``
  group, are now exposed in nova. These include:

  - ``log_dir``
  - ``file_event_handler``
  - ``file_event_handler_interval``

  These will allow using a file trigger for the reports, which is
  particularly useful for Windows nodes where the default signals are not
  available. Also, specifying a log directory will allow the reports to be
  generated at a specific location instead of stdout.

.. releasenotes/notes/placement-allocations-link-in-get-resource-providers-0b1d26a264eceb4b.yaml @ b'a9105b4904b23f640537b36b6b474e74dab26541'

- A new 1.11 API microversion is added to the Placement REST API.  This adds
  the ``resource_providers/{rp_uuid}/allocations`` link to the  ``links``
  section of the response from ``GET /resource_providers``.

.. releasenotes/notes/placement-last-modified-cf43aece4c54fc97.yaml @ b'b3843ee352bfc4f13bdfe2ccce646234bf578128'

- Throughout the Placement API, in microversion 1.15, 'last-modified' headers
  have been added to GET responses and those PUT and POST responses that have
  bodies. The value is either the actual last modified time of the most
  recently modified associated database entity or the current time if there
  is no direct mapping to the database. In addition,
  'cache-control: no-cache' headers are added where the 'last-modified'
  header has been added to prevent inadvertent caching of resources.

.. releasenotes/notes/placement-rest-api-nested-resource-providers-552a923a96d7adca.yaml @ b'109f21f3c82edef720e1ff35da24d574dd004d7f'

- New placement REST API microversion 1.14 is added to support nested resource providers. Users of the placement REST API can now pass a ``in_tree=<UUID>`` parameter to the ``GET /resource_providers`` REST API call.  This will trigger the placement service to return all resource provider records within the "provider tree" of the resource provider with the supplied UUID value. The resource provider representation now includes a ``parent_provider_uuid`` value that indicates the UUID of the immediate parent resource provider, or ``null`` if the provider has no parent. For convenience, the resource provider resource also contains a ``root_provider_uuid`` field that is populated with the UUID of the top-most resource provider in the provider tree.

.. releasenotes/notes/post-allocations-427581fa41671820.yaml @ b'8caf4f514898ae1af2c3d0e1e477a5d5f3060c60'

- Microversion 1.13 of the Placement API gives the ability to set or clear
  allocations for more than one consumer uuid with a request to
  ``POST /allocations``.

.. releasenotes/notes/qemu-native-luks-decryption-6e9ad8cc658be14d.yaml @ b'e04ef32244a5866eb0b60a28cc6e1450fac36d16'

- QEMU 2.6.0 and Libvirt 2.2.0 allow LUKS encrypted RAW files, block devices
  and network devices (such as rbd) to be decrypted natively by QEMU.
  If qemu >= 2.6.0 and libvirt >= 2.2.0 are installed and the volume
  encryption provider is 'luks', the libvirt driver will use native QEMU
  decryption for encrypted volumes. The libvirt driver will generate a secret
  to hold the LUKS passphrase for unlocking the volume and the volume driver
  will use the secret to generate the required encryption XML for the disk.
  QEMU will then be able to read from and write to the encrypted disk
  natively, without the need of os-brick encryptors.

  Instances that have attached encrypted volumes from before Queens will
  continue to use os-brick encryptors after a live migration or direct
  upgrade to Queens. A full reboot or another live migration between Queens
  compute hosts is required before the instance will attempt to use QEMU
  native LUKS decryption.

.. releasenotes/notes/rebuild-ironic-config-drive-77bea47ad20c105b.yaml @ b'878c44f0cff4f11b2a01e60019d79ccf5e5d707a'

- Now when you rebuild a baremetal instance, a new config drive
  will be generated for the node based on the passed in personality files,
  metadata, admin password, etc. This fix requires Ironic API 1.35.

.. releasenotes/notes/request-traits-in-nova-ffcb00f76229b6e9.yaml @ b'284ba35c33053f9ef2786eacf81d6c8cdcf8e24a'

- Added traits support to the scheduler. A new flavor extra spec is added to
  support specifying the required traits. The syntax of extra spec is
  ``trait:<trait_name>=required``, for example:

  - trait:HW_CPU_X86_AVX2=required
  - trait:STORAGE_DISK_SSD=required

  The scheduler will pass required traits to the
  ``GET /allocation_candidates`` endpoint in the Placement API to include
  only resource providers that can satisfy the required traits. Currently
  the only valid value is ``required``. Any other value will be considered
  invalid.

  This requires that the Placement API version 1.17 is available before
  the ``nova-scheduler`` service can use this feature.

  The FilterScheduler is currently the only scheduler driver that supports
  this feature.

.. releasenotes/notes/share-pci-between-numa-nodes-0bd206eeca4ebcde.yaml @ b'5622a9082aa37d7ae67adc01c5044edc0cf8df74'

- Added support for PCI device NUMA affinity policies. These allow you to
  configure how strict your NUMA affinity should be on a per-device basis or,
  more specifically, per device alias. These are configured as part of the
  ``[pci]alias`` configuration option(s).

  There are three policies supported:

  - ``required`` (must-have)
  - ``legacy`` (must-have-if-available) (default)
  - ``preferred`` (nice-to-have)

  In all cases, strict NUMA affinity is provided if possible. The key
  difference between the policies is how much NUMA affinity one is willing to
  forsake before failing to schedule.

.. releasenotes/notes/shared-volume-between-guests-6eb6cc9e3bcf80fa.yaml @ b'7e6ae9afd9f6f6bb1bf4289c598fbc95dfd52612'

- This release adds support to attach a volume to multiple
  server instances. The feature can only be used in Nova if the
  volume is created in Cinder with the **multiattach** flag set
  to True. It is the responsibility of the user to use a
  proper filesystem in the guest that supports shared read/write access.

  This feature is currently only supported by the libvirt compute driver
  and only then if qemu<2.10 or libvirt>3.10 on the compute host.

  API restrictions:

  * Compute API microversion 2.60 must be used to create a server from
    a multiattach volume or to attach a multiattach volume to an existing
    server instance.
  * When creating a server using a multiattach volume, the API will check
    if the compute services have all been upgraded to a minimum level of
    support and will fail with a 409 HTTPConflict response if the computes
    are not yet upgraded.
  * Attaching a multiattach volume to a shelved offloaded instance is not
    supported and will result in a 400 HTTPBadRequest response.
  * Attaching a multiattach volume to an existing server instance will check
    that the compute hosting that instance is new enough to support it and
    has the capability to support it. If the compute cannot support the
    multiattach volume, a 409 HTTPConflict response is returned.

  See the `Cinder enable multiattach`_ spec for details on configuring
  Cinder for multiattach support.

  .. _Cinder enable multiattach: https://specs.openstack.org/openstack/cinder-specs/specs/queens/enable-multiattach.html

.. releasenotes/notes/shuffle-best-hosts-447c1703a5d6d140.yaml @ b'3759f105a7c4c3029a81a5431434190ef1bbb020'

- Added a new boolean configuration option
  ``[filter_scheduler]shuffle_best_same_weighed_hosts`` (default is False).

  Enabling it will spread instances between hosts that have the same weight
  according to request spec. It is mostly useful when the
  ``[filter_scheduler]host_subset_size`` option has default value of 1,
  but available hosts have the same weight (e.g. ironic nodes using resource
  classes). In this case enabling it will decrease the number of
  rescheduling events.

  On the other hand, enabling it will make packing of VMs on hypervizors
  less dence even when host weighing is disabled.

.. releasenotes/notes/use-neutron-when-list-instances-by-ip-6682018bf88b6b0e.yaml @ b'3f35fe6a88672ea2ab7e080a55235c5cca45dc2c'

- When ``IP address substring filtering`` extension is available in Neutron, Nova will proxy the instance list with ``ip`` or ``ip6`` filter to Neutron for better performance.

.. releasenotes/notes/vgpu-18da86834c90f041.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- When using XenAPI driver for XenServer, we can support booting instances
  with a vGPU attached to get better graphics processing capability.
  In order to use this feature, the operators should specify the enabled
  vGPU types in the nova compute configuration file with the configuration
  option - ``[devices]/enabled_vgpu_types``. Only the enabled vGPU types
  can be used by instances.

  XenServer automatically detects and groups together identical physical
  GPUs. Although the physical GPUs may support multiple vGPU types, at
  the moment nova only supports a single vGPU type for each compute node.
  The operators can run the following CLI commands in XenServer to get
  the available vGPU types if the host supports vGPU::

    xe vgpu-type-list

  The values of ``model-name ( RO):`` from the output of the above commands
  are the vGPU type names which you can choose from to set the nova
  configure - ``[devices]/enabled_vgpu_types``. Please choose only one
  vGPU type to be enabled.

  The operators should specify a vGPU resource in the flavor's extra_specs::

    nova flavor-key <flavor-id> set resources:VGPU=1

  Then users can use the flavor to boot instances with a vGPU attached.
  At the moment, XenServer doesn't support multiple vGPUs for a single
  instance, so ``resources:VGPU`` in the flavor's extra_specs should
  always be ``1``.

.. releasenotes/notes/vmware-boot-uefi-f26ab3b9bdecf24a.yaml @ b'fc0c6d2f9ab55554299b2adcac2b08991a9683fd'

- The VMware vCenter compute driver now supports booting from images
  which specify they require UEFI or BIOS firmware, using the
  ``hw_firmware_type`` image metadata.

.. releasenotes/notes/vmware-console-log-384fbb9a6aa095ad.yaml @ b'd9c03b1ecbc79021cbd597e45a29b84587db0a67'

- VMware serial console log is completed. `VSPC`_ must be deployed along
  with nova-compute and configured properly. The ``[vmware]/serial_log_dir``
  config option must have the same value in both nova.conf and vspc.conf.

  .. _VSPC: https://github.com/openstack/vmware-vspc

.. releasenotes/notes/websocket-proxy-to-host-security-c3eca0647b0cbc02.yaml @ b'7c593dc505111ac79a75f4e09a2a37485e36fae8'

- Added a number of new configuration options to the ``[vnc]`` group, which
  together allow for the configuration of authentication used between the
  *nova-novncproxy* server and the compute node VNC server.

  - ``auth_schemes``
  - ``vencrypt_client_key``
  - ``vencrypt_client_cert``
  - ``vencrypt_ca_certs``

  For more information, refer to `the documentation`__.

  __ https://docs.openstack.org/nova/latest/admin/remote-console-access.html

.. releasenotes/notes/websocket-proxy-to-host-security-c3eca0647b0cbc02.yaml @ b'7c593dc505111ac79a75f4e09a2a37485e36fae8'

- The *nova-novncproxy* server can now be configured to do a security
  negotiation with the compute node VNC server. If the VeNCrypt auth scheme
  is enabled, this establishes a TLS session to provide encryption of all
  data. The proxy will validate the x509 certs issued by the remote server to
  ensure it is connecting to a valid compute node. The proxy can also send
  its own x509 cert to allow the compute node to validate that the connection
  comes from the official proxy server.

  To make use of VeNCrypt, configuration steps are required for both the
  ``nova-novncproxy`` service and libvirt on all the compute nodes. The
  ``/etc/libvirt/qemu.conf`` file should be modified to set the ``vnc_tls``
  option to ``1``, and optionally the ``vnc_tls_x509_verify`` option to
  ``1``. Certificates must also be deployed on the compute node.

  The ``nova.conf`` file should have the ``auth_schemes`` parameter in the
  ``vnc`` group set. If there are a mix of compute nodes, some with VeNCrypt
  enabled and others with it disabled, then the ``auth_schemes``
  configuration option should be set to ``['vencrypt', 'none']``.

  Once all compute nodes have VeNCrypt enabled, the ``auth_schemes``
  parameter can be set to just ``['vencrypt']``.

  For more information, refer to `the documentation`__.

  __ https://docs.openstack.org/nova/latest/admin/remote-console-access.html


.. _Release Notes_17.0.0_queens-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1747511-glance-api-servers-1e17757b901a76d8.yaml @ b'62ef6cfcf01d84813f71d1e8252b86c170ee39f0'

- Due to a bug in python-glanceclient:

  https://bugs.launchpad.net/python-glanceclient/+bug/1707995

  If ``[glance]/api_servers`` is not set in nova.conf, and there is a
  versioned endpoint URL in the service catalog, nova makes a best attempt
  at parsing and stripping the version from the URL in order to make
  API requests to the image service.

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'9ed692bf8c84e0a702536101cd6cb084d33e1c26'

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

.. releasenotes/notes/over-quota-api-behavior-change-fc2cbbf7c79b5ae3.yaml @ b'f49ec409fd8fe2dc38d2978255c68850c427f94a'

- In 16.0.0 Pike release, quota limits are checked in a new fashion after change 5c90b25e49d47deb7dc6695333d9d5e46efe8665 and a new config option ``[quota]/recheck_quota`` has been added in change eab1d4b5cc6dd424c5c7dfd9989383a8e716cae5 to recheck quota after resource creation to prevent allowing quota to be exceeded as a result of racing requests. These changes could lead to requests blocked by over quota resulting in instances in the ``ERROR`` state, rather than no instance records as before. Refer to https://bugs.launchpad.net/nova/+bug/1716706 for detailed bug report.


.. _Release Notes_17.0.0_queens-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/aarch64-set-proper-cpu-mode-8455bad7d69dc6fd.yaml @ b'8bc7b950b7c0a3c80cdd120fe4df97c14848c344'

- On AArch64 architecture ``cpu_mode`` for libvirt is set to ``host-passthrough``
  by default.

  AArch64 currently lacks ``host-model`` support because neither libvirt nor
  QEMU are able to tell what the host CPU model exactly is and there is no
  CPU description code for ARM(64) at this point.

  .. warning:: ``host-passthrough`` mode will completely break live
     migration, *unless* all the Compute nodes (running libvirtd) have
     *identical* CPUs.

.. releasenotes/notes/add_keystone_option-138dff5efb9a53aa.yaml @ b'905d31dd9715505599b0a2ad123eebef37f606f5'

- A new ``keystone`` config section is added so that you can
  set session link attributes for communicating with keystone. This
  allows the use of custom certificates to secure the link between
  Nova and Keystone.

.. releasenotes/notes/agg-resource-filters-6e24c92a69afa85f.yaml @ b'1c4d2f4cbdf096cbd79297338cfb40d15875f930'

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

.. releasenotes/notes/api.fault-notification-removal-9f3142ba7cb13ca9.yaml @ b'0d4c3cc65b78bafef69afc45cb156afe38f857c3'

- The ``notify_on_api_faults`` config option and the ``api.fault``
  notification it enabled have been removed. As noted in `bug 1699115`_,
  the ``api.fault`` notification has not worked since the v2.1 API was
  introduced. As the v2.0 API is supported with the v2.1 codebase since
  Newton, this notification has not been emitted since Newton. Given that
  no one has reported an issue with this in that time, it is simply
  removed.

  .. _`bug 1699115`: https://bugs.launchpad.net/nova/+bug/1699115

.. releasenotes/notes/bug-1712008-4ab2538211b8c3d9.yaml @ b'02a82c41f90a64f261d81cdc0bc57471d15a7c8e'

- The ``nova-conductor`` service now needs access to the Placement service
  in the case of forcing a destination host during a live migration. Ensure
  the ``[placement]`` section of nova.conf for the ``nova-conductor`` service
  is filled in.

.. releasenotes/notes/bug-1713150-default_publisher_id-f46f4f6a39347951.yaml @ b'27cd4dd70b5a51919ce0091ab4247f65e5a27526'

- The ``[notifications]/default_publisher_id`` configuration option now
  defaults to ``[DEFAULT]/host`` rather than ``[DEFAULT]/my_ip``.

.. releasenotes/notes/ceph-minimum-version-bump-6ef4597c3e117201.yaml @ b'1e70cb8d4dace3c3372cd6e1bb13060becf25c6a'

- Nova now requires Ceph/librados >= 11.1.0 if running under Python 3 with
  the RBD image backend for the libvirt driver. Requirements for Python 2
  users or users using a different backend remain unchanged.

.. releasenotes/notes/default-non-inheritable-image-properties-dfd13ba3b09278dd.yaml @ b'82c823bcec5850f6876308ebcdbcb37312bf763f'

- The default list of non-inherited image properties to pop when creating a
  snapshot has been extended to include image signature properties. The
  properties ``img_signature_hash_method``, ``img_signature``,
  ``img_signature_key_type`` and ``img_signature_certificate_uuid`` are no
  longer inherited by the snapshot image as they would otherwise result in
  a Glance attempting to verify the snapshot image with the signature of the
  original.

.. releasenotes/notes/delete-TypeAffinityFilter-61bb92d1382f4a68.yaml @ b'ed3c69cb45c234be35fce04413650d9054ac57b4'

- The ``TypeAffinityFilter``, which was deprecated in the 16.0.0 Pike
  release, has been removed. The filter was flawed in that it relied on the
  flavor ``id`` primary key which cannot be relied upon since you cannot
  "edit" a flavor to change its disk, vcpu, etc values. Therefore to change
  a given flavor, it must be deleted and re-created, which means a new ``id``
  value, thus potentially breaking the usefulness of the filter. Also, the
  flavor migration from the ``nova`` database to the ``nova_api`` database
  would also have resulted in different ``id`` values.

.. releasenotes/notes/drop-cinder-v2-support-d761d12d552616aa.yaml @ b'eadbacbda628ecc969a980378faf55bc02f514bf'

- Nova no longer supports the Block Storage (Cinder) v2 API. Ensure the
  following configuration options are set properly for Cinder v3:

  - ``[cinder]/catalog_info`` - Already defaults to Cinder v3
  - ``[cinder]/endpoint_template`` - Not used by default.

.. releasenotes/notes/glance-api-servers-must-be-urls-558298647cbfc81c.yaml @ b'c56fc55170d16e31f2f304e526df975ced857ba6'

- If using the ``api_servers`` option in the ``[glance]`` configuration
  section, the values therein must be URLs.  Raw IP addresses will result
  in hard failure of API requests.

.. releasenotes/notes/glance-via-ksa-5646eb3d5db51c54.yaml @ b'9519601401ee116a9197fe3b5d571495a96912e9'

- Nova now uses keystoneauth1 configuration to set up communication with the
  image service.  Use keystoneauth1 loading parameters for Session and
  Adapter setup in the ``[glance]`` conf section.  This includes using
  ``endpoint_override`` in favor of ``api_servers``.  The
  ``[glance]api_servers`` conf option is still supported, but should only be
  used if you need multiple endpoints and are unable to use a load balancer
  for some reason.  However, note that no configuration is necessary with an
  appropriate service catalog entry for the image service.

.. releasenotes/notes/ironic-via-ksa-deffd3dac48ff4eb.yaml @ b'0a8f019be0f75005929724df3238b0a1ed49c88d'

- Nova now uses keystoneauth1 configuration to set up communication with the
  baremetal service.  Use keystoneauth1 loading parameters for auth, Session,
  and Adapter setup in the ``[ironic]`` conf section.  This includes using
  ``endpoint_override`` in favor of ``api_endpoint``.

.. releasenotes/notes/live_snapshot_by_default-f231485fc2bf77f1.yaml @ b'980d0fcd75c2b15ccb0af857a9848031919c6c7d'

- Nova now defaults to using the live snapshot feature of libvirt
  when taking snapshots. This was previously disabled by default due
  to crashes on load seen with older libvirt versions. It has been
  used in production by many clouds, and appears stable in real
  world environments. If you see crashes of guests during snapshots,
  you can disable this with the ``disable_libvirt_livesnapshot``
  config value in ``[workarounds]``.

.. releasenotes/notes/min-required-shred-9e6454ab2038619e.yaml @ b'308ac6e6d151330cd1a78f376cfe07a3b7fef30e'

- The minimum required version of shred has been increased to 8.22.

.. releasenotes/notes/neutron-via-ksa-9f386b09cff98a9e.yaml @ b'6cde77ebbab85bc8ccd2ab7ad977b1d4af4a13fa'

- Nova now uses keystoneauth1 configuration to set up communication with the
  network service.  Use keystoneauth1 loading parameters for Adapter setup in
  the ``[neutron]`` conf section (auth and Session options continue to work
  as before).  Of note:

  * Legacy option ``url`` is deprecated and replaced by
    ``endpoint_override``.  This should not need to be specified if an
    appropriate service catalog entry exists for the network service.
  * When ``url`` is not used, ``region_name`` no longer defaults to
    ``RegionOne``.
  * In Queens, specifying ``url`` will trigger the legacy behavior.  The
    ``url`` option will be removed in Rocky.

.. releasenotes/notes/placement-via-ksa-02d87c87636912f8.yaml @ b'987d451f4d4c8006cc6e32ea2d966c749c2d9265'

- Nova now uses keystoneauth1 configuration to set up communication with the
  placement service.  Use keystoneauth1 loading parameters for auth, Session,
  and Adapter setup in the ``[placement]`` conf section.  Note that, by
  default, the 'internal' interface will be tried first, followed by the
  'public' interface.  Use the conf option ``[placement].valid_interfaces``
  to override this behavior.

.. releasenotes/notes/privsep-queens-rootwrap-adds-907aa1bc8e3eb2ca.yaml @ b'635d205268c1f1d5a3d43d9230fa72487cd4e2df'

- A sys-admin privsep daemon has been added and needs to be included in your
  rootwrap configuration.

.. releasenotes/notes/privsep-queens-rootwrap-adds-907aa1bc8e3eb2ca.yaml @ b'635d205268c1f1d5a3d43d9230fa72487cd4e2df'

- Calls to mount in the virt disk api no longer ignore the value of stderr.

.. releasenotes/notes/privsep-queens-rootwrap-adds-907aa1bc8e3eb2ca.yaml @ b'635d205268c1f1d5a3d43d9230fa72487cd4e2df'

- The nova-idmapshift binary has been removed. This has been replaced by
  internal functionality using privsep.

.. releasenotes/notes/privsep-queens-rootwrap-adds-907aa1bc8e3eb2ca.yaml @ b'635d205268c1f1d5a3d43d9230fa72487cd4e2df'

- The following commands are no longer required to be listed in your rootwrap
  configuration: blkid; blockdev; cat; chown; cryptsetup; dd; ebrctl; ifc_ctl;
  kpartx; losetup; lvcreate; lvremove; lvs; mkdir; mm-ctl; mount;
  nova-idmapshift; parted; ploop; prl_disk_tool; qemu-nbd; readlink; shred; tee;
  touch; umount; vgs; vrouter-port-control; and xend.

.. releasenotes/notes/queens-compute-requires-placement-1.14-for-nested-rps-8abb49df061b167e.yaml @ b'4b7a1505845f92c0425b49c6f8f843c6ad81d2e1'

- The ``nova-compute`` service requires Placement API version 1.14 at a
  minimum to support `nested resource providers`_.

  .. _nested resource providers: http://specs.openstack.org/openstack/nova-specs/specs/queens/approved/nested-resource-providers.html

.. releasenotes/notes/remove-deprecated-compute-opts-bc935162bc4723ac.yaml @ b'694fa59338640f26750127797e1c36b6b098cebb'

- The following deprecated configuration options have been removed from the
  ``compute`` section of ``nova.conf``:

  - ``null_kernel``

  These were deprecated in the 15.0.0 release as they allowed for
  inconsistent API behavior across deployments.

.. releasenotes/notes/remove-deprecated-keymgr-db807dc76c83263e.yaml @ b'f65d436c114bbfc2051c6f5b6d7a9d12daacc29d'

- The old deprecated ``keymgr`` options have been removed.
  Configuration options using the ``[keymgr]`` group will not be
  applied anymore. Use the ``[key_manager]`` group from Castellan instead.
  The Castellan ``api_class`` options should also be used instead, as most
  of the options that lived in Nova have migrated to Castellan.

  - Instead of ``api_class`` option ``nova.keymgr.barbican.BarbicanKeyManager``,
    use ``castellan.key_manager.barbican_key_manager.BarbicanKeyManager``
  - Instead of ``api_class`` option ``nova.tests.unit.keymgr.mock_key_mgr.MockKeyManager``,
    use ``castellan.tests.unit.key_manager.mock_key_manager.MockKeyManager``
  - ``nova.keymgr.conf_key_mgr.ConfKeyManager`` still remains, but the ``fixed_key``
    configuration options should be moved to the ``[key_manager]`` section

.. releasenotes/notes/remove-deprecated-nicira-iface-id-in-xenserver-870bfab82f22cac1.yaml @ b'fb8978b91e171bbdcb96f3cec9f9e0e9d112a2db'

- Setting of 'nicira-iface-id' in XenServer VIF's other-config
  field by XenAPI driver has been removed to avoid VM booting
  timeout problem when using neutron polling mode.
  It was previously deprecated in Pike.

.. releasenotes/notes/remove-deprecated-nova-manage-commands-2826e6b50eccfef1.yaml @ b'd2eb7eaf01fc12ac66cdf77c382f3f8ea13894c7'

- The following ``nova-manage`` commands have been removed.

  - ``quota``
  - ``shell``
  - ``project``
  - ``account``
  - ``logs``
  - ``host``
  - ``agent``

  These were previously deprecated in 16.0.0.

.. releasenotes/notes/remove-deprecated-remap_vbd_dev-opt-22c1898f25b58280.yaml @ b'29c962f3bac3125fc5ca2d84facba7eacea4d40d'

- The following deprecated configuration options have been removed from the
  ``xenserver`` section of ``nova.conf``:

  - ``remap_vbd_dev``
  - ``remap_vbd_dev_prefix``

.. releasenotes/notes/remove-deprecated-vendordata_driver-opt-3ececc051e581070.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- The ``[DEFAULT] vendordata_driver`` option was deprecated in Mitaka and has
  now been removed. Configuration of vendordata drivers should now be done by
  using the ``[api] vendordata_providers`` option. For more information,
  refer to the `vendordata documentation`__.

  __ https://docs.openstack.org/nova/latest/user/vendordata.html

.. releasenotes/notes/remove-deprecated-vendordata_driver-opt-3ececc051e581070.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- The ``[api] vendordata_providers`` option now defaults to ``[StaticJSON]``.
  This ensures existing behavior of the vendordata v1 driver is preserved.

.. releasenotes/notes/remove-trusted-filter-82afe7ebd3413e3e.yaml @ b'aecc165a588061bc6bf9e124cf011e45a3b08c85'

- The *TrustedFilter* along with its related ``[trusted_computing]``
  configuration options were deprecated in the 16.0.0 Pike release and have
  been removed in the 17.0.0 Queens release. The *TrustedFilter* was always
  experimental, had no continuous integration testing to prove it still
  worked, and no reported users.

.. releasenotes/notes/rename-vnc-opts-3367a07523100d51.yaml @ b'e5a03e3c54d57aa29bd8154c9eddf7ee52c6c3b5'

- The following configuration options have been renamed:

  - ``[vnc]vncserver_listen`` (now ``[vnc]server_listen``)
  - ``[vnc]vncserver_proxyclient_address`` (now
    ``[vnc]server_proxyclient_address``)

  This establishes a consistent naming between VNC and Spice options and
  removes some unnecessary duplication.

.. releasenotes/notes/require_port_binding_ext-e6d9bdd4f6eef4e3.yaml @ b'7f38e25e7df7be805459998c591e7bf8d900f766'

- Nova now has a hard requirement that the Port Binding extension is
  enabled in the Neutron service. This simplifies the logic between
  Nova and Neutron.


.. _Release Notes_17.0.0_queens-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/bug-1716786-7c3fc081f29f4dac.yaml @ b'503a78b47c49e9361d606a967605796baaa1b87c'

- The ``idle_timeout`` option in the ``api_database`` group
  has been renamed to ``connection_recycle_time``.

.. releasenotes/notes/deprecate-api-extensions-policies-5613bc4eea59709d.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- Nova API extension concept is removed in Pike. These extensions
  have their own policies enforcement which are not needed any more.
  All the below policies which were added mainly for extensions are
  deprecated for removal:

  - Show & List detail server

    - ``os_compute_api:os-config-drive``
    - ``os_compute_api:os-extended-availability-zone``
    - ``os_compute_api:os-extended-status``
    - ``os_compute_api:os-extended-volumes``
    - ``os_compute_api:os-keypairs``
    - ``os_compute_api:os-server-usage``
    - ``os_compute_api:os-security-groups`` (only from ``/servers`` APIs)

  - Create, Update, Show & List detail flavor

    - ``os_compute_api:os-flavor-rxtx``
    - ``os_compute_api:os-flavor-access`` (only from ``/flavors`` APIs)

  - Show & List detail image

    - ``os_compute_api:image-size``

.. releasenotes/notes/deprecate-baremetal-filters-618249af65115bf6.yaml @ b'b4295ef0496849c1bc43481d31f57d79afaf6b7b'

- The configuration options ``baremetal_enabled_filters`` and
  ``use_baremetal_filters`` are deprecated in Pike and should only be used if
  your deployment still contains nodes that have not had their resource_class
  attribute set. See `Ironic release notes <https://docs.openstack.org/releasenotes/ironic/>`_
  for upgrade concerns.

.. releasenotes/notes/deprecate-baremetal-filters-618249af65115bf6.yaml @ b'b4295ef0496849c1bc43481d31f57d79afaf6b7b'

- The following scheduler filters are deprecated in Pike: ``ExactRamFilter``,
  ``ExactCoreFilter`` and ``ExactDiskFilter`` and should only be used if your
  deployment still contains nodes that have not had their resource_class
  attribute set. See `Ironic release notes <https://docs.openstack.org/releasenotes/ironic/>`_
  for upgrade concerns.

.. releasenotes/notes/deprecate-configurable-hide-server-address-feature-0ca03d8c8d11e991.yaml @ b'3e329e73e7ffab63a2c1c33533e7c96f82c7c142'

- The ``hide_server_address_states`` configuration option is now
  deprecated for removal. In future, there will be hard coded
  server state ``building`` for which server address will be hidden.
  The policy 'os_compute_api:os-hide-server-addresses' also is deprecated
  for removal. More details `here`_

  .. _here: https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/remove-configurable-hide-server-address-feature.html

.. releasenotes/notes/deprecate-image-download-ext-point-cd5809e11bbd09d3.yaml @ b'dd4ebfad130ec282a100ae49fcd0a6ec7a2be113'

- The ``[glance]/allowed_direct_url_schemes`` configuration option and
  ``nova.image.download.modules`` extension point have been deprecated for
  removal. These were originally added for the *nova.image.download.file*
  FileTransfer extension which was removed in the 16.0.0 Pike release. The
  ``nova.image.download.modules`` extension point is not maintained
  and there is no indication of its use in production clouds. If you are
  using this extension point, please make the nova development team
  aware by contacting us in the #openstack-nova freenode IRC channel or
  on the openstack-dev mailing list.

.. releasenotes/notes/deprecate-ironic-host-manager-bacb8d7b1e318e37.yaml @ b'c99fc64271f41a028c75e96348813f673d04e245'

- The ``IronicHostManager`` is now deprecated along with the
  ``[scheduler]/host_manager`` option of ``ironic_host_manager``.

  As of the 16.0.0 Pike release, the ``ExactRamFilter``, ``ExactCoreFilter``,
  and ``ExactDiskFilter`` scheduler filters are all deprecated along with
  the ``[scheduler]/use_baremetal_filters`` and
  ``[scheduler]/baremental_enabled_filters`` options. Deployments should
  migrate to using resource classes with baremetal flavors as described in
  the ironic install guide:

  https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-based-on-resource-classes

.. releasenotes/notes/deprecate-monkey-patch-5cd654924694b9ae.yaml @ b'a3bc1b067b4434a894288410201dc9c03aa7a50b'

- The following configuration options are deprecated for removal:

  - ``[DEFAULT]/monkey_patch``
  - ``[DEFAULT]/monkey_patch_modules``

  Monkey patching nova is not tested, not supported, and is a barrier to
  interoperability. If you have code which relies on monkey patching
  decorators, for example, for notifications, please propose those changes
  upstream.

  As a result, the following option is also deprecated for removal since it
  is only used when specified with ``[DEFAULT]/monkey_patch_modules``:

  - ``[notifications]/default_publisher_id``

.. releasenotes/notes/deprecate-nova-manage-commands-569835050b675180.yaml @ b'dcef0aa666a05e0053c928dd0fca0354f0f61f72'

- The ``nova-manage cell`` command has been deprecated. This command
  configures various aspects of the Cells v1 functionality. Cells v1 has
  been deprecated, thus, this command is also deprecated. It will be removed
  in its entirety when Cells v1 is removed.

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'9ed692bf8c84e0a702536101cd6cb084d33e1c26'

- Scheduling bare metal (ironic) instances using standard resource classes
  (VCPU, memory, disk) is deprecated and will no longer be supported in
  Queens.  Custom resource classes should be used instead.
  Please refer to the `ironic documentation
  <https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html#scheduling-based-on-resource-classes>`_
  for a detailed explanation.

.. releasenotes/notes/hyper-v-server-2012-support-deprecated-02a956e3926351d6.yaml @ b'2e51da875aceeb21d5bde9ab844c3882178ccd99'

- Support for Windows / Hyper-V Server 2012 has been deprecated in Queens
  in nova and will be removed in Rocky. The supported versions are Windows /
  Hyper-V Server 2012 R2 or newer.

.. releasenotes/notes/ironic-via-ksa-deffd3dac48ff4eb.yaml @ b'0a8f019be0f75005929724df3238b0a1ed49c88d'

- Configuration option ``[ironic]api_endpoint`` is deprecated in favor of
  ``[ironic]endpoint_override``.

.. releasenotes/notes/placement-via-ksa-02d87c87636912f8.yaml @ b'987d451f4d4c8006cc6e32ea2d966c749c2d9265'

- Configuration options in the ``[placement]`` section are deprecated as
  follows:

  * ``os_region_name`` is deprecated in favor of ``region_name``
  * ``os_interface`` is deprecated in favor of ``valid_interfaces``


.. _Release Notes_17.0.0_queens-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1664931-validate-image-rebuild-9c5b05a001c94a4d.yaml @ b'31d28eef95ab82bdfce2221cd5633bcf4bc13653'

- `OSSA-2017-005`_: Nova Filter Scheduler bypass through rebuild action

  By rebuilding an instance, an authenticated user may be able to circumvent
  the FilterScheduler bypassing imposed filters (for example, the
  ImagePropertiesFilter or the IsolatedHostsFilter). All setups using the
  FilterScheduler (or CachingScheduler) are affected.

  The fix is in the ``nova-api`` and ``nova-conductor`` services.

  .. _OSSA-2017-005: https://security.openstack.org/ossa/OSSA-2017-005.html

.. releasenotes/notes/bug-1732976-doubled-allocations-rebuild-23e4d3b06eb4f43f.yaml @ b'25a1d78e83065c5bea5d8e0a017fd9d0914d41d9'

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

.. releasenotes/notes/privsep-queens-4548989d1cbe3aeb.yaml @ b'f535e8bb9905b5632416135af5789704db6d2867'

- Privsep transitions. Nova is transitioning from using the older style rootwrap privilege escalation path to the new style Oslo privsep path. This should improve performance and security of Nova in the long term. - | privsep daemons are now started by nova when required. These daemons can be started via rootwrap if required. rootwrap configs therefore need to be updated to include new privsep daemon invocations.


.. _Release Notes_17.0.0_queens-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1482040-rebuild-volume-backed-new-image-1b8e130c06e05b86.yaml @ b'132636dd610d7e5cce24848776e942d229199e18'

- A fix is made for `bug 1482040`_ where a request to rebuild a volume-backed
  server with a new image which is different than what is in the root volume
  will now fail with a ``400 Bad Request`` response. The compute API would
  previously return a ``202 Accepted`` response but the backend compute service
  does not replace the image in the root disk so the API behavior was always
  wrong and is now explicit about the failure.

  .. _bug 1482040: https://bugs.launchpad.net/nova/+bug/1482040

.. releasenotes/notes/bug-1664931-refine-validate-image-rebuild-6d730042438eec10.yaml @ b'f7c688b8ef88a7390f5b09719a2b3e80368438c0'

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

.. releasenotes/notes/bug-1695861-ebc8a0aa7a87f7e0.yaml @ b'38b25397e805dcf7a995666049713304fe4f1af1'

- Fixes `bug 1695861`_ in which the aggregate API accepted requests that
  have availability zone names including ':'. With this fix, a creation
  of an availability zone whose name includes ':' results in a
  ``400 BadRequest`` error response.

  .. _bug 1695861: https://bugs.launchpad.net/nova/+bug/1695861

.. releasenotes/notes/bug-1712008-4ab2538211b8c3d9.yaml @ b'02a82c41f90a64f261d81cdc0bc57471d15a7c8e'

- When forcing a specified destination host during live migration, the
  scheduler is bypassed but resource allocations will still be made in the
  Placement service against the forced destination host. If the resource
  allocation against the destination host fails, the live migration operation
  will fail, regardless of the ``force`` flag being specified in the API.
  The guest will be unchanged on the source host. For more details, see
  `bug 1712008`_.

  .. _bug 1712008: https://bugs.launchpad.net/nova/+bug/1712008

.. releasenotes/notes/bug-1713786-0ee9e543683dafa4.yaml @ b'd564266a019cb009ece1a63e5d544698f2bf74d1'

- When forcing a specified destination host during evacuate, the
  scheduler is bypassed but resource allocations will still be made in the
  Placement service against the forced destination host. If the resource
  allocation against the destination host fails, the evacuate operation
  will fail, regardless of the ``force`` flag being specified in the API.
  The guest will be unchanged on the source host. For more details, see
  `bug 1713786`_.

  .. _bug 1713786: https://bugs.launchpad.net/nova/+bug/1713786

.. releasenotes/notes/bug-1732000-log-options-6db2cc8c747145ca.yaml @ b'53dc0917c57243ba96845b4ba72f4069ee0d21ac'

- The ``[DEFAULT]/log_options`` configuration option can be used to log
  configuration options at DEBUG level when the ``placement-api`` and/or
  ``nova-api`` services are started under WSGI. The default behavior is to
  log options on startup.

.. releasenotes/notes/bug-1733886-os-quota-sets-force-2.36-5866924621ecc857.yaml @ b'9ddbaa15cb55d1245a8a63d9414d134746fc2f3c'

- This release includes a fix for `bug 1733886`_ which was a regression
  introduced in the 2.36 API microversion where the ``force`` parameter was
  missing from the ``PUT /os-quota-sets/{tenant_id}`` API request schema so
  users could not force quota updates with microversion 2.36 or later. The
  bug is now fixed so that the ``force`` parameter can once again be
  specified during quota updates. There is no new microversion for this
  change since it is an admin-only API.

  .. _bug 1733886: https://bugs.launchpad.net/nova/+bug/1733886

.. releasenotes/notes/bug-1744325-rebuild-error-status-9e2da03f3f81fd6e.yaml @ b'd03a890a34f632adc9a19a33c8a5aebbccec50e4'

- If scheduling fails during rebuild the server instance will go to ERROR
  state and a fault will be recorded. `Bug 1744325`_

  .. _Bug 1744325: https://bugs.launchpad.net/nova/+bug/1744325

.. releasenotes/notes/config-cinder-admin-creds-b86038a3e87a1021.yaml @ b'ca6daf148debb9c9646fcf6db9660c830da5a594'

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

.. releasenotes/notes/fix-ironic-inventory-d565c77af83c710d.yaml @ b'9ed692bf8c84e0a702536101cd6cb084d33e1c26'

- The ironic virt driver no longer reports an empty inventory for bare metal
  nodes that have instances on them. Instead the custom resource class, VCPU,
  memory and disk are reported as they are configured on the node.

.. releasenotes/notes/ironic-empty-vcpus-66b4e1500ef8a34e.yaml @ b'b25928dc0459e44c5cef8c1f16db76d779fbf556'

- Fixes a bug preventing ironic nodes without VCPUs, memory or disk in their
  properties from being picked by nova.

.. releasenotes/notes/scheduler-limit-placement-650fc06be2a08781.yaml @ b'f029784eaf0d19bd7bb5d4eb66f1ea37d3036099'

- The FilterScheduler now limits the number of results in the query it makes
  to placement to avoid situations where every compute node in a large
  deployment is returned. This is configurable with the new
  ``[scheduler]/max_placement_results`` configuration option, which defaults
  to 1000, a sane starting value for any size deployment.

.. releasenotes/notes/unsettable-keymap-settings-fa831c02e4158507.yaml @ b'd983234288728427235ef2c1f355ec135119b865'

- It is now possible to unset the ``[vnc]keymap`` and ``[spice]keymap``
  configuration options. These were known to cause issues for some users
  with non-US keyboards and may be deprecated in the future.

.. releasenotes/notes/update-swap-decorator-7622a265df55feaa.yaml @ b'b40d949b3137473227949b597b2a61da41752ee5'

- prevent swap_volume action if the instance is in state SUSPENDED, STOPPED or SOFT_DELETED. A conflict (409) will be raised now as previously it used to fail silently.

.. releasenotes/notes/vmware-mem-stats-a9b6fac815d2bc57.yaml @ b'93bd310b91f2ca6034fea04a48e8399270db1816'

- Fixes how memory stats are reported for VMware. The total memory for the
  vCenter cluster managed by Nova should be the aggregated sum of total
  memory of each ESX host in the cluster. This is more accurate than using
  the available memory of the resource pool associated to the cluster.

.. releasenotes/notes/xentool-destory-cached-image-c9d39a733002ca7d.yaml @ b'693ace79fbf856967684f11dfd7663d465dbe19a'

- For the XenAPI driver, in order to delete cached images based on when they
  were created, a new ``--keep-days DAYS`` option is added to the
  ``destroy_cached_images`` script to delete cached images which were created
  at least ``DAYS`` days ago. By default, all unused cached images will be
  deleted when the script is run if they have ``cached_time``.


.. _Release Notes_17.0.0_queens-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bp-cinder-new-attach-apis-eca854e27a255e3e.yaml @ b'6d70d6adf9c902f0a9f1735ef90d992cbc0dcb46'

- Nova will now internally use a new flow for new volume attachments when:

  * All *nova-compute* services are upgraded
  * The *block-storage* 3.44 API microversion is available

  This change should be transparent to end users and does not affect existing
  volume attachments. Also, this does not affect how new volumes are created
  and attached during boot-from-volume when the
  ``block_device_mapping_v2.source_type`` is ``blank``, ``image`` or
  ``snapshot`` and the ``block_device_mapping_v2.destination_type`` is
  ``volume``.

  The motivation behind these changes are:

  * Track volume attachment state in the block storage service rather than
    the compute service (separation of duties, simplicity, etc)
  * Removal of technical debt from the compute service long-term
  * Enable a foundation on which to build support for multi-attach volumes

  More details can be found in the spec:

  https://specs.openstack.org/openstack/nova-specs/specs/queens/approved/cinder-new-attach-apis.html

.. releasenotes/notes/bug-1686136-b07bef4c56e92b31.yaml @ b'bd3da5d763d2dcb0426e9acaa419e9e9574569ca'

- Adds ``sata`` as a valid disk bus for qemu and kvm hypervisors. Setting the ``hw_disk_bus`` custom property on glance images allows for selecting the type of disk bus e.g. VIRTIO/IDE/SCSI. Some Linux (custom) images require use of SATA bus rather than any other that seem to be allowed.

.. releasenotes/notes/ironic_offline_flavor_migration-4845307799f0e24e.yaml @ b'8f8982d8ef381729ef12a14f37486335f31c4fd3'

- The ironic driver will automatically migrate instance flavors for resource classes
  at runtime. If you are not able to run the compute and ironic services at pike because
  you are automating an upgrade past this release, you can use the
  ``nova-manage db ironic_flavor_migration`` to push the migration manually. This is only
  for advanced users taking on the risk of automating the process of upgrading through
  pike and is not recommended for normal users.


