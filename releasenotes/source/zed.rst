========================
Zed Series Release Notes
========================

.. _Release Notes_26.3.0_zed-eom:

26.3.0
======

.. _Release Notes_26.3.0_zed-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/libvirt-enlightenments-stop-unconditionally-enabling-evmcs-993a825641c4b9f3.yaml @ b'3ef339a383e7e23085a582260badb347d96d8935'

- Bug 2009280 has been fixed by no longer enabling the evmcs enlightenment in
  the libvirt driver. evmcs only works on Intel CPUs, and domains with that
  enlightenment cannot be started on AMD hosts. There is a possible future
  feature to enable support for generating this enlightenment only when
  running on Intel hosts.


.. _Release Notes_26.2.1_zed-eom:

26.2.1
======

.. _Release Notes_26.2.1_zed-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/translate_vf_network_capabilities_to_port_binding-48abbfe0ce2923cf.yaml @ b'c36e0db95749395d5915b366fe6d36f516151c1a'

- Previously ``switchdev`` capabilities should be configured manually by a
  user with admin privileges using port's binding profile. This blocked
  regular users from managing ports with Open vSwitch hardware offloading
  as providing write access to a port's binding profile to non-admin users
  introduces security risks. For example, a binding profile may contain a
  ``pci_slot`` definition, which denotes the host PCI address of the
  device attached to the VM. A malicious user can use this parameter to
  passthrough any host device to a guest, so it is impossible to provide
  write access to a binding profile to regular users in many scenarios.

  This patch fixes this situation by translating VF capabilities reported
  by Libvirt to Neutron port binding profiles. Other VF capabilities are
  translated as well for possible future use.


.. _Release Notes_26.2.1_zed-eom_Other Notes:

Other Notes
-----------

.. releasenotes/notes/Do-not-send-mtu-value-in-metadata-for-networks-with-enabled-dhcp-641506f2a13b540f.yaml @ b'ec15df83d2d8eb9744438c7129f64a00e5c5694e'

- For networks which have any subnets with enabled DHCP, MTU value is not send
  in the metadata. In such case MTU is configured through the DHCP server.


.. _Release Notes_26.2.0_zed-eom:

26.2.0
======

.. _Release Notes_26.2.0_zed-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/service-user-token-421d067c16257782.yaml @ b'8b4b99149a35663fc11d7d163082747b1b210b4d'

- Configuration of service user tokens is now **required** for all Nova services
  to ensure security of block-storage volume data.

  All Nova configuration files must configure the ``[service_user]`` section as
  described in the `documentation`__.

  See https://bugs.launchpad.net/nova/+bug/2004555 for more details.

  __ https://docs.openstack.org/nova/latest/admin/configuration/service-user-token.html


.. _Release Notes_26.1.1_zed-eom:

26.1.1
======

.. _Release Notes_26.1.1_zed-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/rescue-volume-based-instance-c6e3fba236d90be7.yaml @ b'd00a848a735f98b028f5930798ee69ef205c8e2e'

- Fix rescuing volume based instance by adding a check for 'hw_rescue_disk'
  and 'hw_rescue_device' properties in image metadata before attempting
  to rescue instance.


.. _Release Notes_26.1.0_zed-eom:

26.1.0
======

.. _Release Notes_26.1.0_zed-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-ironic-scheduler-race-08cf8aba0365f512.yaml @ b'c9de185ea1ac1e8d4435c5863b2ad7cefdb28c76'

- Fixed when placement returns ironic nodes that have just started automatic
  cleaning as possible valid candidates. This is done by marking all ironic
  nodes with an instance on them as reserved, such that nova only makes them
  available once we have double checked Ironic reports the node as available.
  If you don't have automatic cleaning on, this might mean it takes longer
  than normal for Ironic nodes to become available for new instances.
  If you want the old behaviour use the following workaround config:
  ``[workarounds]skip_reserve_in_use_ironic_nodes=true``

.. releasenotes/notes/multiple-config-files-with-mod_wsgi-f114ea5fdd8b9a51.yaml @ b'd92d0934188a14741dd86949ddf98bd1208f3d96'

