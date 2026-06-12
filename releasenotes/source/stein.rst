===================================
 Stein Series Release Notes
===================================

.. _Release Notes_19.3.2-19_stein-eol:

19.3.2-19
=========

.. _Release Notes_19.3.2-19_stein-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/increase_glance_num_retries-ddfcd7053631882b.yaml @ b'ed7767865f891d5a90915f3486d567e2ac649a7e'

- The default for ``[glance] num_retries`` has changed from ``0`` to ``3``.
  The option controls how many times to retry a Glance API call in response
  to a HTTP connection failure. When deploying Glance behind HAproxy it is
  possible for a response to arrive just after the HAproxy idle time. As a
  result, an exception will be raised when the connection is closed resulting
  in a failed request. By increasing the default value, Nova can be more
  resilient to this scenario were HAproxy is misconfigured by retrying the
  request.


.. _Release Notes_19.3.2-19_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821755-7bd03319e34b6b10.yaml @ b'5fa8718fe57e59b178d081e2068109151fdc3926'

- Improved detection of anti-affinity policy violation when performing live
  and cold migrations. Most of the violations caused by race conditions due
  to performing concurrent live or cold migrations should now be addressed
  by extra checks in the compute service. Upon detection, cold migration
  operations are automatically rescheduled, while live migrations have two
  checks and will be rescheduled if detected by the first one, otherwise the
  live migration will fail cleanly and revert the instance state back to its
  previous value.

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'73e631862a81e85fdf9305f3d15b201d780c8743'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361


.. _Release Notes_19.3.2_stein-eol:

19.3.2
======

.. _Release Notes_19.3.2_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841363-fallback-to-threaded-io-when-native-io-is-not-supported-fe56014e9648a518.yaml @ b'cc2f45ebb03326c757abbfaef4de3e2c1fa4ead2'

- Since Libvirt v.1.12.0 and the introduction of the `libvirt issue`_ ,
  there is a fact that if we set cache mode whose write semantic is not
  O_DIRECT (i.e. "unsafe", "writeback" or "writethrough"), there will
  be a problem with the volume drivers (i.e. LibvirtISCSIVolumeDriver,
  LibvirtNFSVolumeDriver and so on), which designate native io explicitly.

  When the driver_cache (default is none) has been configured as neither
  "none" nor "directsync", the libvirt driver will ensure the driver_io
  to be "threads" to avoid an instance spawning failure.

  .. _`libvirt issue`: https://bugzilla.redhat.com/show_bug.cgi?id=1086704

.. releasenotes/notes/bug-1893263-769acadc4b6141d0.yaml @ b'8699156d86e0a40b25dd4e22092654b8bc14cccf'

- Addressed an issue that prevented instances using multiqueue feature from
  being created successfully when their vif_type is TAP.


.. _Release Notes_19.3.0_stein-eol:

19.3.0
======

.. _Release Notes_19.3.0_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1852458-cell0-instance-action-e3112cf17bcc7c64.yaml @ b'7ff71e6b87bd0ea2ed5bc4ac8dd8a2b6fc188ff4'

- This release contains a fix for a `regression`__ introduced in 15.0.0
  (Ocata) where server create failing during scheduling would not result in
  an instance action record being created in the cell0 database. Now when
  creating a server fails during scheduling and is "buried" in cell0 a
  ``create`` action will be created with an event named
  ``conductor_schedule_and_build_instances``.

  .. __: https://bugs.launchpad.net/nova/+bug/1852458

.. releasenotes/notes/bug-1878024-reserve-disk-for-image-cache-ef6688f869b12bcb.yaml @ b'86be251451716e3fa64f030c1f44954251bbee5d'

- A new ``[workarounds]/reserve_disk_resource_for_image_cache`` config
  option was added to fix the `bug 1878024`_ where the images in the compute
  image cache overallocate the local disk. If this new config is set then the
  libvirt driver will reserve DISK_GB resources in placement based on the
  actual disk usage of the image cache.

  .. _bug 1878024: https://bugs.launchpad.net/nova/+bug/1878024

.. releasenotes/notes/bug-1882919-support-e1000e-vif-5437a45c13dff978.yaml @ b'5482dde3298ce9679dbb8378fe8e216fc24dd024'

- Previously, attempting to configure an instance with the ``e1000e`` or
  legacy ``VirtualE1000e`` VIF types on a host using the QEMU/KVM driver
  would result in an incorrect ``UnsupportedHardware`` exception. These
  interfaces are now correctly marked as supported.


.. _Release Notes_19.2.0_stein-eol:

19.2.0
======

.. _Release Notes_19.2.0_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/cinder-detect-nonbootable-image-6fad7f865b45f879.yaml @ b'6e71909b0b8ad8d20d0863e714cad2a7b120f658'

- The Compute service has never supported direct booting of an instance from
  an image that was created by the Block Storage service from an encrypted
  volume.  Previously, this operation would result in an ACTIVE instance that
  was unusable.  Beginning with this release, an attempt to boot from such an
  image will result in the Compute API returning a 400 (Bad Request)
  response.

.. releasenotes/notes/neutron-connection-retries-c276010afe238abc.yaml @ b'a96e7ab83066bee0a13a54070aab988396bae320'

- A new config option ``[neutron]http_retries`` is added which defaults to
  3. It controls how many times to retry a Neutron API call in response to a
  HTTP connection failure. An example scenario where it will help is when a
  deployment is using HAProxy and connections get closed after idle time. If
  an incoming request tries to reuse a connection that is simultaneously
  being torn down, a HTTP connection failure will occur and previously Nova
  would fail the entire request. With retries, Nova can be more resilient in
  this scenario and continue the request if a retry succeeds. Refer to
  https://launchpad.net/bugs/1866937 for more details.


.. _Release Notes_19.1.0_stein-eol:

19.1.0
======

.. _Release Notes_19.1.0_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1852610-service-delete-with-migrations-ca0565fc0b503519.yaml @ b'a0290858b717b4cefd0d6fc17acc2b143ab12ac4'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is involved in in-progress migrations. This is because doing
  so would not only orphan the compute node resource provider in the
  placement service on which those instances have resource allocations but
  can also break the ability to confirm/revert a pending resize properly.
  See https://bugs.launchpad.net/nova/+bug/1852610 for more details.

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'8346c527b379395851a9de063b4978b489076bf6'

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

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'8346c527b379395851a9de063b4978b489076bf6'

- With the changes introduced to address `bug #1763766`_, Nova now guards
  against NUMA constraint changes on rebuild. As a result the
  ``NUMATopologyFilter`` is no longer required to run on rebuild since
  we already know the topology will not change and therefore the existing
  resource claim is still valid. As such it is now possible to do an in-place
  rebuild of an instance with a NUMA topology even if the image changes
  provided the new image does not alter the topology which addresses
  `bug #1804502`_.

  ..  _`bug #1804502`: https://bugs.launchpad.net/nova/+bug/1804502


.. _Release Notes_19.1.0_stein-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/heal-allocations-dry-run-1761fab00f7967d1.yaml @ b'4acec3e715b72f2f191ea544f135e40dc8fdaa81'

