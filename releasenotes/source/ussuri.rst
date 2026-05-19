===========================
Ussuri Series Release Notes
===========================

.. _Release Notes_21.2.4-19_ussuri-eol:

21.2.4-19
=========

.. _Release Notes_21.2.4-19_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/fix-ironic-compute-restart-port-attachments-3282e9ea051561d4.yaml @ b'2b8c1cffe409af1e1da6597ea0b7b96931a035f7'

- Fixes slow compute restart when using the ``nova.virt.ironic`` compute
  driver where the driver was previously attempting to attach VIFS on
  start-up via the ``plug_vifs`` driver method. This method has grown
  otherwise unused since the introduction of the ``attach_interface``
  method of attaching VIFs. As Ironic manages the attachment of VIFs to
  baremetal nodes in order to align with the security requirements of a
  physical baremetal node's lifecycle. The ironic driver now ignores calls
  to the ``plug_vifs`` method.

.. releasenotes/notes/ignore-instance-task-state-for-evacuation-e000f141d0153638.yaml @ b'90e65365ab608792c4b8d8c4c3a87798fccadeec'

- If compute service is down in source node and user try to stop
  instance, instance gets stuck at powering-off, hence evacuation fails with
  msg: Cannot 'evacuate' instance <instance-id> while it is in
  task_state powering-off.
  It is now possible for evacuation to ignore the vm task state.
  For more details see: `bug 1978983`_

  .. _`bug 1978983`: https://bugs.launchpad.net/nova/+bug/1978983

.. releasenotes/notes/minimize-bug-1841481-race-window-f76912d4985770ad.yaml @ b'67be896e0f70ac3f4efc4c87fc03395b7029e345'

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


.. _Release Notes_21.2.3_ussuri-eol:

21.2.3
======

.. _Release Notes_21.2.3_ussuri-eol_Security Issues:

Security Issues
---------------

.. releasenotes/notes/console-proxy-reject-open-redirect-4ac0a7895acca7eb.yaml @ b'719e651e6be277950632e0c2cf5cc9a018344e7b'

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


.. _Release Notes_21.2.3_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1939604-547c729b7741831b.yaml @ b'fa0ad18619bfc1d56afdc7aa61729a1098ef651a'

- Addressed an issue that prevented instances with 1 vcpu using multiqueue
  feature from being created successfully when their vif_type is TAP.


.. _Release Notes_21.2.2_ussuri-eol:

21.2.2
======

.. _Release Notes_21.2.2_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1821755-7bd03319e34b6b10.yaml @ b'bf90a1e06181f6b328b967124e538c6e2579b2e5'

- Improved detection of anti-affinity policy violation when performing live
  and cold migrations. Most of the violations caused by race conditions due
  to performing concurrent live or cold migrations should now be addressed
  by extra checks in the compute service. Upon detection, cold migration
  operations are automatically rescheduled, while live migrations have two
  checks and will be rescheduled if detected by the first one, otherwise the
  live migration will fail cleanly and revert the instance state back to its
  previous value.


.. _Release Notes_21.2.0_ussuri-eol:

21.2.0
======

.. _Release Notes_21.2.0_ussuri-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/warn-when-services-started-with-old-compute-fc80b4ff58a2aaea.yaml @ b'75bac345d5d579591f6f7f047f0c8f68b4e89002'

- Nova services only support old computes if the compute is not
  older than the previous major nova release. From now on nova services will
  emit a warning at startup if the deployment contains too old compute
  services. From the 23.0.0 (Wallaby) release nova services will refuse to
  start if the deployment contains too old compute services to prevent
  compatibility issues.


.. _Release Notes_21.2.0_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/restore-rocky-portbinding-semantics-48e9b1fa969cc5e9.yaml @ b'afa843c8a7e128489a8245ed7a1b391c022b3305'

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


.. _Release Notes_21.1.2_ussuri-eol:

21.1.2
======

.. _Release Notes_21.1.2_ussuri-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/cros-scell-resize-not-supported-with-ports-having-resource-request-a8e1029ef5983793.yaml @ b'8daac915bba7e9431c70b27ffef34bef28a9b0e1'

- When the tempest test coverage was added for resize and cold migrate
  with neutron ports having QoS minimum bandwidth policy rules we
  discovered that the cross cell resize code path cannot handle such ports.
  See bug https://bugs.launchpad.net/nova/+bug/1907522 for details. A fix
  was implemented that makes sure that Nova falls back to same-cell resize if
  the server has such ports.


.. _Release Notes_21.1.2_ussuri-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/increase_glance_num_retries-ddfcd7053631882b.yaml @ b'1f9dd694b937cc55a81a64fdce442829f009afb3'

- The default for ``[glance] num_retries`` has changed from ``0`` to ``3``.
  The option controls how many times to retry a Glance API call in response
  to a HTTP connection failure. When deploying Glance behind HAproxy it is
  possible for a response to arrive just after the HAproxy idle time. As a
  result, an exception will be raised when the connection is closed resulting
  in a failed request. By increasing the default value, Nova can be more
  resilient to this scenario were HAproxy is misconfigured by retrying the
  request.


.. _Release Notes_21.1.2_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841932-c871ac7b3b05d67e.yaml @ b'9d28d7ec808469ec129b66c69b9e63cd9537a63f'

- Add support for the ``hw:hide_hypervisor_id`` extra spec. This is an
  alias for the ``hide_hypervisor_id`` extra spec, which was not
  compatible with the ``AggregateInstanceExtraSpecsFilter`` scheduler
  filter. See
  `bug 1841932 <https://bugs.launchpad.net/nova/+bug/1841932>`_ for more
  details.

.. releasenotes/notes/bug-1892361-pci-deivce-type-update-c407a66fd37f6405.yaml @ b'f58399cf496566e39d11f82a61e0b47900f2eafa'

- Fixes `bug 1892361`_ in which the pci stat pools are not updated when an
  existing device is enabled with SRIOV capability. Restart of nova-compute
  service updates the pci device type from type-PCI to type-PF but the pools
  still maintain the device type as type-PCI. And so the PF is considered for
  allocation to instance that requests vnic_type=direct. With this fix, the
  pci device type updates are detected and the pci stat pools are updated
  properly.

  .. _bug 1892361: https://bugs.launchpad.net/nova/+bug/1892361


.. _Release Notes_21.1.1_ussuri-eol:

21.1.1
======

.. _Release Notes_21.1.1_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1841363-fallback-to-threaded-io-when-native-io-is-not-supported-fe56014e9648a518.yaml @ b'0bd58921a1fcaffcc4fac25f63434c9cab93b061'

- Since Libvirt v.1.12.0 and the introduction of the `libvirt issue`_ ,
  there is a fact that if we set cache mode whose write semantic is not
  O_DIRECT (i.e. "unsafe", "writeback" or "writethrough"), there will
  be a problem with the volume drivers (i.e. LibvirtISCSIVolumeDriver,
  LibvirtNFSVolumeDriver and so on), which designate native io explicitly.

  When the driver_cache (default is none) has been configured as neither
  "none" nor "directsync", the libvirt driver will ensure the driver_io
  to be "threads" to avoid an instance spawning failure.

  .. _`libvirt issue`: https://bugzilla.redhat.com/show_bug.cgi?id=1086704

.. releasenotes/notes/bug-1889633-37e524fb6c20fbdf.yaml @ b'7ddab327675d36a4ba59d02d22d042d418236336'

- An issue that could result in instances with the ``isolate`` thread policy
  (``hw:cpu_thread_policy=isolate``) being scheduled to hosts with SMT
  (HyperThreading) and consuming ``VCPU`` instead of ``PCPU`` has been
  resolved. See `bug #1889633`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1889633