- apache mod_wsgi does not support passing commandline arguments to the wsgi
  application that it hosts. As a result when the nova api or metadata api
  where run under mod_wsgi it was not possible to use multiple config files
  or non-default file names i.e. nova-api.conf
  This has been addressed by the introduction of a new, optional, environment
  variable ``OS_NOVA_CONFIG_FILES``. ``OS_NOVA_CONFIG_FILES`` is a ``;``
  separated list of file path relative to ``OS_NOVA_CONFIG_DIR``.
  When unset the default ``api-paste.ini`` and ``nova.conf`` will be used
  form ``/etc/nova``. This is supported for the nova api and nova metadata
  wsgi applications.


.. _Release Notes_26.1.0_zed-eom_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1982284-libvirt-handle-no-ram-info-was-set-99784934ed80fd72.yaml @ b'00396fa9396324780c09161ed57a86b7e458c26f'

- A workaround has been added to the libvirt driver to catch and pass
  migrations that were previously failing with the error:

  ``libvirt.libvirtError: internal error: migration was active, but no RAM info was set``

  See `bug 1982284`_ for more details.

  .. _bug 1982284: https://bugs.launchpad.net/nova/+bug/1982284


.. _Release Notes_26.0.0_zed-eom:

26.0.0
======

.. _Release Notes_26.0.0_zed-eom_Prelude:

Prelude
-------

.. releasenotes/notes/zed-prelude-a3cddb8b2ac8e293.yaml @ b'cfd3aa8dfc4d69f9766602bffe9229596b9a93d4'

The 26.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 25.0.0 (Yoga) to 26.0.0 (Zed).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Zed is `v2.93`__.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#maximum-in-zed

- `Virtual IOMMU devices`__  can now be created and attached to an instance
  when running on a x86 host
  and using the libvirt driver.

  .. __: https://docs.openstack.org/nova/latest/admin/pci-passthrough.html#virtual-iommu-support

- Improved behavior for Windows guest by adding by default following
  `Hyper-V enlightments`__ on all libvirt guests : ``vpindex``, ``runtime``,
  ``synic``, ``reset``, ``frequencies``, ``reenlightenment``, ``tlbflush``, ``ipi`` and
  ``evmc``.

  .. __: https://libvirt.org/formatdomain.html#hypervisor-features

- All lifecycle actions are now fully supported for
  `instances with vDPA ports`__, including vDPA hot-plug live migration,
  suspend and attach/detach.

  .. __: https://docs.openstack.org/nova/latest/admin/vdpa.html

- Volume-backed instances (instances with root disk attached as a volume)
  can now be rebuilt by specifying a 2.93 microversion instead of returning
  a HTTP400 exception.

- The ``unshelve`` instance API action now provides a new ``host`` parameter
  with 2.91 microversion (for only admins).

- With microversion 2.92, you can only import a public key and not generate
  a keypair. You can also use an extended name pattern.

- The default system scope is removed from all APIs hence finishing to
  implement `phase #1 of new RBAC guidelines`__ that are opt-in.

  .. __: https://governance.openstack.org/tc/goals/selected/consistent-and-secure-rbac.html#phase-1


.. _Release Notes_26.0.0_zed-eom_New Features:

New Features
------------

.. releasenotes/notes/add-volume-rebuild-b973562ea8f49347.yaml @ b'45c5b80fd076d0017f957a2150d7496f6d4a4fcf'

- Added support for rebuilding a volume-backed instance with a different
  image. This is achieved by reimaging the boot volume i.e. writing new
  image on the boot volume at cinder side.
  Previously rebuilding volume-backed instances with same image was
  possible but this feature allows rebuilding volume-backed instances
  with a different image than the existing one in the boot volume.
  This is supported starting from API microversion 2.93.

.. releasenotes/notes/bp-keypair-generation-removal-3004a8643dcd1fd9.yaml @ b'a755e5d9f25c7bb06533a3799d9c39b74f334873'

- The 2.92 microversion makes the following changes:

  * Make public_key a mandatory parameter for keypair creation. This means
    that by this microversion, Nova will stop to support automatic keypair
    generations. Only imports will be possible.
  * Allow 2 new special characters: '@' and '.' (dot),
    in addition to the existing constraints of ``[a-z][A-Z][0-9][_- ]``

.. releasenotes/notes/bp-pci-device-tracking-in-placement-75ee1d20a57662f2.yaml @ b'efb6fd834eed77e0345ba88dc4e692426d7c12b7'

- Nova started tracking PCI devices in Placement. This is an optional feature
  disabled by default while we are implementing inventory tracking and
  scheduling support for both PCI passthrough devices and SR-IOV devices
  consumed via Neutron ports. Please read our
  `documentation <https://docs.openstack.org/nova/latest/admin/pci-passthrough.html#pci-tracking-in-placement>`_
  for more details on what is supported how this feature can be enabled.

