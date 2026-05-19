=========================
Yoga Series Release Notes
=========================

.. _Release Notes_25.3.0_yoga-eom:

25.3.0
======

.. _Release Notes_25.3.0_yoga-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/remove-default-cputune-shares-values-85d5ddf4b8e24eaa.yaml @ b'0a6b57a9a24a0936383aaf444c690772aacc3245'

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


.. _Release Notes_25.2.1_yoga-eom:

25.2.1
======

.. _Release Notes_25.2.1_yoga-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1983753-update-requestspec-pci_request-for-resize-a3c6b0a979db723f.yaml @ b'19bac6e9c362ee692f4be92041bb3f6c3b9b6c23'

- `Bug #1941005 <https://bugs.launchpad.net/nova/+bug/1941005>`_ is fixed.
  During resize Nova now uses the PCI requests from the new flavor to select
  the destination host.


.. _Release Notes_25.2.0_yoga-eom:

25.2.0
======

.. _Release Notes_25.2.0_yoga-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/service-user-token-421d067c16257782.yaml @ b'4d8efa2d196f72fdde33136a0b50c4ee8da3c941'

- Configuration of service user tokens is now **required** for all Nova services
  to ensure security of block-storage volume data.

  All Nova configuration files must configure the ``[service_user]`` section as
  described in the `documentation`__.

  See https://bugs.launchpad.net/nova/+bug/2004555 for more details.

  __ https://docs.openstack.org/nova/latest/admin/configuration/service-user-token.html


.. _Release Notes_25.1.1_yoga-eom:

25.1.1
======

.. _Release Notes_25.1.1_yoga-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-group-policy-validation-with-deleted-groups-4f685fd1d6b84192.yaml @ b'7934b9ec57d7060fbcf27706aa98ebf5a83f920a'

- When the server group policy validation upcall is enabled
  nova will assert that the policy is not violated on move operations
  and initial instance creation. As noted in `bug 1890244`_, if a
  server was created in a server group and that group was later deleted
  the validation upcall would fail due to an uncaught exception if the
  server group was deleted. This prevented evacuate and other move
  operations form functioning. This has now been fixed and nova will
  ignore deleted server groups.

  .. _bug 1890244: https://bugs.launchpad.net/nova/+bug/1890244

.. releasenotes/notes/rescue-volume-based-instance-c6e3fba236d90be7.yaml @ b'4073aa51f79be54e2e6e8143666a7c1f9a00e03d'

- Fix rescuing volume based instance by adding a check for 'hw_rescue_disk'
  and 'hw_rescue_device' properties in image metadata before attempting
  to rescue instance.


.. _Release Notes_25.1.0_yoga-eom:

25.1.0
======

.. _Release Notes_25.1.0_yoga-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/skip-compare-cpu-on-dest-6ae419ddd61fd0f8.yaml @ b'277f88e3872ea41bce02d09c4537946a74d74533'

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


.. _Release Notes_25.1.0_yoga-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1942329-22b08fa4b322881d.yaml @ b'813377077bd0173bdf128823e46b5df7c0a575b9'

- As a fix for `bug 1942329 <https://bugs.launchpad.net/neutron/+bug/1942329>`_
  nova now updates the MAC address of the ``direct-physical`` ports during
  mova operations to reflect the MAC address of the physical device on the
  destination host. Those servers that were created before this fix need to be
  moved or the port needs to be detached and the re-attached to synchronize the
  MAC address.

.. releasenotes/notes/bug-1978444-db46df5f3d5ea19e.yaml @ b'b94ffb1123b1a6cf0a8675e0d6f1072e9625f570'

- `Bug #1978444 <https://bugs.launchpad.net/nova/+bug/1978444>`_: Now nova
  retries deleting a volume attachment in case Cinder API returns
  ``504 Gateway Timeout``. Also, ``404 Not Found`` is now ignored and
  leaves only a warning message.