.. releasenotes/notes/bug-1892870-eb894956bf04713d.yaml @ b'1825fa997d93fce2bb397409bc954c810a8243a7'

- Resolve a race condition that may occur during concurrent
  ``interface detach/attach``, resulting in an interface accidentally unbind
  after attached. See `bug 1892870`_ for more details.

  .. _bug 1892870: https://bugs.launchpad.net/nova/+bug/1892870

.. releasenotes/notes/bug-1893263-769acadc4b6141d0.yaml @ b'a69845f3732843ee1451b2e4ebf547d9801e898d'

- Addressed an issue that prevented instances using multiqueue feature from
  being created successfully when their vif_type is TAP.

.. releasenotes/notes/bug-1894966-d25c12b1320cb910.yaml @ b'781210bd598c3e0ee9bd6a7db5d25688b5fc0131'

- Resolved an issue whereby providing an empty list for the ``policies``
  field in the request body of the ``POST /os-server-groups`` API would
  result in a server error. This only affects the 2.1 to 2.63 microversions,
  as the 2.64 microversion replaces the ``policies`` list field with a
  ``policy`` string field. See `bug #1894966`__ for more information.

  .. __: https://bugs.launchpad.net/nova/+bug/1894966


.. _Release Notes_21.1.0_ussuri-eol:

21.1.0
======

.. _Release Notes_21.1.0_ussuri-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1882821-file-backed-memory-reserved-conflict-3ad4c04ab993ebf8.yaml @ b'9d3ebd58aa6a7514ab4db401980848570415706a'

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


.. _Release Notes_21.1.0_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1878024-reserve-disk-for-image-cache-ef6688f869b12bcb.yaml @ b'968981b5853724a8225cfc16b04ea83b4f485a9a'

- A new ``[workarounds]/reserve_disk_resource_for_image_cache`` config
  option was added to fix the `bug 1878024`_ where the images in the compute
  image cache overallocate the local disk. If this new config is set then the
  libvirt driver will reserve DISK_GB resources in placement based on the
  actual disk usage of the image cache.

  .. _bug 1878024: https://bugs.launchpad.net/nova/+bug/1878024

.. releasenotes/notes/bug-1882919-support-e1000e-vif-5437a45c13dff978.yaml @ b'840de3b8924612fa3fc47a4c9032a4723d536613'

- Previously, attempting to configure an instance with the ``e1000e`` or
  legacy ``VirtualE1000e`` VIF types on a host using the QEMU/KVM driver
  would result in an incorrect ``UnsupportedHardware`` exception. These
  interfaces are now correctly marked as supported.


.. _Release Notes_21.0.0_ussuri-eol:

21.0.0
======

.. _Release Notes_21.0.0_ussuri-eol_Prelude:

Prelude
-------

.. releasenotes/notes/ussuri-prelude-4b96f1244cefcdf4.yaml @ b'f284b264b98e238c8e63bcda82df178d18d1225d'

The 21.0.0 release includes many new features and bug fixes. Please be
sure to read the upgrade section which describes the required actions to
upgrade your cloud from 20.0.0 (Train) to 21.0.0 (Ussuri).

There are a few major changes worth mentioning. This is not an exhaustive
list:

- The latest Compute API microversion supported for Ussuri is v2.87.
  Details on REST API microversions added since the 20.0.0 Train release
  can be found in the `REST API Version History`__ page.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html

- `Image pre-caching support to compute hosts`__ using ``os-aggregates``
  API information, allowing some distributed edge cases and preemptive
  image caching for instance creation.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id74

- Support for `cold migrating and resizing servers between Nova cells`__.

  .. __: https://docs.openstack.org/nova/latest/admin/configuration/cross-cell-resize.html

- Added support for `evacuate, live migrate and unshelve servers with
  minimum bandwidth guarantees`__.

  .. __: https://docs.openstack.org/api-guide/compute/port_with_resource_request.html

- New ``nova-manage placement audit`` CLI command to `find and clean up
  orphaned resource allocations`__.

  .. __: https://docs.openstack.org/nova/latest/cli/nova-manage.html

- Support for scope types and additional roles in the default nova
  policies, allowing for richer access management including the ability to
  configure *read-only* access to resources. This feature is disabled by
  default. See the `Policy Concepts`__ documentation for more details.

  .. __: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html

- Support for `creating servers with accelerator devices via Cyborg`__.

  .. __: https://docs.openstack.org/api-guide/compute/accelerator-support.html

- Enabled `rescue for boot-from-volume instances`__. Rescue now also allows
  to attach stable disk devices to the rescued instance.

  .. __: https://docs.openstack.org/nova/latest/user/rescue.html

- Validation for `known flavor extra specs with recognized namespaces`__.

  .. __: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id79

- Support for `heterogeneous virtual GPU types per compute node`__.

  .. __: https://docs.openstack.org/nova/latest/admin/virtual-gpu.html#enable-gpu-types-compute

- Python 2 is no longer supported by Nova, Python 3.6 and 3.7 are.

- Removal of the ``os-consoles`` and ``os-networks`` REST APIs. See the
  :ref:`Upgrade Notes <21.0.0.0-upgrade-notes-os-consoles>` section for more details.

- Removal of the ``nova-dhcpbridge``, ``nova-console`` and
  ``nova-xvpvncproxy`` services. See the :ref:`Upgrade Notes <21.0.0.0-upgrade-notes-xvncproxy>` section for more
  details.


.. _Release Notes_21.0.0_ussuri-eol_New Features:

New Features
------------

.. releasenotes/notes/accelerator-requests-6c9a6fef77ab776a.yaml @ b'0a795a3b64a25bd03ea520309ff555935112d9ee'

- Handling accelerator requests for an instance is now supported (where
  supported by the underlying virt driver) as of microversion
  2.82. The Cyborg service generates an event for the binding
  completion for each accelerator request (ARQ) for an instance.
  Adds a new event ``accelerator_request_bound`` for this to the API
  ``POST /os-server-external-events``

  The lists of operations that are supported or unsupported for
  instances with accelerators are listed in
  `accelerator operation guide
  <https://docs.openstack.org/api-guide/compute/accelerator-support.html>`_

.. releasenotes/notes/add-support-for-live-migration-with-vpmem-9af5057dbe551f3b.yaml @ b'4bd5af66b55b1ac5e5fa654eb31bf90616d62256'

- The libvirt driver now supports live migration with virtual persistent
  memory (vPMEM), which requires QEMU as hypervisor. In virtualization layer,
  QEMU will copy vpmem over the network like volatile memory, due to the
  typical large capacity of vPMEM, it may takes longer time for live
  migration.

.. releasenotes/notes/allow-non-admin-filter-instance-more-filter-ea5abad7c32ff328.yaml @ b'4018d6fb71a4e5bb0554ac36479cb217f55a6fcf'

- Allow the following filter parameters for ``GET /servers/detail``
  and ``GET /servers`` for non-admin in microversion 2.83:

  - availability_zone
  - config_drive
  - key_name
  - created_at
  - launched_at
  - terminated_at
  - power_state
  - task_state
  - vm_state
  - progress
  - user_id

.. releasenotes/notes/bp-action-event-fault-details-8bfabc6e7390446a.yaml @ b'8337bee4b58e0bc36e28d392c25e16d2161e00da'

- With microversion 2.84 the
  ``GET /servers/{server_id}/os-instance-actions/{request_id}`` API returns
  a ``details`` parameter for each failed event with a fault message, similar
  to the server ``fault.message`` parameter in ``GET /servers/{server_id}``
  for a server with status ``ERROR``.