- A ``--dry-run`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command to get output without committing any changes to placement.

.. releasenotes/notes/heal-allocations-instance-uuid-9aa93fdef5015c64.yaml @ b'92645be4bb2f580b7499b1d7d162abf8caf2cdd6'

- An ``--instance`` option has been added to the
  ``nova-manage placement heal_allocations`` CLI which allows running the
  command on a specific instance given its UUID.


.. _Release Notes_19.0.3_stein-eol:

19.0.3
======

.. _Release Notes_19.0.3_stein-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/eventlet-monkey-patch-5f734ef581aa550e.yaml @ b'a694952eacfe3a2dac34957cf95d5529eb89d4b2'

- Operators should be aware that nova-api has a dependency on eventlet for
  executing parallel queries across multiple cells and is monkey-patched
  accordingly. When nova-api is running under uWSGI or mod_wsgi, the wsgi
  app will pause after idle time. While the wsgi app is paused, rabbitmq
  heartbeats will not be sent and log messages related to this can be seen
  in the nova-api logs when the wsgi app resumes when new requests arrive to
  the nova-api. These messages are not harmful. When the wsgi app resumes,
  oslo.messaging will reconnect to rabbitmq and requests will be served
  successfully.

  There is one caveat, which is that the wsgi app configuration must be left
  as the default ``threads=1`` or set explicitly to ``threads=1`` to ensure
  that reconnection will work properly. When threads > 1, it is not
  guaranteed that oslo.messaging will reconnect to rabbitmq when the wsgi app
  resumes after pausing during idle time. Threads are used internally by
  oslo.messaging for heartbeats and more, and it may fail in a variety of
  ways if run under eventlet with an app that violates eventlet's threading
  guarantees. When oslo.messaging does not reconnect to rabbitmq after a
  wsgi app pause, RPC requests will fail with a ``MessagingTimeout`` error.
  So, it is necessary to have the wsgi app configured with ``threads=1`` for
  reconnection to work properly.

  If running with ``threads=1`` is not an option in a particular environment,
  there are two other workarounds:

  * Use the eventlet wsgi server instead of uWSGI or mod_wsgi, or

  * Disable eventlet monkey-patching using the environment variable
    ``OS_NOVA_DISABLE_EVENTLET_PATCHING=yes``.

    Note that disabling eventlet monkey-patching will cause queries across
    multiple cells to be serialized instead of running in parallel and this
    may be undesirable in a large deployment with multiple cells, for
    performance reasons.

  Please see the following related bugs for more details:

  * https://bugs.launchpad.net/nova/+bug/1825584
  * https://bugs.launchpad.net/nova/+bug/1829062

.. releasenotes/notes/placement-eventlet-stall-ffcca23a6a364c78.yaml @ b'd7996ff5e7f6c48637ad9eab813317e4ff24de60'

- In Stein the Placement service is available either as part of Nova, or
  independently packaged from its own project. This is to allow easier
  migration from one to another. See the `upgrade notes`_ for more
  information.

  When using the Placement packaged from Nova, some deployment strategies can
  lead to the service stalling with error messages similar to::

      Traceback (most recent call last):
        File "/usr/lib/python2.7/site-packages/eventlet/hubs/hub.py", line 460, in fire_timers
          timer()
        File "/usr/lib/python2.7/site-packages/eventlet/hubs/timer.py", line 59, in __call__
          cb(*args, **kw)
        File "/usr/lib/python2.7/site-packages/eventlet/semaphore.py", line 147, in _do_acquire
          waiter.switch()
      error: cannot switch to a different thread

  The reasons this is happening are discussed in bug 1829062_. There are
  three workarounds available:

  * In the environment of the web server running the placement service, set
    ``OS_NOVA_DISABLE_EVENTLET_PATCHING=yes`` so that eventlet does not
    conflict with thread handling in the web server.

  * Turn off threading in the web server. For example, if using ``mod_wsgi``
    or ``uwsgi``, set ``threads=1`` in their respective configurations.

  * Switch to using the extracted placement. It does not suffer from eventlet.

  .. _upgrade notes: https://docs.openstack.org/placement/latest/upgrade/to-stein.html
  .. _1829062: https://bugs.launchpad.net/nova/+bug/1829062


.. _Release Notes_19.0.2_stein-eol:

19.0.2
======

.. _Release Notes_19.0.2_stein-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1837877-cve-fault-message-exposure-5360d794f4976b7c.yaml @ b'67651881163b75eb1983eaf753471a91ecec35eb'

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


.. _Release Notes_19.0.2_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1811726-multi-node-delete-2ba17f02c6171fbb.yaml @ b'e9889be94ee58a6da78ef96d09d8f5282b86f648'

- `Bug 1811726`_ is fixed by deleting the resource provider (in placement)
  associated with each compute node record managed by a ``nova-compute``
  service when that service is deleted via the
  ``DELETE /os-services/{service_id}`` API. This is particularly important
  for compute services managing ironic baremetal nodes.

  .. _Bug 1811726: https://bugs.launchpad.net/nova/+bug/1811726

.. releasenotes/notes/support-novnc-1.1.0-ce677fe3381b2a11.yaml @ b'186aff98b751b973dd5a7de9c8077b1a8bca0ba9'

- Add support for noVNC >= v1.1.0 for VNC consoles. Prior to this fix, VNC
  console token validation always failed regardless of actual token validity
  with noVNC >= v1.1.0. See
  https://bugs.launchpad.net/nova/+bug/1822676 for more details.


.. _Release Notes_19.0.1_stein-eol:

19.0.1
======

.. _Release Notes_19.0.1_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1775418-754fc50261f5d7c3.yaml @ b'9b21d1067a071ab17758068dfca5cd2ebd29d868'

- The `os-volume_attachments`_ update API, commonly referred to as the swap
  volume API will now return a ``400`` (BadRequest) error when attempting to
  swap from a multi attached volume with more than one active read/write
  attachment resolving `bug #1775418`_.

  .. _os-volume_attachments: https://developer.openstack.org/api-ref/compute/?expanded=update-a-volume-attachment-detail
  .. _bug #1775418: https://launchpad.net/bugs/1775418

.. releasenotes/notes/qb-bug-1730933-6695470ebaee0fbd.yaml @ b'656aa1cd40570154df606484d31616989b5296aa'

- Fixes a bug that caused Nova to fail on mounting Quobyte volumes
  whose volume URL contained multiple registries.


.. _Release Notes_19.0.0_stein-eol:

19.0.0
======

.. _Release Notes_19.0.0_stein-eol_Prelude:

Prelude
-------

.. releasenotes/notes/stein-prelude-b5fe92310e1e725e.yaml @ b'028418788b0095c7a0dbf04b6df75560a63765f8'

The 19.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 18.0.0 (Rocky) to 19.0.0 (Stein).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Stein is v2.72. Details
  on REST API microversions added since the 18.0.0 Rocky release can be
  found in the `REST API Version History`_ page.

- It is now possible to run Nova with version 1.0.0 of the recently
  extracted placement service, hosted from its own repository. Note
  that install/upgrade of an extracted placement service is not yet fully
  implemented in all deployment tools. Operators should check with their
  particular deployment tool for support before proceeding. See the
  placement `install`_ and `upgrade`_ documentation for more details.
  In Stein, operators may choose to continue to run with the integrated
  placement service from the Nova repository, but should begin planning a
  migration to the extracted placement service by Train, as the removal of
  the integrated placement code from Nova is planned for the Train release.

- Users can now specify a volume type when creating servers when using the
  2.67 compute API microversion. See the `block device mapping`_
  documentation for more details.

- The 2.69 compute API microversion adds handling of server details in the
  presence of down or poor-performing cells in a multi-cell environment for
  the ``GET /servers``, ``GET /servers/detail``,
  ``GET /servers/{server_id}``, ``GET /os-services`` REST APIs. See the
  `handling down cells`_ documentation for more details.

- Users are now able to create servers with Neutron ports that have QoS
  minimum bandwidth rules when using the 2.72 compute API microversion. See
  the `using ports with resource request`_ documentation for more details.

- Operators can now set overcommit allocation ratios using Nova
  configuration files or the placement API, by making use of the initial
  allocation ratio configuration options. See the `initial allocation
  ratios`_ documentation for more details.

- Compute capabilities are now exposed as traits in the placement API.
  See the `compute capabilities as traits`_ documentation for more details.

- The configuration option
  ``[compute]resource_provider_association_refresh`` can now be set to zero
  to disable refresh entirely. This should be useful for large-scale
  deployments.

- The VMwareVCDriver now supports live migration. See the
  `live migration configuration`_ documentation for information on how to
  enable it.

- Nova now supports nested resource providers in two cases:

  #. QoS-enabled ports will have inventories and allocations created on
     nested resource providers from the start.
  #. Libvirt compute nodes reporting VGPU inventory will have that VGPU
     inventory and corresponding allocations moved to a child resource
     provider on restart of the nova-compute service after upgrading to
     Stein.

  In both cases this means when looking at resource providers, depending on
  the scenario, you can see more than one provider where there was
  initially just a root compute node provider per compute service.

