==========================
Train Series Release Notes
==========================

.. _Release Notes_20.6.1-41_train-eol:

20.6.1-41
=========

.. _Release Notes_20.6.1-41_train-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/console-proxy-reject-open-redirect-4ac0a7895acca7eb.yaml @ b'04d48527b62a35d912f93bc75613a6cca606df66'

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


.. _Release Notes_20.6.1-41_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821755-7bd03319e34b6b10.yaml @ b'a22d1b04de9e6ebc33b5ab9871b86f8e4022e7a9'

- Improved detection of anti-affinity policy violation when performing live
  and cold migrations. Most of the violations caused by race conditions due
  to performing concurrent live or cold migrations should now be addressed
  by extra checks in the compute service. Upon detection, cold migration
  operations are automatically rescheduled, while live migrations have two
  checks and will be rescheduled if detected by the first one, otherwise the
  live migration will fail cleanly and revert the instance state back to its
  previous value.

.. releasenotes/notes/fix-ironic-compute-restart-port-attachments-3282e9ea051561d4.yaml @ b'6786e9630b10c0c01c8797a4e2e0a1a35fd3ca94'

- Fixes slow compute restart when using the ``nova.virt.ironic`` compute
  driver where the driver was previously attempting to attach VIFS on
  start-up via the ``plug_vifs`` driver method. This method has grown
  otherwise unused since the introduction of the ``attach_interface``
  method of attaching VIFs. As Ironic manages the attachment of VIFs to
  baremetal nodes in order to align with the security requirements of a
  physical baremetal node's lifecycle. The ironic driver now ignores calls
  to the ``plug_vifs`` method.

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'321573995596be145d3b091e341d7d66853436b8'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/minimize-bug-1841481-race-window-f76912d4985770ad.yaml @ b'912fabac79ae48a856de9786678846efa01395b1'

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

.. releasenotes/notes/restore-rocky-portbinding-semantics-48e9b1fa969cc5e9.yaml @ b'5a6fd88f7aaa18b9cbd7ab594b4e1dac0b7d22ca'

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


.. _Release Notes_20.6.1-41_train-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/avoid_muli_ceph_download-4083decf501dba40.yaml @ b'794bedf00e6a3dcdf89f07ae3f63deee09138a9a'

- Nova now has a config option called
  ``[workarounds]/never_download_image_if_on_rbd`` which helps to
  avoid pathological storage behavior with multiple ceph clusters.
  Currently, Nova does *not* support multiple ceph clusters
  properly, but Glance can be configured with them. If an instance
  is booted from an image residing in a ceph cluster other than the
  one Nova knows about, it will silently download it from Glance and
  re-upload the image to the local ceph privately for that
  instance. Unlike the behavior you expect when configuring Nova and
  Glance for ceph, Nova will continue to do this over and over for
  the same image when subsequent instances are booted, consuming a
  large amount of storage unexpectedly. The new workaround option
  will cause Nova to refuse to do this download/upload behavior and
  instead fail the instance boot. It is simply a stop-gap effort to
  allow unsupported deployments with multiple ceph clusters from
  silently consuming large amounts of disk space.


.. _Release Notes_20.6.1_train-eol:

20.6.1
======

.. _Release Notes_20.6.1_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841932-c871ac7b3b05d67e.yaml @ b'f60253677830483e63f73bcfd554f5e165cfc850'

- Add support for the ``hw:hide_hypervisor_id`` extra spec. This is an
  alias for the ``hide_hypervisor_id`` extra spec, which was not
  compatible with the ``AggregateInstanceExtraSpecsFilter`` scheduler
  filter. See
  `bug 1841932 <https://bugs.launchpad.net/nova/+bug/1841932>`_ for more
  details.


.. _Release Notes_20.5.0_train-eol:

20.5.0
======

.. _Release Notes_20.5.0_train-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/increase_glance_num_retries-ddfcd7053631882b.yaml @ b'ca2fd8098a47cf2c38351dc4c8c65c7c5fe0afc3'

- The default for ``[glance] num_retries`` has changed from ``0`` to ``3``.
  The option controls how many times to retry a Glance API call in response
  to a HTTP connection failure. When deploying Glance behind HAproxy it is
  possible for a response to arrive just after the HAproxy idle time. As a
  result, an exception will be raised when the connection is closed resulting
  in a failed request. By increasing the default value, Nova can be more
  resilient to this scenario were HAproxy is misconfigured by retrying the
  request.


.. _Release Notes_20.5.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'8378785f995dd4bec2a5a20f7bf5946b3075120d'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361


.. _Release Notes_20.5.0_train-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/virtio-max-queues-27f73e988c7e66ba.yaml @ b'286d7cfc5c45535561b6ed6e7906bb40de5abc93'

- The nova libvirt virt driver supports creating instances with multi-queue
  virtio network interfaces. In previous releases nova has based the maximum
  number of virtio queue pairs that can be allocated on the reported kernel
  major version. It has been reported in `bug #1847367`_ that some distros have
  backported changes from later major versions that make major version
  number no longer suitable to determine the maximum virtio queue pair count.
  A new config option has been added to the libvirt section of the nova.conf.
  When defined nova will now use the ``[libvirt]/max_queues`` option to
  define the max queues that can be configured, if undefined it will
  fallback to the previous kernel version approach.

  .. _`bug #1847367`: https://bugs.launchpad.net/nova/+bug/1847367


.. _Release Notes_20.4.1_train-eol:

20.4.1
======

.. _Release Notes_20.4.1_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841363-fallback-to-threaded-io-when-native-io-is-not-supported-fe56014e9648a518.yaml @ b'd92fe4f3e69db51b7bbad52a1fe1740e37bade9a'

- Since Libvirt v.1.12.0 and the introduction of the `libvirt issue`_ ,
  there is a fact that if we set cache mode whose write semantic is not
  O_DIRECT (i.e. "unsafe", "writeback" or "writethrough"), there will
  be a problem with the volume drivers (i.e. LibvirtISCSIVolumeDriver,
  LibvirtNFSVolumeDriver and so on), which designate native io explicitly.

  When the driver_cache (default is none) has been configured as neither
  "none" nor "directsync", the libvirt driver will ensure the driver_io
  to be "threads" to avoid an instance spawning failure.

  .. _`libvirt issue`: https://bugzilla.redhat.com/show_bug.cgi?id=1086704

.. releasenotes/notes/bug-1889633-37e524fb6c20fbdf.yaml @ b'44676ddf843ba84e26721cd2e3f65dc45a881f66'

- An issue that could result in instances with the ``isolate`` thread policy
  (``hw:cpu_thread_policy=isolate``) being scheduled to hosts with SMT
  (HyperThreading) and consuming ``VCPU`` instead of ``PCPU`` has been
  resolved. See `bug #1889633`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1889633

.. releasenotes/notes/bug-1893263-769acadc4b6141d0.yaml @ b'750655c19daf4e8d0dcf35d3b1cab5e6d8ac69ba'

- Addressed an issue that prevented instances using multiqueue feature from
  being created successfully when their vif_type is TAP.

.. releasenotes/notes/bug-1894966-d25c12b1320cb910.yaml @ b'1634d3f59ace0206131992e31ee2d4b64123d7e8'

- Resolved an issue whereby providing an empty list for the ``policies``
  field in the request body of the ``POST /os-server-groups`` API would
  result in a server error. This only affects the 2.1 to 2.63 microversions,
  as the 2.64 microversion replaces the ``policies`` list field with a
  ``policy`` string field. See `bug #1894966`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1894966


.. _Release Notes_20.4.0_train-eol:

20.4.0
======

.. _Release Notes_20.4.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1882919-support-e1000e-vif-5437a45c13dff978.yaml @ b'ddbc262494cf0df3f3abd5b5139eb787bb085f8c'

- Previously, attempting to configure an instance with the ``e1000e`` or
  legacy ``VirtualE1000e`` VIF types on a host using the QEMU/KVM driver
  would result in an incorrect ``UnsupportedHardware`` exception. These
  interfaces are now correctly marked as supported.