.. releasenotes/notes/bp-add-user-id-field-to-the-migrations-table-af5989e74634b9c4.yaml @ b'ac165112b7918e5aaaa80819e37b223edf86bb06'

- Microversion 2.80 changes the list migrations APIs and the
  os-migrations API.

  In this microversion, expose the ``user_id`` and ``project_id``
  fields in the following APIs:

  * ``GET /os-migrations``
  * ``GET /servers/{server_id}/migrations``
  * ``GET /servers/{server_id}/migrations/{migration_id}``

  The ``GET /os-migrations`` API will also have optional ``user_id`` and
  ``project_id`` query parameters for filtering migrations by user and/or
  project, for example:

  * ``GET /os-migrations?user_id=ef9d34b4-45d0-4530-871b-3fb535988394``
  * ``GET /os-migrations?project_id=011ee9f4-8f16-4c38-8633-a254d420fd54``
  * ``GET /os-migrations?user_id=ef9d34b4-45d0-4530-871b-3fb535988394&project_id=011ee9f4-8f16-4c38-8633-a254d420fd54``

.. releasenotes/notes/bp-destroy-instance-with-datavolume-4c71b12e005832b0.yaml @ b'733d4133df8d0e13c48f45416658ec71ffff5f04'

- With microversion 2.85 add new API
  ``PUT /servers/{server_id}/os-volume_attachments/{volume_id}`` which
  support for specifying ``delete_on_termination`` field in the request
  body to re-config the attached volume whether to delete when the instance
  is deleted.

.. releasenotes/notes/bp-policy-defaults-refresh-b8e6e2d6b1a7bc21.yaml @ b'af21183082a185f1af946734caf8f28ee5ea20ec'

- The Nova policies implemented the scope concept and new default roles
  (``admin``, ``member``, and ``reader``) provided by keystone.

.. releasenotes/notes/bug-1834506-7c6875bbdc32ab0b.yaml @ b'8f975bc8287d980f3e6c5da601051cf626c081dd'

- LXC instances now support cloud-init.

.. releasenotes/notes/cross-cell-resize-37a735adadbafe91.yaml @ b'6ebee92445d799a2e610116cf72b4bf3d3d6a2f3'

- Cross-cell resize is now supported but is disabled by default for all
  users. Refer to the `administrator documentation`__ for details.

  .. __: https://docs.openstack.org/nova/latest/admin/configuration/cross-cell-resize.html

.. releasenotes/notes/flavor-extra-spec-validators-76d1f2e52ba753db.yaml @ b'4e30693727d47ea89acd0b21964e3d2ec32ec615'

- The 2.86 microversion adds support for flavor extra spec validation when
  creating or updating flavor extra specs. Use of an unrecognized or invalid
  flavor extra spec in the following namespaces will result in a HTTP 400
  response.

  - ``accel``
  - ``aggregate_instance_extra_specs``
  - ``capabilities``
  - ``hw``
  - ``hw_rng``
  - ``hw_video``
  - ``os``
  - ``pci_passthrough``
  - ``powervm``
  - ``quota``
  - ``resources`` (including ``_{group}`` suffixes)
  - ``trait`` (including ``_{group}`` suffixes)
  - ``vmware``

.. releasenotes/notes/host_status_unknown_policy-839cfda56b610d39.yaml @ b'f9c608924482eb8f3db403b8f49d3d885fed5997'

- A new policy rule ``os_compute_api:servers:show:host_status:unknown-only``
  has been added to control whether a user can view a server host status of
  ``UNKNOWN`` in the following APIs:

  * ``GET /servers/{server_id}`` if using API microversion >= 2.16
  * ``GET /servers/detail`` if using API microversion >= 2.16
  * ``PUT /servers/{server_id}`` if using API microversion >= 2.75
  * ``POST /servers/{server_id}/action`` (rebuild) if using API microversion
    >= 2.75

  This is different than the ``os_compute_api:servers:show:host_status``
  policy rule which controls whether a user can view all possible host
  status in the aforementioned APIs including ``UP``, ``DOWN``,
  ``MAINTENANCE``, and ``UNKNOWN``.

.. releasenotes/notes/image-metadata-prefiltering-2921c1d38951f7a9.yaml @ b'd1c4f13d7c6572071e2196bfcd8de30b44c3f64a'

- A new image metadata prefilter has been added to allow translation of
  hypervisor-specific device model requests to standard traits. When this
  feature is enabled, nova is able to utilize placement to select hosts that
  are capable of emulating the requested devices, avoiding hosts that
  could not support the request. This feature is currently supported by the
  libvirt driver and can be enabled by configuring the
  ``[scheduler]/image_metadata_prefilter`` to ``True`` in the controller
  ``nova.conf``.

.. releasenotes/notes/image-precaching-d46506568fefa1ea.yaml @ b'339129870692467b703220dbc3905fd8bffe6a83'

- Image pre-caching on hosts by aggregate is now supported (where
  supported by the underlying virt driver) as of microversion
  2.81. A group of hosts within an aggregate can be compelled to
  fetch and cache a list of images to reduce time-to-boot
  latency. Adds the new API:

  * ``POST /os-aggregates/{aggregate_id}/images``

  which is controlled by the policy ``compute:aggregates:images`` rule.

  See the ``[image_cache]/precache_concurrency`` config option
  for more information about throttling this operation.

.. releasenotes/notes/register-allocation-per-cell-9177b3e2161a632c.yaml @ b'1a39ed9005306b0d3f42480b1fedf36b0b7834ff'

- Add ``--cell`` option to the ``nova-manage placement heal_allocations`` command. This option allows healing instance allocations within a specific cell.

.. releasenotes/notes/separate-update-and-swap-volume-policy-for-attachment-e4c20d4907a52fa7.yaml @ b'fcf586366287155dfb1007643bd6cc513300285e'

- With microversion 2.85, existing policy ``os-volumes-attachments:update``
  is used for updating the resources with the change in its default value
  from ``SYSTEM_ADMIN`` to ``PROJECT_MEMBER_OR_SYSTEM_ADMIN``.
  New policy ``os-volumes-attachments:swap`` is introduced for swapping
  the attachment of servers with default to ``SYSTEM_ADMIN``.

.. releasenotes/notes/sriov-numa-affinity-policy-b49858452827c727.yaml @ b'8c7224172641c6194582ca4cf7ce11e907df50aa'

- Added support for instance-level PCI NUMA policies using the
  ``hw:pci_numa_affinity_policy`` flavor extra spec and
  ``hw_pci_numa_affinity_policy`` image metadata property.
  These apply to both PCI passthrough and SR-IOV devices,
  unlike host-level PCI NUMA policies configured via the
  ``alias`` key of the ``[pci] alias`` config option.
  See the `VM Scoped SR-IOV NUMA Affinity`_ spec for more
  info.

  .. _`VM Scoped SR-IOV NUMA Affinity`: http://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/vm-scoped-sriov-numa-affinity.html

.. releasenotes/notes/stable_rescue_bfv-cd0e9f0f7e9eaa25.yaml @ b'24106290e665bfdc4aa3a2937f0a4b5462fb220e'

- Stable device rescue for boot from volume instances is now supported
  through the use of the 2.87 microversion when the compute hosting the
  instance also reports the ``COMPUTE_RESCUE_BFV`` trait such as the libvirt
  driver.

  No changes have been made to the request or response parameters of the
  rescue API itself.