.. _REST API Version History: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html
.. _install: https://docs.openstack.org/placement/latest/install/index.html
.. _upgrade: https://docs.openstack.org/placement/latest/upgrade/to-stein.html
.. _handling down cells: https://developer.openstack.org/api-guide/compute/down_cells.html
.. _block device mapping: https://docs.openstack.org/nova/latest/user/block-device-mapping.html
.. _using ports with resource request: https://developer.openstack.org/api-guide/compute/port_with_resource_request.html
.. _initial allocation ratios: https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#allocation-ratios
.. _compute capabilities as traits: https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html#compute-capabilities-as-traits
.. _live migration configuration: https://docs.openstack.org/nova/latest/admin/configuring-migrations.html#vmware


.. _Release Notes_19.0.0_stein-eol_New Features:

New Features
------------

.. releasenotes/notes/add-instance-name-to-instance-create-notification-4c2f5eca9e574178.yaml @ b'0240c7b5b6bd8cddbe4384b3ab4154c9b27f5113'

- The field ``instance_name`` has been added to the
  ``InstanceCreatePayload`` in the following versioned notifications:

  * ``instance.create.start``
  * ``instance.create.end``
  * ``instance.create.error``

.. releasenotes/notes/add-server-use_all_filters-policy-3ddfe1885056f0ca.yaml @ b'7c56588647be64a2248b1f37d40369765bc6b977'

- A new policy rule ``os_compute_api:servers:allow_all_filters`` has been
  added to control whether a user can use all filters when listing servers.

.. releasenotes/notes/boot-instance-specific-storage-backend-c34ee0a871efec3b.yaml @ b'c7f4190af26ad106bea29f66770b9569ab3fc4e1'

- Microversion 2.67 adds the optional parameter ``volume_type`` to block_device_mapping_v2, which can be used to specify ``volume_type`` when creating a server.
  This would only apply to BDMs with ``source_type`` of ``blank``, ``image`` and ``snapshot`` and ``destination_type`` of ``volume``.
  The compute API will reject server create requests with a specified ``volume_type`` until all nova-compute services are upgraded to Stein.

.. releasenotes/notes/bp-extend-in-use-rbd-volumes-8f334ce2a06ee247.yaml @ b'eab58069ea6afba875fb0a7d7ac68c7e83ebf14a'

- Adds support for extending RBD attached volumes using the libvirt network
  volume driver.

.. releasenotes/notes/bp-handling-down-cell-10f76145d767300c.yaml @ b'833af5c9bf6178e7c7a7dc4ed9db4f9ae7533cd8'

- From microversion 2.69 the responses of ``GET /servers``,
  ``GET /servers/detail``, ``GET /servers/{server_id}`` and
  ``GET /os-services`` will contain missing keys during down cell situations
  because of adding support for returning minimal constructs based on the
  available information from the API database for those records in the
  down cells. See `Handling Down Cells`_ for more information on the missing
  keys.

  .. _Handling Down Cells: https://developer.openstack.org/api-guide/compute/down_cells.html

.. releasenotes/notes/bp-io-semaphore-for-concurrent-disk-ops-690890c9f01fa18c.yaml @ b'728f20e8f4ac2e3d4b893b7169b81d20471d0be9'

- Introduced a new config option ``[compute]/max_concurrent_disk_ops`` to
  reduce disk contention by specifying the maximum number of concurrent
  disk-IO-intensive operations per compute service.  This would include
  operations such as image download, image format conversion, snapshot
  extraction, etc.
  The default value is 0, which means that there is no limit.

.. releasenotes/notes/bp-support-hpet-on-guest-2292b2b863c4d9ef.yaml @ b'9e884de68af9b83a92850e823cae152cfe8fe783'

- Added support for the High Precision Event Timer (HPET) for x86 guests
  in the libvirt driver when image property ``hypervisor_type=qemu`` is set.
  The timer can be set by setting a ``hw_time_hpet=True`` image property
  key/value pair. By default HPET remains turned off. When it is turned on
  the HPET is activated in libvirt.

.. releasenotes/notes/conf-max-attach-disk-devices-82dc1e0825e00b35.yaml @ b'bb0906f4f3199295e9f65bd4c8f6cab995f4ec42'

- A new configuration option, ``[compute]/max_disk_devices_to_attach``, which
  defaults to ``-1`` (unlimited), has been added and can be used to configure
  the maximum number of disk devices allowed to attach to a single server,
  per compute host. Note that the number of disks supported by a server
  depends on the bus used. For example, the ``ide`` disk bus is limited to 4
  attached devices.

  Usually, disk bus is determined automatically from the device type or disk
  device, and the virtualization type. However, disk bus
  can also be specified via a block device mapping or an image property.
  See the ``disk_bus`` field in
  https://docs.openstack.org/nova/latest/user/block-device-mapping.html
  for more information about specifying disk bus in a block device mapping,
  and see
  https://docs.openstack.org/glance/latest/admin/useful-image-properties.html
  for more information about the ``hw_disk_bus`` image property.

  The configured maximum is enforced during server create, rebuild, evacuate,
  unshelve, live migrate, and attach volume. When the maximum is exceeded
  during server create, rebuild, evacuate, unshelve, or live migrate, the
  server will go into ``ERROR`` state and the server fault message will
  indicate the failure reason. When the maximum is exceeded during a server
  attach volume API operation, the request will fail with a
  ``403 HTTPForbidden`` error.

.. releasenotes/notes/disable-rt-cache-refresh-9f6633e585516760.yaml @ b'bbc2fcb8fb20dde1b81597c319392afb5b2c53fe'

- The configuration option
  ``[compute]resource_provider_association_refresh`` can now
  be set to zero to disable refresh entirely. This follows on from `bug
  1767309`_ allowing more aggressive reduction in the amount of traffic to
  the placement service.

  The cache can be cleared manually at any time by sending SIGHUP to the
  compute process. This will cause the cache to be repopulated the next time
  the data is accessed.

  .. _`bug 1767309`: https://bugs.launchpad.net/nova/+bug/1767309

.. releasenotes/notes/driver-capabilities-to-traits-152eb851cd016f4d.yaml @ b'7ce265ebc5937a922efabedbfcec4fa0733ea511'

- Compute drivers now expose capabilities via traits in the
  Placement API.  Capabilities must map to standard traits defined
  in `the os-traits project
  <https://docs.openstack.org/os-traits/latest/>`_; for now these
  are:

  * ``COMPUTE_NET_ATTACH_INTERFACE``
  * ``COMPUTE_DEVICE_TAGGING``
  * ``COMPUTE_NET_ATTACH_INTERFACE_WITH_TAG``
  * ``COMPUTE_VOLUME_ATTACH_WITH_TAG``
  * ``COMPUTE_VOLUME_EXTEND``
  * ``COMPUTE_VOLUME_MULTI_ATTACH``
  * ``COMPUTE_TRUSTED_CERTS``

  Any traits provided by the driver will be automatically added
  during startup or a periodic update of a compute node.  Similarly
  any traits later retracted by the driver will be automatically
  removed.

  However any traits which are removed by the admin from the compute
  node resource provider via the Placement API will not be
  reinstated until the compute service's provider cache is reset.
  This can be triggered via a ``SIGHUP``.

.. releasenotes/notes/instance-list-batching-45f90a8b13eef512.yaml @ b'c3a77f80b1863e114109af9c32ea01b205c1a735'

- Instance list operations across cells are now made more efficient by batching queries
  as a fraction of the total limit for a request. Before this, an instance list with a
  limit of 1000 records (the default) would generate queries to each cell with that
  limit, and potentially process/sort/merge $num_cells*$limit records, despite only
  returning $limit to the user. The strategy can now be controlled via
  ``[api]/instance_list_cells_batch_strategy`` and related options to either use
  fixed batch sizes, or a fractional value that scales with the number of configured
  cells.

.. releasenotes/notes/ironic-partition-compute-nodes-fc60a6557fae9c5e.yaml @ b'2728dec51a6011c7d340d7f6d98ccf30cd7249e0'