.. releasenotes/notes/bug-1981813-vnic-type-change-9f3e16fae885b57f.yaml @ b'a28c82719545d5c8ee7f3ff1361b3a796e05095a'

- `Bug #1981813 <https://bugs.launchpad.net/nova/+bug/1981813>`_: Now nova
  detects if the ``vnic_type`` of a bound port has been changed in neutron
  and leaves an ERROR message in the compute service log as such change on a
  bound port is not supported. Also the restart of the nova-compute service
  will not crash any more after such port change. Nova will log an ERROR and
  skip the  initialization of the instance with such port during the startup.

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'6d61fccb8455367aaa37ae7bddf3b8befd3c3d88'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/vdpa-move-ops-a7b3799807807a92.yaml @ b'041939361e393b808724b8590eb76b3aa075814e'

- When vDPA was first introduced move operations were implemented in the code
  but untested either in a real environment or in functional tests. Due to
  this gap nova elected to block move operations for instance with vDPA
  devices. All move operations except for live migration have now been tested
  and found to indeed work so the API blocks have now been removed and
  functional tests introduced. Other operations such as suspend and
  live migration require code changes to support and will be enabled as new
  features in the future.


.. _Release Notes_25.1.0_yoga-eom_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1982284-libvirt-handle-no-ram-info-was-set-99784934ed80fd72.yaml @ b'4316234e63b76e4f9877ec6e924b5c54ea761bbb'

- A workaround has been added to the libvirt driver to catch and pass
  migrations that were previously failing with the error:

  ``libvirt.libvirtError: internal error: migration was active, but no RAM info was set``

  See `bug 1982284`_ for more details.

  .. _bug 1982284: https://bugs.launchpad.net/nova/+bug/1982284


.. _Release Notes_25.0.1_yoga-eom:

25.0.1
======

.. _Release Notes_25.0.1_yoga-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1944619-fix-live-migration-rollback.yaml @ b'29b94aa34ad954e617c2a0d6df0809765dced188'

- Instances with hardware offloaded ovs ports no longer lose connectivity
  after failed live migrations. The driver.rollback_live_migration_at_source
  function is no longer called during during pre_live_migration rollback
  which previously resulted in connectivity loss following a failed live
  migration. See `Bug 1944619`_ for more details.

  .. _Bug 1944619: https://bugs.launchpad.net/nova/+bug/1944619

.. releasenotes/notes/bug-1970383-segment-scheduling-permissions-92ba907b10a9eb1c.yaml @ b'60548e804219d91d8c68ab3d74dd0ae956cd33f3'

- `Bug #1970383 <https://bugs.launchpad.net/nova/+bug/1970383>`_: Fixes a
  permissions error when using the
  'query_placement_for_routed_network_aggregates' scheduler variable, which
  caused a traceback on instance creation for non-admin users.


.. _Release Notes_25.0.0_yoga-eom:

25.0.0
======

.. _Release Notes_25.0.0_yoga-eom_Prelude:

Prelude
-------

.. releasenotes/notes/yoga-prelude-31dd83eb18c789f6.yaml @ b'9f1c28e4aea9a7830026e6b1c72ee9b765f45ac1'

The 25.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 24.0.0 (Xena) to 25.0.0 (Yoga).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Yoga is `v2.90`__ (same
  as the Xena release).

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html

- Experimental support is added for Keystone's `unified limits`__.
  This will allow operators to test this feature in non-production
  systems so we can collect early feedback about performance.

  .. __: https://docs.openstack.org/keystone/latest/admin/unified-limits.html

- Keystone's policy concepts of system vs. project scope and roles has been
  implemented in Nova and `defaults roles and scopes have been defined`__,
  while legacy policies continue to be enabled by default. Operators are
  encouraged to familiarize with the new policies and `enable them
  in advance`__ before Nova switches from the legacy roles in a later
  release.

  .. __: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html#nova-supported-scope-roles
  .. __: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html#migration-plan