.. _Release Notes_20.3.0_train-eol:

20.3.0
======

.. _Release Notes_20.3.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1878024-reserve-disk-for-image-cache-ef6688f869b12bcb.yaml @ b'90c70f04d777e444eb8e2f0bccb8aa616e69dc66'

- A new ``[workarounds]/reserve_disk_resource_for_image_cache`` config
  option was added to fix the `bug 1878024`_ where the images in the compute
  image cache overallocate the local disk. If this new config is set then the
  libvirt driver will reserve DISK_GB resources in placement based on the
  actual disk usage of the image cache.

  .. _bug 1878024: https://bugs.launchpad.net/nova/+bug/1878024


.. _Release Notes_20.2.0_train-eol:

20.2.0
======

.. _Release Notes_20.2.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1852458-cell0-instance-action-e3112cf17bcc7c64.yaml @ b'6484d9ff5b03f7b7d8e9ba296f7f32d2e54fcc11'

- This release contains a fix for a `regression`__ introduced in 15.0.0
  (Ocata) where server create failing during scheduling would not result in
  an instance action record being created in the cell0 database. Now when
  creating a server fails during scheduling and is "buried" in cell0 a
  ``create`` action will be created with an event named
  ``conductor_schedule_and_build_instances``.

  .. __: https://bugs.launchpad.net/nova/+bug/1852458

.. releasenotes/notes/bug-1856925-check-source-compute-resize-16e9c3b24cf72301.yaml @ b'938b499b1f427c3464602a28a63fe96056f1df25'

- This release contains a fix for `bug 1856925`_ such that ``resize`` and
  ``migrate`` server actions will be rejected with a 409 ``HTTPConflict``
  response if the source compute service is down.

  .. _bug 1856925: https://bugs.launchpad.net/nova/+bug/1856925

.. releasenotes/notes/cinder-detect-nonbootable-image-6fad7f865b45f879.yaml @ b'240d0309023fcaf20df44f819e9b3e14af97f526'

- The Compute service has never supported direct booting of an instance from
  an image that was created by the Block Storage service from an encrypted
  volume.  Previously, this operation would result in an ACTIVE instance that
  was unusable.  Beginning with this release, an attempt to boot from such an
  image will result in the Compute API returning a 400 (Bad Request)
  response.

.. releasenotes/notes/neutron-connection-retries-c276010afe238abc.yaml @ b'71971c206292232fff389dedbf412d780f0a557a'

- A new config option ``[neutron]http_retries`` is added which defaults to
  3. It controls how many times to retry a Neutron API call in response to a
  HTTP connection failure. An example scenario where it will help is when a
  deployment is using HAProxy and connections get closed after idle time. If
  an incoming request tries to reuse a connection that is simultaneously
  being torn down, a HTTP connection failure will occur and previously Nova
  would fail the entire request. With retries, Nova can be more resilient in
  this scenario and continue the request if a retry succeeds. Refer to
  https://launchpad.net/bugs/1866937 for more details.


.. _Release Notes_20.1.1_train-eol:

20.1.1
======

.. _Release Notes_20.1.1_train-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/instances_hidden_after_upgrade_to_train-9ce4731f31bc6bd2.yaml @ b'8363905a6a6d5c8b2488619bdf807c5dc17b2842'

- Upgrading to Train on a deployment with a large database may hit
  `bug 1862205`_, which results in instance records left in a bad
  state, and manifests as instances not being shown in list
  operations. Users upgrading to Train for the first time will
  definitely want to apply a version which includes this fix.  Users
  already on Train should upgrade to a version including this fix to
  ensure the problem is addressed.

  .. _bug 1862205: https://launchpad.net/bugs/1862205


.. _Release Notes_20.1.1_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/instances_hidden_after_upgrade_to_train-9ce4731f31bc6bd2.yaml @ b'8363905a6a6d5c8b2488619bdf807c5dc17b2842'

- A fix for serious `bug 1862205`_ is provided which addresses both
  the performance aspect of schema migration 399, as well as the
  potential fallout for cases where this migration silently fails
  and leaves large numbers of instances hidden from view from the
  API.


.. _Release Notes_20.1.0_train-eol:

20.1.0
======

.. _Release Notes_20.1.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1845986-70730d9f6c09e68b.yaml @ b'7bdd8e97fb5c4ae302eff79d257cec6b8cd2d27c'

- `Bug 1845986`_ has been fixed by adding iommu driver when the following
  metadata options are used with AMD SEV:

  - ``hw_scsi_model=virtio-scsi`` and either ``hw_disk_bus=scsi`` or
    ``hw_cdrom_bus=scsi``
  - ``hw_video_model=virtio``

  Also a virtio-serial controller is created when ``hw_qemu_guest_agent=yes``
  option is used, together with iommu driver for it.

  .. _Bug 1845986: https://launchpad.net/bugs/1845986

.. releasenotes/notes/bug-1852610-service-delete-with-migrations-ca0565fc0b503519.yaml @ b'a9650b3cbfc674e283964090fb64ac6297be5b78'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is involved in in-progress migrations. This is because doing
  so would not only orphan the compute node resource provider in the
  placement service on which those instances have resource allocations but
  can also break the ability to confirm/revert a pending resize properly.
  See https://bugs.launchpad.net/nova/+bug/1852610 for more details.

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'48bb9a9663374936221144bb6a24688128a51146'

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

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'48bb9a9663374936221144bb6a24688128a51146'

- With the changes introduced to address `bug #1763766`_, Nova now guards
  against NUMA constraint changes on rebuild. As a result the
  ``NUMATopologyFilter`` is no longer required to run on rebuild since
  we already know the topology will not change and therefore the existing
  resource claim is still valid. As such it is now possible to do an in-place
  rebuild of an instance with a NUMA topology even if the image changes
  provided the new image does not alter the topology which addresses
  `bug #1804502`_.

  ..  _`bug #1804502`: https://bugs.launchpad.net/nova/+bug/1804502


.. _Release Notes_20.0.0_train-eol:

20.0.0
======

.. _Release Notes_20.0.0_train-eol_Prelude:

Prelude
-------

.. releasenotes/notes/train-prelude-3db0f5f6a75cc57a.yaml @ b'7c25caa4183e6a728063ad0144525b83d336cbb8'

The 20.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 19.0.0 (Stein) to 20.0.0 (Train).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Train is v2.79. Details
  on REST API microversions added since the 19.0.0 Stein release can be
  found in the `REST API Version History`_ page.

- Live migration support for servers with a
  `NUMA topology, pinned CPUs <https://docs.openstack.org/nova/latest/admin/cpu-topologies.html>`_
  and/or `huge pages <https://docs.openstack.org/nova/latest/admin/huge-pages.html>`_,
  when using the libvirt compute driver.

- Live migration support for servers with
  `SR-IOV ports <https://docs.openstack.org/neutron/latest/admin/config-sriov>`_
  attached when using the libvirt compute driver.

- Support for cold migrating and resizing servers with bandwidth-aware
  `Quality of Service ports <https://docs.openstack.org/api-guide/compute/port_with_resource_request.html>`_
  attached.

- Improvements to the scheduler for more intelligently filtering
  `results from the Placement service <https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#prefiltering>`_.

- Improved multi-cell resilience with the ability to
  `count quota usage <https://docs.openstack.org/nova/latest/user/quotas.html#quota-usage-from-placement>`_
  using the Placement service and API database.

- A new framework supporting hardware-based encryption of guest memory
  to protect users against attackers or rogue administrators snooping on
  their workloads when using the libvirt compute driver. Currently only has
  basic support for
  `AMD SEV (Secure Encrypted Virtualization) <https://docs.openstack.org/nova/latest/admin/configuration/hypervisor-kvm.html#amd-sev-secure-encrypted-virtualization>`_.