.. releasenotes/notes/bp-unshelve_to_host-c9047d518eb67747.yaml @ b'09239fc2eadcf266b42c640e386c7cebad715eea'

- Microversion 2.91 adds the optional parameter ``host`` to
  the ``unshelve`` server action API.
  Specifying a destination host is only
  allowed to admin users and server status must be ``SHELVED_OFFLOADED``
  otherwise a HTTP 400 (bad request) response is returned.
  It also allows to set ``availability_zone`` to None to unpin a server
  from an availability_zone.

.. releasenotes/notes/guest-iommu-device-4795c3a060aca424.yaml @ b'14e3b352c24b2a1fe54ba13a733cf6e7989215cc'

- The Libvirt driver can now add a virtual IOMMU device
  to all created guests, when running on an x86 host and using the Q35
  machine type or on AArch64.

  To enable this, provide ``hw:viommu_model`` in flavor extra
  spec or equivalent image metadata property ``hw_viommu_model`` and with the
  guest CPU architecture and OS allows, we will enable viommu in Libvirt
  driver. Support values intel|smmuv3|virtio|auto. Default to ``auto``.
  Which ``auto`` will automatically select ``virtio`` if Libvirt supports it,
  else ``intel`` on X86 (Q35) and ``smmuv3`` on AArch64.
  vIOMMU config will raise invalid exception if the guest architecture is
  neither X86 (Q35) or AArch64.

  Note that, enable vIOMMU might introduce significant performance overhead.
  You can see performance comparison table from
  `AMD vIOMMU session on KVM Forum 2021`_.
  For above reason, vIOMMU should only be enable for workflow that require it.
  .. _`AMD vIOMMU session on KVM Forum 2021`: https://static.sched.com/hosted_files/kvmforum2021/da/vIOMMU%20KVM%20Forum%202021%20-%20v4.pdf

.. releasenotes/notes/new_locked_memory_option-b68a031779366828.yaml @ b'572c2b18e27f6fcbbd4a1f416b0ec21098b3ba74'

- Add new ``hw:locked_memory`` extra spec and ``hw_locked_memory`` image
  property to lock memory on libvirt guest. Locking memory marks the guest
  memory allocations as unmovable and unswappable.
  ``hw:locked_memory`` extra spec and ``hw_locked_memory`` image property
  accept boolean values in string format like 'Yes' or 'false' value.
  Exception ``LockMemoryForbidden`` will raise, if you set lock memory value
  but not set either flavor extra spec
  ``hw:mem_page_size`` or image property ``hw_mem_page_size``,
  so we can ensure that the scheduler can actually account for this correctly
  and prevent out of memory events.

.. releasenotes/notes/project-reader-rbac-8a1d11b3b2e776fd.yaml @ b'69034568205839830c73d0ffe6ec19dd866140ce'

- The Nova policies have been modified to drop the system scope. Every
  API policy is scoped to project. This means that system scoped users
  will get 403 permission denied error.

  Also, the project reader role is ready to use. Users with reader role
  can only perform the read-only operations within their project. This
  role can be used for the audit purposes.

  Currently, nova supports the following roles:

  * ``admin`` (Legacy admin)
  * ``project member``
  * ``project reader``

  For the details on what changed from the existing policy, please refer
  to the `RBAC new guidelines`_. We have implemented only phase-1 of the
  `RBAC new guidelines`_.
  Currently, scope checks and new defaults are disabled by default. You can
  enable them by switching the below config option in ``nova.conf`` file::

    [oslo_policy]
    enforce_new_defaults=True
    enforce_scope=True

  We recommend to enable the both scope as well new defaults together
  otherwise you may experience some late failures with unclear error
  messages.

  Please refer `Policy New Defaults`_ for detail about policy new defaults
  and migration plan.

  .. _`RBAC new guidelines`: https://governance.openstack.org/tc/goals/selected/consistent-and-secure-rbac.html#phase-1
  .. _`Policy New Defaults`: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html

.. releasenotes/notes/update-libvirt-enlightenments-for-windows-23abea98cc1db667.yaml @ b'57ab45323cf5617ebd2decd757e708673d949a8f'