- In deployments with Ironic, adds the ability for compute services to manage
  a subset of Ironic nodes. If the ``[ironic]/partition_key`` configuration
  option is set, the compute service will only consider nodes with a matching
  ``conductor_group`` attribute for management. Setting the
  ``[ironic]/peer_list`` configuration option allows this subset of nodes to
  be distributed among the compute services specified to further reduce
  failure domain. This feature is useful to co-locate nova-compute services
  with ironic-conductor services managing the same nodes, or to better
  control failure domain of a given compute service.

.. releasenotes/notes/live-migration-force-after-timeout-54f2a4b631d295bb.yaml @ b'4c3698c0b63ef0a5298cd94a8f23f87605bfc0f5'

- A new configuration option ``[libvirt]/live_migration_timeout_action``
  is added. This new option will have choices ``abort`` (default)
  or ``force_complete``. This option will determine what actions will be
  taken against a VM after ``live_migration_completion_timeout`` expires.
  Currently nova just aborts the live migrate operation after completion
  timeout expires. By default, we keep the same behavior of aborting after
  completion timeout. ``force_complete`` will either pause the VM or trigger
  post-copy depending on if post copy is enabled and available.

  The ``[libvirt]/live_migration_completion_timeout`` is restricted by
  minimum 0 and will now raise a ValueError if the configuration option
  value is less than minimum value.

  Note if you configure Nova to have no timeout, post copy will never be
  automatically triggered. None of this affects triggering post copy via
  the force live-migration API, that continues to work in the same way.

.. releasenotes/notes/microversion-2.70-expose-virtual-device-tags-ca82ba6ee6cf9272.yaml @ b'1c6fdc9aecba310630b6e74e861d31a4c3be1bed'

- The 2.70 compute API microversion exposes virtual device tags for volume
  attachments and virtual interfaces (ports). A ``tag`` parameter is added
  to the response body for the following APIs:

  **Volumes**

  * GET /servers/{server_id}/os-volume_attachments (list)
  * GET /servers/{server_id}/os-volume_attachments/{volume_id} (show)
  * POST /servers/{server_id}/os-volume_attachments (attach)

  **Ports**

  * GET /servers/{server_id}/os-interface (list)
  * GET /servers/{server_id}/os-interface/{port_id} (show)
  * POST /servers/{server_id}/os-interface (attach)

.. releasenotes/notes/per-aggregate-scheduling-weight-7535fd6e8345034d.yaml @ b'e66443770dc97f3006b360095b5158d2b203a74a'

- Added the ability to allow users to use
  ``Aggregate``'s ``metadata`` to override the global config options
  for weights to achieve more fine-grained control over resource
  weights.

  Such as, for the CPUWeigher, it weighs hosts based on available vCPUs
  on the compute node, and multiplies it by the cpu weight multiplier. If
  per-aggregate value (which the key is "cpu_weight_multiplier") is found,
  this value would be chosen as the cpu weight multiplier. Otherwise, it
  will fall back to the ``[filter_scheduler]/cpu_weight_multiplier``. If
  more than one value is found for a host in aggregate metadata, the minimum
  value will be used.

.. releasenotes/notes/placement-reshaper-6f3ef70c3a550d09.yaml @ b'4d525b4ec1afbcfb93c93a19ccdc452af2ad0ebc'

- Microversion 1.30 of the placement API adds support for a
  ``POST /reshaper`` resource that provides for atomically migrating resource
  provider inventories and associated allocations when some of the inventory
  moves from one resource provider to another, such as when a class of
  inventory moves from a parent provider to a new child provider.

  .. note:: This is a special operation that should only be used in rare
            cases of resource provider topology changing when inventory is in
            use. Only use this if you are really sure of what you are doing.

.. releasenotes/notes/run-meta-api-per-cell-69d74cdd70528085.yaml @ b'e2e372b2b159630f82bb9e70a59ac87904ef7e7d'

- Added configuration option ``[api]/local_metadata_per_cell`` to allow
  users to run Nova metadata API service per cell. Doing this could provide
  performance improvement and data isolation in a multi-cell deployment.
  But it has some caveats, see the
  `Metadata api service in cells v2 layout`_ for more details.

  .. _Metadata api service in cells v2 layout: https://docs.openstack.org/nova/latest/user/cellsv2-layout.html#nova-metadata-api-service

.. releasenotes/notes/show-server-group-8d4bf609213a94de.yaml @ b'2cc7c0e58924b201d5353a6289883b0aec760543'

- Starting with the 2.71 microversion the ``server_groups`` parameter will be
  in the response body of the following APIs to list the server groups to
  which the server belongs:

  * ``GET /servers/{server_id}``
  * ``PUT /servers/{server_id}``
  * ``POST /servers/{server_id}/action (rebuild)``

.. releasenotes/notes/support-neutron-ports-with-resource-request-cb9ad5e9757792d0.yaml @ b'c4295f87adf0843746346e922a23de7ad1f920d3'

- API microversion 2.72 adds support for creating servers with neutron ports
  that has resource request, e.g. neutron ports with
  `QoS minimum bandwidth rule`_. Deleting servers with such ports have
  already been handled properly as well as detaching these type of ports.

  API limitations:

  * Creating servers with Neutron networks having QoS minimum bandwidth rule
    is not supported.

  * Attaching Neutron ports and networks having QoS minimum bandwidth rule
    is not supported.

  * Moving (resizing, migrating, live-migrating, evacuating,
    unshelving after shelve offload) servers with ports having resource
    request is not yet supported.

.. releasenotes/notes/support-qemu-native-tls-for-migration-31d8b0ae9eb2c893.yaml @ b'9160fe50987131feda9429c4e95d573e176916b6'

- The libvirt driver now supports "QEMU-native TLS" transport for live
  migration.  This will provide encryption for all migration streams,
  namely: guest RAM, device state and disks on a non-shared setup that are
  transported over NBD (Network Block Device), also called as "block
  migration".

  This can be configured via a new configuration attribute
  ``[libvirt]/live_migration_with_native_tls``.  Refer to its
  documentation in ``nova.conf`` for usage details.  Note that this is
  the preferred the way to secure all migration streams in an
  OpenStack network, instead of
  ``[libvirt]/live_migration_tunnelled``.

.. releasenotes/notes/support-to-query-nova-resources-filter-by-changes-before-e4942cde61070e28.yaml @ b'28c1075b59031fa154b1e2222ab2485b2f78fc5f'

- Microversion 2.66 adds the optional filter parameter ``changes-before``
  which can be used to get resources changed before or equal to the
  specified date and time.

  Like the ``changes-since`` filter, the ``changes-before`` filter will
  also return deleted servers.

  This parameter (``changes-before``) does not change any read-deleted
  behavior in the os-instance-actions or os-migrations APIs.
  The os-instance-actions API with the 2.21 microversion allows retrieving
  instance actions for a deleted server resource. The os-migrations API
  takes an optional ``instance_uuid`` filter parameter but does not support
  returning deleted migration records.

  The ``changes-before`` request parameter can be passed to the servers,
  os-instance-action and os-migrations APIs:

  * ``GET /servers``
  * ``GET /servers/detail``
  * ``GET /servers/{server_id}/os-instance-actions``
  * ``GET /os-migrations``

.. releasenotes/notes/versioned-notification-interface-is-complete-06725d7d4d761849.yaml @ b'c6e7cc927f0e202ef4a1faa643b0e3398c033443'

- The versioned notification interface of nova is now complete and in
  feature parity with the legacy interface. The emitted notifications
  are documented in `notification dev ref`_ with full sample files.
  The deprecation of the legacy notification interface is under discussion
  and will be handled separately.

  .. _notification dev ref: https://docs.openstack.org/nova/latest/reference/notifications.html#existing-versioned-notifications

.. releasenotes/notes/vmware-add-max-ram-validation-f27f94d4a04aef3a.yaml @ b'38aa83b7fc53b76f7cef92573da235838629b499'