- Improved `operational tooling <https://docs.openstack.org/nova/latest/cli/nova-manage.html>`_
  for things like archiving the database and healing instance resource
  allocations in Placement.

- Improved coordination with the baremetal service during external node
  `power cycles <https://docs.openstack.org/ironic/latest/admin/power-sync.html>`_.

- Support for
  `VPMEM (Virtual Persistent Memory) <https://docs.openstack.org/nova/latest/admin/virtual-persistent-memory.html>`_
  when using the libvirt compute driver. This provides data persistence
  across power cycles at a lower cost and with much larger capacities than
  DRAM, especially benefitting HPC and memory databases such as redis,
  rocksdb, oracle, SAP HANA, and Aerospike.

- It is now possible to place CPU pinned and unpinned servers on the same
  compute host when using the libvirt compute driver. See the
  `admin guide <https://docs.openstack.org/nova/latest/admin/cpu-topologies.html#configuring-libvirt-compute-nodes-for-cpu-pinning>`_
  for details.

- Nova no longer includes Placement code. You must use the extracted
  Placement service. See the `Placement extraction upgrade instructions`_
  for details.

- The XenAPI virt driver is now deprecated and may be removed in a future
  release as its quality can not be ensured due to lack of maintainers.

- The ``nova-consoleauth`` service has been removed as it was deprecated
  since the 18.0.0 (Rocky) release.

- The deprecated ``Cells V1`` feature (not to be confused with `Cells V2`_)
  has been removed.

.. _REST API Version History: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html
.. _Placement extraction upgrade instructions: https://docs.openstack.org/placement/latest/upgrade/to-stein.html
.. _Cells V2: https://docs.openstack.org/nova/latest/user/cells.html


.. _Release Notes_20.0.0_train-eol_New Features:

New Features
------------

.. releasenotes/notes/add-host-and-hypervisor-hostname-flag-to-create-server-847ba43abd6be02c.yaml @ b'564290ab145d2710d3e82b5c4871e647e4d516c4'

- API microversion 2.74 adds support for specifying optional ``host``
  and/or ``hypervisor_hostname`` parameters in the request body of
  ``POST /servers``. These request a specific destination host/node
  to boot the requested server. These parameters are mutually exclusive
  with the special ``availability_zone`` format of ``zone:host:node``.
  Unlike ``zone:host:node``, the ``host`` and/or ``hypervisor_hostname``
  parameters still allow scheduler filters to be run. If the requested
  host/node is unavailable or otherwise unsuitable, earlier failure will
  be raised.
  There will be also a new policy named
  ``compute:servers:create:requested_destination``. By default,
  it can be specified by administrators only.

.. releasenotes/notes/add-server-subresource-topology-c52e21f36497e62c.yaml @ b'3dcb404b1fbb3eb23f98c0c0b6e1898cfec993c8'

- Microversion 2.78 adds a new ``topology`` sub-resource to the
  servers API:

  - ``GET /servers/{server_id}/topology``

  This API provides information about the NUMA topology of a server,
  including instance to host CPU pin mappings, if CPU pinning is used, and
  pagesize information.

  The information exposed by this API is admin or owner only by default,
  controlled by rule:

  - ``compute:server:topology:index``

  And following fine control policy  use to keep host only information to
  admin:

  - ``compute:server:topology:host:index``

.. releasenotes/notes/add-support-for-vpmem-libvirt-8b66add5b2d8f5f5.yaml @ b'0e4ca433110efa286285d442fb531ba046b16bc9'

- The libvirt driver now supports booting instances with virtual persistent
  memory (vPMEM), also called persistent memory (PMEM) namespaces.
  To enable vPMEM support, the user should specify the PMEM namespaces
  in the ``nova.conf`` by using the configuration option
  ``[libvirt]/pmem_namespaces``. For example::

    [libvirt]
    # pmem_namespaces=$LABEL:$NSNAME[|$NSNAME][,$LABEL:$NSNAME[|$NSNAME]]
    pmem_namespaces = 128G:ns0|ns1|ns2|ns3,262144MB:ns4|ns5,MEDIUM:ns6|ns7

  Only PMEM namespaces listed in the configuration file can be used by
  instances. To identify the available PMEM namespaces on the host or create
  new namespaces, the ``ndctl`` utility can be used::

    ndctl create-namespace -m devdax -s $SIZE -M mem -n $NSNAME

  Nova will invoke this utility to identify available PMEM namespaces.
  Then users can specify vPMEM resources in a flavor by adding flavor's
  extra specs::

    openstack flavor set --property hw:pmem=6GB,64GB <flavor-id>

.. releasenotes/notes/always-set-dhcp-server-if-enable-dhcp-b96bf720af235902.yaml @ b'c7f572d65b57e034c1391ed49d84f6e5f1d672ad'

- When ``enable_dhcp`` is set on a subnet but there is no DHCP port on neutron then the ``dhcp_server`` value in meta hash will contain the subnet gateway IP instead of being absent.

.. releasenotes/notes/api-consistency-cleanup-700b260ced206d92.yaml @ b'b26bc7fd7a2e66e7659704d902bf6f8af902cfd8'

- Multiple API cleanups is done in API microversion 2.75:

  * 400 for unknown param for query param and for request body.

  * Making server representation always consistent among GET, PUT
    and Rebuild serevr APIs response. ``PUT /servers/{server_id}``
    and ``POST /servers/{server_id}/action {rebuild}`` API response
    is modified to add all the missing fields which are return
    by ``GET /servers/{server_id}``.
  * Change the default return value of swap field from the empty
    string to 0 (integer) in flavor APIs.

  * Return ``servers`` field always in the response of GET
    hypervisors API even there are no servers on hypervisor.

.. releasenotes/notes/archive-db-from-all-cells-b4775b3f1feb004e.yaml @ b'97b8cb3f5804cd39b7eb3ac2d481e43ceb52f2cf'

- Support for archiving deleted rows from the database across
  all cells has been added to the ``nova-manage db archive_deleted_rows``
  command. Specify the ``--all-cells`` option to run the process across all
  existing cells. It is only possible to archive all DBs from a node where
  the ``[api_database]/connection`` option is configured.

.. releasenotes/notes/bp-add-locked-reason-fb757750f7f077ef.yaml @ b'c541ace518219f6edad779ee0324586a0430b481'

- Added a new ``locked_reason`` option in microversion 2.73 to the
  ``POST /servers/{server_id}/action`` request where the action is lock.
  It enables the user to specify a reason when locking a server. This
  information will be exposed through the response of the following APIs:

  - ``GET servers/{server_id}``
  - ``GET /servers/detail``
  - ``POST /servers/{server_id}/action`` where the action is rebuild
  - ``PUT servers/{server_id}``

  In addition, ``locked`` will be supported as a valid filter/sort parameter
  for ``GET /servers/detail`` and ``GET /servers`` so that users can filter
  servers based on their locked value. Also the instance action versioned
  notifications for the lock/unlock actions now contain the ``locked_reason``
  field.

.. releasenotes/notes/bp-amd-sev-libvirt-support-4b7cf8f0756d88b8.yaml @ b'922d8bf8117d781cafcb958a0aea848a1de1e487'

- The libvirt driver can now support requests for guest RAM to be
  encrypted at the hardware level, if there are compute hosts which
  support it.  Currently only AMD SEV (Secure Encrypted
  Virtualization) is supported, and it has certain minimum version
  requirements regarding the kernel, QEMU, and libvirt.

  Memory encryption can be required either via a flavor which has the
  ``hw:mem_encryption`` extra spec set to ``True``, or via an image
  which has the ``hw_mem_encryption`` property set to ``True``.
  These do not inherently cause a preference for SEV-capable
  hardware, but for now SEV is the only way of fulfilling the
  requirement.  However in the future, support for other
  hardware-level guest memory encryption technology such as Intel
  MKTME may be added.  If a guest specifically needs to be booted
  using SEV rather than any other memory encryption technology, it
  is possible to ensure this by adding
  ``trait:HW_CPU_X86_AMD_SEV=required`` to the flavor extra specs or
  image properties.

  In all cases, SEV instances can only be booted from images which
  have the ``hw_firmware_type`` property set to ``uefi``, and only
  when the machine type is set to ``q35``.  The latter can be set per
  image by setting the image property ``hw_machine_type=q35``, or
  per compute node by the operator via the ``hw_machine_type``
  configuration option in the ``[libvirt]`` section of
  :file:`nova.conf`.

  For information on how to set up support for AMD SEV, please see
  the `KVM section of the Configuration Guide
  <https://docs.openstack.org/nova/latest/admin/configuration/hypervisor-kvm.html#amd-sev>`_.

