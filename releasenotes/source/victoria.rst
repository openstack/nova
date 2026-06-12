=============================
Victoria Series Release Notes
=============================

.. _Release Notes_22.4.0-23_victoria-eom:

22.4.0-23
=========

.. _Release Notes_22.4.0-23_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1978444-db46df5f3d5ea19e.yaml @ b'3cb1e35b5e3a3f8949bb0fd31fb8a246c5346703'

- `Bug #1978444 <https://bugs.launchpad.net/nova/+bug/1978444>`_: Now nova
  retries deleting a volume attachment in case Cinder API returns
  ``504 Gateway Timeout``. Also, ``404 Not Found`` is now ignored and
  leaves only a warning message.

.. releasenotes/notes/fix-ironic-compute-restart-port-attachments-3282e9ea051561d4.yaml @ b'35fb52f53fbd3f8290f775760a842d70f583fa67'

- Fixes slow compute restart when using the ``nova.virt.ironic`` compute
  driver where the driver was previously attempting to attach VIFS on
  start-up via the ``plug_vifs`` driver method. This method has grown
  otherwise unused since the introduction of the ``attach_interface``
  method of attaching VIFs. As Ironic manages the attachment of VIFs to
  baremetal nodes in order to align with the security requirements of a
  physical baremetal node's lifecycle. The ironic driver now ignores calls
  to the ``plug_vifs`` method.

.. releasenotes/notes/greendns-34df7f9fba952bcd.yaml @ b'f02099ea537aa3feba15cfea900a58b5c593f343'

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

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'3224ceb3fffc57d2375e5163d8ffbbb77529bc38'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/minimize-bug-1841481-race-window-f76912d4985770ad.yaml @ b'bc5fc2bc688056bc18cf3ae581d8e23592d110da'

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

.. releasenotes/notes/unplug-vifs-in-resize_instance-fcd98ea44e4b8725.yaml @ b'95614f600bdc09c2c96ca61a6e7e5d66cc93e9d7'

- Support for cold migration and resize between hosts with different network backends
  was previously incomplete. If the os-vif plugin for all network backends available
  in the cloud are not installed on all nodes unplugging will fail during confirming
  the resize. The issue is caused by the VIF unplug that happened during the resize
  confirm action on the source host when the original backend information of the VIF
  was not available. The fix moved the unplug to happen during the resize action
  when such information is still available. See `bug #1895220`_ for more details.

  .. _`bug #1895220`: https://bugs.launchpad.net/nova/+bug/1895220


.. _Release Notes_22.4.0_victoria-eom:

22.4.0
======

.. _Release Notes_22.4.0_victoria-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1946729-wait-for-vif-plugged-event-during-hard-reboot-fb491f6a68370bab.yaml @ b'c531fdcc192afb5af628ac567cb0ff8aa3eab052'

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


.. _Release Notes_22.3.0_victoria-eom:

22.3.0
======

.. _Release Notes_22.3.0_victoria-eom_Security Issues:

Security Issues
---------------

.. releasenotes/notes/console-proxy-reject-open-redirect-4ac0a7895acca7eb.yaml @ b'6b70350bdcf59a9712f88b6435ba2c6500133e5b'

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


.. _Release Notes_22.3.0_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1939604-547c729b7741831b.yaml @ b'aaa56240b0311ad47ccccc3b7850ddc5b0a21702'

- Addressed an issue that prevented instances with 1 vcpu using multiqueue
  feature from being created successfully when their vif_type is TAP.


.. _Release Notes_22.2.2_victoria-eom:

22.2.2
======

.. _Release Notes_22.2.2_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821755-7bd03319e34b6b10.yaml @ b'6ede6df7f41db809de19e124d3d4994180598f19'

- Improved detection of anti-affinity policy violation when performing live
  and cold migrations. Most of the violations caused by race conditions due
  to performing concurrent live or cold migrations should now be addressed
  by extra checks in the compute service. Upon detection, cold migration
  operations are automatically rescheduled, while live migrations have two
  checks and will be rescheduled if detected by the first one, otherwise the
  live migration will fail cleanly and revert the instance state back to its
  previous value.


.. _Release Notes_22.2.1_victoria-eom:

22.2.1
======

.. _Release Notes_22.2.1_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1911924-6e93d8a5038d18c1.yaml @ b'3d84097eab617d8e29754160c2f6eb6e1a024f76'