.. releasenotes/notes/support-server-move-operations-with-neutron-ports-with-resource-request-c41598d0e4aef37b.yaml @ b'24113ba0156414b38613e8d52fe8363e8edbaaa8'

- The server ``evacuate``, ``os-migrateLive`` and ``unshelve`` action APIs
  now support servers with neutron ports having resource requests, e.g.
  ports that have QoS minimum bandwidth rules attached.

.. releasenotes/notes/vgpu-multiple-types-2b1ded7d1cc28880.yaml @ b'5b5cbc64f9b4b024ec6686ed05e8b9b887d64ca1'

- The libvirt driver now supports defining different virtual GPU types for
  each physical GPU. See the ``[devices]/enabled_vgpu_types`` configuration
  option for knowing how to do it. Please refer to
  https://docs.openstack.org/nova/latest/admin/virtual-gpu.html for further
  documentation.

.. releasenotes/notes/virtio-rng-by-default-9cc1366ed1634129.yaml @ b'de512f2c025429b72ade5a5ec38a6f1bde60af3c'

- When using the libvirt driver, Nova instances will now get a
  VirtIO-RNG (Random Number Generator) device by default.  This is to
  ensure guests are not starved of entropy during boot time.  In case
  you want to *disallow* setting an RNG device for some reason, it can
  be done by setting the flavor Extra Spec property ``hw_rng:allowed``
  to ``False``.


.. _Release Notes_21.0.0_ussuri-eol_Known Issues:

Known Issues
------------

.. releasenotes/notes/absolutely-non-inheritable-image-properties-85f7f304fdc20b61.yaml @ b'bc290840127c3179227a662584404f9c0178d588'

- In prior releases, an attempt to boot an instance directly from an image
  that was created by the Block Storage Service from an encrypted volume
  resulted in the instance going ACTIVE but being unusable.  If a user then
  performed the image-create action on such an instance, the new image would
  inherit the ``cinder_encryption_key_id`` and, beginning with the 20.0.0
  (Train) release, the ``cinder_encryption_key_deletion_policy`` image
  properties, assuming these were not included in the
  ``non_inheritable_image_properties`` configuration option.  (The default
  setting for that option does *not* include these.)  Beginning with 20.0.0
  (Train), when the new image was deleted, the encryption key for the
  *original* image would be deleted, thereby rendering it unusable for the
  normal workflow of creating a volume from the image and booting an instance
  from the volume.  Beginning with this release:

  * The Compute API will return a 400 (Bad Request) response to a request
    to directly boot an image created from an encrypted volume.
  * The image properties ``cinder_encryption_key_id`` and
    ``cinder_encryption_key_deletion_policy`` are absolutely non-inheritable
    regardless of the ``non_inheritable_image_properties`` setting.


.. _Release Notes_21.0.0_ussuri-eol_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/absolutely-non-inheritable-image-properties-85f7f304fdc20b61.yaml @ b'bc290840127c3179227a662584404f9c0178d588'

- The ``non_inheritable_image_properties`` configuration option inhibits
  the transfer of image properties from the image an instance was created
  from to images created from that instance.  There are, however, image
  properties (for example, the properties used for image signature
  validation) that should *never* be transferred to an instance snapshot.
  Prior to this release, such properties were included in the default
  setting for this configuration option, but this allowed the possibility
  that they might be removed by mistake, thereby resulting in a poor user
  experience.  To prevent that from happening, nova now maintains an
  internal list of image properties that are absolutely non-inheritable
  regardless of the setting of the configuration option.  See the help
  text for ``non_inheritable_image_properties`` in the sample nova
  configuration file for details.

.. releasenotes/notes/bp-policy-defaults-refresh-b8e6e2d6b1a7bc21.yaml @ b'af21183082a185f1af946734caf8f28ee5ea20ec'

- All the policies except the deprecated APIs policy have been changed to
  implement the ``scope_type`` and new defaults. Deprecated APIs policy will
  be moved to ``scope_type`` and new defaults in the next release.

  Please refer `Policy New Defaults`_ for detail about policy new defaults
  and migration plan.

  * **Scope**

    Each policy is protected with appropriate ``scope_type``. Nova support
    two types of ``sope_type`` with their combination. ``['system']``,
    ``['project']`` and ``['system', 'project']``.

    To know each policy scope_type, please refer the `Policy Reference`_

    This feature is disabled by default can be enabled via config option
    ``[oslo_policy]enforce_scope`` in ``nova.conf``

  * **New Defaults(Admin, Member and Reader)**

    Policies are default to Admin, Member and Reader roles. Old roles
    are also supported. You can switch to new defaults via config option
    ``[oslo_policy]enforce_new_defaults`` in ``nova.conf`` file.

  * **Policies granularity**

    To implement the reader roles, Below policies are made more granular

    - ``os_compute_api:os-agents`` is made granular to

      - ``os_compute_api:os-agents:create``
      - ``os_compute_api:os-agents:update``
      - ``os_compute_api:os-agents:delete``
      - ``os_compute_api:os-agents:list``

    - ``os_compute_api:os-attach-interfaces`` is made granular to

      - ``os_compute_api:os-attach-interfaces:create``
      - ``os_compute_api:os-attach-interfaces:delete``
      - ``os_compute_api:os-attach-interfaces:show``
      - ``os_compute_api:os-attach-interfaces:list``

    - ``os_compute_api:os-deferred-delete`` is made granular to

      - ``os_compute_api:os-deferred-delete:restore``
      - ``os_compute_api:os-deferred-delete:force``

    - ``os_compute_api:os-hypervisors`` is made granular to

      - ``os_compute_api:os-hypervisors:list``
      - ``os_compute_api:os-hypervisors:list-detail``
      - ``os_compute_api:os-hypervisors:statistics``
      - ``os_compute_api:os-hypervisors:show``
      - ``os_compute_api:os-hypervisors:uptime``
      - ``os_compute_api:os-hypervisors:search``
      - ``os_compute_api:os-hypervisors:servers``

    - ``os_compute_api:os-security-groups`` is made granular to

      - ``os_compute_api:os-security-groups:add``
      - ``os_compute_api:os-security-groups:remove``
      - ``os_compute_api:os-security-groups:list``

    - ``os_compute_api:os-instance-usage-audit-log`` is made granular to

      - ``os_compute_api:os-instance-usage-audit-log:list``
      - ``os_compute_api:os-instance-usage-audit-log:show``

    - ``os_compute_api:os-instance-actions`` is made granular to

      - ``os_compute_api:os-instance-actions:list``
      - ``os_compute_api:os-instance-actions:show``

    - ``os_compute_api:os-server-password`` is made granular to

      - ``os_compute_api:os-server-password:show``
      - ``os_compute_api:os-server-password:clear``

    - ``os_compute_api:os-rescue`` is made granular to

      - ``os_compute_api:os-rescue``
      - ``os_compute_api:os-unrescue``

    - ``os_compute_api:os-used-limits`` is renamed to

      - ``os_compute_api:limits:other_project``

    - ``os_compute_api:os-services`` is made granular to

      - ``os_compute_api:os-services:list``
      - ``os_compute_api:os-services:update``
      - ``os_compute_api:os-services:delete``

.. releasenotes/notes/bug-1875418-0df3198e36530ec7.yaml @ b'dd3cc59ccf8c963e078359d4b27dacf7d54a14ee'

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

.. releasenotes/notes/drop-python-2-7-73d3113c69d724d6.yaml @ b'14872caae1a51c7015dd7c509d0173df2e943ed4'

- Python 2.7 support has been dropped. The minimum version of Python now
  supported by nova is Python 3.6.