- For the VMware vCenter driver, added support for the configured video ram ``hw_video_ram`` from the image,
  which will be checked against the maximum allowed video ram ``hw_video:ram_max_mb``
  from the flavor.
  If the selected video ram from the image is less than or equal to the maximum allowed ram,
  the ``videoRamSizeInKB`` will be set.
  If the selected ram is more than the maximum allowed one, then server creation will fail for the given
  image and flavor.
  If the maximum allowed video ram is not set in the flavor we do not set ``videoRamSizeInKB`` in the VM.

.. releasenotes/notes/vmware-live-migration-c09cce337301cab0.yaml @ b'2fe92e91625222afcc01765437ba47c5374b7a76'

- The VMware compute driver now supports live migration. Each compute node
  must be managing a cluster in the same vCenter and ESX hosts must have
  vMotion enabled.

.. releasenotes/notes/vrouter-hw-offloads-38257f49ac1d3a60.yaml @ b'4d32b45c152c4dedcb9d01380f557338c3acb81e'

- This release adds support for ``direct`` and ``virtio-forwarder`` VNIC
  types to the ``vrouter`` VIF type. In order to use these VNIC types,
  support is required from the version of OpenContrail, Contrail or Tungsten
  Fabric that is installed, as well the required hardware. At this time, the
  reference os-vif plugin is hosted on OpenContrail at
  https://github.com/Juniper/contrail-nova-vif-driver but is expected to
  transition to Tungsten Fabric in the future. Version 5.1 or later of the
  plugin is required to use these new VNIC types. Consult the `Tungsten
  Fabric documentation <https://tungstenfabric.github.io/website/>`_ for
  release notes, when available, about hardware support. For commercial
  support, consult the release notes from a downstream vendor.


.. _Release Notes_19.0.0_stein-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/conf-max-attach-disk-devices-82dc1e0825e00b35.yaml @ b'bb0906f4f3199295e9f65bd4c8f6cab995f4ec42'

- Operators changing the ``[compute]/max_disk_devices_to_attach`` on a
  compute service that is hosting servers should be aware that it could
  cause rebuilds to fail, if the maximum is decreased lower than the number
  of devices already attached to servers. For example, if server A has 26
  devices attached and an operators changes
  ``[compute]/max_disk_devices_to_attach`` to 20, a request to rebuild server
  A will fail and go into ERROR state because 26 devices are already
  attached and exceed the new configured maximum of 20.

  Operators setting ``[compute]/max_disk_devices_to_attach`` should also be
  aware that during a cold migration, the configured maximum is only enforced
  in-place and the destination is not checked before the move. This means if
  an operator has set a maximum of 26 on compute host A and a maximum of 20
  on compute host B, a cold migration of a server with 26 attached devices
  from compute host A to compute host B will succeed. Then, once the server
  is on compute host B, a subsequent request to rebuild the server will fail
  and go into ERROR state because 26 devices are already attached and exceed
  the configured maximum of 20 on compute host B.

  The configured maximum is not enforced on shelved offloaded servers, as
  they have no compute host.

.. releasenotes/notes/leaking_migration_allocations_in_placement-bd0a6f2a30e2e3d2.yaml @ b'3a43a931d4e46a0aa66683da22482f3e78f26cd7'

- Nova leaks resource allocations in placement during
  ``POST /servers/{server_id}/action (revertResize Action)`` and
  ``POST /servers/{server_id}/action (confirmResize Action)`` and
  ``POST /servers/{server_id}/action (os-migrateLive Action)`` and if the
  allocation held by the migration_uuid is modified in parallel with the
  lifecycle operation. Nova will log an ERROR and will put the server into
  ERROR state but will not delete the migration allocation. We assume that
  this can only happen if somebody outside of nova is actively changing the
  migration allocation in placement. Therefore it is not considered as a bug.

.. releasenotes/notes/min-bandwidth-workaround-0533ad03f67592a9.yaml @ b'70989c3eb508ac4633a921a3760e02a4b74a9784'

- Nova leaks bandwidth resources if a bound port that has QoS minimum
  bandwidth rules is deleted in Neutron before the port is logically detached
  from the server. To avoid any leaks, users should detach the port from the
  server using the Nova API first before deleting the port in Neutron. If the
  server is in a state such that the port cannot be detached using the Nova
  API, bandwidth resources will be freed when the server is deleted. Another
  alternative to clean up the leak is to remove the
  ``NET_BW_EGR_KILOBIT_PER_SEC`` and/or ``NET_BW_IGR_KILOBIT_PER_SEC``
  allocations related to the deleted port for the server `using the CLI`_.
  See related bug https://bugs.launchpad.net/nova/+bug/1820588 for more
  details.

  .. _using the CLI: https://docs.openstack.org/osc-placement/latest/cli/index.html#resource-provider-allocation-set


.. _Release Notes_19.0.0_stein-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/Use-virt-as-machine-type-for-ARMv7-cd2c252336057ec8.yaml @ b'e155baefb0bbaa0aa78e54fe9e0f10c12336c01a'

- The default QEMU machine type for ARMv7 architecture is now changed
  to ``virt`` (from the older ``vexpress-a15``, which is a particular
  ARM development board).  The ``virt`` board is the recommended
  default for ARMv7, which is explicitly designed to be
  used with virtual machines.  It is more flexible, supports PCI and
  'virtio' devices, has decent RAM limits, and so forth.  For
  pre-existing Nova guests on ARMv7 to acquire the ``virt`` machine
  type: (a) upgrade Nova with this fix; (b) explicitly start and stop
  the guests, then they will pick up the 'virt' machine type.

.. releasenotes/notes/add_initial_allocation_ratio-2d2666d62426a4bf.yaml @ b'945e7cb2a476258229ba94754c159ff966726459'

- The default value for the "cpu_allocation_ratio", "ram_allocation_ratio"
  and "disk_allocation_ratio" configurations have been changed to ``None``.

  The ``initial_cpu_allocation_ratio``, ``initial_ram_allocation_ratio`` and
  ``initial_disk_allocation_ratio`` configuration options have been added to
  the ``DEFAULT`` group:

  - initial_cpu_allocation_ratio with default value 16.0
  - initial_ram_allocation_ratio with default value 1.5
  - initial_disk_allocation_ratio with default value 1.0

  These options help operators specify initial virtual CPU/ram/disk to
  physical CPU/ram/disk allocation ratios. These options are only used when
  initially creating the ``computes_nodes`` table record for a given
  nova-compute service.

  Existing ``compute_nodes`` table records with ``0.0`` or ``None`` values
  for ``cpu_allocation_ratio``, ``ram_allocation_ratio`` or
  ``disk_allocation_ratio`` will be migrated online when accessed or when
  the ``nova-manage db online_data_migrations`` command is run.

  For more details, refer to the `spec`__.

  .. __: https://specs.openstack.org/openstack/nova-specs/specs/stein/approved/initial-allocation-ratios.html

.. releasenotes/notes/bug-1815791-f84a913eef9e3b21.yaml @ b'19cb8280232fd3b0ba0000a475d061ea9fb10e1a'

- Adds a ``use_cache`` parameter to the virt driver ``get_info``
  method. Out of tree drivers should add support for this
  parameter.

.. releasenotes/notes/conf-max-attach-disk-devices-82dc1e0825e00b35.yaml @ b'bb0906f4f3199295e9f65bd4c8f6cab995f4ec42'

- The new configuration option, ``[compute]/max_disk_devices_to_attach``
  defaults to ``-1`` (unlimited). Users of the libvirt driver should be
  advised that the default limit for non-ide disk buses has changed from 26
  to unlimited, upon upgrade to Stein. The ``ide`` disk bus continues to be
  limited to 4 attached devices per server.

.. releasenotes/notes/default-zero-disk-flavor-to-admin-api-fd99e162812c2c7f.yaml @ b'c8e65a5eb11515cfe70f8e6850b842cd594af6a5'

- The default value for policy rule
  ``os_compute_api:servers:create:zero_disk_flavor`` has changed from
  ``rule:admin_or_owner`` to ``rule:admin_api`` which means that by default,
  users without the admin role will not be allowed to create servers using
  a flavor with ``disk=0`` *unless* they are creating a volume-backed server.
  If you have these kinds of flavors, you may need to take action or
  temporarily override the policy rule. Refer to
  `bug 1739646 <https://launchpad.net/bugs/1739646>`_ for more details.