- The following enlightenments are now added by default to the libvirt XML for Windows guests:

  * vpindex
  * runtime
  * synic
  * reset
  * frequencies
  * reenlightenment
  * tlbflush
  * ipi
  * evmc

  This adds to the list of already existing enlightenments, namely:

  * relaxed
  * vapic
  * spinlocks retries
  * vendor_id spoofing

.. releasenotes/notes/vdpa-suspend-detach-and-live-migrate-e591e6a03a0c834d.yaml @ b'0aad338b1c68f319df603bca340ff33dc7fd7b54'

- vDPA support was first introduced in the 23.0.0 (Wallaby)
  release with limited instance lifecycle operations. Nova now supports
  all instance lifecycle operations including suspend, attach/detach
  and hot-plug live migration.

  QEMU and the Linux kernel do not currently support transparent
  live migration of vDPA devices at this time. Hot-plug live migration
  unplugs the VDPA device on the source host before the VM is live migrated
  and automatically hot-plugs the device on the destination after the
  migration. While this can lead to packet loss it enable live migration
  to be used when needed until transparent live migration can be added
  in a future release.

  VDPA Hot-plug live migration requires all compute services to be upgraded
  to service level 63 to be enabled. Similarly suspend resume need service
  level 63 and attach/detach require service level 62.
  As such it will not be available to use during a rolling upgrade but will
  become available when all host are upgraded to the 26.0.0 (Zed) release.

  With the addition of these features, all instance lifecycle operations are
  now valid for VMs with VDPA neutron ports.


.. _Release Notes_26.0.0_zed-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/skip-compare-cpu-on-dest-6ae419ddd61fd0f8.yaml @ b'267a40663cd8d0b94bbc5ebda4ece55a45753b64'

- Nova's use of libvirt's compareCPU() API served its purpose over the
  years, but its design limitations break live migration in subtle
  ways. For example, the compareCPU() API compares against the host
  physical CPUID. Some of the features from this CPUID aren not
  exposed by KVM, and then there are some features that KVM emulates
  that are not in the host CPUID. The latter can cause bogus live
  migration failures.

  With QEMU >=2.9 and libvirt >= 4.4.0, libvirt will do the right
  thing in terms of CPU compatibility checks on the destination host
  during live migration. Nova satisfies these minimum version
  requirements by a good margin. So, this workaround provides a way to
  skip the CPU comparison check on the destination host before
  migrating a guest, and let libvirt handle it correctly.

  This workaround will be deprecated and removed once Nova replaces
  the older libvirt APIs with their newer counterparts. The work is
  being tracked via this `blueprint
  cpu-selection-with-hypervisor-consideration`_.

  .. _blueprint cpu-selection-with-hypervisor-consideration: https://blueprints.launchpad.net/nova/+spec/cpu-selection-with-hypervisor-consideration


.. _Release Notes_26.0.0_zed-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/default-host-numa-strategy-to-spread-18668c6d80154042.yaml @ b'e76ec7af4d30604e3df9423226ebda90035f30b2'

- During the triage of https://bugs.launchpad.net/nova/+bug/1978372
  we compared the performance of nova's numa allocations strategies
  as it applied to the large numbers of host and guest numa nodes.
  Prior to ``Xena`` nova only supported a linear packing strategy.
  In ``Xena`` ``[compute]/packing_host_numa_cells_allocation_strategy``
  was introduced maintaining the previous packing behavior by default.
  The numa allocation strategy has now been defaulted to spread.
  The old behavior can be restored by defining:
  ``[compute]/packing_host_numa_cells_allocation_strategy=true``

.. releasenotes/notes/deprecate-use_forwarded_for-f7b24eaf130782b9.yaml @ b'cf906cdcc25c112956f56f9fb9f62b2cfdeacc65'

- The default ``api-paste.ini`` file has been updated and now the Metadata
  API pipeline includes the ``HTTPProxyToWSGI`` middleware.

.. releasenotes/notes/drop-python-3-6-and-3-7-cd3bf1e945f05fd3.yaml @ b'b70cd298fc04b2aa667e0071074faacc21cd93ef'

- Python 3.6 & 3.7 support has been dropped. The minimum version of Python now
  supported by nova is Python 3.8.

.. releasenotes/notes/remove-default-cputune-shares-values-85d5ddf4b8e24eaa.yaml @ b'f77a9fee5b736899ecc39d33e4f4e4012cee751c'