- Support is added for network backends that leverage SmartNICs to
  `offload the control plane from the host server`__. Accordingly, Neutron
  needs to be `configured`__ in order to enable it correctly.
  Increased security is enabled by removing the control plane from the
  host server and overhead is reduced by leveraging the cpu and ram
  resources on modern SmartNIC DPUs.

  .. __: https://docs.openstack.org/nova/latest/admin/networking.html#sr-iov
  .. __: https://docs.openstack.org/neutron/latest/admin/ovn/smartnic_dpu


- Experimental support for `emulated architecture is now implemented`__.
  AArch64, PPC64LE, MIPs, and s390x guest architectures are
  available independent of the host architecture. This is strictly not
  intended for production use for various reasons, including no security
  guarantees.

  .. __: https://docs.openstack.org/nova/latest/admin/hw-emulation-architecture.html


.. _Release Notes_25.0.0_yoga-eom_New Features:

New Features
------------

.. releasenotes/notes/add-vmware-fcd-support-822edccb0e38bc37.yaml @ b'd5faf45e9df00528e6e3aa55cd2edd184181a249'

- Added support for VMware VStorageObject based volumes in
  VMware vCenter driver. vSphere version 6.5 is required.

.. releasenotes/notes/announce-self-post-live-migration-936721b1ab887514.yaml @ b'd44e24efe28e825fbfd2c75a032bf2d10109a439'

- Added a new configuration option ``[workarounds]/enable_qemu_monitor_announce_self``
  that when enabled causes the Libvirt driver to send a announce_self QEMU
  monitor command post live-migration. Please see `bug 1815989 <https://bugs.launchpad.net/nova/+bug/1815989>`_
  for more details. Please note that this causes the domain to be considered
  tainted by libvirt.

.. releasenotes/notes/bp-boot-vm-with-unaddressed-port-4cb05bb6dc859d98.yaml @ b'0d71c5a1c1f0e474d4b612eadf8787172af34e15'

- Nova now allows to create an instance with a non-deferred port that has no fixed IP address if the network backend has level-2 connectivity.

.. releasenotes/notes/bp-pick-guest-arch-based-on-host-arch-in-libvirt-driver-f087c3799d388bb6.yaml @ b'31ff7ce7e21fc7c654ab7b4187774fec5be371ca'

- image meta now includes the ``hw_emulation_architecture`` property.
  This allows an operator to define their emulated cpu architecture for
  an image, and nova will deploy accordingly.

  See the `spec`_ for more details and reasoning.

  .. _spec: https://specs.openstack.org/openstack/nova-specs/specs/yoga/approved/pick-guest-arch-based-on-host-arch-in-libvirt-driver.html

.. releasenotes/notes/bp-policy-defaults-refresh-2-473c70f641f9f397.yaml @ b'f9c1d1163ddd924b0721f5dd7146a2a87a2afa31'

- The Nova policies have been modified to isolate the system and project
  level APIs policy. This means system users will be allowed to perform
  the operation on system level resources and will not to allowed any
  operation on project level resources. Project Level APIs operation will be
  performed by the project scoped users.
  Currently, nova supports:

  * ``system admin``
  * ``project admin``
  * ``project member``
  * ``project reader``

  For the details on what changed from the existing policy, please refer the
  `RBAC new guidelines`_. We have implemented only phase-1
  `RBAC new guidelines`_.
  Currently, scope checks and new defaults are disabled by default. You can
  enable them by switching the below config option in ``nova.conf`` file::

    [oslo_policy]
    enforce_new_defaults=True
    enforce_scope=True

  Please refer `Policy New Defaults`_ for detail about policy new defaults
  and migration plan.

  .. _RBAC new guidelines: https://governance.openstack.org/tc/goals/selected/consistent-and-secure-rbac.html#phase-1
  .. _Policy New Defaults: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html

.. releasenotes/notes/cinder-debug-c522618d82987971.yaml @ b'159016a4c3fcc8204b769fb41cdab84f2becfc1b'