.. releasenotes/notes/instances_hidden_after_upgrade_to_train-9ce4731f31bc6bd2.yaml @ b'001f3a7bfe6b2c8af135daff8e154a708792070e'

- Upgrading to Train on a deployment with a large database may hit
  `bug 1862205`_, which results in instance records left in a bad
  state, and manifests as instances not being shown in list
  operations. Users upgrading to Train for the first time will
  definitely want to apply a version which includes this fix.  Users
  already on Train should upgrade to a version including this fix to
  ensure the problem is addressed.

  .. _bug 1862205: https://launchpad.net/bugs/1862205

.. releasenotes/notes/new-COMPUTE_NODE-trait-06701d03b17d179f.yaml @ b'a79d3d546bbf679fdc7d337824dbe1a26451fbaa'

- Starting in the Ussuri release, compute node resource providers are
  automatically marked with the ``COMPUTE_NODE`` trait. This allows them to
  be distinguished easily from other providers, including sharing and nested
  providers, as well as other non-compute-related providers in a deployment.
  To make effective use of this trait (e.g. for scheduling purposes), all
  compute nodes must be upgrade to Ussuri. Alternatively, you can manually
  add the trait to pre-Ussuri compute node providers via `openstack resource
  provider trait set
  <https://docs.openstack.org/osc-placement/train/cli/index.html#resource-provider-trait-set>`_

.. releasenotes/notes/remove-deprecated-osapi_v21-conf-option-42d11017ec5db5a7.yaml @ b'088f237e59b17424ce06be663e88f71a96a4ebd6'

- The ``[osapi_v21]/project_id_regex`` configuration option which has been deprecated since the Mitaka 13.0.0 release has now been removed.

.. releasenotes/notes/remove-nova-console-5a2b86210a43e7c8.yaml @ b'f284b264b98e238c8e63bcda82df178d18d1225d'

-
  .. _21.0.0.0-upgrade-notes-os-consoles:

  The ``nova-console`` service has been deprecated since the 19.0.0 Stein
  release and has now been removed. The following configuration options are
  therefore removed.

  * ``[upgrade_levels] console``

  In addition, the following APIs have been removed. Calling these APIs will
  now result in a ``410 HTTPGone`` error response:

  * ``POST /servers/{server_id}/consoles``
  * ``GET /servers/{server_id}/consoles``
  * ``GET /servers/{server_id}/consoles/{console_id}``
  * ``DELETE /servers/{server_id}/consoles/{console_id}``

  Finally, the following policies are removed. These were related to the
  removed APIs listed above and no longer had any effect:

  * ``os_compute_api:os-consoles:index``
  * ``os_compute_api:os-consoles:create``
  * ``os_compute_api:os-consoles:delete``
  * ``os_compute_api:os-consoles:show``

.. releasenotes/notes/remove-nova-network-c02953ba72a1795d.yaml @ b'f5f73b4c4e00164d3ced8f9def5c9084397bc591'

- The *nova-network* feature has been deprecated since the 14.0.0 (Newton)
  release and has now been removed. The remaining *nova-network* specific
  REST APIs have been removed along with their related policy rules. Calling
  these APIs will now result in a ``410 (Gone)`` error response.

  * ``GET /os-security-group-default-rules``
  * ``POST /os-security-group-default-rules``
  * ``GET /os-security-group-default-rules/{id}``
  * ``DELETE /os-security-group-default-rules/{id}``
  * ``POST /os-networks``
  * ``DELETE /os-networks``
  * ``POST /os-networks/add``
  * ``POST /os-networks/{id} (associate_host)``
  * ``POST /os-networks/{id} (disassociate)``
  * ``POST /os-networks/{id} (disassociate_host)``
  * ``POST /os-networks/{id} (disassociate_project)``
  * ``POST /os-tenant-networks``
  * ``DELETE /os-tenant-networks``

  The following policies have also been removed.

  * ``os_compute_api:os-security-group-default-rules``
  * ``os_compute_api:os-networks``
  * ``os_compute_api:os-networks-associate``

.. releasenotes/notes/remove-nova-network-c02953ba72a1795d.yaml @ b'f5f73b4c4e00164d3ced8f9def5c9084397bc591'

- The ``networks`` quota, which was only enabled if the
  ``enabled_network_quota`` config option was enabled and only useful with
  *nova-network*, is removed. It will not longer be present in the responses
  for the APIs while attempts to update the quota will be rejected.

  * ``GET /os-quota-sets``
  * ``GET /os-quota-sets/{project_id}``
  * ``GET /os-quota-sets/{project_id}/defaults``
  * ``GET /os-quota-sets/{project_id}/detail``
  * ``PUT /os-quota-sets/{project_id}``
  * ``GET /os-quota-class-sets/{id}``
  * ``PUT /os-quota-class-sets/{id}``

  The following related config options have been removed.

  * ``enable_network_quota``
  * ``quota_networks``

.. releasenotes/notes/remove-nova-network-c02953ba72a1795d.yaml @ b'f5f73b4c4e00164d3ced8f9def5c9084397bc591'

- The following ``nova-manage`` commands have been removed.

  * ``network``
  * ``floating``

  These were only useful for the now-removed *nova-network* service and have
  been deprecated since the 15.0.0 (Ocata) release.

.. releasenotes/notes/remove-nova-network-c02953ba72a1795d.yaml @ b'f5f73b4c4e00164d3ced8f9def5c9084397bc591'

- The ``nova-dhcpbridge`` service has been removed. This was only used with
  the now-removed *nova-network* service.

.. releasenotes/notes/remove-nova-network-c02953ba72a1795d.yaml @ b'f5f73b4c4e00164d3ced8f9def5c9084397bc591'