.. releasenotes/notes/disable-live-migration-with-numa-bc710a1bcde25957.yaml @ b'ae2e5650d14a2c81dd397727d67b60f9b8dd0dd7'

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

.. releasenotes/notes/drop-reqspec-migration-4d493450ce436f7e.yaml @ b'5fd2402d56c4f664c65ca96706b5ae1fbde9e6a0'

- The online data migration ``migrate_instances_add_request_spec``, which was
  added in the 14.0.0 Newton release, has now been removed. Compatibility
  code in the controller services for old instances without a matching
  ``request_specs`` entry in the ``nova_api`` database is also gone.
  Ensure that the ``Request Spec Migration`` check in the
  ``nova-status upgrade check`` command is successful before upgrading to
  the 19.0.0 Stein release.

.. releasenotes/notes/fill_virtual_interface_list-1ec5bcccde2ebd22.yaml @ b'3534471c578eda6236e79f43153788c4725a5634'

- The ``nova-manage db online_data_migrations`` command will now fill missing ``virtual_interfaces`` records for instances created before the Newton release. This is related to a fix for https://launchpad.net/bugs/1751923 which makes the _heal_instance_info_cache periodic task in the ``nova-compute`` service regenerate an instance network info cache from the current neutron port list, and the VIFs from the database are needed to maintain the port order for the instance.

.. releasenotes/notes/flavor-extra-spec-image-property-validation-7310954ba3822477.yaml @ b'5e7b840e48eb480ba1955e6ba52fbcaf9884c3fa'

- With added validations for flavor extra-specs and image properties, the
  APIs for server create, resize and rebuild will now return 400 exceptions
  where they did not before due to the extra-specs or properties not being
  properly formatted or being mutually incompatible.

  For all three actions we will now check both the flavor and image to
  validate the CPU policy, CPU thread policy, CPU topology, memory topology,
  hugepages, serial ports, realtime CPU mask, NUMA topology details, CPU
  pinning, and a few other things.

  The main advantage to this is to catch invalid configurations as early
  as possible so that we can return a useful error to the user rather than
  fail later on much further down the stack where the operator would have
  to get involved.

.. releasenotes/notes/ironic-remove-properties-scheduling-7555eb8e5e25f18d.yaml @ b'a985e34cdeef777fe7ff943e363a5f1be6d991b7'

- Ironic nodes are now only scheduled using the ``resource_class`` field set
  on the node. CPUs, RAM, and disks are not reported to the resource tracker.
  Ironic nodes must have the ``resource_class`` field set before upgrading.
  Flavors must also be configured to use resource classes instead of node
  properties. See the `ironic flavor configuration guide
  <https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html>`_
  for more information on doing this.

.. releasenotes/notes/libvirt-stein-vgpu-reshape-a1fa23b8ad8aa966.yaml @ b'054eb3a652f340d819f1b04567d0ed5e207ed733'

- The libvirt compute driver will "reshape" VGPU inventories and allocations
  on start of the ``nova-compute`` service. This will result in moving
  VGPU inventory from the root compute node resource provider to a nested
  (child) resource provider in the tree and move any associated VGPU
  allocations with it. This will be a one-time operation on startup in Stein.
  There is no end-user visible impact for this; it is for internal resource
  tracking purposes. See the `spec`__ for more details.

  .. __: https://specs.openstack.org/openstack/nova-specs/specs/stein/approved/reshape-provider-tree.html

.. releasenotes/notes/live-migration-force-after-timeout-54f2a4b631d295bb.yaml @ b'4c3698c0b63ef0a5298cd94a8f23f87605bfc0f5'

- Config option ``[libvirt]/live_migration_progress_timeout`` was deprecated
  in Ocata, and has now been removed.

  Current logic in libvirt driver to auto trigger post-copy based on
  progress information is removed as it has `proved impossible`__ to detect
  when live-migration appears to be making little progress.

  .. __: https://bugs.launchpad.net/nova/+bug/1644248

.. releasenotes/notes/live_migration_wait_for_vif_plug-stein-default-true-12103b09b8ac686a.yaml @ b'1a42eb9ec13b04c96f6eb380a53d1e656f087f36'

- The default value for the ``[compute]/live_migration_wait_for_vif_plug``
  configuration option has been changed to True. As noted in the help text
  for the option, some networking backends will not work with this set to
  True, although OVS and linuxbridge will.

.. releasenotes/notes/maximum_instance_delete_attempts-option-force-minimum-value-2ce74351650e7b21.yaml @ b'25477e6771a226bb676b2d54e5ccffe5c5a64fb0'

- The ``maximum_instance_delete_attempts`` configuration option has been restricted by the minimum value and now raises a ValueError if the value is less than 1.

.. releasenotes/notes/move-vrouter-plug-unplug-to-separate-os-vif-plugin-5557c9cd6f926fd8.yaml @ b'172855f293b6a48b4b64fd9e47c377c7124e192c'

- This release moves the ``vrouter`` VIF plug and unplug code to a
  separate package called ``contrail-nova-vif-driver``. This package is a
  requirement on compute nodes when using Contrail, OpenContrail or
  Tungsten Fabric as a Neutron plugin.
  At this time, the reference plugin is hosted on OpenContrail at
  https://github.com/Juniper/contrail-nova-vif-driver but is expected to
  transition to Tungsten Fabric in the future.
  Release ``r5.1.alpha0`` or later of the plugin is required, which will
  be included in Tungsten Fabric 5.1.

.. releasenotes/notes/nova-manage-online-migrations-exit-status-9de5ea7836d0e368.yaml @ b'3eea37b85b1abc72786a2b24baf01141b4d95f08'

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

.. releasenotes/notes/nova-status-check-consoleauths-618acb3a67f97418.yaml @ b'ea71592d7a10e453e648744f290feb593a50114a'

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

.. releasenotes/notes/per-instance-serial-f2e597cb05d1b09e.yaml @ b'b29158149d802cfc81541f13255394da559d0c48'

- Added a new ``unique`` choice to the ``[libvirt]/sysinfo_serial``
  configuration which if set will result in the guest serial number being
  set to ``instance.uuid``. This is now the default value
  of the ``[libvirt]/sysinfo_serial`` config option and is the recommended
  choice since it ensures the guest serial is the same even if the instance
  is migrated between hosts.

.. releasenotes/notes/remove-caching-scheduler-cfe0985b5a58bef4.yaml @ b'25dadb94db37e0f1c6769bf586ec06c3b5ea3051'

- The ``caching_scheduler`` scheduler driver, which was deprecated in the
  16.0.0 Pike release, has now been removed. Unlike the default
  ``filter_scheduler`` scheduler driver which creates resource allocations
  in the placement service during scheduling, the ``caching_scheduler``
  driver did not interface with the placement service. As more and more
  functionality within nova relies on managing (sometimes complex) resource
  allocations in the placement service, compatibility with the
  ``caching_scheduler`` driver is difficult to maintain, and seldom tested.
  The original reasons behind the need for the CachingScheduler should now
  be resolved with the FilterScheduler and the placement service, notably:

  * resource claims (allocations) are made atomically during scheduling to
    alleviate the potential for racing to concurrently build servers on the
    same compute host which could lead to failures
  * because of the atomic allocation claims made during scheduling by the
    ``filter_scheduler`` driver, it is safe [1]_ to run multiple scheduler
    workers and scale horizontally

    .. [1] There are still known race issues with concurrently building some
      types of resources and workloads, such as anything that requires
      PCI/NUMA or (anti-)affinity groups. However, those races also existed
      with the ``caching_scheduler`` driver.

  To migrate from the CachingScheduler to the FilterScheduler, operators can
  leverage the ``nova-manage placement heal_allocations`` command:

  https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement

  Finally, it is still technically possible to load an out-of-tree scheduler
  driver using the ``nova.scheduler.driver`` entry-point. However,
  out-of-tree driver interfaces are not guaranteed to be stable:

  https://docs.openstack.org/nova/latest/contributor/policies.html#out-of-tree-support

  And as noted above, as more of the code base evolves to rely on resource
  allocations being tracked in the placement service (created during
  scheduling), out-of-tree scheduler driver support may be severely impacted.

  If you rely on the ``caching_scheduler`` driver or your own out-of-tree
  driver which sets ``USES_ALLOCATION_CANDIDATES = False`` to bypass the
  placement service, please communicate with the nova development team in
  the openstack-dev mailing list and/or #openstack-nova freenode IRC channel
  to determine what prevents you from using the ``filter_scheduler`` driver.