- A new ``[cinder]/debug`` configurable has been introduced to enable DEBUG
  logging for both the ``python-cinderclient`` and ``os-brick`` libraries
  independently to the rest of Nova.

.. releasenotes/notes/extra-sorting-for-host-cells-c03e37de1e57043b.yaml @ b'd13412648d011994a146dac1e7214ead3b82b31b'

- Extra sorting were added to numa_fit_instance_to_host function
  to balance usage of hypervisor's NUMA cells. Hypervisor's NUMA
  cells with more free resources (CPU, RAM, PCI if requested)
  will be used first (spread strategy) when configuration option
  ``packing_host_numa_cells_allocation_strategy`` was set to False.
  Default value of ``packing_host_numa_cells_allocation_strategy``
  option is set to True which leads to packing strategy usage.

.. releasenotes/notes/flavor-based-multiqueue-configuration-41e2cbc4ca024682.yaml @ b'f42fb1241bb70b03b0715412b99257339e6bdc8d'

- The ``hw:vif_multiqueue_enabled`` flavor extra spec has been added. This
  is a boolean option that, when set, can be used to enable or disable
  multiqueue for virtio-net VIFs. It complements the equivalent image
  metadata property, ``hw_vif_multiqueue_enabled``. If both values are set,
  they must be identical or an error will be raised.

.. releasenotes/notes/lightos-fcafefdfd0939316.yaml @ b'e5ed77cf8ba2edd288aed6bd0ca714e66e0105c5'