- The `os-resetState`_ API will now log an instance action when called. The
  resulting instance action being visible via the `os-instance-actions`_ API
  to users and admins, resolving `bug 1911924`_.

  .. _bug 1911924: https://launchpad.net/bugs/1911924
  .. _os-instance-actions: https://docs.openstack.org/api-ref/compute/?expanded=reset-server-state-os-resetstate-action-detail,list-actions-for-server-detail
  .. _os-resetState: https://docs.openstack.org/api-ref/compute/?expanded=reset-server-state-os-resetstate-action-detail

.. releasenotes/notes/bug_1905701-fdc7402ffe70d104.yaml @ b'eda11a4875ff30b8c3103475421ace3ebd440e4a'

- The libvirt virt driver will no longer attempt to fetch volume
  encryption metadata or the associated secret key when attaching ``LUKSv1``
  encrypted volumes if a libvirt secret already exists on the host.

  This resolves `bug 1905701`_ where instances with ``LUKSv1`` encrypted
  volumes could not be restarted automatically by the ``nova-compute``
  service after a host reboot when the
  ``[DEFAULT]/resume_guests_state_on_host_boot`` configurable was enabled.

  .. _bug 1905701: https://launchpad.net/bugs/1905701


.. _Release Notes_22.1.0_victoria-eom:

22.1.0
======

.. _Release Notes_22.1.0_victoria-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/cros-scell-resize-not-supported-with-ports-having-resource-request-a8e1029ef5983793.yaml @ b'6b57575092aa5f16f51e5af8b0e62617f46b420a'

- When the tempest test coverage was added for resize and cold migrate
  with neutron ports having QoS minimum bandwidth policy rules we
  discovered that the cross cell resize code path cannot handle such ports.
  See bug https://bugs.launchpad.net/nova/+bug/1907522 for details. A fix
  was implemented that makes sure that Nova falls back to same-cell resize if
  the server has such ports.


.. _Release Notes_22.1.0_victoria-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/warn-when-services-started-with-old-compute-fc80b4ff58a2aaea.yaml @ b'0c5ca351e27ca74610478d8af9777de0db5c0acc'

- Nova services only support old computes if the compute is not
  older than the previous major nova release. From now on nova services will
  emit a warning at startup if the deployment contains too old compute
  services. From the 23.0.0 (Wallaby) release nova services will refuse to
  start if the deployment contains too old compute services to prevent
  compatibility issues.


.. _Release Notes_22.0.1_victoria-eom:

22.0.1
======

.. _Release Notes_22.0.1_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'd8b8a8193b6b8228f6e7d6bde68b5ea6bb53dd8b'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361

.. releasenotes/notes/bug_1902925-351f563340a1e9a5.yaml @ b'a06e27592f5819b41e45a9e69f677d059205b87d'

- When upgrading compute services from Ussuri to Victoria each by one, the
  Compute RPC API was pinning to 5.11 (either automatically or by using
  the specific rpc version in the option) but when rebuilding an instance,
  a TypeError was raised as an argument was not provided. This error is
  fixed by `bug 1902925`_.

  .. _bug 1902925: https://bugs.launchpad.net/nova/+bug/1902925/


.. _Release Notes_22.0.0_victoria-eom:

22.0.0
======

.. _Release Notes_22.0.0_victoria-eom_Prelude:

Prelude
-------

.. releasenotes/notes/victoria-prelude-9b4c16ff8c6e7f3e.yaml @ b'09204e6616d5d6439a6b918dec6979d489a92ab2'

The 22.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 21.0.0 (Ussuri) to 22.0.0 (Victoria).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Victoria is v2.87.
  No new microversions were added during this cycle but you can find all
  of them in the `REST API Version History`__ page.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html

- Support for a new ``mixed`` `flavor CPU allocation policy`__ that allows
  both pinned and floating CPUs within the same instance.

  .. __: https://docs.openstack.org/nova/latest/user/flavors.html

- Custom Placement resource inventories and traits can now be described
  using a single `providers configuration file`__.

  .. __: https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html

- Glance multistore configuration with multiple RBD backends is now
  supported within Nova for libvirt RBD-backed images using
  ``[libvirt]/images_rbd_glance_store_name`` configuration option.

- An `emulated Virtual Trusted Platform Module`__ can be exposed to
  instances running on a ``libvirt`` hypervisor with ``qemu`` or ``kvm``
  backends.

  .. __: https://docs.openstack.org/nova/latest/admin/emulated-tpm.html

- Support for the ``xen``, ``uml``, ``lxc`` and ``parallels`` libvirt
  backends has been deprecated.

- ``XenAPI`` virt driver has been removed, including the related
  configuration options.

- ``VMWare`` virt driver is now supported again in Victoria after being
  deprecated during the Ussuri release, as testing issues have been
  addressed.


.. _Release Notes_22.0.0_victoria-eom_New Features:

New Features
------------

.. releasenotes/notes/bug-1884231-16acf297d88b122e.yaml @ b'9fc63c764429c10f9041e6b53659e0cbd595bf6b'

- It is now possible to allocate all cores in an instance to realtime and
  omit the ``hw:cpu_realtime_mask`` extra spec. This requires specifying the
  ``hw:emulator_threads_policy`` extra spec.

.. releasenotes/notes/bug-1884231-16acf297d88b122e.yaml @ b'9fc63c764429c10f9041e6b53659e0cbd595bf6b'

- It is now possible to specify a mask in ``hw:cpu_realtime_mask`` without a
  leading ``^``. When this is omitted, the value will specify the cores that
  should be included in the set of realtime cores, as opposed to those that
  should be excluded.

.. releasenotes/notes/emulated-tpm-cb277659fc2f9660.yaml @ b'25d786bd8aafe47bbda928666392a8980f0e7dd7'

- Nova now supports adding an emulated virtual `Trusted Platform Module`__ to
  libvirt guests with a ``virt_type`` of ``kvm`` or ``qemu``. Not all server
  operations are fully supported yet. See the documentation__ for details.

  .. __: https://en.wikipedia.org/wiki/Trusted_Platform_Module
  .. __: https://docs.openstack.org/nova/latest/admin/emulated-tpm.rst

.. releasenotes/notes/enable_rbd_download-e60470890518a605.yaml @ b'3ae215363276bc3f156b739da22d8708f3a2031c'

- New ``[glance]/enable_rbd_download`` config option was introduced.
  The option allows for the configuration of direct downloads
  of Ceph hosted glance images into the libvirt image cache via rbd when
  ``[glance]/enable_rbd_download= True`` and ``[glance]/rbd_user``,
  ``[glance]/rbd_pool``, ``[glance]/rbd_connect_timeout``,
  ``[glance]/rbd_ceph_conf`` are correctly configured.

.. releasenotes/notes/force-heal-allocations-7834f3156be90c94.yaml @ b'87936baaac3a1b5227ab779398dc26b4546e1af1'

- Add ``--force`` option to the ``nova-manage placement heal_allocations`` command to forcefully heal allocations for a specific instance.

.. releasenotes/notes/libvirt-rbd-glance-multistore-ecb66a071c282183.yaml @ b'07025abf72e33b352de080db29e1f43ca1e2facb'

- The libvirt RBD image backend module can now handle a Glance
  multistore environment where multiple RBD clusters are in use
  across a single Nova/Glance deployment, configured as independent
  Glance stores. In the case where an instance is booted with an
  image that does not exist in the RBD cluster that Nova is
  configured to use, Nova can ask Glance to copy the image from
  whatever store it is currently in to the one that represents its
  RBD cluster. To enable this feature, set
  ``[libvirt]/images_rbd_glance_store_name`` to tell Nova the Glance
  store name of the RBD cluster it uses.

.. releasenotes/notes/max-concurrent-snapshots-21a0a437dbe1044a.yaml @ b'6bb0c4fdabb98f168c530617b7c7a8f9396075fc'

- A new configuration option, ``[DEFAULT]/max_concurrent_snapshots``,
  has been added. This allow operator to configure maximum concurrent
  snapshots on a compute host and prevent resource overuse related
  to snapshot.

.. releasenotes/notes/provider-config-file-bf026380cb5a7898.yaml @ b'260713dc22c2b8da1588e44d57d25404a3ae2b1b'

- Nova now supports defining of additional resource provider traits and
  inventories by way of YAML configuration files. The location of these
  files is defined by the new config option
  ``[compute]provider_config_location``. Nova will look in this directory
  for ``*.yaml`` files. See the `specification`__ and `admin guide`__ for
  more details.

  __ https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/provider-config-file.html
  __ https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html

.. releasenotes/notes/qemu-accept-vmxnet3-nic.yaml @ b'7ba8f40134bf1f4dcb179a102cde1eea63f92aae'

- Add the ability to use ``vmxnet3`` NIC on a host using the QEMU/KVM driver. This allows
  the migration of an ESXi VM to QEMU/KVM, without any driver changes. ``vmxnet3``
  comes with better performance and lower latency comparing to an emulated driver like
  ``e1000``.

.. releasenotes/notes/rbd-increase-timeout-c4e5a34cf5da7fdc.yaml @ b'6458c3dba53b9a9fb903bdb6e5e08af14ad015d6'