.. releasenotes/notes/remove-deprecated-api-extensions-policies-311846b2eb839a22.yaml @ b'f72fa9a739ce3f9e789ffa8547c3a9447a735c3b'

- The following deprecated Policy Rules have been removed:

  - Show & List server details

    - os_compute_api:os-config-drive
    - os_compute_api:os-extended-availability-zone
    - os_compute_api:os-extended-status
    - os_compute_api:os-extended-volumes
    - os_compute_api:os-keypairs
    - os_compute_api:os-server-usage
    - os_compute_api:os-security-groups (only from /servers APIs)

  - Create, Update, Show & List flavor details

    - os_compute_api:os-flavor-rxtx
    - os_compute_api:os-flavor-access (only from /flavors APIs)

  - Show & List image details

    - os_compute_api:image-size

  These were deprecated in the 17.0.0 release as nova removed the concept
  of API extensions.

.. releasenotes/notes/remove-deprecated-flavors-policy-c03c5d227a7b0c87.yaml @ b'297bedbfde0a99de4ab3e7cc6b4c65bb1d34d1d0'

- The ``os_compute_api:flavors`` policy deprecated in 16.0.0 has been removed.

.. releasenotes/notes/remove-deprecated-os-flavor-manage-policy-138296853d957c5f.yaml @ b'dedeff70a76f1485cfa1f32683e122957063e6ef'

- The ``os_compute_api:os-flavor-manage`` policy has been removed
  because it has been deprecated since 16.0.0.
  Use the following policies instead:

  * ``os_compute_api:os-flavor-manage:create``
  * ``os_compute_api:os-flavor-manage:delete``

.. releasenotes/notes/remove-deprecated-os-server-groups-policy-de89d5d11d490338.yaml @ b'84341788231e7bfb15a33c871b58fe31dba108a5'

- The ``os_compute_api:os-server-groups`` policy deprecated in 16.0.0 has been removed.

.. releasenotes/notes/remove-live-migrate-evacuate-force-flag-cb50608d5930585c.yaml @ b'36a91936a821b0c1f502d7d8f1ffd8c4d179d212'

- It is no longer possible to force server live migrations or evacuations
  to a specific destination host starting with API microversion 2.68.
  This is because it is not possible to support these requests for servers
  with complex resource allocations. It is still possible to request a
  destination host but it will be validated by the scheduler.

.. releasenotes/notes/remove-quota-options-0e407c56ea993f5a.yaml @ b'4743b08f47d5058f557d923736837cee16ecb2e2'

- The following configuration options in the ``quota`` group have been
  removed because they have not been used since 17.0.0.

  - ``reservation_expire``
  - ``until_refresh``
  - ``max_age``

.. releasenotes/notes/remove_ChanceScheduler-0f4861f788adcfc7.yaml @ b'92a459331f775569b95aae05d37f7143fe95e96a'

- The ``chance_scheduler`` scheduler driver was deprecated in Pike
  and has now been removed. You should enable the ``filter_scheduler``
  driver instead. If ``chance_scheduler`` behavior is desired
  (i.e. speed is valued over correctness) then configuring the
  ``filter_scheduler`` with only the ``AllHostsFilter`` enabled and
  adjusting ``[filter_scheduler]/host_subset_size`` will provide similar
  performance.

.. releasenotes/notes/stein-affinity-weight-multiplier-cleanup-fed9ec25660befd3.yaml @ b'313becd5ffac3fd7c9a41d34134ee66d9a145228'

- The ``[filter_scheduler]/soft_affinity_weight_multiplier`` and
  ``[filter_scheduler]/soft_anti_affinity_weight_multiplier`` configuration
  options now have a hard minimum value of 0.0. Also, the deprecated alias
  to the ``[DEFAULT]`` group has been removed so the options must appear in
  the ``[filter_scheduler]`` group.

.. releasenotes/notes/stein-remove-hide_server_address_states-edbc36bc02e1df52.yaml @ b'9b69afd4573bf6e44d696e2bdacac44f172e8f3c'

- The ``[api]/hide_server_address_states`` configuration option and
  ``os_compute_api:os-hide-server-addresses`` policy rule were deprecated
  in the 17.0.0 Queens release. They have now been removed. If you never
  changed these values, the API behavior remains unchanged.


.. _Release Notes_19.0.0_stein-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-config_drive_format-62d481260c254187.yaml @ b'c19ecc34ea7fc19e5c4278eb4fda8b5cf7e9d638'

- The ``config_drive_format`` config option has been deprecated. This was
  necessary to workaround an issue with libvirt that was later resolved in
  libvirt v1.2.17. For more information refer to `bug #1246201`__.

  __ https://bugs.launchpad.net/nova/+bug/1246201

.. releasenotes/notes/deprecate-core-ram-disk-filters-06a3ce2a820426d9.yaml @ b'243ba8513097ca715af738422a9e1249c6a7a1f0'

- The ``CoreFilter``, ``DiskFilter`` and ``RamFilter`` are now deprecated.
  VCPU, DISK_GB and MEMORY_MB filtering is performed natively using the
  Placement service when using the ``filter_scheduler`` driver. Users of the
  ``caching_scheduler`` driver may still rely on these filters but the
  ``caching_scheduler`` driver is itself deprecated. Furthermore, enabling
  these filters may incorrectly filter out baremetal nodes which must be
  `scheduled using custom resource classes <https://docs.openstack.org/ironic/latest/install/configure-nova-flavors.html>`_.

.. releasenotes/notes/deprecate-disable_libvirt_livesnapshot-413c71b96f5e38d4.yaml @ b'1fae0052f23cc8d8511833ea9b7b9090e88e4d3b'

- The ``[workarounds] disable_libvirt_livesnapshot`` config option has been
  deprecated. This was necessary to work around an issue with libvirt v1.2.2,
  which we no longer support. For more information refer to `bug
  #1334398`__.

  __ https://bugs.launchpad.net/nova/+bug/1334398

.. releasenotes/notes/deprecate-nova-console-8247a1e2565dc326.yaml @ b'1f0c79b39ab6267f7ce00268b5fe456839c4f492'

- The ``nova-console`` service is deprecated as it is XenAPI specific, does
  not function properly in a multi-cell environment, and has effectively
  been replaced by noVNC and the ``nova-novncproxy`` service. noVNC should
  therefore be configured instead.

.. releasenotes/notes/deprecate-nova-xvpvncproxy-16b56634cd07dbd9.yaml @ b'4e6cffe45e3e132066822129dd540b15ecdef667'

- The nova-xvpvncproxy service is deprecated as it is Xen specific and has
  effectively been replaced by noVNC and the nova-novncproxy service.

.. releasenotes/notes/deprecate-yet-another-nova-network-opt-b23b7bd9c31383eb.yaml @ b'5a0027204342168614d9e3b2990748eadd43221d'

- The following options, found in ``DEFAULT``, were only used for configuring
  nova-network and are, like nova-network itself, now deprecated.

  - ``defer_iptables_apply``


.. _Release Notes_19.0.0_stein-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1378904-disable-az-rename-b22a558a20b12706.yaml @ b'8e19ef4173906da0b7c761da4de0728a2fd71e24'

- ``PUT /os-aggregates/{aggregate_id}`` and
  ``POST /os-aggregates/{aggregate_id}/action`` (for set_metadata action) will
  now return HTTP 400 for availability zone renaming if the hosts of
  the aggregate have any instances.

.. releasenotes/notes/bug-1675791-snapshot-member-access-c40bba36606618f7.yaml @ b'35cc0f5e943642dd8d9dacbf0dac6e260f708d7d'

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