.. releasenotes/notes/bp-nova-support-instance-power-update-8328355a0f3fb508.yaml @ b'62f6a0a1bc6c4b24621e1c2e927177f99501bef3'

- It is now possible to signal and perform an update of an instance's power
  state as of the 2.76 microversion using the ``power-update`` external
  event. Currently it is only supported in the ironic driver and through
  this event Ironic will send all "power-on to power-off" and
  "power-off to power-on" type power state changes on a physical instance
  to nova which will update its database accordingly. This way nova will
  not be able to enforce an incorrect power state on the physical instance
  during the periodic ``_sync_power_states`` task. The changes to the power
  state of an instance caused by this event can be viewed through
  ``GET /servers/{server_id}/os-instance-actions`` and
  ``GET /servers/{server_id}/os-instance-actions/{request_id}``.

.. releasenotes/notes/bp-placement-req-filter-isolated-aggregates-26f34213ca757b5a.yaml @ b'1bbef754fb9e2db30b9d14eb05d68b9afb1c9296'

- Blueprint `placement-req-filter-forbidden-aggregates`_ adds the ability
  for operators to set traits on aggregates which if not requested in flavor
  extra specs or image properties will result in disallowing all hosts
  belonging to those aggregates from booting the requested instances. This
  feature is enabled via a new config option
  ``[scheduler]/enable_isolated_aggregate_filtering``.
  See `Filtering hosts by isolated aggregates`_ for more details.

  .. _placement-req-filter-forbidden-aggregates: https://specs.openstack.org/openstack/nova-specs/specs/train/approved/placement-req-filter-forbidden-aggregates.html
  .. _Filtering hosts by isolated aggregates: https://docs.openstack.org/nova/latest/reference/isolate-aggregates.html

.. releasenotes/notes/bp-specifying-az-to-unshelve-server-aa355fef1eab2c02.yaml @ b'27b6c18c666389ee68935f28cf340b7673879d6f'

- Microversion 2.77 adds the optional parameter ``availability_zone`` to
  the ``unshelve`` server action API.

  * Specifying an availability zone is only allowed when the server status
    is ``SHELVED_OFFLOADED`` otherwise a 409 HTTPConflict response is
    returned.

  * If the ``[cinder]/cross_az_attach`` configuration option is False then
    the specified availability zone has to be the same as the availability
    zone of any volumes attached to the shelved offloaded server, otherwise
    a 409 HTTPConflict error response is returned.

.. releasenotes/notes/bp-support-delete-on-termination-in-server-attach-volume-5d08b4e97fdd24f9.yaml @ b'e5b47543cf2693f8d79df304ac3dc56a8f54089b'

- Microversion 2.79 adds support for specifying the ``delete_on_termination``
  field in the request body when attaching a volume to a server, to support
  configuring whether to delete the data volume when the server is destroyed.
  Also, ``delete_on_termination`` is added to the GET responses when showing
  attached volumes.

  The affected APIs are as follows:

  * ``POST /servers/{server_id}/os-volume_attachments``
  * ``GET /servers/{server_id}/os-volume_attachments``
  * ``GET /servers/{server_id}/os-volume_attachments/{volume_id}``

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- Compute nodes using the libvirt driver can now report ``PCPU`` inventory.
  This is consumed by instances with dedicated (pinned) CPUs. This can be
  configured using the ``[compute] cpu_dedicated_set`` config option. The
  scheduler will automatically translate the legacy ``hw:cpu_policy`` flavor
  extra spec or ``hw_cpu_policy`` image metadata property to ``PCPU``
  requests, falling back to ``VCPU`` requests only if no ``PCPU`` candidates
  are found. Refer to the help text of the ``[compute] cpu_dedicated_set``,
  ``[compute] cpu_shared_set`` and ``vcpu_pin_set`` config options for more
  information.

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- Compute nodes using the libvirt driver will now report the
  ``HW_CPU_HYPERTHREADING`` trait if the host has hyperthreading. The
  scheduler will automatically translate the legacy ``hw:cpu_thread_policy``
  flavor extra spec or ``hw_cpu_thread_policy`` image metadata property to
  either require or forbid this trait.

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- A new configuration option, ``[compute] cpu_dedicated_set``, has been
  added. This can be used to configure the host CPUs that should be used for
  ``PCPU`` inventory.

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- A new configuration option, ``[workarounds] disable_fallback_pcpu_query``,
  has been added. When creating or moving pinned instances, the scheduler will
  attempt to provide a ``PCPU``-based allocation, but can also fallback to a legacy
  ``VCPU``-based allocation. This fallback behavior is enabled by
  default to ensure it is possible to upgrade without having to modify compute
  node configuration but it results in an additional request for allocation
  candidates from placement. This can have a slight performance impact and is
  unnecessary on new or upgraded deployments where the compute nodes have been
  correctly configured to report ``PCPU`` inventory. The ``[workarounds]
  disable_fallback_pcpu_query`` config option can be used to disable this
  fallback allocation candidate request, meaning only ``PCPU``-based
  allocation candidates will be retrieved.

.. releasenotes/notes/extend-libvirt-video-model-support-d630b99ef5039f51.yaml @ b'35a591d33d8b1a6c30bf40ddc48a07715fd87339'

- In this release support was added for two additional libvirt video models:
  ``gop``, the UEFI graphic output protocol device model; and the ``none``
  device model. Existing support for ``virtio`` has been extended to all
  architectures and may now be requested via the ``hw_video_model`` image
  metadata property. Prior to this release the ``virtio`` video model was
  unconditionally enabled for ``AARCH64``. This is unchanged but it can now
  be explicitly enabled on all supported architectures. The ``none`` video
  model can be used to disable emulated video devices when using pGPU or
  vGPU passthrough.

.. releasenotes/notes/image_type_request_filter-7577ded9834330b6.yaml @ b'57978de4a8ef43cd46e95e81e5d1874fdf4c69e4'

- The scheduler can now use placement to more efficiently query for hosts that support
  the disk_format of the image used in a given request. The
  ``[scheduler]/query_placement_for_image_type_support`` config
  option enables this behavior, but must not be turned on until all
  computes have been upgraded to this version and thus are exposing image
  type support traits.

.. releasenotes/notes/libvirt-cpu-models-selection-153e734946a7f5cc.yaml @ b'f80e5f989db7f326e824b671cfe0a8bbb047cfca'

- It is now possible to specify an ordered list of CPU models in the
  ``[libvirt] cpu_models`` config option. If ``[libvirt] cpu_mode``
  is set to ``custom``, the libvirt driver will select the first
  CPU model in this list that can provide the required feature
  traits.

.. releasenotes/notes/libvirt-pmu-configuration-ec24904bddc84bef.yaml @ b'326bc658eef04576230d5ba90d2a02bf32deee03'

- The libvirt driver has been extended to support user configurable
  performance monitoring unit (vPMU) virtualization.
  This is particularly useful for real-time workloads.
  A pair of boolean flavor extra spec and image metadata properties
  ``hw:pmu`` and ``hw_pmu`` have been added to control the emulation
  of the vPMU. By default the behavior of vPMU emulation has
  not been changed. To take advantage of this new feature, the operator
  or tenant will need to update their flavors or images to define the
  new property.