- Added params ``[libvirt]/rbd_destroy_volume_retries``, defaulting to 12,
  and ``[libvirt]/rbd_destroy_volume_retry_interval``, defaulting to 5, that
  Nova will use when trying to remove a volume from Ceph in a retry loop
  that combines these parameters together. Thus, maximum elapsing time is by
  default 60 seconds.

.. releasenotes/notes/support-sriov-attach-5a52a3388e2e41c2.yaml @ b'1361ea5ad128e7048430612e01d97281fd094f05'

- Nova now supports attaching and detaching PCI device backed Neutron ports
  to running servers.

.. releasenotes/notes/use-pcpu-and-vcpu-in-one-instance-0ea66aeb9c2970de.yaml @ b'dd1b812ebd0c0d969048acbc1f24432d284772fe'

- Add the ``mixed`` instance CPU allocation policy for instance mixing with
  both ``PCPU`` and ``VCPU`` resources. This is useful for applications that
  wish to schedule the CPU intensive workload on the ``PCPU`` and the other
  workloads on ``VCPU``. The mixed policy avoids the necessity of making
  all instance CPUs to be pinned CPUs, as a result, reduces the consuption
  of pinned CPUs and increases the instance density.

  Extend the real-time instance with the ``mixed`` CPU allocation policy. In
  comparing with ``dedicated`` policy real-time instance, the non-real-time
  CPUs are not longer required to be pinned on dedicated host CPUs, but
  float on a range of host CPUs sharing with other instances.

.. releasenotes/notes/use-pcpu-and-vcpu-in-one-instance-0ea66aeb9c2970de.yaml @ b'dd1b812ebd0c0d969048acbc1f24432d284772fe'

- Add the extra spec ``hw:cpu_dedicated_mask`` to set the pinned CPUs for
  the mixed instance. This is a core mask and can be used to include or
  exclude CPUs. Any core not included or explicitly excluded is treated as a
  shared CPU.

.. releasenotes/notes/use-pcpu-and-vcpu-in-one-instance-0ea66aeb9c2970de.yaml @ b'dd1b812ebd0c0d969048acbc1f24432d284772fe'

- Export instance pinned CPU list through the ``dedicated_cpus`` section in
  the metadata service API.


.. _Release Notes_22.0.0_victoria-eom_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1894804-c03c20cd983c3192.yaml @ b'57ac83d4d71c903bbaf88a9b6b88a86916c1767c'

- `bug 1894804`_ documents a known device detachment issue with QEMU
  ``4.2.0`` as shipped by the Focal ``20.04`` Ubuntu release. This can lead
  to the failure to detach devices from the underlying libvirt domain of an
  instance as QEMU never emits the correct ``DEVICE_DELETED`` event to
  libvirt. This in turn leaves the device attached within libvirt and
  OpenStack Nova while it has been detached from the underlying QEMU process.
  Subsequent attempts to detach the device will also fail as it is no longer
  found within the QEMU process.

  There is no known workaround within OpenStack Nova to this issue.

  .. _bug 1894804: https://bugs.launchpad.net/qemu/+bug/1894804


.. _Release Notes_22.0.0_victoria-eom_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bp-policy-defaults-refresh-deprecated-apis-a758af4090419b11.yaml @ b'366ed139372bb6a5299f8fad95a890241dacf5bc'

- All APIs except deprecated APIs were modified to implement ``scope_type``
  and use new defaults in 21.0.0 (Ussuri). The remaining APIs
  have now been updated.

  Refer to the `Nova Policy Concepts <https://docs.openstack.org/nova/latest/configuration/policy-concepts.html>`_
  for details and migration plan.

.. releasenotes/notes/bug-1875418-0df3198e36530ec7.yaml @ b'd4af91f349b9d3fe4f840878906032a62b589324'

- Nova policies implemented the ``scope_type`` and new defaults
  provided by keystone. Old defaults are deprecated and still work
  if rules are not overridden in the policy file. If you don't override
  any policies at all, then you don't need to do anything different until the
  W release when old deprecated rules are removed and tokens need to be
  scoped to work with new defaults and scope of policies. For migration
  to new policies you can refer to `this document
  <https://docs.openstack.org/nova/latest/configuration/policy-concepts.html#migration-plan>`_.

  If you are overwriting the policy rules (all or some of them) in the policy
  file with new default values or any new value that requires scoped tokens,
  then non-scoped tokens will not work. Also if you generate the policy
  file with 'oslopolicy-sample-generator' json format or any other tool,
  you will get rules defaulted in the new format, which examines the token
  scope. Unless you turn on ``oslo_policy.enforce_scope``, scope-checking
  rules will fail. Thus, be sure to enable ``oslo_policy.enforce_scope`` and
  `educate <https://docs.openstack.org/nova/latest/configuration/policy-concepts.html>`_
  end users on how to request scoped tokens from Keystone, or
  use a pre-existing sample config file from the Train release until you are
  ready to migrate to scoped policies. Another way is to generate the policy
  file in yaml format as described `here
  <https://docs.openstack.org/oslo.policy/latest/cli/index.html#oslopolicy-policy-generator>`_
  and update the policy.yaml location in ``oslo_policy.policy_file``.

  For more background about the possible problem, check `this bug
  <https://bugs.launchpad.net/nova/+bug/1875418>`_.
  A upgrade check has been added to the ``nova-status upgrade check``
  command for this.