.. releasenotes/notes/bug-1773342-52b6a1460c7bee64.yaml @ b'716d17e05491b5d319025cfce221eca5f78e02c0'

- Fixes `bug 1773342`_ where the Hyper-v driver always deleted unused images
  ignoring ``remove_unused_images`` config option. This change will now allow
  deployers to disable the auto-removal of old images.

  .. _bug 1773342: https://bugs.launchpad.net/nova/+bug/1773342

.. releasenotes/notes/bug-1795992-long_rpc_timeout-select_destinations-9712e8690160928f.yaml @ b'5af632e9cab670cc25c2f627bb0d4c0a02258277'

- The ``long_rpc_timeout`` configuration option is now used for the RPC
  call to the scheduler to select a host. This is in order to avoid a
  timeout when scheduling multiple servers in a single request and/or when
  the scheduler needs to process a large number of hosts.

.. releasenotes/notes/bug-1799707-fix-shutdown_timeout-min-22ce0b373af1ec90.yaml @ b'2cff865af4a36c200a7b1737929b7e0595325478'

- The ``[DEFAULT]/shutdown_timeout`` configuration option minimum value has
  been fixed to be 0 rather than 1 to align with the corresponding
  ``os_shutdown_timeout`` image property. See bug
  https://launchpad.net/bugs/1799707 for details.

.. releasenotes/notes/bug-1801702-c8203d3d55007deb.yaml @ b'14d98ef1b48ca7b2ea468a8f1ec967b954955a63'

- When testing whether direct IO is possible on the backing storage
  for an instance, Nova now uses a block size of 4096 bytes instead
  of 512 bytes, avoiding issues when the underlying block device has
  sectors larger than 512 bytes. See bug
  https://launchpad.net/bugs/1801702 for details.

.. releasenotes/notes/bug-1815791-f84a913eef9e3b21.yaml @ b'19cb8280232fd3b0ba0000a475d061ea9fb10e1a'

- Fixes a race condition that could allow a newly created Ironic
  instance to be powered off after deployment, without letting
  the user power it back on.

.. releasenotes/notes/fix-simple-tenant-usage-pagination-393ed6e7d0e31594.yaml @ b'afc3a16ce3364c233e6e1cffc9f38987d1d65318'

- The ``os-simple-tenant-usage`` pagination has been fixed. In some cases,
  nova usage-list would have returned incorrect results because of this.
  See bug https://launchpad.net/bugs/1796689 for details.

.. releasenotes/notes/libvirt-live-migration-speed-limit-revert-81a9d29d60b0df4b.yaml @ b'411c45842f6b4bef21710b4d7fa2f473976bc566'

- Note that the original fix for `bug 1414559`_ committed early in rocky was automatic and always
  enabled. Because of `bug 1786346`_ that fix has since been reverted and superseded by an opt-in
  mechanism which must be enabled. Setting ``[compute]/live_migration_wait_for_vif_plug=True``
  will restore the behavior of `waiting for neutron events`_ during the live migration process.

  .. _bug 1414559: https://bugs.launchpad.net/neutron/+bug/1414559
  .. _bug 1786346: https://bugs.launchpad.net/nova/+bug/1786346
  .. _waiting for neutron events: https://docs.openstack.org/nova/latest/configuration/config.html#compute.live_migration_wait_for_vif_plug

.. releasenotes/notes/libvirt_fix_ipv6_live_migration-bbcde8f3b7d17921.yaml @ b'8b019d6f1e7893a7e308bd79c879e94d3400e007'

- A change has been introduced in the libvirt driver to correctly handle IPv6 addresses for live migration.

.. releasenotes/notes/make-disk-image-conversion-faster-c4abe83ae702888b.yaml @ b'e7b64eaad82db38dd46f586b650da4ddde42533b'

- By using ``writeback`` QEMU cache mode, make Nova's disk image
  conversion (e.g. from raw to QCOW2 or vice versa) dramatically
  faster, without compromising data integrity.  `Bug 1818847`_.

  .. _Bug 1818847: https://bugs.launchpad.net/nova/+bug/1818847

.. releasenotes/notes/set-endpoint-interface-for-ironicclient-a0b6b8f8dedc7341.yaml @ b'e082bdc166cb8215576801e0c89ef1fe771681ed'

- [`bug 1818295 <https://bugs.launchpad.net/nova/+bug/1818295>`_]
  Fixes the problem with endpoint lookup in Ironic driver where only public
  endpoint is possible, which breaks deployments where the controllers have
  no route to the public network per security requirement. Note that
  python-ironicclient fix I610836e5038774621690aca88b2aee25670f0262 must
  also be present to resolve the bug.


.. _Release Notes_19.0.0_stein-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/bug-1414895-8f7d8da6499f8e94.yaml @ b'd6c1f6a1032ed2ea99f3d8b70ccf38065163d785'

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

.. releasenotes/notes/bug-1803627-cinder-catalog-info-service-name-optional-fa673ad29fb762ea.yaml @ b'd0ba488c1df86905082a13cc8598548244db0fd7'

- The ``[cinder]/catalog_info`` default value is changed such that the
  ``service_name`` portion of the value is no longer set and is also
  no longer required. Since looking up the cinder endpoint in the service
  catalog should only need the endpoint type (``volumev3`` by default) and
  interface (``publicURL`` by default), the service name is dropped and only
  provided during endpoint lookup if configured.
  See `bug 1803627 <https://bugs.launchpad.net/nova/+bug/1803627>`_ for
  details.

.. releasenotes/notes/records-list-skip-down-cells-84d995e75c77c041.yaml @ b'21c5f3e2e5eee162e9781f733f2eac7ebd94655f'

- In case of infrastructure failures like non-responsive cells, prior to
  `change e3534d`_ we raised an API 500 error. However currently when
  listing instances or migrations, we skip that cell and display results from
  the up cells with the aim of increasing availability at the expense of
  accuracy. If the old behaviour is desired, a new flag called
  ``CONF.api.list_records_by_skipping_down_cells`` has been added which can
  be set to False to mimic the old behavior. Both of these potential
  behaviors will be unified in an upcoming microversion done through the
  `blueprint handling-down-cell`_  where minimal constructs would be returned
  for the down cell instances instead of raising 500s or skipping down cells.

  .. _change e3534d : https://review.openstack.org/#/q/I308b494ab07f6936bef94f4c9da45e9473e3534d
  .. _blueprint handling-down-cell: https://blueprints.launchpad.net/nova/+spec/handling-down-cell

.. releasenotes/notes/reject-interface-attach-with-port-resource-request-17473ddc5a989a2a.yaml @ b'c4295f87adf0843746346e922a23de7ad1f920d3'

- The ``POST /servers/{server_id}/os-interface`` request will be rejected
  with HTTP 400 if the Neutron port referenced in the request body has
  resource request as Nova currently cannot support such operation. For
  example a Neutron port has resource request if a `QoS minimum bandwidth
  rule`_ is attached to that port in Neutron.

  .. _QoS minimum bandwidth rule: https://docs.openstack.org/neutron/latest/admin/config-qos-min-bw.html

.. releasenotes/notes/reject-networks-with-qos-policy-2746c74fd1f3ff26.yaml @ b'c4295f87adf0843746346e922a23de7ad1f920d3'

- The ``POST /servers/{server_id}/os-interface`` request and the
  ``POST /servers`` request will be rejected with HTTP 400 if the Neutron
  network referenced in the request body has `QoS minimum bandwidth rule`_
  attached as Nova currently cannot support such operations.

  .. _QoS minimum bandwidth rule: https://docs.openstack.org/neutron/latest/admin/config-qos-min-bw.html

.. releasenotes/notes/stein-nova-cells-v1-experimental-ci-de47b3c62e5fb675.yaml @ b'e02fbb53d5fe093469d2aa188007ed2c5c67c98b'

- CI testing of Cells v1 has been moved to the ``experimental`` queue meaning
  changes proposed to nova will not be tested against a Cells v1 setup unless
  explicitly run through the ``experimental`` queue by leaving a review
  comment on the patch of "check experimental". Cells v1 has been deprecated
  since the 16.0.0 Pike release and this is a further step in its eventual
  removal.