- In the libvirt driver, the default value of the ``<cputune><shares>``
  element has been removed, and is now left to libvirt to decide. This is
  because allowed values are platform dependent, and the previous code was
  not guaranteed to be supported on all platforms. If any of your flavors are
  using the quota:cpu_shares extra spec, you may need to resize to a
  supported value before upgrading.

  To facilitate the transition to no Nova default for ``<cputune><shares>``,
  its value will be removed during live migration unless a value is set in
  the ``quota:cpu_shares`` extra spec. This can cause temporary CPU
  starvation for the live migrated instance if other instances on the
  destination host still have the old default ``<cputune><shares>`` value. To
  fix this, hard reboot, cold migrate, or live migrate the other instances.

.. releasenotes/notes/remove-powervm-6132cc10255ca205.yaml @ b'deae81461123e7d61b3a6eca6f085a9d7ee5689e'

- The powervm virt driver has been removed. The driver was not tested by
  the OpenStack project nor did it have clear maintainers and thus its
  quality could not be ensured.

.. releasenotes/notes/too-old-compute-check-code-7dbcde45cfd23394.yaml @ b'9af4c6115fcfce9c76a1e7fd5b93bb43cec66a4d'

- The upgrade check tooling now returns a non-zero exit code in the presence
  of compute node services that are too old. This is to avoid situations in
  which Nova control services fail to start after an upgrade.


.. _Release Notes_26.0.0_zed-eom_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-passthrough_whitelist-config-name-0530d502c960d753.yaml @ b'14e68ac6e996587a969a6006030cbca686643dd9'

- The [pci]passthrough_whitelist config option is renamed to
  [pci]device_spec. The old name is deprecated and aliased to the new one.
  The old name will be removed in a future release.

.. releasenotes/notes/deprecate-use_forwarded_for-f7b24eaf130782b9.yaml @ b'cf906cdcc25c112956f56f9fb9f62b2cfdeacc65'

- The ``[api] use_forwarded_for`` parameter has been deprecated. Instead of
  using this parameter, add the ``HTTPProxyToWSGI`` middleware to api
  pipelines, and ``[oslo_middleware] enable_proxy_headers_parsing = True``
  to nova.conf.


.. _Release Notes_26.0.0_zed-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1942329-22b08fa4b322881d.yaml @ b'cd03bbc1c33e33872594cf002f0e7011ab8ea047'

- As a fix for `bug 1942329 <https://bugs.launchpad.net/neutron/+bug/1942329>`_
  nova now updates the MAC address of the ``direct-physical`` ports during
  mova operations to reflect the MAC address of the physical device on the
  destination host. Those servers that were created before this fix need to be
  moved or the port needs to be detached and the re-attached to synchronize the
  MAC address.

.. releasenotes/notes/bug-1944619-fix-live-migration-rollback.yaml @ b'63ffba7496182f6f6f49a380f3c639fc3ded9772'

- Instances with hardware offloaded ovs ports no longer lose connectivity
  after failed live migrations. The driver.rollback_live_migration_at_source
  function is no longer called during during pre_live_migration rollback
  which previously resulted in connectivity loss following a failed live
  migration. See `Bug 1944619`_ for more details.

  .. _Bug 1944619: https://bugs.launchpad.net/nova/+bug/1944619

.. releasenotes/notes/bug-1967157-extend-encrypted.yaml @ b'8fbaeba11f445bcf6c6be1f5f7b7aeeb6995c9cd'

- Extending attached encrypted volumes that failed before because they were
  not being decrypted using libvirt (any other than LUKS) now work as
  expected and the new size will be visible within the instance. See
  `Bug 1967157`_ for more details.

  .. _Bug 1967157: https://bugs.launchpad.net/nova/+bug/1967157

.. releasenotes/notes/bug-1970383-segment-scheduling-permissions-92ba907b10a9eb1c.yaml @ b'ee32934f34afd8e6df467361e9d71788cd36f6ee'

- `Bug #1970383 <https://bugs.launchpad.net/nova/+bug/1970383>`_: Fixes a
  permissions error when using the
  'query_placement_for_routed_network_aggregates' scheduler variable, which
  caused a traceback on instance creation for non-admin users.

.. releasenotes/notes/bug-1978372-optimized-numa-fitting-algorithm-5d5b922b0bdbf818.yaml @ b'099a6f63af7805440d91976ba0ea03bc6c278280'