.. releasenotes/notes/nova-manage-db-archive-before-option-8296af1c815f5f8a.yaml @ b'd8ad9f986e021e4b1e1e67e8376f122d55c8e816'

- An option ``--before`` has been added to ``nova-manage db archive_deleted_rows`` command. This options limits archiving of records to those deleted before the specified date.

.. releasenotes/notes/numa-aware-live-migration-4297653974458ee1.yaml @ b'083bafc3533c9122347ae13ccbc4a453dfe5b2a9'

- With the libvirt driver, live migration now works correctly for instances
  that have a NUMA topology. Previously, the instance was naively moved to
  the destination host, without updating any of the underlying NUMA guest to
  host mappings or the resource usage. With the new NUMA-aware live migration
  feature, if the instance cannot fit on the destination the live migration
  will be attempted on an alternate destination if the request is
  setup to have alternates. If the instance can fit on the destination, the
  NUMA guest to host mappings will be re-calculated to reflect its new
  host, and its resource usage updated.

.. releasenotes/notes/pre-filter-disabled-computes-0b15d2cad19398e4.yaml @ b'168d34c8d1161dc4d62493e194819297e079bb51'

- A mandatory scheduling pre-filter has been added which will exclude
  disabled compute nodes where the related ``nova-compute`` service status
  is mirrored with a ``COMPUTE_STATUS_DISABLED`` trait on the compute node
  resource provider(s) for that service in Placement. See the
  `admin scheduler configuration docs`__ for details.

  __ https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#compute-disabled-status-support

.. releasenotes/notes/qb-bug-1730933-6695470ebaee0fbd.yaml @ b'05a73c0f3a9f8edf9024f9870279bc6fb7bba2e7'

- The Quobyte Nova volume driver now supports identifying Quobyte
  mounts via the mounts fstype field, which is used by Quobyte 2.x
  clients. The previous behaviour is deprecated and may be removed
  from the Quobyte clients in the future.

.. releasenotes/notes/sriov-live-migration-0311dfb7102a48db.yaml @ b'd966ffabc373b4549ab47d3d3487f398073ce2bf'

- In this release SR-IOV live migration support is added to the libvirt
  virt driver for Neutron interfaces. Neutron SR-IOV interfaces can be
  grouped into two categories, direct mode interfaces and indirect.
  Direct mode SR-IOV interfaces are directly attached to the guest and
  exposed to the guest OS. Indirect mode SR-IOV interfaces have a software
  interface such as a macvtap between the guest and the SR-IOV device.
  This feature enables transparent live migration for instances with
  indirect mode SR-IOV devices. As there is no generic way to copy
  hardware state during a live migration, direct mode migration is not
  transparent to the guest. For direct mode interfaces, we mimic the
  workflow already in place for suspend and resume. For instance with
  SR-IOV devices, we detach the direct mode interfaces before migration
  and re-attach them after the migration. As a result, instances
  with direct mode SR-IOV port will lose network connectivity during a
  migration unless a bond with a live migratable interface is created
  within the guest.

.. releasenotes/notes/support-cold-migrating-neutron-ports-with-resource-request-6d23be654a253625.yaml @ b'3dc277be453ea6631229a06eef658fce874299fb'

- Cold migration and resize are now supported for servers with neutron ports
  having resource requests. E.g. ports that have QoS minimum bandwidth rules
  attached. Note that the migration is only supported if both the source and
  the destination compute services are upgraded to Train and the
  ``[upgrade_levels]/compute`` configuration does not prevent the computes
  from using the latest RPC version.


.. _Release Notes_20.0.0_train-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug-1845986-95cbede0a296b088.yaml @ b'9545edc79d75e75d47c51d5da651975c01e919ec'

- The support for guest RAM encryption using AMD SEV (Secure Encrypted
  Virtualization) added in Train is incompatible with a number of image
  metadata options:

  - ``hw_scsi_model=virtio-scsi`` and either ``hw_disk_bus=scsi`` or
    ``hw_cdrom_bus=scsi``
  - ``hw_video_model=virtio``
  - ``hw_qemu_guest_agent=yes``

  When used together, the guest kernel can malfunction with repeated warnings
  like::

      NMI watchdog: BUG: soft lockup - CPU#0 stuck for 22s! [system-udevd:272]

  This will be resolved in a future patch release. For more information,
  refer to `bug 1845986`__

  __ https://bugs.launchpad.net/nova/+bug/1845986


.. _Release Notes_20.0.0_train-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/block_device_allocate_retries-min-0-uprade-dc97b8f0e7716a3b.yaml @ b'5106d340f785f9de708b93eecc7c54419e45aa5b'

- The ``[DEFAULT]/block_device_allocate_retries`` configuration option now
  has a minimum required value of 0. Any previous configuration with a value
  less than zero will now result in an error.

.. releasenotes/notes/bp-nova-support-instance-power-update-8328355a0f3fb508.yaml @ b'62f6a0a1bc6c4b24621e1c2e927177f99501bef3'

- Until all the ``nova-compute`` services that run the ironic driver are
  upgraded to the Train code that handles the ``power-update`` callbacks from
  ironic, the ``[nova]/send_power_notifications`` config option can be kept
  disabled in ironic.

.. releasenotes/notes/bug-1816686-77060eb8f8bd4092.yaml @ b'6c6ffc0476b56fe0bf822ddcf3c9a2d543912f38'

- The libvirt driver's RBD imagebackend no longer supports setting
  force_raw_images to False. Setting force_raw_images = False and
  images_type = rbd in nova.conf will cause the nova compute service
  to refuse to start. To fix this, set force_raw_images = True. This
  change was required to fix the `bug 1816686`_.

  Note that non-raw cache image files will be removed if you set
  force_raw_images = True and images_type = rbd now.

  .. _bug 1816686: https://bugs.launchpad.net/nova/+bug/1816686

.. releasenotes/notes/bug-1840978-nova-manage-255-88df61a0b69c21c7.yaml @ b'df2845308dd32e1abd0b75a70f6997b1e4698745'

- The ``nova-manage`` set of commands would previously exit with return
  code 1 due to any unexpected error. However, some commands, such as
  ``nova-manage db archive_deleted_rows``,
  ``nova-manage cell_v2 map_instances`` and
  ``nova-manage placement heal_allocations`` use return code 1 for flow
  control with automation. As a result, the unexpected error return code
  has been changed from 1 to 255 for all ``nova-manage`` commands.

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- Previously, if ``vcpu_pin_set`` was not defined, the libvirt driver would
  count all available host CPUs when calculating ``VCPU`` inventory,
  regardless of whether those CPUs were online or not. The driver will now
  only report the total number of online CPUs. This should result in fewer
  build failures on hosts with offlined CPUs.

.. releasenotes/notes/live-migration-with-PCI-device-b96bdad273fa1d2b.yaml @ b'a32ef11e3ae4ca0b0474b1e4784c036ad1ff6472'

- Live migration of an instance with PCI devices is now blocked
  in the following scenarios:

  1. Instance with non-network related PCI device.

  2. Instance with network related PCI device and either:

     a. Neutron does not support extended port binding API.
     b. Source or destination compute node does not support
        libvirt-sriov-live-migration.

  Live migration will fail with a user friendly error.

  .. note:: Previously, the operation would have failed with an obscure error
      resulting in the instance still running on the source node or ending up
      in an inoperable state.

.. releasenotes/notes/max_concurrent_live_migrations-option-force-minimum-value-c0455a1b97d54bf1.yaml @ b'37c42c97e22b891e7c2d99d4452aa5b5e9e6d6a7'

- The ``max_concurrent_live_migrations`` configuration option has been restricted by the minimum value and now raises a ValueError if the value is less than 0.

.. releasenotes/notes/numa-aware-live-migration-4297653974458ee1.yaml @ b'083bafc3533c9122347ae13ccbc4a453dfe5b2a9'