- Nova now support integration with the Lightbits Labs
  (http://www.lightbitslabs.com) LightOS storage solution.
  LightOS is a software-defined, cloud native,
  high-performance, clustered scale-out and redundant NVMe/TCP storage
  that performs like local NVMe flash.

.. releasenotes/notes/nova-manage-image-property-26b2e3eaa2ef343b.yaml @ b'19b7cf21706c7975088dd52e02178e7c5f85666b'

- New ``nova-manage image_property`` commands have been added to help update
  instance image properties that have become invalidated by a change of
  instance machine type.

  * The ``nova-manage image_property show`` command can be used to show the
    current stored image property value for a given instance and property.

  * The ``nova-manage image_property set`` command can be used to update the
    stored image properties stored in the database for a given instance and
    image properties.

  For more detail on command usage, see the machine type documentation:

  https://docs.openstack.org/nova/latest/admin/hw-machine-type.html#device-bus-and-model-image-properties

.. releasenotes/notes/pci-vpd-capability-0d8039629db4afb8.yaml @ b'ab49f97b2c08294234c7bfd3dedb75780ca519e6'

- Add VPD capability parsing support when a PCI VPD capability is exposed
  via node device XML in Libvirt. The XML data from Libvirt is parsed and
  formatted into PCI device JSON dict that is sent to Nova API and is stored
  in the extra_info column of a PciDevice.

  The code gracefully handles the lack of the capability since it is optional
  or Libvirt may not support it in a particular release.

  A serial number is extracted from PCI VPD of network devices (if present)
  and is sent to Neutron in port updates.

  Libvirt supports parsing the VPD capability from PCI/PCIe devices and
  exposing it via nodedev XML as of 7.9.0.

  - https://libvirt.org/news.html#v7-9-0-2021-11-01
  - https://libvirt.org/drvnodedev.html#VPDCap

.. releasenotes/notes/support-port-resource-request-groups-neutron-api-extension-70a902b79f735cff.yaml @ b'9c2cb1fd4ff141da04c62943c5690a55e7c77f06'

- Added support for ports with minimum guaranteed packet rate QoS policy
  rules. Support is provided for all server operations including cold
  migration, resize, interface attach/detach, etc.
  This feature required adding support for the
  ``port-resource-request-groups`` neutron API extension, as ports with such
  a QoS policy will have multiple rules, each requesting resources.
  For more details see the  `admin guide`_.

.. releasenotes/notes/support-port-resource-request-groups-neutron-api-extension-70a902b79f735cff.yaml @ b'9c2cb1fd4ff141da04c62943c5690a55e7c77f06'

- The ``nova-manage placement heal_allocations`` `CLI`_ now allows
  regenerating the placement allocation of servers with ports using minimum
  guaranteed packet rate QoS policy rules.

  .. _`admin guide`: https://docs.openstack.org/nova/latest/admin/ports-with-resource-requests.html
  .. _`CLI`: https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement-heal-allocations

.. releasenotes/notes/use-multipath-0a0aa2b479e02370.yaml @ b'e8380b96a0893229629a6b790b3785c5a31e1f0c'

- The libvirt driver now allows using Native NVMeoF multipathing
  for NVMeoF connector, via the configuration attribute in nova-cpu.conf
  ``[libvirt]/volume_use_multipath``, defaulting to False (disabled).

.. releasenotes/notes/virtio-as-default-display-device-5341d3d5180036e2.yaml @ b'cc59698d6903b0ed3778826d6704758294abbd69'

- From this release, Nova instances will get ``virtio`` as the default
  display device (instead of ``cirrus``, which has many limitations).
  If your guest has a native kernel (called "virtio-gpu" in Linux;
  available since  Linux 4.4 and above) driver, then it'll be used;
  otherwise, the 'virtio' model will gracefully fallback to VGA
  compatibility mode, which is still better than ``cirrus``.

.. releasenotes/notes/vnic-type-remote-managed-b90cacf1c91df22b.yaml @ b'0620678344d0f032a33e952d4d0fa653741f09e7'

- Added support for off-path networking backends where devices exposed to the
  hypervisor host are managed remotely (which is the case, for example, with
  various SmartNIC DPU devices). ``VNIC_TYPE_REMOTE_MANAGED`` ports can now
  be added to Nova instances as soon as all compute nodes are upgraded to
  the new compute service version. In order to use this feature, VF PCI/PCIe
  devices need to be tagged as ``remote_managed: "true"`` in the Nova config
  in the ``passthrough_whitelist`` option.

  This feature relies on Neutron being upgraded to the corresponding release
  of OpenStack and having an appropriate backend capable of binding
  ``VNIC_TYPE_REMOTE_MANAGED`` ports (at the time of writing, ML2 with the OVN
  ML2 mechanism driver is the only supported backend, see the Neutron
  documentation for more details).

  Note that the PCI devices (VFs or, alternatively, their PF) must have a
  valid PCI Vital Product Data (VPD) with a serial number present in it for
  this feature to work properly. Also note that only VFs can be tagged as
  ``remote_managed: "true"`` and they cannot be used for legacy SR-IOV
  use-cases.

  Nova operations on instances with ``VNIC_TYPE_REMOTE_MANAGED`` ports
  follow the same logic as the operations on direct SR-IOV ports.

  This feature is only supported with the Libvirt driver.


.. _Release Notes_25.0.0_yoga-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1946729-wait-for-vif-plugged-event-during-hard-reboot-fb491f6a68370bab.yaml @ b'68c970ea9915a95f9828239006559b84e4ba2581'

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


.. _Release Notes_25.0.0_yoga-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/drop-bandwidth-field-from-notifications-d98812a3256cd573.yaml @ b'2b02b66bae7fba5103839e48bc4c48bb30cffead'

- The ``bandwidth`` field has been removed from the ``instance.exists`` and
  ``instance.update`` versioned notifications and the version for both
  notifications has been bumped to 2.0. The ``bandwidth`` field was only
  relevant when the XenAPI virt driver was in use, but this driver was
  removed in the Victoria (22.0.0) release and the field has been a no-op
  since.

.. releasenotes/notes/remove-deprecated-vnc-opts-c2bbcbf0fb777593.yaml @ b'cec9e7f1f13f62ff813df32d70d6455917398868'

- vnc-related config options were deprecated in Pike release and now has been
  removed:

  - ``vncserver_listen`` opt removed, now we use only server_listen to bind
    vnc address opt.
  - ``vncserver_proxyclient_address`` opt removed, now we use only
    server_proxyclient_address opt.

.. releasenotes/notes/remove-qos-queue-vmware-nsx-extension-208d72da23e7ae49.yaml @ b'36db6b746a68c02d1ffcdd8e1bcf29686b4f4b18'

- Support for the ``qos-queue`` extension provided by the vmware-nsx neutron
  plugin for the VMWare NSX Manager has been removed. This extension was
  removed from the vmware-nsx project when support for NSX-MH was removed in
  15.0.0.


.. _Release Notes_25.0.0_yoga-eom_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-powervm-yoga-d368b43ba86eb830.yaml @ b'0d7061625dcbf7e9e7dc374edc775e62666bfd00'

- The powervm virt driver is deprecated and may be removed in a future
  release. The driver is not tested by the OpenStack project nor does it have
  clear maintainers and thus its quality can not be ensured.


.. _Release Notes_25.0.0_yoga-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821088-reject-duplicate-port-ids-a38739d67d5d7c5d.yaml @ b'9fe465427310f8215890d26bf169617653605e23'

- The ``POST /servers`` (create server) API will now reject attempts to
  create a server with the same port specified multiple times. This was
  previously accepted by the API but the instance would fail to spawn and
  would instead transition to the error state.

.. releasenotes/notes/bug-1829479-cd2db21526965e6d.yaml @ b'e5a34fffdf97fcda7d0abfdc9e23485479ca2c4f'

- `Bug #1829479 <https://bugs.launchpad.net/nova/+bug/1829479>`_: Now
  deleting a nova-compute service removes allocations of successfully
  evacuated instances. This allows the associated resource provider to be
  deleted automatically even if the nova-compute service cannot recover after
  all instances on the node have been successfully evacuated.

.. releasenotes/notes/bug-1948705-ff80ae392c525475.yaml @ b'16f7c601b63bd1e7ca13917261300a7064ec72bc'

- Amended the guest resume operation to support mediated devices, as
  libvirt's minimum required version (v6.0.0) supports the hot-plug/unplug of
  mediated devices, which was addressed in v4.3.0.

.. releasenotes/notes/bug-1952941-request-spec-numa-topology-migration-c97dbd51b3c6c116.yaml @ b'e853bb57181721725a89656b3cb3058636630a6e'

- The `bug 1952941`_  is fixed where a pre-Victoria server with pinned
  CPUs cannot be migrated or evacuated after the cloud is upgraded to
  Victoria or newer as the scheduling fails with
  ``NotImplementedError: Cannot load 'pcpuset'`` error.

  .. _bug 1952941: https://bugs.launchpad.net/nova/+bug/1952941

.. releasenotes/notes/bug-1958636-smm-check-and-enable.yaml @ b'6ad789010043dc4dcf8d1c0f497b6c728d230f45'

- [`bug 1958636 <https://bugs.launchpad.net/nova/+bug/1958636>`_]
  Explicitly check for and enable SMM when firmware requires it.
  Previously we assumed libvirt would do this for us but this is
  not true in all cases.

.. releasenotes/notes/bug-1960230-cleanup-instances-dir-resize-56282e1b436a4908.yaml @ b'9111b99f739d41c092db8d01712a5aa72388b5fb'

- Fixed bug `1960230 <https://bugs.launchpad.net/nova/+bug/1960230>`_ that
  prevented resize of instances that had previously failed and not been
  cleaned up.

.. releasenotes/notes/bug-1960401-504eb255253d966a.yaml @ b'9eb116b99ce32bc69c4abf8ec3b0179ef89a8860'

- The `bug 1960401`_  is fixed which can cause invalid ``BlockDeviceMappings``
  to accumulate in the database. This prevented the respective volumes from
  being attached again to the instance.

  .. _bug 1960401: https://bugs.launchpad.net/nova/+bug/1960401

.. releasenotes/notes/bug-retry-corrupted-download-5798b0df44a00e4e.yaml @ b'ce493273b9404530dfa8ecfe3eaa3d6c81a20e39'

- `Bug 1950657 <https://bugs.launchpad.net/nova/+bug/1950657>`_, fixing
  behavior when nova-compute wouldn't retry image download when gets
  "Corrupt image download" error from glanceclient and has num_retries
  config option set.

.. releasenotes/notes/fix-ironic-compute-restart-port-attachments-3282e9ea051561d4.yaml @ b'7f81cf28bf21ad2afa98accfde3087c83b8e269b'

- Fixes slow compute restart when using the ``nova.virt.ironic`` compute
  driver where the driver was previously attempting to attach VIFS on
  start-up via the ``plug_vifs`` driver method. This method has grown
  otherwise unused since the introduction of the ``attach_interface``
  method of attaching VIFs. As Ironic manages the attachment of VIFs to
  baremetal nodes in order to align with the security requirements of a
  physical baremetal node's lifecycle. The ironic driver now ignores calls
  to the ``plug_vifs`` method.

.. releasenotes/notes/greendns-34df7f9fba952bcd.yaml @ b'fe1ebe69f358cbed62434da3f1537a94390324bb'

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


.. _Release Notes_25.0.0_yoga-eom_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bp-unified-limits-656b55863df22e16.yaml @ b'21972909448db2bc45375047a4d71b0188e77b82'

- This release includes work in progress support for Keystone's unified
  limits. This should not be used in production. It is included so we can
  collect early feedback from operators around the performance of the new
  limits system. There is currently no way to export your existing quotas
  and import them into Keystone. There is also no proxy API to allow you
  to update unified limits via Nova APIs. All the update APIs behave as if
  you are using the noop driver when the unified limits quota driver is
  configured.

  When you enable unified limits, those are configured in Keystone against
  the Nova endpoint, using the names:

  * ``class:VCPU``
  * ``servers``
  * ``class:MEMORY_MB``
  * ``server_metadata_items``
  * ``server_injected_files``
  * ``server_injected_file_content_bytes``
  * ``server_injected_file_path_bytes``
  * ``server_key_pairs``
  * ``server_groups``
  * ``server_group_members``

  All other resources classes requested via flavors are also now supported as
  unified limits. Note that nova configuration is ignored, as the default
  limits come from the limits registered for the Nova endpoint in Keystone.

  All previous quotas other than ``cores``, ``instances`` and ``ram`` are
  still enforced, but the limit can only be changed globally in Keystone as
  registered limits. There are no per project or per user overrides
  possible.

  Work in progress support for Keystone's unified limits
  can be enabled via ``[quota]/driver=nova.quota.UnifiedLimitsDriver``

  A config option ``[workarounds]unified_limits_count_pcpu_as_vcpu`` is
  available for operators who require the legacy quota usage behavior where
  VCPU = VCPU + PCPU. Note that if ``PCPU`` is specified in the flavor
  explicitly, it will be expected to have its own unified limit registered
  and PCPU usage will *not* be merged into VCPU usage.

.. releasenotes/notes/register-defaults-for-undefined-hw-image-properties-d86bcf99f4610239.yaml @ b'7ecdfb61a92301fef8c036572367ee6d1ffc3c0d'

- Default image properties for device buses and models are now persisted in
  the instance system metadata for the following image properties:

  * ``hw_cdrom_bus``
  * ``hw_disk_bus``
  * ``hw_input_bus``
  * ``hw_pointer_model``
  * ``hw_video_model``
  * ``hw_vif_model``

  Instance device buses and models will now remain stable across reboots and
  will not be changed by new defaults in libosinfo or the OpenStack Nova
  libvirt driver.