- The following config options only applied when using the *nova-network*
  network driver which has now been removed. The config options have
  therefore been removed also.

  * ``[DEFAULT] firewall_driver``
  * ``[DEFAULT] allow_same_net_traffic``
  * ``[DEFAULT] flat_network_bridge``
  * ``[DEFAULT] flat_network_dns``
  * ``[DEFAULT] flat_interface``
  * ``[DEFAULT] vlan_interface``
  * ``[DEFAULT] vlan_start``
  * ``[DEFAULT] num_networks``
  * ``[DEFAULT] vpn_ip``
  * ``[DEFAULT] vpn_start``
  * ``[DEFAULT] network_size``
  * ``[DEFAULT] fixed_range_v6``
  * ``[DEFAULT] gateway``
  * ``[DEFAULT] gateway_v6``
  * ``[DEFAULT] cnt_vpn_clients``
  * ``[DEFAULT] fixed_ip_disassociate_timeout``
  * ``[DEFAULT] create_unique_mac_address_attempts``
  * ``[DEFAULT] teardown_unused_network_gateway``
  * ``[DEFAULT] l3_lib``
  * ``[DEFAULT] network_driver``
  * ``[DEFAULT] network_manager``
  * ``[DEFAULT] multi_host``
  * ``[DEFAULT] force_dhcp_release``
  * ``[DEFAULT] update_dns_entries``
  * ``[DEFAULT] dns_update_periodic_interval``
  * ``[DEFAULT] dhcp_domain``
  * ``[DEFAULT] use_neutron``
  * ``[DEFAULT] auto_assign_floating_ip``
  * ``[DEFAULT] floating_ip_dns_manager``
  * ``[DEFAULT] instance_dns_manager``
  * ``[DEFAULT] instance_dns_domain``
  * ``[DEFAULT] default_floating_pool``
  * ``[DEFAULT] ipv6_backend``
  * ``[DEFAULT] metadata_host``
  * ``[DEFAULT] metadata_port``
  * ``[DEFAULT] iptables_top_regex``
  * ``[DEFAULT] iptables_bottom_regex``
  * ``[DEFAULT] iptables_drop_action``
  * ``[DEFAULT] ldap_dns_url``
  * ``[DEFAULT] ldap_dns_user``
  * ``[DEFAULT] ldap_dns_password``
  * ``[DEFAULT] ldap_dns_soa_hostmaster``
  * ``[DEFAULT] ldap_dns_servers``
  * ``[DEFAULT] ldap_dns_base_dn``
  * ``[DEFAULT] ldap_dns_soa_refresh``
  * ``[DEFAULT] ldap_dns_soa_retry``
  * ``[DEFAULT] ldap_dns_soa_expiry``
  * ``[DEFAULT] ldap_dns_soa_minimum``
  * ``[DEFAULT] dhcpbridge_flagfile``
  * ``[DEFAULT] dhcpbridge``
  * ``[DEFAULT] dhcp_lease_time``
  * ``[DEFAULT] dns_server``
  * ``[DEFAULT] use_network_dns_servers``
  * ``[DEFAULT] dnsmasq_config_file``
  * ``[DEFAULT] ebtables_exec_attempts``
  * ``[DEFAULT] ebtables_retry_interval``
  * ``[DEFAULT] fake_network``
  * ``[DEFAULT] send_arp_for_ha``
  * ``[DEFAULT] send_arp_for_ha_count``
  * ``[DEFAULT] dmz_cidr``
  * ``[DEFAULT] force_snat_range``
  * ``[DEFAULT] linuxnet_interface_driver``
  * ``[DEFAULT] linuxnet_ovs_integration_bridge``
  * ``[DEFAULT] use_single_default_gateway``
  * ``[DEFAULT] forward_bridge_interface``
  * ``[DEFAULT] ovs_vsctl_timeout``
  * ``[DEFAULT] networks_path``
  * ``[DEFAULT] public_interface``
  * ``[DEFAULT] routing_source_ip``
  * ``[DEFAULT] use_ipv6``
  * ``[DEFAULT] allow_same_net_traffic``
  * ``[DEFAULT] defer_iptables_apply``
  * ``[DEFAULT] share_dhcp_address``
  * ``[upgrade_levels] network``
  * ``[vmware] vlan_interface``

.. releasenotes/notes/remove-nova-xvpvncproxy-1c189cdff4b133e8.yaml @ b'f284b264b98e238c8e63bcda82df178d18d1225d'

-
  .. _21.0.0.0-upgrade-notes-xvncproxy:

  The ``nova-xvpvncproxy`` service has been deprecated since the 19.0.0 Stein
  release and has now been removed. The following configuration options have
  also been removed:

  * ``[vnc] xvpvncproxy_base_url``
  * ``[vnc] xvpvncproxy_host``
  * ``[vnc] xvpvncproxy_port``
  * ``[xvp] console_xvp_conf_template``
  * ``[xvp] console_xvp_conf``
  * ``[xvp] console_xvp_log``
  * ``[xvp] console_xvp_multiplex_port``
  * ``[xvp] console_xvp_pid``

.. releasenotes/notes/unauthed-version-discovery-cc38986617dc1c02.yaml @ b'1e907602e37fb55bbe5a20164db6d074f87369af'

- New paste pipelines and middleware have been created to allow API version
  discovery to be performed without authentication or redirects. Because this
  involves an ``api-paste.ini`` change, you will need to manually update your
  ``api-paste.ini`` with the one from the release to get this functionality.

.. releasenotes/notes/ussuri-rm-non-upt-compat-b2847eb93bb609a9.yaml @ b'c80912866f080c2049fb3860221f55e3c73cbf5e'

- Compatibility code for compute drivers that do not implement the
  `update_provider_tree`__ interface has been removed. All compute drivers
  must now implement ``update_provider_tree``.

  __ https://docs.openstack.org/nova/latest/reference/update-provider-tree.html


.. _Release Notes_21.0.0_ussuri-eol_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/bp-policy-defaults-refresh-b8e6e2d6b1a7bc21.yaml @ b'af21183082a185f1af946734caf8f28ee5ea20ec'

- During Policy new defaults, below policies are deprecated and will be
  removed in 23.0.0 release. These are replaced by the new granular
  policies listed in feature section.

  - ``os_compute_api:os-agents``
  - ``os_compute_api:os-attach-interfaces``
  - ``os_compute_api:os-deferred-delete``
  - ``os_compute_api:os-hypervisors``
  - ``os_compute_api:os-security-groups``
  - ``os_compute_api:os-instance-usage-audit-log``
  - ``os_compute_api:os-instance-actions``
  - ``os_compute_api:os-server-password``
  - ``os_compute_api:os-used-limits``
  - ``os_compute_api:os-services``

.. releasenotes/notes/deprecate-api-auth_strategy-noauth2-ed29c499a68b08ce.yaml @ b'18de63deaab792a490e987663d96b6025309b862'

- The ``[api]auth_strategy`` conf option and the corresponding test-only
  ``noauth2`` pipeline in ``api-paste.ini`` are deprecated and will be
  removed in a future release. The only supported ``auth_strategy`` is
  ``keystone``, the default.

.. releasenotes/notes/deprecate-glance-api_servers-d05695ea52b831e0.yaml @ b'cffbc2e431e90f7b6a67cf4a82349ee1d8de202a'

- The ``[glance]api_servers`` configuration option is deprecated and will be
  removed in a future release. Deployments should use standard keystoneauth1
  options to configure communication with a single image service endpoint.
  Any load balancing or high availability requirements should be satisfied
  outside of nova.

.. releasenotes/notes/deprecate-scheduler-driver-opt-4d6a266590b52e2c.yaml @ b'6a4cb24d39623930fd240e67d65013803459839d'

- The ``[scheduler] driver`` config option has been deprecated. This was
  previously used to switch between different scheduler drivers including
  custom, out-of-tree ones. However, only the ``FilterScheduler`` has been
  supported in-tree since 19.0.0 (Stein) and nova increasingly relies on
  placement for basic functionality, meaning developing and maintaining
  out-of-tree drivers is increasingly difficult. Users who still rely on a
  custom scheduler driver should migrate to the filter scheduler, using
  custom filters and weighters where necessary.

.. releasenotes/notes/deprecate-vmware-ussuri-39e0215eca80ffd7.yaml @ b'd98d72828505d250698fcab7cd310820b3a52f7a'

- The vmwareapi driver is deprecated in this release and may be
  removed in a future one. The driver is not tested by the OpenStack
  Nova project and does not have a clear maintainer.

.. releasenotes/notes/image_cache-conf-opts-moved-e552e4a2d59e056e.yaml @ b'828e8047e5c8651ea757bda7922670889d5e8818'

- The following conf options have been moved to the ``[image_cache]`` group
  and renamed accordingly. The old option paths are deprecated and will be
  removed in a future release.

  .. list-table::
     :header-rows: 1

     * - Deprecated Option
       - New Option
     * - ``[DEFAULT]image_cache_manager_interval``
       - ``[image_cache]manager_interval``
     * - ``[DEFAULT]image_cache_subdirectory_name``
       - ``[image_cache]subdirectory_name``
     * - ``[DEFAULT]remove_unused_base_images``
       - ``[image_cache]remove_unused_base_images``
     * - ``[DEFAULT]remove_unused_original_minimum_age_seconds``
       - ``[image_cache]remove_unused_original_minimum_age_seconds``
     * - ``[libvirt]remove_unused_resized_minimum_age_seconds``
       - ``[image_cache]remove_unused_resized_minimum_age_seconds``