.. releasenotes/notes/bug-1875418-default-policy-file-change-22bd4cc6e27e0091.yaml @ b'fe545dbe5fb434d5fce2d4d0f24c6c4a6bdd7d21'

- The default value of ``[oslo_policy] policy_file`` config option has been
  changed from ``policy.json``
  to ``policy.yaml``. Nova policy new defaults since 21.0.0 and current
  default value of ``[oslo_policy] policy_file`` config option (``policy.json``)
  does not work when ``policy.json`` is generated by
  `oslopolicy-sample-generator <https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-sample-generator.html>`_  tool.
  Refer to `bug 1875418 <https://bugs.launchpad.net/nova/+bug/1875418>`_
  for more details.
  Also check `oslopolicy-convert-json-to-yaml <https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-convert-json-to-yaml.html>`_
  tool to convert the JSON to YAML formatted policy file in
  backward compatible way.

.. releasenotes/notes/bug-1882821-file-backed-memory-reserved-conflict-3ad4c04ab993ebf8.yaml @ b'3b99747b42e460567d52cc6d748396cb349d56b8'

- When using file-backed memory, the ``nova-compute`` service will now fail
  to start if the amount of reserved memory configured using ``[DEFAULT]
  reserved_host_memory_mb`` is equal to or greater than the total amount of
  memory configured using ``[libvirt] file_backed_memory``. Where reserved
  memory is less than the total amount of memory configured, a warning will
  be raised. This warning will become an error in a future release.

  The former combination is invalid as it would suggest reserved memory is
  greater than total memory available, while the latter is considered
  incorrect behavior as reserving of file-backed memory can and should be
  achieved by reducing the filespace allocated as memory by modifying
  ``[libvirt] file_backed_memory``.

.. releasenotes/notes/increase_glance_num_retries-ddfcd7053631882b.yaml @ b'662af9fab6eacb46bcaee38d076d33c2c0f82b9b'

- The default for ``[glance] num_retries`` has changed from ``0`` to ``3``.
  The option controls how many times to retry a Glance API call in response
  to a HTTP connection failure. When deploying Glance behind HAproxy it is
  possible for a response to arrive just after the HAproxy idle time. As a
  result, an exception will be raised when the connection is closed resulting
  in a failed request. By increasing the default value, Nova can be more
  resilient to this scenario were HAproxy is misconfigured by retrying the
  request.

.. releasenotes/notes/max-concurrent-snapshots-21a0a437dbe1044a.yaml @ b'6bb0c4fdabb98f168c530617b7c7a8f9396075fc'

- Previously, the number of concurrent snapshots was unlimited, now it is
  limited via ``[DEFAULT]/max_concurrent_snapshots``, which currently
  defaults to 5.

.. releasenotes/notes/remove-hooks-96d08645404d327c.yaml @ b'b72980960e62e05ad4dcd9af196105e3af0ac43f'

- Support for hooks has been removed. In previous versions of nova, these
  provided a mechanism to extend nova with custom code through a plugin
  mechanism. However, they were deprecated in 13.0.0 (Mitaka) as
  unmaintainable long-term. `Versioned notifications`__ and `vendordata`__
  should be used instead.
  For more information, refer to `this thread`__.

  __ https://docs.openstack.org/nova/latest/reference/notifications.html
  __ https://docs.openstack.org/nova/latest/admin/vendordata.html
  __ http://lists.openstack.org/pipermail/openstack-dev/2016-February/087782.html

.. releasenotes/notes/remove-image-download-hook-27b39dca2497446a.yaml @ b'2fbe8e02d5ed82da84543488bf2e8ee9df6594b5'

- The ``nova.image.download`` entry point hook has been removed, per the deprecation
  announcement in the 17.0.0 (Queens) release.

.. releasenotes/notes/remove-intel-cmt-perf-events-69df7324d6fe41a8.yaml @ b'e45f3b5d71342d179bc150901f2dd5dabef238ca'