- For the libvirt driver, the NUMA-aware live migration feature requires the
  conductor, source compute, and destination compute to be upgraded to Train.
  It also requires the conductor and source compute to be able to send RPC
  5.3 - that is, their ``[upgrade_levels]/compute`` configuration option must
  not be set to less than 5.3 or a release older than "train".

  In other words, NUMA-aware live migration with the libvirt driver is not
  supported until:

  * All compute and conductor services are upgraded to Train code.
  * The ``[upgrade_levels]/compute`` RPC API pin is removed (or set to
    "auto") and services are restarted.

  If any of these requirements are not met, live migration of instances with
  a NUMA topology with the libvirt driver will revert to the legacy naive
  behavior, in which the instance was simply moved over without updating its
  NUMA guest to host mappings or its resource usage.

  .. note:: The legacy naive behavior is dependent on the value of the
            ``[workarounds]/enable_numa_live_migration`` option. Refer to the
            Deprecations sections for more details.

.. releasenotes/notes/placement-deleted-a79ad405f428a5f8.yaml @ b'70a2879b2c75377f728f8faec8bd581613061230'

- If you upgraded your OpenStack deployment to Stein without switching to use
  the now independent placement service, you must do so before upgrading to
  Train. `Instructions <https://docs.openstack.org/placement/latest/upgrade/to-stein.html>`_
  for one way to do this are available.

.. releasenotes/notes/quota-usage-placement-5b3f62e83056f59d.yaml @ b'8354f42e20da952a6ab5612363afb77386886df0'