.. _Release Notes_21.0.0_ussuri-eol_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bp-policy-defaults-refresh-b8e6e2d6b1a7bc21.yaml @ b'af21183082a185f1af946734caf8f28ee5ea20ec'

- Below bugs are fixed for policies default values

  - https://bugs.launchpad.net/nova/+bug/1863009
  - https://bugs.launchpad.net/nova/+bug/1869396
  - https://bugs.launchpad.net/nova/+bug/1867840
  - https://bugs.launchpad.net/nova/+bug/1869791
  - https://bugs.launchpad.net/nova/+bug/1869841
  - https://bugs.launchpad.net/nova/+bug/1869543
  - https://bugs.launchpad.net/nova/+bug/1870883
  - https://bugs.launchpad.net/nova/+bug/1871287
  - https://bugs.launchpad.net/nova/+bug/1870488
  - https://bugs.launchpad.net/nova/+bug/1870872
  - https://bugs.launchpad.net/nova/+bug/1870484
  - https://bugs.launchpad.net/nova/+bug/1870881
  - https://bugs.launchpad.net/nova/+bug/1871665
  - https://bugs.launchpad.net/nova/+bug/1870226

  .. _policy-defaults-refresh: https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/policy-defaults-refresh.html
  .. _Policy Reference: https://docs.openstack.org/nova/latest/configuration/policy.html
  .. _Policy New Defaults: https://docs.openstack.org/nova/latest/configuration/policy-concepts.html

.. releasenotes/notes/bug-1694844-cross-az-attach-ab1f05e8693f6902.yaml @ b'07a24dcef7ce6767b4b5bab0c8d3166cbe5b39c0'

- Long standing `bug 1694844`_ is now fixed where the following conditions
  would lead to a 400 error response during server create:

  * ``[cinder]/cross_az_attach=False``
  * ``[DEFAULT]/default_schedule_zone=None``
  * A server is created without an availability zone specified but with
    pre-existing volume block device mappings

  Before the bug was fixed, users would have to specify an availability zone
  that matches the zone that the volume(s) were in. With the fix, the compute
  API will implicitly create the server in the zone that the volume(s) are
  in as long as the volume zone is not the same as the
  ``[DEFAULT]/default_availability_zone`` value (defaults to ``nova``).

  .. _bug 1694844: https://launchpad.net/bugs/1694844

.. releasenotes/notes/bug-1748697-COMPUTE_SAME_HOST_COLD_MIGRATE-19ed64bf48bb1fc7.yaml @ b'4921e822e73383af0c8da4c5e3acfaa021eafe68'

- This release contains a fix for `bug 1748697`_ which distinguishes between
  resize and cold migrate such that the ``allow_resize_to_same_host`` config
  option is no longer used to determine if a server can be cold migrated to
  the same compute service host. Now when requesting a cold migration the
  API will check if the source compute node resource provider has the
  ``COMPUTE_SAME_HOST_COLD_MIGRATE`` trait and if so the scheduler can select
  the source host. Note that the only in-tree compute driver that supports
  cold migration to the same host is ``VMwareVCDriver``.

  To support rolling upgrades with N-1 computes if a node does not report the
  trait and is old the API will fallback to the ``allow_resize_to_same_host``
  config option value. That compatibility will be removed in a subsequent
  release.

  .. _bug 1748697: https://launchpad.net/bugs/1748697

.. releasenotes/notes/bug-1845628-3152e73a1e4856b2.yaml @ b'9ae4d9274e3e310fdd04c81e92e9c4803c434fff'

- Prior to this release Nova determined if ``UEFI`` support should be
  enable solely by checking host support as reported in `bug 1845628`_.

  Nova now correctly check for guest os support via the ``hw_firmware_type``
  image metadata property when spawning new instance and only
  enables ``UEFI`` if the guest and host support it.
  Guest deletion has also been updated to correctly clean up based on
  the ``UEFI`` or ``BIOS`` configuration of the vm.

  .. _bug 1845628: https://bugs.launchpad.net/nova/+bug/1845628

.. releasenotes/notes/bug-1845986-70730d9f6c09e68b.yaml @ b'c2fd8294fdb615d5229c4eb2abef1226b7cc580b'

- `Bug 1845986`_ has been fixed by adding iommu driver when the following
  metadata options are used with AMD SEV:

  - ``hw_scsi_model=virtio-scsi`` and either ``hw_disk_bus=scsi`` or
    ``hw_cdrom_bus=scsi``
  - ``hw_video_model=virtio``

  Also a virtio-serial controller is created when ``hw_qemu_guest_agent=yes``
  option is used, together with iommu driver for it.

  .. _Bug 1845986: https://launchpad.net/bugs/1845986

.. releasenotes/notes/bug-1852458-cell0-instance-action-e3112cf17bcc7c64.yaml @ b'f2608c91175411ec7c2604035adb39306d7e607e'

- This release contains a fix for a `regression`__ introduced in 15.0.0
  (Ocata) where server create failing during scheduling would not result in
  an instance action record being created in the cell0 database. Now when
  creating a server fails during scheduling and is "buried" in cell0 a
  ``create`` action will be created with an event named
  ``conductor_schedule_and_build_instances``.

  .. __: https://bugs.launchpad.net/nova/+bug/1852458

.. releasenotes/notes/bug-1852610-service-delete-with-migrations-ca0565fc0b503519.yaml @ b'92fed026103b47fa2a76ea09204a4ba24c21e191'

- The ``DELETE /os-services/{service_id}`` compute API will now return a
  ``409 HTTPConflict`` response when trying to delete a ``nova-compute``
  service which is involved in in-progress migrations. This is because doing
  so would not only orphan the compute node resource provider in the
  placement service on which those instances have resource allocations but
  can also break the ability to confirm/revert a pending resize properly.
  See https://bugs.launchpad.net/nova/+bug/1852610 for more details.

.. releasenotes/notes/bug-1856925-check-source-compute-resize-16e9c3b24cf72301.yaml @ b'ea2ea492a3d046d53d44039206fff69fe7e3ac61'

- This release contains a fix for `bug 1856925`_ such that ``resize`` and
  ``migrate`` server actions will be rejected with a 409 ``HTTPConflict``
  response if the source compute service is down.

  .. _bug 1856925: https://bugs.launchpad.net/nova/+bug/1856925

.. releasenotes/notes/bug-1864588-737c29560effd16e.yaml @ b'5d4f82a15c7bccc89f78a5a1f00a25cfafdbdde0'

- For AArch64 Nova now sets ``max`` as the default CPU model. It does the
  right thing in context of both QEMU TCG (plain emulation) and for KVM
  (hardware acceleration).

.. releasenotes/notes/cinder-detect-nonbootable-image-6fad7f865b45f879.yaml @ b'963fd8c0f956bdf5c6c8987aa5d9f836386fd5ed'

- The Compute service has never supported direct booting of an instance from
  an image that was created by the Block Storage service from an encrypted
  volume.  Previously, this operation would result in an ACTIVE instance that
  was unusable.  Beginning with this release, an attempt to boot from such an
  image will result in the Compute API returning a 400 (Bad Request)
  response.

.. releasenotes/notes/instances_hidden_after_upgrade_to_train-9ce4731f31bc6bd2.yaml @ b'001f3a7bfe6b2c8af135daff8e154a708792070e'

- A fix for serious `bug 1862205`_ is provided which addresses both
  the performance aspect of schema migration 399, as well as the
  potential fallout for cases where this migration silently fails
  and leaves large numbers of instances hidden from view from the
  API.