- The algorithm that is used to see if a multi NUMA guest fits to
  a multi NUMA host has been optimized to speed up the decision
  on hosts with high number of NUMA nodes ( > 8). For details see
  `bug 1978372`_

  .. _bug 1978372: https://bugs.launchpad.net/nova/+bug/1978372

.. releasenotes/notes/bug-1978444-db46df5f3d5ea19e.yaml @ b'8f4b740ca5292556f8e953a30f2a11ed4fbc2945'

- `Bug #1978444 <https://bugs.launchpad.net/nova/+bug/1978444>`_: Now nova
  retries deleting a volume attachment in case Cinder API returns
  ``504 Gateway Timeout``. Also, ``404 Not Found`` is now ignored and
  leaves only a warning message.

.. releasenotes/notes/bug-1981813-vnic-type-change-9f3e16fae885b57f.yaml @ b'e43bf900dc8ca66578603bed333c56b215b1876e'

- `Bug #1981813 <https://bugs.launchpad.net/nova/+bug/1981813>`_: Now nova
  detects if the ``vnic_type`` of a bound port has been changed in neutron
  and leaves an ERROR message in the compute service log as such change on a
  bound port is not supported. Also the restart of the nova-compute service
  will not crash any more after such port change. Nova will log an ERROR and
  skip the  initialization of the instance with such port during the startup.

.. releasenotes/notes/bug-1983753-update-requestspec-pci_request-for-resize-a3c6b0a979db723f.yaml @ b'82cdfa23c7a0e269ab038e241bb7428b7f1391aa'

- `Bug #1941005 <https://bugs.launchpad.net/nova/+bug/1941005>`_ is fixed.
  During resize Nova now uses the PCI requests from the new flavor to select
  the destination host.

.. releasenotes/notes/bug-1986838-pci-double-booking-1da71ea4399db65a.yaml @ b'2b447b7236f95752d00ebcee8c32cfef4850cf5d'

- `Bug #1986838 <https://bugs.launchpad.net/nova/+bug/1986838>`_: Nova now
  correctly schedules an instance that requests multiple PCI devices via
  multiple PCI aliases in the flavor extra_spec when multiple similar devices
  are requested but the compute host has only one such device matching with
  each request individually.

.. releasenotes/notes/fix-group-policy-validation-with-deleted-groups-4f685fd1d6b84192.yaml @ b'cd2c2f359bbd4913cfe73199847bc35b2664aaa9'

- When the server group policy validation upcall is enabled
  nova will assert that the policy is not violated on move operations
  and initial instance creation. As noted in `bug 1890244`_, if a
  server was created in a server group and that group was later deleted
  the validation upcall would fail due to an uncaught exception if the
  server group was deleted. This prevented evacuate and other move
  operations form functioning. This has now been fixed and nova will
  ignore deleted server groups.

  .. _bug 1890244: https://bugs.launchpad.net/nova/+bug/1890244

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'db919aa15f24c0d74f3c5c0e8341fad3f2392e57'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/validate-machine-type-0d5f3dbd1e2ace31.yaml @ b'467bbee7581ed2fd68c483914d12ee4c7a8b7773'

- Added validation for image machine type property. Different APIs which
  uses machine type for server creation, resize or rebuild will raise
  InvalidMachineType exception with message "provided machine type is not
  supported by host" and suggest possible/valid machine types in compute logs.
  For more details see: `bug 1933097`_

  .. _`bug 1933097`: https://bugs.launchpad.net/nova/+bug/1933097

.. releasenotes/notes/vdpa-move-ops-a7b3799807807a92.yaml @ b'95f96ed3aa201bc5b90e589b288fa4039bc9c0d2'

- When vDPA was first introduced move operations were implemented in the code
  but untested either in a real environment or in functional tests. Due to
  this gap nova elected to block move operations for instance with vDPA
  devices. All move operations except for live migration have now been tested
  and found to indeed work so the API blocks have now been removed and
  functional tests introduced. Other operations such as suspend and
  live migration require code changes to support and will be enabled as new
  features in the future.

.. releasenotes/notes/vmware-add-ram-size-multiple-of-4-validation-9740bf60d59ce5e2.yaml @ b'08e8bdf2711d717adc1028b5acecd81e4ce71572'

- For the VMware ESXi, VM memory should be multiple of 4. Otherwise creating
  instance on ESXi fails with error "VimFaultException: Memory (RAM) size is
  invalid.". Instances will now fail to spawn if flavor memory is not a
  multiple of 4.