- Intel CMT perf events - ``cmt``, ``mbmt``, and ``mbml`` - are no longer
  supported by the ``[libvirt] enabled_perf_events`` config option. These
  event types were broken by design and are not supported in recent Linux
  kernels (4.14+).

.. releasenotes/notes/remove-keymap-options-8db6d03ccf098db1.yaml @ b'46b1ff4e8025435a86c8cbba1b3e0ca983715d7e'

- The ``[vnc] keymap`` and ``[spice] keymap`` configuration options, first
  deprecated in 18.0.0 (Rocky), have now been removed.  The VNC option
  affected the libvirt and VMWare virt drivers, while the SPICE option only
  affected libvirt. For the libvirt driver, configuring these options
  resulted in lossy keymap conversions for the given graphics method.  Users
  can replace this host-level configuration with guest-level configuration.
  This requires noVNC 1.0.0 or greater, which provides support for QEMU's
  Extended Key Event messages. Refer to `bug #1682020`__ and the `QEMU RFB
  pull request`__ for more information.

  For the VMWare driver, only the VNC option applied. However, the
  ``[vmware] vnc_keymap`` option was introduce in 18.0.0 (Rocky) and can be
  used to replace ``[vnc] keymap``.

  __ https://bugs.launchpad.net/nova/+bug/1682020
  __ https://github.com/novnc/noVNC/pull/596

.. releasenotes/notes/remove-retry-and-aggregate-filters-f872a85d0b815982.yaml @ b'b0ebdf860294901f5a5ef5b8ba7199381d90664f'

- The following deprecated scheduler filters have been removed.

  RetryFilter
    Deprecated in Train (20.0.0). The RetryFilter has
    not been required since Queens following the completion of the
    return-alternate-hosts blueprint

  Aggregatefilter, AggregateRAMFilter, AggregateDiskFilter
    Deprecated in Train (20.0.0). These filters have not worked
    correctly since the introduction of placement in ocata.

  On upgrade operators should ensure they have not configured
  any of the new removed filters and instead should use placement
  to control cpu, ram and disk allocation ratios.

  Refer to the `config reference documentation`__ for more information.

  .. __: https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#allocation-ratios

.. releasenotes/notes/remove-xenapi-driver-194756049f22dc9e.yaml @ b'adb28f503ca8c38bd7224ec0a335f730557d7ca9'

- The ``XenAPI`` driver, which was deprecated in the 20.0.0 (Train), has now
  been removed.

.. releasenotes/notes/remove-xenapi-driver-194756049f22dc9e.yaml @ b'adb28f503ca8c38bd7224ec0a335f730557d7ca9'

- The following config options only apply when using the ``XenAPI`` virt
  driver which has now been removed. The config options have therefore been
  removed also.

  * ``[xenserver] agent_timeout``
  * ``[xenserver] agent_version_timeout``
  * ``[xenserver] agent_resetnetwork_timeout``
  * ``[xenserver] agent_path``
  * ``[xenserver] disable_agent``
  * ``[xenserver] use_agent_default``
  * ``[xenserver] login_timeout``
  * ``[xenserver] connection_concurrent``
  * ``[xenserver] cache_images``
  * ``[xenserver] image_compression_level``
  * ``[xenserver] default_os_type``
  * ``[xenserver] block_device_creation_timeout``
  * ``[xenserver] max_kernel_ramdisk_size``
  * ``[xenserver] sr_matching_filter``
  * ``[xenserver] sparse_copy``
  * ``[xenserver] num_vbd_unplug_retries``
  * ``[xenserver] ipxe_network_name``
  * ``[xenserver] ipxe_boot_menu_url``
  * ``[xenserver] ipxe_mkisofs_cmd``
  * ``[xenserver] connection_url``
  * ``[xenserver] connection_username``
  * ``[xenserver] connection_password``
  * ``[xenserver] vhd_coalesce_poll_interval``
  * ``[xenserver] check_host``
  * ``[xenserver] vhd_coalesce_max_attempts``
  * ``[xenserver] sr_base_path``
  * ``[xenserver] target_host``
  * ``[xenserver] target_port``
  * ``[xenserver] independent_compute``
  * ``[xenserver] running_timeout``
  * ``[xenserver] image_upload_handler``
  * ``[xenserver] image_handler``
  * ``[xenserver] introduce_vdi_retry_wait``
  * ``[xenserver] ovs_integration_bridge``
  * ``[xenserver] use_join_force``
  * ``[xenserver] console_public_hostname``

.. releasenotes/notes/victoria-libvirt-version-bump-e1a09b3a72ee56a4.yaml @ b'95103c3bc9707be2ee97f314df0d52ee5ab6e10a'