- It is now possible to count quota usage for cores and ram from the
  placement service and instances from instance mappings in the API database
  instead of counting resources from cell databases. This makes quota usage
  counting resilient in the presence of down or poor-performing cells.

  Quota usage counting from placement is opt-in via the
  ``[quota]count_usage_from_placement`` configuration option.

  There are some things to note when opting in to counting quota usage from
  placement:

  * Counted usage will not be accurate in an environment where multiple Nova
    deployments are sharing a placement deployment because currently
    placement has no way of partitioning resource providers between different
    Nova deployments. Operators who are running multiple Nova deployments
    that share a placement deployment should not set the
    ``[quota]count_usage_from_placement`` configuration option to ``True``.

  * Behavior will be different for resizes. During a resize, resource
    allocations are held on both the source and destination (even on the same
    host, see https://bugs.launchpad.net/nova/+bug/1790204) until the resize
    is confirmed or reverted. Quota usage will be inflated for servers in
    the ``VERIFY_RESIZE`` state and operators should weigh the advantages and
    disadvantages before enabling ``[quota]count_usage_from_placement``.

  * The ``populate_queued_for_delete`` and ``populate_user_id`` online data
    migrations must be completed before usage can be counted from placement.
    Until the data migration is complete, the system will fall back to legacy
    quota usage counting from cell databases depending on the result of an
    ``EXISTS`` database query during each quota check, if
    ``[quota]count_usage_from_placement`` is set to ``True``.  Operators who
    want to avoid the performance hit from the ``EXISTS`` queries should wait
    to set the ``[quota]count_usage_from_placement`` configuration option to
    ``True`` until after they have completed their online data migrations via
    ``nova-manage db online_data_migrations``.

  * Behavior will be different for unscheduled servers in ``ERROR`` state.
    A server in ``ERROR`` state that has never been scheduled to a compute
    host will not have placement allocations, so it will not consume quota
    usage for cores and ram.

  * Behavior will be different for servers in ``SHELVED_OFFLOADED`` state.
    A server in ``SHELVED_OFFLOADED`` state will not have placement
    allocations, so it will not consume quota usage for cores and ram. Note
    that because of this, it will be possible for a request to unshelve a
    server to be rejected if the user does not have enough quota available to
    support the cores and ram needed by the server to be unshelved.

.. releasenotes/notes/remove-arguments-db-sync-command-1a3249d05322e571.yaml @ b'2c94aa7d9fc2abd8c2223409195ba46e5b395af7'

- The ``--version`` argument has been removed in the following commands.
  Use the ``VERSION`` positional argument instead.

  - ``nova-manage db sync``
  - ``nova-manage api_db sync``

.. releasenotes/notes/remove-cells-v1-055028c270d06680.yaml @ b'614475b482ffd5ab13a717df52b1b49bb00cb330'

- The *cells v1* feature has been deprecated since the 16.0.0 Pike release
  and has now been removed. The ``nova-cells`` service and ``nova-manage
  cells`` commands have been removed, while the ``nova-manage cell_v2
  simple_cell_setup`` command will no longer check if cells v1 is enabled and
  therefore can no longer exit with ``2``.

  The *cells v1* specific REST APIs have been removed along with their
  related policy rules. Calling these APIs will now result in a ``410
  (Gone)`` error response.

  * ``GET /os-cells``
  * ``POST /os-cells``
  * ``GET /os-cells/capacities``
  * ``GET /os-cells/detail``
  * ``GET /os-cells/info``
  * ``POST /os-cells/sync_instances``
  * ``GET /os-cells/{cell_id}``
  * ``PUT /os-cells/{cell_id}``
  * ``DELETE /os-cells/{cell_id}``
  * ``GET /os-cells/{cell_id}/capacities``

  The *cells v1* specific policies have been removed.

  * ``cells_scheduler_filter:DifferentCellFilter``
  * ``cells_scheduler_filter:TargetCellFilter``

  The *cells v1* specific configuration options, previously found in
  ``cells``, have been removed.

  * ``enabled``
  * ``name``
  * ``capabilities``
  * ``call_timeout``
  * ``reserve_percent``
  * ``cell_type``
  * ``mute_child_interval``
  * ``bandwidth_update_interval``
  * ``instance_update_sync_database_limit``
  * ``mute_weight_multiplier``
  * ``ram_weight_multiplier``
  * ``offset_weight_multiplier``
  * ``instance_updated_at_threshold``
  * ``instance_update_num_instances``
  * ``max_hop_count``
  * ``scheduler``
  * ``rpc_driver_queue_base``
  * ``scheduler_filter_classes``
  * ``scheduler_weight_classes``
  * ``scheduler_retries``
  * ``scheduler_retry_delay``
  * ``db_check_interval``
  * ``cells_config``

  In addition, the following *cells v1* related RPC configuration options,
  previously found in ``upgrade_levels``, have been removed.

  * ``cells``
  * ``intercell``

.. releasenotes/notes/remove-core-ram-disk-filters-9510cbe5b4e295b6.yaml @ b'78645e61c63bf042453d1f822ae8b3f1ee6a311b'

- The ``CoreFilter``, ``DiskFilter`` and ``RamFilter``, which were
  deprecated in Stein (19.0.0), are now removed. ``VCPU``,
  ``DISK_GB`` and ``MEMORY_MB`` filtering is performed natively
  using the Placement service. These filters have been warning
  operators at startup that they conflict with proper operation of
  placement and should have been disabled since approximately
  Pike. If you did still have these filters enabled and were relying
  on them to account for virt driver overhead (at the expense of
  scheduler races and retries), see the `scheduler`_ documentation about
  the topic.

  .. _scheduler: https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#hypervisor-specific-considerations

.. releasenotes/notes/remove-deprecated-default-flavor-opt-a3dfafe59b076153.yaml @ b'7cf16e317bab6e2520b3ee5241a5ed73c17749a4'

- The ``[DEFAULT]/default_flavor`` option deprecated in 14.0.0 (Newton) has been removed.

.. releasenotes/notes/remove-image-cache-checksumming-1c9f1bebfbd00673.yaml @ b'e141bcdb25bcbb68267a4b26169a8c734e35c02e'

- The ``image_info_filename_pattern``, ``checksum_base_images``, and ``checksum_interval_seconds`` options have been removed in the ``[libvirt]`` config section.

.. releasenotes/notes/remove-ironic-api_endpoint-db922182356b8ac2.yaml @ b'd54f35d54e0d8274fc729d62fdaff426bb112486'

- Config option ``[ironic]api_endpoint`` was deprecated in the 17.0.0 Queens
  release and is now removed. To achieve the same effect, set the
  ``[ironic]endpoint_override`` option. (However, it is preferred to omit
  this setting and let the endpoint be discovered via the service catalog.)

.. releasenotes/notes/remove-nova-consoleauth-b7c61e50649206ea.yaml @ b'2398b78df5c30ccb71ea22821a40ad2a793a6a1a'

- The ``nova-consoleauth`` service has been deprecated since the 18.0.0
  Rocky release and has now been removed. The following configuration
  options have been removed:

  * ``[upgrade_levels] consoleauth``
  * ``[workarounds] enable_consoleauth``

.. releasenotes/notes/remove-nova-status-check-consoleauths-5df5c2e91749eefc.yaml @ b'bedaeab074eaf4193cdb0d8eebeb2fe89c76a8bf'

- A check for the use of the ``nova-consoleauth`` service, added to the
  ``nova-status upgrade check`` CLI in Rocky, is now removed.

.. releasenotes/notes/rm-neutron-url-conf-2056befe7207bd0b.yaml @ b'8f53a051cc7f5381a0b389847c17db5c127dc89e'

- The ``[neutron]/url`` configuration option, which was deprecated in the
  17.0.0 Queens release, has now been removed. The same functionality is
  available via the ``[neutron]/endpoint_override`` option.

.. releasenotes/notes/sriov-live-migration-0311dfb7102a48db.yaml @ b'd966ffabc373b4549ab47d3d3487f398073ce2bf'

- The Libvirt SR-IOV migration feature intoduced in this release requires
  both the source and destination node to support the feature. As a result
  it will be automatically disabled until the conductor and compute nodes
  have been upgraded.

.. releasenotes/notes/train-require-cinder-3.44-6965b902dd230413.yaml @ b'270d5d351e1f1a3ac27aa91ff7ec756b672401df'

- The block-storage (cinder) version 3.44 API is now required when working
  with volume attachments. A check has been added to the
  ``nova-status upgrade check`` command for this requirement.

.. releasenotes/notes/unversioned-as-default-notification_format-f149db44b319aa07.yaml @ b'ed613aa66fe37737ab97ce7e483949d931a0c3a5'

- To resolve `bug 1805659`_ the default value of
  ``[notifications]/notification_format`` is changed from ``both`` to
  ``unversioned``. For more information see the `documentation of the config
  option`_. If you are using versioned notifications, you will need to adjust
  your config to ``versioned``"

  .. _`bug 1805659`: https://bugs.launchpad.net/nova/+bug/1805659
  .. _`documentation of the config option`: https://docs.openstack.org/nova/latest/configuration/config.html#notifications.notification_format


.. _Release Notes_20.0.0_train-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/cpu-resources-d4e6a0c12681fa87.yaml @ b'278ab01c320f16b13e4d6e32768ff70b54ceaf36'

- The ``vcpu_pin_set`` configuration option has been deprecated. You should
  migrate host CPU configuration to the ``[compute] cpu_dedicated_set`` or
  ``[compute] cpu_shared_set`` config options, or both. Refer to the help
  text of these config options for more information.

.. releasenotes/notes/deprecate-aggregate-core-ram-disk-filters-59b9c430c5c26153.yaml @ b'588194d785b1bb52e53ed159c5d8645bf3a28b7d'

- The ``AggregateCoreFilter``, ``AggregateRamFilter`` and
  ``AggregateDiskFilter`` are now deprecated.
  They will be removed in a future release and should no longer be used.
  Their functionality has been replaced with a placement native approach
  by combining host aggregate mirroring added in Rocky and initial allocation
  ratios added in Stein. See the `scheduler documentation`_ for details.

  .. _`scheduler documentation`: https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html

.. releasenotes/notes/deprecate-retry-filter-4d1dba39a2c21836.yaml @ b'257ef9573f35a822602e233652ca12cd95c815ca'

- The ``RetryFilter`` is deprecated and will be removed in an upcoming
  release. Since the 17.0.0 (Queens) release, the scheduler has provided
  alternate hosts for rescheduling so the scheduler does not need to be
  called during a reschedule which makes the ``RetryFilter`` useless.
  See the `Return Alternate Hosts`_ spec for details.

  .. _Return Alternate Hosts: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/return-alternate-hosts.html

.. releasenotes/notes/deprecate-xen-driver-train-bd57a16fa51ab679.yaml @ b'af280ffe3098b84123eae218989ea056e9935bf1'

- The xenapi driver is deprecated and may be removed in a future release.
  The driver is not tested by the OpenStack project nor does it have clear
  maintainer(s) and thus its quality can not be ensured. If you are using
  the driver in production please let us know in freenode IRC and/or the
  openstack-discuss mailing list.

.. releasenotes/notes/numa-aware-live-migration-4297653974458ee1.yaml @ b'083bafc3533c9122347ae13ccbc4a453dfe5b2a9'

- With the introduction of the NUMA-aware live migration feature for the
  libvirt driver, ``[workarounds]/enable_numa_live_migration`` is
  deprecated. Once a cell has been fully upgraded to Train, its value is
  ignored.

  .. note:: Even in a cell fully upgraded to Train, RPC pinning via
            ``[upgrade_levels]/compute`` can cause live migration of
            instances with a NUMA topology to revert to the legacy naive
            behavior. For more details refer to the Upgrade section.

.. releasenotes/notes/train-deprecate-non-upt-compat-d061edf3f702eeec.yaml @ b'c76f3bd7bc5da52d117f5478a6c9e17ffc840f7a'

- Compatibility code for compute drivers that do not implement the
  `update_provider_tree`__ interface is deprecated and will be removed
  in a future release.

  __ https://docs.openstack.org/nova/latest/reference/update-provider-tree.html


.. _Release Notes_20.0.0_train-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'298b337a16c0d10916b4431c436d19b3d6f5360e'

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

.. releasenotes/notes/rootwrap-removed-3faca1fdc214f6bf.yaml @ b'e90c2ba868da6c77fc875631a39548965969e4ed'

- The transition from rootwrap (or sudo) to privsep has been completed for
  nova. The only case where rootwrap is still used is to start privsep
  helpers. All other rootwrap configurations for nova may now be removed.


.. _Release Notes_20.0.0_train-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/SIGHUP-works-c810d5ed14c73f68.yaml @ b'73f1fda7e93325d3ca2b2c62afb17fe011d650f3'

- By incorporating oslo fixes for `bug 1715374`_ and `bug 1794708`_, the
  nova-compute service now handles ``SIGHUP`` properly.

  .. _`bug 1794708`: https://bugs.launchpad.net/oslo.service/+bug/1794708
  .. _`bug 1715374`: https://bugs.launchpad.net/nova/+bug/1715374

.. releasenotes/notes/bug-1756823-fix-d3a999a258019c54.yaml @ b'7231f7dee10fa8f9e6cead026f6a5ae3f5b15ae4'

- Fixes a bug causing mount failures on systemd based systems that are
  using the systemd-run based mount with the Nova Quobyte driver.

.. releasenotes/notes/bug-1775418-754fc50261f5d7c3.yaml @ b'5a1d159d142997bb4288d4bf86d4e144334905cd'

- The `os-volume_attachments`_ update API, commonly referred to as the swap
  volume API will now return a ``400`` (BadRequest) error when attempting to
  swap from a multi attached volume with more than one active read/write
  attachment resolving `bug #1775418`_.

  .. _os-volume_attachments: https://developer.openstack.org/api-ref/compute/?expanded=update-a-volume-attachment-detail
  .. _bug #1775418: https://launchpad.net/bugs/1775418

.. releasenotes/notes/bug-1779845-8819eea6e91fb09c.yaml @ b'ca543438e183b2bd97a08ef781ddeab8303354ed'

- Blueprints `hide-hypervisor-id-flavor-extra-spec`_ and
  `add-kvm-hidden-feature`_ enabled NVIDIA drivers in Linux guests using KVM
  and QEMU, but support was not included for Windows guests. This is now
  fixed. See `bug 1779845`_ for details.

  .. _hide-hypervisor-id-flavor-extra-spec: https://blueprints.launchpad.net/nova/+spec/hide-hypervisor-id-flavor-extra-spec
  .. _add-kvm-hidden-feature: https://blueprints.launchpad.net/nova/+spec/add-kvm-hidden-feature
  .. _bug 1779845: https://bugs.launchpad.net/nova/+bug/1779845

.. releasenotes/notes/bug-1811726-multi-node-delete-2ba17f02c6171fbb.yaml @ b'650fe118d128f09f78552b82abc114bb4b84930e'

- `Bug 1811726`_ is fixed by deleting the resource provider (in placement)
  associated with each compute node record managed by a ``nova-compute``
  service when that service is deleted via the
  ``DELETE /os-services/{service_id}`` API. This is particularly important
  for compute services managing ironic baremetal nodes.

  .. _Bug 1811726: https://bugs.launchpad.net/nova/+bug/1811726

.. releasenotes/notes/bug-1824813-4441265dc805e792.yaml @ b'97549a2c416873ed0ef4a497095524516386579c'

- Unsetting '[DEFAULT] dhcp_domain' will now correctly result in the metadata
  service/config drive providing an instance hostname of '${hostname}' instead
  of '${hostname}None', as was previously seen.

.. releasenotes/notes/qb-bug-1730933-6695470ebaee0fbd.yaml @ b'05a73c0f3a9f8edf9024f9870279bc6fb7bba2e7'

- Fixes a bug that caused Nova to fail on mounting Quobyte volumes
  whose volume URL contained multiple registries.

.. releasenotes/notes/support-novnc-1.1.0-ce677fe3381b2a11.yaml @ b'9606c80402f6db20d62b689c58aa8f024183628a'

- Add support for noVNC >= v1.1.0 for VNC consoles. Prior to this fix, VNC
  console token validation always failed regardless of actual token validity
  with noVNC >= v1.1.0. See
  https://bugs.launchpad.net/nova/+bug/1822676 for more details.

.. releasenotes/notes/use-placement-in-tree-756cb20af66b08bd.yaml @ b'575fd08e63119900969d1f6784034772c7ab450b'

- There had been `bug 1777591`_ that placement filters out the specified
  target host when deploying an instance by the random limitation. In
  previous releases the bug has been worked around by unlimiting the results
  from the Placement service if the target host is specified. From this
  release, the Nova scheduler uses more optimized path retrieving only the
  target host information from placement. Note that it still uses the unlimit
  workaround if a target host is specified without a specific node and
  multiple nodes are found for the target host. This can happen in some of
  the virt drivers such as the Ironic driver.

  .. _bug 1777591: https://bugs.launchpad.net/nova/+bug/1777591

.. releasenotes/notes/writeback-cache-mode-for-guests-a7e4d2806c956164.yaml @ b'b9dc86d8d646472195070022ff7ae4c372bef4ca'

- Update the way QEMU cache mode is configured for Nova guests: If the
  file system hosting the directory with Nova instances is capable of
  Linux's O_DIRECT, use ``none``; otherwise fallback to ``writeback``
  cache mode.  This improves performance without compromising data
  integrity.  `Bug 1818847`_.

  Context: What makes ``writethrough`` so safe against host crashes is
  that it never keeps data in a "write cache", but it calls fsync()
  after *every* write.  This is also what makes it horribly slow.  But
  cache mode ``none`` doesn't do this and therefore doesn't provide
  this kind of safety.  The guest OS must explicitly flush the cache
  in the right places to make sure data is safe on the disk; and all
  modern OSes flush data as needed.  So if cache mode ``none`` is safe
  enough for you, then ``writeback`` should be safe enough too.

  .. _Bug 1818847: https://bugs.launchpad.net/nova/+bug/1818847


.. _Release Notes_20.0.0_train-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1834048-8b19ae1c5048b801.yaml @ b'03f7dc29b75d1099ef44a034ed7e23d2a4444ac6'

- A new ``[libvirt]/rbd_connect_timeout`` configuration option has been
  introduced to limit the time spent waiting when connecting to a RBD cluster
  via the RADOS API. This timeout currently defaults to 5 seconds.

  This aims to address issues reported in `bug 1834048`_ where failures to
  initially connect to a RBD cluster left the nova-compute service inoperable
  due to constant RPC timeouts being hit.

  .. _bug 1834048: https://bugs.launchpad.net/nova/+bug/1834048

.. releasenotes/notes/defaulting_group_policy-36f584cd3920818c.yaml @ b'ad4f79836264ec79068f087008367e2d2ae8cbea'

- `Numbered request groups`_ can be defined in the flavor extra_spec
  but they can come from other sources as well (e.g. neutron ports).
  If there is more than one numbered request group in the
  allocation candidate query and the flavor does not specify any
  group policy then the query will fail in placement as group_policy
  is mandatory in this case. Nova previously printed a warning to the
  scheduler logs but let the request fail. However the creator of
  the flavor cannot know if the flavor later on will be used in a boot
  request that has other numbered request groups. So nova will start
  defaulting the group_policy to 'none' which means that the resource
  providers fulfilling the numbered request groups can overlap.
  Nova will only default the group_policy if it is not provided in the flavor
  extra_spec, and there is more than one numbered request group present in
  the final request, and the flavor only provided one or zero of such groups.

  .. _`Numbered request groups`: https://docs.openstack.org/nova/latest/user/flavors.html#extra-specs-numbered-resource-groupings

.. releasenotes/notes/heal-allocations-dry-run-1761fab00f7967d1.yaml @ b'ded3e4d9007b3806665bc1b7bec2705bcbe2977e'

- A ``--dry-run`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command to get output without committing any changes to placement.

.. releasenotes/notes/heal-allocations-instance-uuid-9aa93fdef5015c64.yaml @ b'c92b297896161e11b6e423a3ae50f7d6c21cb5bd'

- An ``--instance`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command on a specific instance given its UUID.

.. releasenotes/notes/nova-manage-heal-port-allocation-48cc1a34c92d42cd.yaml @ b'54dea2531c887f77e4b7a8e7edb978d8f1ccfe50'

- The ``nova-manage placement heal_allocations`` `CLI`_ has been extended to
  heal missing port allocations which are possible due to `bug 1819923`_ .


  .. _bug 1819923: https://bugs.launchpad.net/nova/+bug/1819923
  .. _CLI: https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement

.. releasenotes/notes/placement-deleted-a79ad405f428a5f8.yaml @ b'70a2879b2c75377f728f8faec8bd581613061230'

- The code for the `placement service
  <https://docs.openstack.org/placement>`_ was moved to its own
  `repository <https://git.openstack.org/cgit/openstack/placement>`_ in
  Stein. The placement code in nova has been deleted.

.. releasenotes/notes/rbd-enhance-get-pool-info-14afc8eccab49dcf.yaml @ b'44254ca865515c2ecd91886f0100ada874a40abe'

- The reporting for bytes available for RBD has been enhanced to accommodate
  `unrecommended
  <http://docs.ceph.com/docs/luminous/start/hardware-recommendations/#hard-disk-drives>`_
  Ceph deployments where multiple OSDs are running on a single disk. The new
  reporting method takes the number of configured replicas into consideration
  when reporting bytes available.

.. releasenotes/notes/undeprecate-dhcp_domain-opt-77c9154c5b06e0ff.yaml @ b'886b0a5d748ae1deda3a039734f831d7c0cf0476'

- The ``dhcp_domain`` option has been undeprecated and moved to the ``[api]``
  group. It is used by the metadata service to configure fully-qualified
  domain names for instances, in addition to its role configuring DHCP
  services for *nova-network*. This use case was missed when deprecating the
  option initially.