.. releasenotes/notes/neutron-connection-retries-c276010afe238abc.yaml @ b'0e34ed9733e3f23d162e3e428795807386abf1cb'

- A new config option ``[neutron]http_retries`` is added which defaults to
  3. It controls how many times to retry a Neutron API call in response to a
  HTTP connection failure. An example scenario where it will help is when a
  deployment is using HAProxy and connections get closed after idle time. If
  an incoming request tries to reuse a connection that is simultaneously
  being torn down, a HTTP connection failure will occur and previously Nova
  would fail the entire request. With retries, Nova can be more resilient in
  this scenario and continue the request if a retry succeeds. Refer to
  https://launchpad.net/bugs/1866937 for more details.

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'f6060ab6b54261ff50b8068732f6e509619d713e'

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

  .. _`bug #1763766`: https://bugs.launchpad.net/nova/+bug/1763766

.. releasenotes/notes/numa-rebuild-b75f9a1966f576ea.yaml @ b'f6060ab6b54261ff50b8068732f6e509619d713e'

- With the changes introduced to address `bug #1763766`_, Nova now guards
  against NUMA constraint changes on rebuild. As a result the
  ``NUMATopologyFilter`` is no longer required to run on rebuild since
  we already know the topology will not change and therefore the existing
  resource claim is still valid. As such it is now possible to do an in-place
  rebuild of an instance with a NUMA topology even if the image changes
  provided the new image does not alter the topology which addresses
  `bug #1804502`_.

  .. _`bug #1804502`: https://bugs.launchpad.net/nova/+bug/1804502

.. releasenotes/notes/unauthed-version-discovery-cc38986617dc1c02.yaml @ b'1e907602e37fb55bbe5a20164db6d074f87369af'

- When using the ``api-paste.ini`` from the release, version discovery
  requests without a trailing slash will no longer receive a 302 redirect to
  the corresponding URL with a trailing slash (e.g. a request for ``/v2.1``
  will no longer redirect to ``/v2.1/``). Instead, such requests will respond
  with the version discovery document regardless of the presence of the
  trailing slash. See
  `bug 1728732 <https://bugs.launchpad.net/nova/+bug/1728732>`_ for details.

.. releasenotes/notes/unauthed-version-discovery-cc38986617dc1c02.yaml @ b'1e907602e37fb55bbe5a20164db6d074f87369af'

- When using the ``api-paste.ini`` from the release, requests to the
  versioned discovery endpoints (``/v2.1`` and ``/v2``) no longer require
  authentication. When using the compute API through certain clients, such as
  openstacksdk, this eliminates an unnecessary additional query. See
  `bug 1845530 <https://bugs.launchpad.net/nova/+bug/1845530>`_ for details.


.. _Release Notes_21.0.0_ussuri-eol_Other Notes:

Other Notes
-----------

.. releasenotes/notes/avoid_muli_ceph_download-4083decf501dba40.yaml @ b'80191e6d828cf823ce3aa7c6176da5e531694900'

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

.. releasenotes/notes/bug-1842149-5ba20d57872e9996.yaml @ b'08bdcdb5b6866c2b6bf084344cca4dd07b960133'

- A new pair of ``ssl_ciphers`` and ``ssl_minimum_version`` configuration
  options have been introduced for use by the ``nova-novncproxy``,
  ``nova-serialproxy``, and ``nova-spicehtml5proxy`` services.  These new
  options allow one to configure the allowed TLS ciphers and minimum protocol
  version to enforce for incoming client connections to the proxy services.

  This aims to address the issues reported in `bug 1842149`_, where it
  describes that the proxy services can inherit insecure TLS ciphers
  and protocol versions from the compiled-in defaults of the OpenSSL
  library on the underlying system.  The proxy services provided no way
  to override such insecure defaults with current day generally accepted
  secure TLS settings.

  .. _bug 1842149: https://bugs.launchpad.net/nova/+bug/1842149

.. releasenotes/notes/placement-audit-59a00dcfb188c6ac.yaml @ b'35ec5a0bd1d82d4d973bdfe1e62dc5a795eb533a'

- A new ``nova-manage`` command, ``placement audit``, has been added.
  This can be used to identify and optionally remove compute allocations in
  placement that are no longer referenced by existing instances or
  migrations. These orphaned allocations typically occur due to race
  conditions during instance migration or removal and will result in capacity
  issues if not addressed.
  For more details on CLI usage, see the man page entry:
  https://docs.openstack.org/nova/latest/cli/nova-manage.html#placement

.. releasenotes/notes/resize-api-cast-always-7eb1dbef8f7fe228.yaml @ b'a05ef30fb9eb2f5250748e5a87f8b61e77464be9'

- The ``resize`` and ``migrate`` server action APIs used to synchronously
  block until a destination host is selected by the scheduler. Those APIs
  now asynchronously return a response to the user before scheduling.
  The response code remains 202 and users can monitor the operation via the
  ``status`` and ``OS-EXT-STS:task_state`` fields on the server resource and
  also by using the ``os-instance-actions`` API. The most notable
  change is ``NoValidHost`` will not be returned in a 400 error response
  from the API if scheduling fails but that information is available via the
  instance actions API interface.

.. releasenotes/notes/virtio-max-queues-27f73e988c7e66ba.yaml @ b'0e6aac3c2d97c999451da50537df6a0cbddeb4a6'

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

.. releasenotes/notes/workarounds-libvirt-disable-native-luks-a4eccca8019db243.yaml @ b'dbb58e964ad1821e96f3e6758b3add747339d052'

- The ``[workarounds]/disable_native_luksv1`` configuration option has
  been introduced. This can be used by operators to workaround recently
  discovered performance issues found within the `libgcrypt library`__ used
  by QEMU when natively decrypting LUKSv1 encrypted disks. Enabling this
  option will result in the use of the legacy ``dm-crypt`` based os-brick
  provided encryptors.

  Operators should be aware that this workaround only applies when using the
  libvirt compute driver with attached encrypted Cinder volumes using the
  ``luks`` encryption provider. The ``luks2`` encryption provider will
  continue to use the ``dm-crypt`` based os-brick encryptors regardless of
  what this configurable is set to.

  This workaround is temporary and will be removed during the W release once
  all impacted distributions have been able to update their versions of the
  libgcrypt library.

  .. warning:: Operators must ensure no instances are running on the compute
    host before enabling this workaround. Any instances with encrypted LUKSv1
    disks left running on the hosts will fail to migrate or stop after this
    workaround has been enabled.

  .. __: https://bugzilla.redhat.com/show_bug.cgi?id=1762765

.. releasenotes/notes/workarounds-libvirt-rbd-host-block-devices-ca5e3c187342ab4d.yaml @ b'7c7a25aa1eda9b1815f12cce25dda0a840d562f1'

- The ``[workarounds]/rbd_volume_local_attach`` configuration option has been
  introduced. This can be used by operators to ensure RBD volumes are
  connected to compute hosts as block devices. This can be used with
  the ``[workarounds]/disable_native_luksv1`` configuration option to
  workaround recently discovered performance issues found within the
  `libgcrypt library`__ used by QEMU when natively decrypting LUKSv1
  encrypted disks.

  This workaround does not currently support extending attached volumes.

  This workaround is temporary and will be removed during the W release once
  all impacted distributions have been able to update their versions of the
  libgcrypt library.

  .. warning:: Operators must ensure no instances are running on the compute
    host before enabling this workaround. Any instances with attached RBD
    volumes left running on the hosts will fail to migrate or stop after this
    workaround has been enabled.

  .. __: https://bugzilla.redhat.com/show_bug.cgi?id=1762765