- The minimum required version of libvirt used by the ``nova-compute`` service
  is now 5.0.0. The minimum required version of QEMU used by the
  ``nova-compute`` service is now 4.0.0. Failing to meet these minimum versions
  when using the libvirt compute driver will result in the ``nova-compute``
  service not starting.


.. _Release Notes_22.0.0_victoria-eom_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-libvirt-backends-496446b8b8b225e9.yaml @ b'340ef02e0678af592992b2d14c26ad2abff6e115'

- Support for the ``xen``, ``uml``, ``lxc`` and ``parallels`` libvirt
  backends, configured via the ``[libvirt] virt_type`` config option, has
  been deprecated. None of these drivers have upstream testing and the
  ``xen`` and ``uml`` backends specifically have never been considered
  production ready. With this change, only the ``kvm`` and ``qemu`` backends
  are considered supported when using the libvirt virt driver.

.. releasenotes/notes/undeprecate-vmware-victoria-2eaf5d877733f8d9.yaml @ b'adbc94f8cdbc66b6f645ae220f3a5f2f58aa62bf'

- The vmwareapi driver was deprecated in Ussuri due to missing third-party CI
  coverage and a clear maintainer. These issues have been addressed
  during the Victoria cycle and the driver is now undeprecated.


.. _Release Notes_22.0.0_victoria-eom_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841363-fallback-to-threaded-io-when-native-io-is-not-supported-fe56014e9648a518.yaml @ b'af2405e1181d70cdf60bcd0e40b3e80f2db2e3a6'

- Since Libvirt v.1.12.0 and the introduction of the `libvirt issue`_ ,
  there is a fact that if we set cache mode whose write semantic is not
  O_DIRECT (i.e. "unsafe", "writeback" or "writethrough"), there will
  be a problem with the volume drivers (i.e. LibvirtISCSIVolumeDriver,
  LibvirtNFSVolumeDriver and so on), which designate native io explicitly.

  When the driver_cache (default is none) has been configured as neither
  "none" nor "directsync", the libvirt driver will ensure the driver_io
  to be "threads" to avoid an instance spawning failure.

  .. _`libvirt issue`: https://bugzilla.redhat.com/show_bug.cgi?id=1086704

.. releasenotes/notes/bug-1841932-c871ac7b3b05d67e.yaml @ b'bf488a8630702160021b5848bf6e86fbb8015205'

- Add support for the ``hw:hide_hypervisor_id`` extra spec. This is an
  alias for the ``hide_hypervisor_id`` extra spec, which was not
  compatible with the ``AggregateInstanceExtraSpecsFilter`` scheduler
  filter. See
  `bug 1841932 <https://bugs.launchpad.net/nova/+bug/1841932>`_ for more
  details.

.. releasenotes/notes/bug-1874032-2b01ed05bc7f6f8d.yaml @ b'be9b7358473ca5276cff3c6491f88cd512d118b8'

- This release contains a fix for `bug 1874032`_ which delegates snapshot
  upload into a dedicated thread. This ensures nova compute service stability
  on busy environment during snapshot, when concurrent snapshots or any
  other tasks slow down storage performance.

  .. _bug 1874032: https://launchpad.net/bugs/1874032

.. releasenotes/notes/bug-1875418-default-policy-file-change-22bd4cc6e27e0091.yaml @ b'fe545dbe5fb434d5fce2d4d0f24c6c4a6bdd7d21'

- Bug `1875418 <https://bugs.launchpad.net/nova/+bug/1875418>`_ is fixed
  by changing the default value of ``[oslo_policy] policy_file`` config
  option to YAML format.

.. releasenotes/notes/bug-1878024-reserve-disk-for-image-cache-ef6688f869b12bcb.yaml @ b'89fe504abfbd41a9c37f9b544c0ce98b23b45799'

- A new ``[workarounds]/reserve_disk_resource_for_image_cache`` config
  option was added to fix the `bug 1878024`_ where the images in the compute
  image cache overallocate the local disk. If this new config is set then the
  libvirt driver will reserve DISK_GB resources in placement based on the
  actual disk usage of the image cache.

  .. _bug 1878024: https://bugs.launchpad.net/nova/+bug/1878024

.. releasenotes/notes/bug-1882919-support-e1000e-vif-5437a45c13dff978.yaml @ b'644cb5cb8bf44184d9b3f046cc67746b13550dd6'

- Previously, attempting to configure an instance with the ``e1000e`` or
  legacy ``VirtualE1000e`` VIF types on a host using the QEMU/KVM driver
  would result in an incorrect ``UnsupportedHardware`` exception. These
  interfaces are now correctly marked as supported.

.. releasenotes/notes/bug-1884231-16acf297d88b122e.yaml @ b'9fc63c764429c10f9041e6b53659e0cbd595bf6b'

- Previously, it was possible to specify values for the
  ``hw:cpu_realtime_mask`` extra spec that were not within the range of valid
  instances cores. This value is now correctly validated.

.. releasenotes/notes/bug-1888022-detach-multiattached-volumes-5fa862aea7f237ea.yaml @ b'806575cfd5327f96e62462f484118d06d17cbe8d'

- `Bug #1888022 <https://launchpad.net/bugs/1888022>`_:
  An issue that prevented detach of multi-attached fs-based volumes
  is resolved.

.. releasenotes/notes/bug-1889633-37e524fb6c20fbdf.yaml @ b'9c270332041d6b98951c0b57d7b344fd551a413c'

- An issue that could result in instances with the ``isolate`` thread policy
  (``hw:cpu_thread_policy=isolate``) being scheduled to hosts with SMT
  (HyperThreading) and consuming ``VCPU`` instead of ``PCPU`` has been
  resolved. See `bug #1889633`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1889633

.. releasenotes/notes/bug-1892870-eb894956bf04713d.yaml @ b'39831c55999abe97e3bd26a1c0db2e4ceb467041'

- Resolve a race condition that may occur during concurrent
  ``interface detach/attach``, resulting in an interface accidentally unbind
  after attached. See `bug 1892870`_ for more details.

  .. _bug 1892870: https://bugs.launchpad.net/nova/+bug/1892870

.. releasenotes/notes/bug-1893263-769acadc4b6141d0.yaml @ b'84cfc8e9ab1396ec17abcfc9646c7d40f1d966ae'

- Addressed an issue that prevented instances using multiqueue feature from
  being created successfully when their vif_type is TAP.

.. releasenotes/notes/bug-1894966-d25c12b1320cb910.yaml @ b'32c43fc8017ee89d4e6cdf79086d87735a00f0c0'

- Resolved an issue whereby providing an empty list for the ``policies``
  field in the request body of the ``POST /os-server-groups`` API would
  result in a server error. This only affects the 2.1 to 2.63 microversions,
  as the 2.64 microversion replaces the ``policies`` list field with a
  ``policy`` string field. See `bug #1894966`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1894966

.. releasenotes/notes/libvirt-nodedev-lookup-d80174ac30bc82f0.yaml @ b'efc27ff84c3f38fbcbf75b0dc230963c58d093e4'

- Since the 16.0.0 (Pike) release, nova has collected NIC feature
  flags via libvirt. To look up the NIC feature flags for a whitelisted
  PCI device the nova libvirt driver computed the libvirt nodedev name
  by rendering a format string using the netdev name associated with
  the interface and its current MAC address. In some environments the
  libvirt nodedev list can become out of sync with the current MAC address
  assigned to a netdev and as a result the nodedev look up can fail.
  Nova now uses PCI addresses, rather than MAC addresses, to look up these
  PCI network devices.

.. releasenotes/notes/rbd-increase-timeout-c4e5a34cf5da7fdc.yaml @ b'6458c3dba53b9a9fb903bdb6e5e08af14ad015d6'

- Nova tries to remove a volume from Ceph in a retry loop of 10 attempts at
  1 second intervals, totaling 10 seconds overall - which, due to 30 second
  ceph watcher timeout, might result in intermittent object removal failures
  on Ceph side (`bug 1856845`_). Setting default values for
  ``[libvirt]/rbd_destroy_volume_retries`` to 12 and
  ``[libvirt]/rbd_destroy_volume_retry_interval`` to 5, now gives Ceph
  reasonable amount of time to complete the operation successfully.

  .. _`bug 1856845`: https://bugs.launchpad.net/nova/+bug/1856845

.. releasenotes/notes/restore-rocky-portbinding-semantics-48e9b1fa969cc5e9.yaml @ b'b8f3be6b3c5af91d215b4a0cecb9be098e8d8799'

- In the Rocky (18.0.0) release support was added to nova to use neutron's
  multiple port binding feature when the binding-extended API extension
  is available. In the Train (20.0.0) release the SR-IOV live migration
  feature broke the semantics of the vifs field in the ``migration_data``
  object that signals if the new multiple port binding workflow should
  be used by always populating it even when the ``binding-extended`` API
  extension is not present. This broke live migration for any deployment
  that did not support the optional ``binding-extended`` API extension.
  The Rocky behavior has now been restored enabling live migration
  using the single port binding workflow when multiple port bindings
  are not available.


