===================================
 Newton Series Release Notes
===================================

.. _Release Notes_14.1.0_stable_newton:

14.1.0
======

.. _Release Notes_14.1.0_stable_newton_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1738094-request_specs.spec-migration-22d3421ea1536a37.yaml @ b'e4e7b8da563e1fe4c2713dad55788f5ba3a86057'

- This release contains a schema migration for the ``nova_api`` database
  in order to address bug 1738094:

  https://bugs.launchpad.net/nova/+bug/1738094

  The migration is optional and can be postponed if you have not been
  affected by the bug. The bug manifests itself through "Data too long for
  column 'spec'" database errors.


.. _Release Notes_14.1.0_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1664931-refine-validate-image-rebuild-6d730042438eec10.yaml @ b'4cbfcc590c17134fd14e3aab90ffbb7c17006a95'

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

.. releasenotes/notes/bug-1733886-os-quota-sets-force-2.36-5866924621ecc857.yaml @ b'9de9faa0f6080e0e01e676330eff293c3d15ffb2'

- This release includes a fix for `bug 1733886`_ which was a regression
  introduced in the 2.36 API microversion where the ``force`` parameter was
  missing from the ``PUT /os-quota-sets/{tenant_id}`` API request schema so
  users could not force quota updates with microversion 2.36 or later. The
  bug is now fixed so that the ``force`` parameter can once again be
  specified during quota updates. There is no new microversion for this
  change since it is an admin-only API.

  .. _bug 1733886: https://bugs.launchpad.net/nova/+bug/1733886


.. _Release Notes_14.0.10_stable_newton:

14.0.10
=======

.. _Release Notes_14.0.10_stable_newton_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1664931-validate-image-rebuild-9c5b05a001c94a4d.yaml @ b'698b261a5a2a6c0f31ef5059046ef7196d5cba30'

- `OSSA-2017-005`_: Nova Filter Scheduler bypass through rebuild action

  By rebuilding an instance, an authenticated user may be able to circumvent
  the FilterScheduler bypassing imposed filters (for example, the
  ImagePropertiesFilter or the IsolatedHostsFilter). All setups using the
  FilterScheduler (or CachingScheduler) are affected.

  The fix is in the `nova-api` and `nova-conductor` services.

  .. _OSSA-2017-005: https://security.openstack.org/ossa/OSSA-2017-005.html


.. _Release Notes_14.0.7_stable_newton:

14.0.7
======

.. _Release Notes_14.0.7_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1673613-7357d40ba9ab1fa6.yaml @ b'e3076f5ff6fea598dc4ad2de9b5cb88eb083688b'

- Includes the fix for `bug 1673613`_ which could cause issues when upgrading
  and running ``nova-manage cell_v2 simple_cell_setup`` or
  ``nova-manage cell_v2 map_cell0`` where the database connection is read
  from config and has special characters in the URL.

  .. _bug 1673613: https://launchpad.net/bugs/1673613

.. releasenotes/notes/bug-1691545-1acd6512effbdffb.yaml @ b'd6a628da62f810310ab1bdc2e04222d8010e7b62'

- Fixes `bug 1691545`_ in which there was a significant increase in database
  connections because of the way connections to cell databases were being
  established. With this fix, objects related to database connections are
  cached in the API service and reused to prevent new connections being
  established for every communication with cell databases.

  .. _bug 1691545: https://bugs.launchpad.net/nova/+bug/1691545

.. releasenotes/notes/fix-default-cell0-db-connection-f9717053cc34778e.yaml @ b'f9a3c3fcff89828b7df45149c2d0ee188f439e46'

- The ``nova-manage cell_v2 simple_cell_setup`` command now creates the
  default cell0 database connection using the ``[database]`` connection
  configuration option rather than the ``[api_database]`` connection. The
  cell0 database schema is the `main` database, i.e. the `instances` table,
  rather than the `api` database schema. In other words, the cell0 database
  would be called something like ``nova_cell0`` rather than
  ``nova_api_cell0``.


.. _Release Notes_14.0.5_stable_newton:

14.0.5
======

.. _Release Notes_14.0.5_stable_newton_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'c2c91ce44592fc5dc2aacee1cf7f5b5cfd2e9a0a'

This release includes fixes for security vulnerabilities.


.. _Release Notes_14.0.5_stable_newton_Known Issues:

Known Issues
------------

.. releasenotes/notes/live-migration-progress-known-issue-20176f49da4d3c91.yaml @ b'64a482c24d4dfc2aae42672de160ea38e948304c'

- The live-migration progress timeout controlled by the configuration option
  ``[libvirt]/live_migration_progress_timeout`` has been discovered to
  frequently cause live-migrations to fail with a progress timeout error,
  even though the live-migration is still making good progress.
  To minimize problems caused by these checks we recommend setting the value
  to 0, which means do not trigger a timeout.  (This has been made the
  default in Ocata and Pike.)
  To modify when a live-migration will fail with a timeout error, please now
  look at ``[libvirt]/live_migration_completion_timeout`` and
  ``[libvirt]/live_migration_downtime``.


.. _Release Notes_14.0.5_stable_newton_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'c2c91ce44592fc5dc2aacee1cf7f5b5cfd2e9a0a'

- [CVE-2017-7214] Failed notification payload is dumped in logs with auth secrets

  * `Bug 1673569 <https://bugs.launchpad.net/nova/+bug/1673569>`_


.. _Release Notes_14.0.4_stable_newton:

14.0.4
======

.. _Release Notes_14.0.4_stable_newton_Known Issues:

Known Issues
------------

.. releasenotes/notes/libvirt-script-with-empty-path-2b49caa68b05278d.yaml @ b'99f8a3c4e9d903d48e5c7e245bcb2d3299b7904d'

- When generating Libvirt XML to attach network interfaces for the `tap`,
  `ivs`, `iovisor`, `midonet`, and `vrouter` virtual interface types Nova
  previously generated an empty path attribute to the script element
  (`<script path=''/>`) of the interface.

  As of Libvirt 1.3.3 (`commit`_) and later Libvirt no longer accepts an
  empty path attribute to the script element of the interface. Notably this
  includes Libvirt 2.0.0 as provided with RHEL 7.3 and CentOS 7.3-1611. The
  creation of virtual machines with offending interface definitions on a host
  with Libvirt 1.3.3 or later will result in an error "libvirtError: Cannot
  find '' in path: No such file or directory".

  Additionally, where virtual machines already exist that were created using
  earlier versions of Libvirt interactions with these virtual machines via
  Nova or other utilities (e.g. `virsh`) may result in similar errors.

  To mitigate this issue Nova no longer generates an empty path attribute
  to the script element when defining an interface. This resolves the issue
  with regards to virtual machine creation. To resolve the issue with regards
  to existing virtual machines a change to Libvirt is required, this is being
  tracked in `Bugzilla 1412834`_

  .. _commit: https://libvirt.org/git/?p=libvirt.git;a=commit;h=9c17d665fdc5f0ab74500a14c30627014c11b2c0
  .. _Bugzilla 1412834: https://bugzilla.redhat.com/show_bug.cgi?id=1412834


.. _Release Notes_14.0.4_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1662699-06203e7262e02aa6.yaml @ b'dce8618166d80dc6cf2854920f6275eee73b8d84'

- Fixes `bug 1662699`_ which was a regression in the v2.1 API from the
  ``block_device_mapping_v2.boot_index`` validation that was performed in the
  legacy v2 API. With this fix, requests to create a server with
  ``boot_index=None`` will be treated as if ``boot_index`` was not specified,
  which defaults to meaning a non-bootable block device.

  .. _bug 1662699: https://bugs.launchpad.net/nova/+bug/1662699


.. _Release Notes_14.0.2_stable_newton:

14.0.2
======

.. _Release Notes_14.0.2_stable_newton_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1635446-newton-2351fe93f9af67e5.yaml @ b'867661d51bdb0cf2a6f326cb18f26bbc1f04eb15'

A new database schema migration is included in this release to fix `bug 1635446 <https://bugs.launchpad.net/nova/+bug/1635446>`_.


.. _Release Notes_14.0.2_stable_newton_Known Issues:

Known Issues
------------

.. releasenotes/notes/bug_1632723-2a4bd74e4a942a06.yaml @ b'92ca31b27d892e5aa9a6ffb990c7ea17b26fa991'

- Use of the newly introduced optional placement RESTful API in Newton requires WebOb>=1.6.0. This requirement was not reflected prior to the release of Newton in requirements.txt with the lower limit being set to WebOb>=1.2.3.


.. _Release Notes_14.0.2_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1635446-newton-2351fe93f9af67e5.yaml @ b'867661d51bdb0cf2a6f326cb18f26bbc1f04eb15'

- Contains database schema migration
  ``021_build_requests_instance_mediumtext`` which increases the size of the
  ``build_requests.instance`` column on MySQL backends. This is needed to
  create new instances which have very large ``user_data`` fields.


.. _Release Notes_14.0.1_stable_newton:

14.0.1
======

.. _Release Notes_14.0.1_stable_newton_Prelude:

Prelude
-------

.. releasenotes/notes/newton_prelude-6a6566c8753d147c.yaml @ b'0c6c2dd59184590cae2b6964042250e4ec0a5021'

Nova 14.0.0 release is including a lot of new features and bugfixes. It can be extremely hard to mention all the changes we introduced during that release but we beg you to read at least the upgrade section which describes the required modifications that you need to do for upgrading your cloud from 13.0.0 (Mitaka) to 14.0.0 (Newton).
That said, a few major changes are worth to notice here. This is not an exhaustive list of things to notice, rather just important things you need to know :

- Latest API microversion supported for Newton is v2.38
- Nova now provides a new placement RESTful API endpoint that is for
  the moment optional where Nova compute nodes use it for providing
  resources. For the moment, the nova-scheduler is not using it but we
  plan to check the placement resources for Ocata. In case you plan to
  rolling-upgrade the compute nodes between Newton and Ocata, please
  look in the notes below how to use the new placement API.
- Cells V2 now supports booting instances for one cell v2 only. We plan
  to add a multi-cell support for Ocata. You can prepare for Ocata now
  by creating a cellv2 now using the nova-manage related commands, but
  configuring Cells V2 is still fully optional for this cycle.
- Nova is now using Glance v2 API for getting image resources.
- API microversions 2.36 and above now deprecate the REST resources in
  Nova used to proxy calls to other service type APIs (eg. /os-volumes).
  We'll still supporting those until we raise our minimum API version
  to 2.36 which is not planned yet (we're supporting v2.1 as of now) but
  you're encouraged to stop using those resources and rather calling the
  other services that provide those natively.


.. _Release Notes_14.0.0_stable_newton:

14.0.0
======

.. _Release Notes_14.0.0_stable_newton_New Features:

New Features
------------

.. releasenotes/notes/add-perf-event-e1385b6b6346fbda.yaml @ b'a2d0b8d1b0954c6fdc622dda8fe8777e41566d92'

- Add perf event support for libvirt driver. This can be done by adding new configure option 'enabled_perf_events' in libvirt section of nova.conf. This feature requires libvirt>=2.0.0.

.. releasenotes/notes/async-live-migration-rest-check-675ec309a9ccc28e.yaml @ b'2a1aad9de7e33ee7bcb496de482d325915373a1a'

- Starting from REST API microversion 2.34 pre-live-migration checks are performed asynchronously. ``instance-actions`` should be used for getting information about the checks results. New approach allows to reduce rpc timeouts amount, as previous workflow was fully blocking and checks before live-migration make blocking rpc request to both source and destination compute node.

.. releasenotes/notes/automatic-live-migration-completion-auto-converge-3ddd3a40eaf3ef5b.yaml @ b'0c0f60031acba11d0bab0617f68b95d9b5eb8d1d'

- New configuration option live_migration_permit_auto_converge has been added to allow hypervisor to throttle down CPU of an instance during live migration in case of a slow progress due to high ratio of dirty pages. Requires libvirt>=1.2.3 and QEMU>=1.6.0.

.. releasenotes/notes/automatic-live-migration-completion-post-copy-a7a3a986961c93d8.yaml @ b'2de3879afabb3738df3a6ae86774eb203332600f'

- New configuration option live_migration_permit_post_copy has been added to start live migrations in a way that allows nova to switch an on-going live migration to post-copy mode. Requires libvirt>=1.3.3 and QEMU>=2.5.0. If post copy is permitted and version requirements are met it also changes behaviour of 'live_migration_force_complete', so that it switches on-going live migration to post-copy mode instead of pausing an instance during live migration.

.. releasenotes/notes/bp-fix-console-auth-tokens-16b1b1b402dca362.yaml @ b'3c3925e71a3a06dc8a47483d90cdc585476b1538'

- Fix os-console-auth-tokens API to return connection info for all types of tokens, not just RDP.

.. releasenotes/notes/bp-hyper-v-remotefx-1474ef1a082ad1b0.yaml @ b'2d94ae597af349c577b33e785664c9205b12dcc0'

- Hyper-V RemoteFX feature.

  Microsoft RemoteFX enhances the visual experience in RDP connections,
  including providing access to virtualized instances of a physical GPU to
  multiple guests running on Hyper-V.

  In order to use RemoteFX in Hyper-V 2012 R2, one or more DirectX 11
  capable display adapters must be present and the RDS-Virtualization
  server feature must be installed.

  To enable this feature, the following config option must be set in
  the Hyper-V compute node's 'nova.conf' file::

      [hyperv]
      enable_remotefx = True

  To create instances with RemoteFX capabilities, the following flavor
  extra specs must be used:

  **os:resolution**. Guest VM screen resolution size. Acceptable values::

      1024x768, 1280x1024, 1600x1200, 1920x1200, 2560x1600, 3840x2160

  '3840x2160' is only available on Windows / Hyper-V Server 2016.

  **os:monitors**. Guest VM number of monitors. Acceptable values::

      [1, 4] - Windows / Hyper-V Server 2012 R2
      [1, 8] - Windows / Hyper-V Server 2016

  **os:vram**. Guest VM VRAM amount. Only available on
  Windows / Hyper-V Server 2016. Acceptable values::

      64, 128, 256, 512, 1024

  There are a few considerations that needs to be kept in mind:

  * Not all guests support RemoteFX capabilities.
  * Windows / Hyper-V Server 2012 R2 does not support Generation 2 VMs
    with RemoteFX capabilities.
  * Per resolution, there is a maximum amount of monitors that can be
    added. The limits are as follows:

    For Windows / Hyper-V Server 2012 R2::

        1024x768: 4
        1280x1024: 4
        1600x1200: 3
        1920x1200: 2
        2560x1600: 1

    For Windows / Hyper-V Server 2016::

        1024x768: 8
        1280x1024: 8
        1600x1200: 4
        1920x1200: 4
        2560x1600: 2
        3840x2160: 1

.. releasenotes/notes/bp-instance-tags-3acb227083320796.yaml @ b'537df23d85e0f7c461643efe6b6501d267ae99d0'

- Microversion v2.26 allows to create/update/delete simple string tags. They can be used for filtering servers by these tags.

.. releasenotes/notes/bp-keypairs-pagination-634c46aaa1058161.yaml @ b'47358449d359a287d21426b4e1f18479a4d1fd36'

- Added microversion v2.35 that adds pagination support for keypairs with the help of new optional parameters 'limit' and 'marker' which were added to GET /os-keypairs request.

.. releasenotes/notes/bp-nova-api-hypervsor-cpu-info-b84cddf8b70b88d2.yaml @ b'228e916cdd54f8ea716728709793c6c1f2189ff1'

- Added microversion v2.28 from which hypervisor's 'cpu_info' field returned as JSON object by sending GET /v2.1/os-hypervisors/{hypervisor_id} request.

.. releasenotes/notes/bp-virtuozzo-cloud-storage-support-4f4cda52ca41538e.yaml @ b'e58e11127b3b7748b6a42cf7349010a93d434a1e'

- Virtuozzo Storage is available as a volume backend in
  libvirt virtualization driver.

  .. note:: Only qcow2/raw volume format supported, but not ploop.

.. releasenotes/notes/bp-virtuozzo-instance-resize-support-b523e6e8a0de0fbc.yaml @ b'd4aa455d53c91c6dfebbf9a9850f7b6c3fef4545'

- Virtuozzo ploop disks can be resized now during "nova resize".

.. releasenotes/notes/bp-virtuozzo-rescue-support-a0f69357a93e5e92.yaml @ b'd60d70598ec0ebdb6eda95fa5ceb7d17b6111c70'

- Virtuozzo instances with ploop disks now support the rescue operation

.. releasenotes/notes/cells-discover-hosts-06a3079ba687e092.yaml @ b'3eb4d1fd1d94dc830f7e3420c49117e01df6451a'

- A new nova-manage command has been added to discover any new hosts that are added to a cell. If a deployment has migrated to cellsv2 using either the simple_cell_setup or the map_cell0/map_cell_and_hosts/map_instances combo then anytime a new host is added to a cell this new "nova-manage cell_v2 discover_hosts" needs to be run before instances can be booted on that host. If multiple hosts are added at one time the command only needs to be run one time to discover all of them. This command should be run from an API host, or a host that is configured to use the nova_api database.
  Please note that adding a host to a cell and not running this command could lead to build failures/reschedules if that host is selected by the scheduler. The discover_hosts command is necessary to route requests to the host but is not necessary in order for the scheduler to be aware of the host. It is advised that nova-compute hosts are configured with "enable_new_services=False" in order to avoid failures before the hosts have been discovered.

.. releasenotes/notes/check_destination_when_evacuating-37b52ebe8b5b086c.yaml @ b'86706785ff251b841dff3590dc60f6b4834d7b7e'

- On evacuate actions, the default behaviour when providing a host in the request body changed. Now, instead of bypassing the scheduler when asking for a destination, it will instead call it with the requested destination to make sure the proposed host is accepted by all the filters and the original request. In case the administrator doesn't want to call the scheduler when providing a destination, a new request body field called ``force`` (defaulted to False) will modify that new behaviour by forcing the evacuate operation to the destination without verifying the scheduler.

.. releasenotes/notes/check_destination_when_livemig-e69d32e02d7a18c9.yaml @ b'7aa2285e724345717a3f333adc13660d7b97dfcd'

- On live-migrate actions, the default behaviour when providing a host in the request body changed. Now, instead of bypassing the scheduler when asking for a destination, it will instead call it with the requested destination to make sure the proposed host is accepted by all the filters and the original request. In case the administrator doesn't want to call the scheduler when providing a destination, a new request body field called ``force`` (defaulted to False) will modify that new behaviour by forcing the live-migrate operation to the destination without verifying the scheduler.

.. releasenotes/notes/get-me-a-network-992eabc81b5e5347.yaml @ b'd727795d6668abaf17b5afe01d2e1757aebe7e2e'

- The 2.37 microversion adds support for automatic allocation of network
  resources for a project when ``networks: auto`` is specified in a server
  create request. If the project does not have any networks available to it
  and the ``auto-allocated-topology`` API is available in the Neutron
  networking service, Nova will call that API to allocate resources for the
  project. There is some setup required in the deployment for the
  ``auto-allocated-topology`` API to work in Neutron. See the
  `Additional features`_ section of the OpenStack Networking Guide
  for more details for setting up this feature in Neutron.

  .. note:: The API does not default to 'auto'. However, python-novaclient
    will default to passing 'auto' for this microversion if no specific
    network values are provided to the CLI.

  .. note:: This feature is not available until all of the compute services
    in the deployment are running Newton code. This is to avoid sending a
    server create request to a Mitaka compute that can not understand a
    network ID of 'auto' or 'none'. If this is the case, the API will treat
    the request as if ``networks`` was not in the server create request body.
    Once all computes are upgraded to Newton, a restart of the nova-api
    service will be required to use this new feature.

  .. _Additional features: https://docs.openstack.org/neutron/rocky/admin/intro-os-networking.html

.. releasenotes/notes/glance_v2-15b080e361804976.yaml @ b'f71cd2ca03693655efdbd1109f406ab6f3b58ee6'

- Nova now defaults to using the glance version 2 protocol for all backend operations for all virt drivers. A ``use_glance_v1`` config option exists to revert to glance version 1 protocol if issues are seen, however that will be removed early in Ocata, and only glance version 2 protocol will be used going forward.

.. releasenotes/notes/ironic-driver-hash-ring-7d763d87b9236e5d.yaml @ b'6047d790a32ef5a65d4d6b029f673ce53c3d4141'

- Adds a new feature to the ironic virt driver, which allows
  multiple nova-compute services to be run simultaneously. This uses
  consistent hashing to divide the ironic nodes between the nova-compute
  services, with the hash ring being refreshed each time the resource tracker
  runs.

  Note that instances will still be owned by the same nova-compute service
  for the entire life of the instance, and so the ironic node that instance
  is on will also be managed by the same nova-compute service until the node
  is deleted. This also means that removing a nova-compute service will
  leave instances managed by that service orphaned, and as such most
  instance actions will not work until a nova-compute service with the same
  hostname is brought (back) online.

  When nova-compute services are brought up or down, the ring will eventually
  re-balance (when the resource tracker runs on each compute). This may
  result in duplicate compute_node entries for ironic nodes while the
  nova-compute service pool is re-balancing. However, because any
  nova-compute service running the ironic virt driver can manage any ironic
  node, if a build request goes to the compute service not currently managing
  the node the build request is for, it will still succeed.

  There is no configuration to do to enable this feature; it is always
  enabled.  There are no major changes when only one compute service is
  running. If more compute services are brought online, the bigger changes
  come into play.

  Note that this is tested when running with only one nova-compute service,
  but not more than one. As such, this should be used with caution for
  multiple compute hosts until it is properly tested in CI.

.. releasenotes/notes/ironic-multitenant-networking-6f124964831d4a6c.yaml @ b'e55cf73890aa104281775c0d2fe4f9f75ab2ec97'

- Multitenant networking for the ironic compute driver is now supported. To enable this feature, ironic nodes must be using the 'neutron' network_interface.

.. releasenotes/notes/libvirt-uses-os-vif-plugins-31a0617de0c248b9.yaml @ b'745f5fbb3a1b0a42eb54e2be2ecfffca3cbbb872'

- The Libvirt driver now uses os-vif plugins for handling plug/unplug actions for the Linux Bridge and OpenVSwitch VIF types. Each os-vif plugin will have its own group in nova.conf for configuration parameters it needs. These plugins will be installed by default as part of the os-vif module installation so no special action is required.

.. releasenotes/notes/libvirt_ppc64le_hugepage_support-b9fd39cf20c8e91d.yaml @ b'abc24acfa1982a0ffccbe08a006ac7c7a9f4ecda'

- Added hugepage support for POWER architectures.

.. releasenotes/notes/modern-microversions-964ae9a17df8c4b3.yaml @ b'bd199e3f9b7336b2cbc583fc6ab352f6e5b4d143'

- Microversions may now (with microversion 2.27) be requested with the "OpenStack-API-Version: compute 2.27" header, in alignment with OpenStack-wide standards. The original format, "X-OpenStack-Nova-API-Version: 2.27", may still be used.

.. releasenotes/notes/mutable-config-e7e82b3d7c38f3a5.yaml @ b'49f547bd2874af9b400ad3dae68c70579489fbe2'

- Nova has been enabled for mutable config. Certain options may be reloaded
  by sending SIGHUP to the correct process. Live migration options will apply
  to live migrations currently in progress. Please refer to the configuration
  manual.

  * DEFAULT.debug
  * libvirt.live_migration_completion_timeout
  * libvirt.live_migration_progress_timeout

.. releasenotes/notes/notification-transformation-newton-29a9324d1428b7d3.yaml @ b'6a2a1a7d630e4fc0b17af834c2a6750f1553019c'

-
  The following legacy notifications have been been transformed to
  a new versioned payload:

  * instance.delete
  * instance.pause
  * instance.power_on
  * instance.shelve
  * instance.suspend
  * instance.restore
  * instance.resize
  * instance.update
  * compute.exception

  Every versioned notification has a sample file stored under
  doc/notification_samples directory. Consult
  http://docs.openstack.org/developer/nova/notifications.html for more information.

.. releasenotes/notes/oslopolicy-scripts-957b364b8ffd7c3f.yaml @ b'3b609a52fb4ac030eef95dd8588e7d54abcc0615'

- Nova is now configured to work with two oslo.policy CLI scripts that have been added.
  The first of these can be called like "oslopolicy-list-redundant --namespace nova" and will output a list of policy rules in policy.[json|yaml] that match the project defaults. These rules can be removed from the policy file as they have no effect there.
  The second script can be called like "oslopolicy-policy-generator --namespace nova --output-file policy-merged.yaml" and will populate the policy-merged.yaml file with the effective policy. This is the merged results of project defaults and config file overrides.

.. releasenotes/notes/pagination-for-hypervisor-9c3393cd58149791.yaml @ b'ec53c6c0ec283a4c179bd2845cf0356c27fa5301'

- Added microversion v2.33 which adds paging support for hypervisors, the admin is able to perform paginate query by using limit and marker to get a list of hypervisors. The result will be sorted by hypervisor id.

.. releasenotes/notes/placement-config-section-59891ba38e0749e7.yaml @ b'a6ad102c9d73c300d4ec45d80dbf914ca9d9ec77'

- The nova-compute worker now communicates with the new placement API service. Nova determines the placement API service by querying the OpenStack service catalog for the service with a service type of 'placement'. If there is no placement entry in the service catalog, nova-compute will log a warning and no longer try to reconnect to the placement API until the nova-worker process is restarted.

.. releasenotes/notes/placement-config-section-59891ba38e0749e7.yaml @ b'a6ad102c9d73c300d4ec45d80dbf914ca9d9ec77'

- A new [placement] section is added to the nova.conf configuration file for configuration options affecting how Nova interacts with the new placement API service. This contains the usual keystone auth and session options.

.. releasenotes/notes/pointer-model-b4a1828c43e8d523.yaml @ b'ed6a82ee227acd0c3d4294e8a868fe6b7f7b313f'

- The pointer_model configuration option and hw_pointer_model image property was added to specify different pointer models for input devices. This replaces the now deprecated use_usb_tablet option.

.. releasenotes/notes/policy-discover-cli-a14a115cacbdc9c6.yaml @ b'9864801d468de5dde79141cbab4374bd2310bef2'

- The nova-policy command line is implemented as a tool to experience the under-development feature policy discovery. User can input the credentials information and the instance info, the tool will return a list of API which can be allowed to invoke. There isn't any contract for the interface of the tool due to the feature still under-development.

.. releasenotes/notes/refresh-quotas-usage-362b239171c75f5f.yaml @ b'8d25383ad2a1bdde22e306bf9daa52508c90dd3d'

- Add a nova-manage command to refresh the quota usages for a project or user.  This can be used when the usages in the quota-usages database table are out-of-sync with the actual usages.  For example, if a resource usage is at the limit in the quota_usages table, but the actual usage is less, then nova will not allow VMs to be created for that project or user. The nova-manage command can be used to re-sync the quota_usages table with the actual usage.

.. releasenotes/notes/set_guest_time-736939fe725cbdab.yaml @ b'0376da0627b022bc6aeb3e423250f9e29181f9ab'

- Libvirt driver will attempt to update the time of a suspended and/or a migrated guest in order to keep the guest clock in sync. This operation will require the guest agent to be configured and running in order to be able to run. However, this operation will not be disruptive.

.. releasenotes/notes/vendordata-reboot-ad1130444a63f2d0.yaml @ b'2c49b1e442272b71be68e156f12fd7f8df26d968'

- This release includes a new implementation of the vendordata metadata system. Please see the blueprint at http://specs.openstack.org/openstack/nova-specs/specs/newton/approved/vendordata-reboot.html for a detailed description. There is also documentation in the Nova source tree in vendordata.rst.

.. releasenotes/notes/virtual-device-role-tagging-ec0c36226a3f2e4d.yaml @ b'2a1aad9de7e33ee7bcb496de482d325915373a1a'

- The 2.32 microversion adds support for virtual device
  role tagging. Device role tagging is an answer to the
  question 'Which device is which, inside the guest?' When
  booting an instance, an optional arbitrary 'tag'
  parameter can be set on virtual network interfaces
  and/or block device mappings. This tag is exposed to the
  instance through the metadata API and on the config
  drive. Each tagged virtual network interface is listed
  along with information about the virtual hardware, such
  as bus type (ex: PCI), bus address (ex: 0000:00:02.0),
  and MAC address. For tagged block devices, the exposed
  hardware metadata includes the bus (ex: SCSI), bus
  address (ex: 1:0:2:0) and serial number.

  The 2.32 microversion also adds the 2016-06-30 version
  to the metadata API. Starting with 2016-06-30, the
  metadata contains a 'devices' sections which lists any
  devices that are tagged as described in the previous
  paragraph, along with their hardware metadata.


.. _Release Notes_14.0.0_stable_newton_Known Issues:

Known Issues
------------

.. releasenotes/notes/cells-discover-hosts-06a3079ba687e092.yaml @ b'3eb4d1fd1d94dc830f7e3420c49117e01df6451a'

- If a deployer has updated their deployment to using cellsv2 using either the simple_cell_setup or the map_cell0/map_cell_and_hosts/map_instances combo and they add a new host into the cell it may cause build failures or reschedules until they run the "nova-manage cell_v2 discover_hosts" command. This is because the scheduler will quickly become aware of the host but nova-api will not know how to route the request to that host until it has been "discovered". In order to avoid that it is advised that new computes are disabled until the discover command has been run.

.. releasenotes/notes/known-issue-on-api-1efca45440136f3e.yaml @ b'ee7a01982611cdf8012a308fa49722146c51497f'

- When using Neutron extension 'port_security' and booting an instance on a network with 'port_security_enabled=False' the Nova API response says there is a 'default' security group attached to the instance which is incorrect. However when listing security groups for the instance there are none listed, which is correct. The API response will be fixed separately with a microversion.

.. releasenotes/notes/os-brick-lock-dir-c659089679aac50f.yaml @ b'65978582e01c37a9972bf9e979c651523f0f1889'

- When running Nova Compute and Cinder Volume or Backup services on the same host they must use a shared lock directory to avoid rare race conditions that can cause volume operation failures (primarily attach/detach of volumes). This is done by setting the "lock_path" to the same directory in the "oslo_concurrency" section of nova.conf and cinder.conf. This issue affects all previous releases utilizing os-brick and shared operations on hosts between Nova Compute and Cinder data services.

.. releasenotes/notes/virtual-device-role-tagging-ec0c36226a3f2e4d.yaml @ b'2a1aad9de7e33ee7bcb496de482d325915373a1a'

- When using virtual device role tagging, the metadata on the config drive lags behind the metadata obtained from the metadata API. For example, if a tagged virtual network interface is detached from the instance, its tag remains in the metadata on the config drive. This is due to the nature of the config drive, which, once written, cannot be easily updated by Nova.


.. _Release Notes_14.0.0_stable_newton_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-cloudpipe-config-to-cloudpipe-group-ab96ebcb3ffc5d82.yaml @ b'512fb41c4e4a5affd774f70d6d51a1992ec68f59'

- All cloudpipe configuration options have been added to the 'cloudpipe' group. They should no longer be included in the 'DEFAULT' group.

.. releasenotes/notes/add-crypto-config-to-crypto-group-ac6c75ccf3c815f1.yaml @ b'e301ed2457996d5143e8a6a8cba1a97b29098485'

- All crypto configuration options have been added to the 'crypto' group. They should no longer be included in the 'DEFAULT' group.

.. releasenotes/notes/add-wsgi-config-to-wsgi-group-712b8cd9ada65b2e.yaml @ b'0b9e378cca2be4e034ad401d71fbe4470907f93a'

- All WSGI configuration options have been added to the 'wsgi' group. They should no longer be included in the 'DEFAULT' group.

.. releasenotes/notes/aggregates-moved-to-api-database-e1bd30909aaf79d3.yaml @ b'7f82c5e6816b3763cde5aee8ba97c56184aeb2aa'

- Aggregates are being moved to the API database for CellsV2. In this release, the online data migrations will move any aggregates you have in your main database to the API database, retaining all attributes. Until this is complete, new attempts to create aggregates will return an HTTP 409 to avoid creating aggregates in one place that may conflict with aggregates you already have and are yet to be migrated.

.. releasenotes/notes/aggregates-moved-to-api-database-e1bd30909aaf79d3.yaml @ b'7f82c5e6816b3763cde5aee8ba97c56184aeb2aa'

- Note that aggregates can no longer be soft-deleted as the API database does not replicate the legacy soft-delete functionality from the main database. As such, deleted aggregates are not migrated and the behavior users will experience will be the same as if a purge of deleted records was performed.

.. releasenotes/notes/bp-cells-instance-groups-api-db-910a44ef5f2f7769.yaml @ b'd35e1577c9510827b2a4802a294714340ccdee7c'

- The nova-manage db online_data_migrations command will now migrate server groups to the API database. New server groups will be automatically created in the API database but existing server groups must be manually migrated using the nova-manage command.

.. releasenotes/notes/bp-memory-bw-4ceb971cfe1a2fd0.yaml @ b'2a53063679346ce91b417e65d0bd1a9c3029d618'

- The get_metrics API has been replaced by populate_metrics in nova.compute.monitors.base module. This change is introduced to allow each monitor plugin to have the flexibility of setting it's own metric value types. The in-tree metrics plugins are modified as a part of this change. However, the out-of-tree plugins would have to adapt to the new API in order to work with nova.

.. releasenotes/notes/bp-virtuozzo-cloud-storage-support-4f4cda52ca41538e.yaml @ b'e58e11127b3b7748b6a42cf7349010a93d434a1e'

- For the Virtuozzo Storage driver to work with os-brick <1.4.0, you need to allow "pstorage-mount" in rootwrap filters for nova-compute.

.. releasenotes/notes/bp-virtuozzo-instance-resize-support-b523e6e8a0de0fbc.yaml @ b'd4aa455d53c91c6dfebbf9a9850f7b6c3fef4545'

- You must update the rootwrap configuration for the compute service if you use ploop images, so that "ploop grow" filter is changed to "prl_disk_tool resize".

.. releasenotes/notes/bug-1559026-47c3fa3468d66b07.yaml @ b'c5311439d6526006dd1354e09f2bfb86505d550d'

- The ``record`` configuration option for the console proxy services (like VNC, serial, spice) is changed from boolean to string. It specifies the filename that will be used for recording websocket frames.

.. releasenotes/notes/cell-id-db-sync-nova-manage-8504b54dd115a2e9.yaml @ b'24f0c5b9d6136fe18c3fba0ddd64dab99f6f1aa5'

- 'nova-manage db sync' can now sync the cell0 database.
  The cell0 db is required to store instances that cannot be scheduled to
  any cell. Before the 'db sync' command is called a cell mapping
  for cell0 must have been created using 'nova-manage cell_v2 map_cell0'.
  This command only needs to be called when upgrading to CellsV2.

.. releasenotes/notes/cells-single-migration-command-0e98d66e31e02a50.yaml @ b'f9a3c3fcff89828b7df45149c2d0ee188f439e46'

- A new nova-manage command has been added which will upgrade a deployment to cells v2. Running the command will setup a single cell containing the existing hosts and instances. No data or instances will be moved during this operation, but new data will be added to the nova_api database.  New instances booted after this point will be placed into the cell.  Please note that this does not mean that cells v2 is fully functional at this time, but this is a significant part of the effort to get there. The new command is "nova-manage cell_v2 simple_cell_setup --transport_url <transport_url>" where transport_url is the connection information for the current message queue used by Nova. Operators must create a new database for cell0 before running `cell_v2 simple_cell_setup`. The simple cell setup command expects the name of the cell0 database to be `<main database name>_cell0` as it will create a cell mapping for cell0 based on the main database connection, sync the cell0 database, and associate existing hosts and instances with the single cell.

.. releasenotes/notes/config-ironic-client_log_level-2bb84f12154417ca.yaml @ b'a924b1db46149d2928731f59afb7fef18deed54d'

- The deprecated configuration option ``client_log_level`` of the section ``[ironic]`` has been deleted. Please use the config options ``log_config_append`` or ``default_log_levels`` of the ``[DEFAULT]`` section.

.. releasenotes/notes/create-cell0-mapping-60a9229c223a7516.yaml @ b'17b57250c269036a8e2c104ee79c0390f0afd3f0'

- A new nova-manage command 'nova-manage cell_v2 map_cell0' is
  now available. Creates a cell mapping for cell0, which is used for
  storing instances that cannot be scheduled to any cell. This command
  only needs to be called when upgrading to CellsV2.

.. releasenotes/notes/default-value-pointer-model-cb3d9a3e9c51e503.yaml @ b'f04dd04342705c8dc745308662b698bb54debf69'

- The default value of the ``pointer_model`` configuration option has been set to 'usbtablet'.

.. releasenotes/notes/extensions_remove-37e9d4092981abbe.yaml @ b'76b58b8f895bb9b8afedeed6f01a6117f9194379'

-
  The following policy enforcement points have been removed as part
  of the restructuring of the Nova API code. The attributes that
  could have been hidden with these policy points will now always be
  shown / accepted.

  * ``os_compute_api:os-disk-config`` - show / accept
    ``OS-DCF:diskConfig`` parameter on servers

  * ``os-access-ips`` - show / accept ``accessIPv4`` and ``accessIPv6``
    parameters on servers

  The following entry points have been removed

  * ``nova.api.v21.extensions.server.resize`` - allowed accepting
    additional parameters on server resize requests.

  * ``nova.api.v21.extensions.server.update`` - allowed accepting
    additional parameters on server update requests.

  * ``nova.api.v21.extensions.server.rebuild`` - allowed accepting
    additional parameters on server rebuild requests.

.. releasenotes/notes/flavors-moved-to-api-database-b33489ed3b1b246b.yaml @ b'17a8e8a68cbe4045a1bc2889d1bf51f2db7ebcca'

- Flavors are being moved to the API database for CellsV2. In this release, the online data migrations will move any flavors you have in your main database to the API database, retaining all attributes. Until this is complete, new attempts to create flavors will return an HTTP 409 to avoid creating flavors in one place that may conflict with flavors you already have and are yet to be migrated.

.. releasenotes/notes/flavors-moved-to-api-database-b33489ed3b1b246b.yaml @ b'17a8e8a68cbe4045a1bc2889d1bf51f2db7ebcca'

- Note that flavors can no longer be soft-deleted as the API database does not replicate the legacy soft-delete functionality from the main database. As such, deleted flavors are not migrated and the behavior users will experience will be the same as if a purge of deleted records was performed.

.. releasenotes/notes/get-me-a-network-992eabc81b5e5347.yaml @ b'd727795d6668abaf17b5afe01d2e1757aebe7e2e'

- The 2.37 microversion enforces the following:

  * ``networks`` is required in the server create request body for the API.
    Specifying ``networks: auto`` is similar to not requesting specific
    networks when creating a server before 2.37.
  * The ``uuid`` field in the ``networks`` object of a server create request
    is now required to be in UUID format, it cannot be a random string. More
    specifically, the API used to support a nic uuid with a "br-" prefix but
    that is a legacy artifact which is no longer supported.

.. releasenotes/notes/glance_v2-15b080e361804976.yaml @ b'f71cd2ca03693655efdbd1109f406ab6f3b58ee6'

- It is now required that the glance environment used by Nova exposes the version 2 REST API. This API has been available for many years, but previously Nova only used the version 1 API.

.. releasenotes/notes/imageRef-as-uuid-only-0164c04206a42683.yaml @ b'cbd3ec476f769c42e5b2a0ef8c996b60935e7f6c'

- imageRef input to the REST API is now restricted to be UUID or an empty string only. imageRef input while create, rebuild and rescue server etc must be a valid UUID now. Previously, a random image ref url containing image UUID was accepted. But now all the reference of imageRef must be a valid UUID (with below exception) otherwise API will return 400.
  Exception- In case boot server from volume. Previously empty string was allowed in imageRef and which is ok in case of boot from volume. Nova will keep the same behavior and allow empty string in case of boot from volume only and 400 in all other case.

.. releasenotes/notes/instance-path-2efca507456d8a70.yaml @ b'1e0b2b582251c401745e0e2813ececeff8ed60a2'

- Prior to Grizzly release default instance directory names were based on
  instance.id field, for example directory for instance could be named
  ``instance-00000008``. In Grizzly this mechanism was changed,
  instance.uuid is used as an instance directory name, e.g. path to instance:

  ``/opt/stack/data/nova/instances/34198248-5541-4d52-a0b4-a6635a7802dd/``.

  In Newton backward compatibility is dropped. For instances that haven't
  been restarted since Folsom and earlier maintanance should be scheduled
  before upgrade(stop, rename directory to instance.uuid, then start) so Nova
  will start using new paths for instances.

.. releasenotes/notes/ironic-multitenant-networking-6f124964831d4a6c.yaml @ b'e55cf73890aa104281775c0d2fe4f9f75ab2ec97'

- The ironic driver now requires python-ironicclient>=1.5.0 (previously >=1.1.0), and requires the ironic service to support API version 1.20 or higher. As usual, ironic should be upgraded before nova for a smooth upgrade process.

.. releasenotes/notes/ironic-resource-class-6496fed067df629f.yaml @ b'7b8195a8a8f2ca61b97a1c4329525bed1848b09d'

- The ironic driver now requires python-ironicclient>=1.6.0, and requires the ironic service to support API version 1.21.

.. releasenotes/notes/keypairs-moved-to-api-9cde30acac6f76b6.yaml @ b'b8aac794d4620aca341b269c6db71ea9e70d2210'

- Keypairs have been moved to the API database, using an online data migration. During the first phase of the migration, instances will be given local storage of their key, after which keypairs will be moved to the API database.

.. releasenotes/notes/libvirt-change-default-value-of-live-migration-tunnelled-4248cf76df605fdf.yaml @ b'61f122637b8c9952e28983de81638941dc4e7bc4'

- Default value of live_migration_tunnelled config option in libvirt section has been changed to False. After upgrading nova to Newton all live migrations will be non-tunnelled unless live_migration_tunnelled is explicitly set to True. It means that, by default, the migration traffic will not go through libvirt and therefore will no longer be encrypted.

.. releasenotes/notes/libvirt-uses-os-vif-plugins-31a0617de0c248b9.yaml @ b'745f5fbb3a1b0a42eb54e2be2ecfffca3cbbb872'

- With the introduction of os-vif, some networking related configuration options have moved, and users will need to update their ``nova.conf``.
  For OpenVSwitch users the following options have moved from ``[DEFAULT]`` to ``[vif_plug_ovs]``
  - network_device_mtu - ovs_vsctl_timeout
  For Linux Bridge users the following options have moved from ``[DEFAULT]`` to ``[vif_plug_linux_bridge]``
  - use_ipv6 - iptables_top_regex - iptables_bottom_regex - iptables_drop_action - forward_bridge_interface - vlan_interface - flat_interface - network_device_mtu
  For backwards compatibility, and ease of upgrade, these options will continue to work from ``[DEFAULT]`` during the Newton release. However they will not in future releases.

.. releasenotes/notes/min-required-libvirt-b948948949669b02.yaml @ b'6b2cad6e1283ed7dc2b45a026b0d4a524486deaf'

- The minimum required version of libvirt has been increased to 1.2.1

.. releasenotes/notes/min-required-qemu-c987a8a5c6c4fee0.yaml @ b'07e4a90cfea56a9513d476769190d488e33ac8b0'

- The minimum required QEMU version is now checked and has been set to 1.5.3

.. releasenotes/notes/network-api-class-removed-a4a754ca24c02bde.yaml @ b'd82db52a093527c7978648c30870faa64043a752'

- The network_api_class option was deprecated in Mitaka and is removed in Newton. The use_neutron option replaces this functionality.

.. releasenotes/notes/newton-has-many-online-migrations-38066facfe197382.yaml @ b'd83c2772da4c1a059c4906d8ea7a5cf942e8e41b'

- The newton release has a lot of online migrations that must be performed before you will be able to upgrade to ocata. Please take extra note of this fact and budget time to run these online migrations before you plan to upgrade to ocata. These migrations can be run without downtime with `nova-manage db online_data_migrations`.

.. releasenotes/notes/notify_on_state_change_opt-e3c6f6664e143993.yaml @ b'5f4dcdce16837e28af18964f533a1eba738b9f34'

- The ``notify_on_state_change`` configuration option was StrOpt, which would accept
  any string or None in the previous release.  Starting in the Newton release,
  it allows only three values: None, ``vm_state``, ``vm_and_task_state``. The default
  value is None.

.. releasenotes/notes/remove-auth-admin-token-support-1b59ae7739b06bc2.yaml @ b'2ea2399ec3e4b976beadfbcd1cab78b94382eca3'

- The deprecated auth parameter `admin_auth_token` was removed from the [ironic] config option group. The use of `admin_auth_token` is insecure compared to the use of a proper username/password.

.. releasenotes/notes/remove-config-serial-listen-2660be1c0863ea5a.yaml @ b'3495330a94e4728ba44077f0585b34b8c74112b0'

- The previously deprecated config option ``listen```of the group
  ``serial_console`` has been removed, as it was never used in the code.

.. releasenotes/notes/remove-deprecated-cells-manager-option-d9d20691c08d2752.yaml @ b'28803fa40b6195b152668da4e1f0feec53df533b'

- The 'manager' option in [cells] group was deprecated in Mitaka and now it is removed completely in newton. There is no impact.

.. releasenotes/notes/remove-deprecated-cinder-options-newton-fc3dce6856101ef8.yaml @ b'fb15c00aa1561973804819d111d52b6d25842293'

- The following deprecated configuration options have been removed from the
  ``cinder`` section of ``nova.conf``:

  - ``ca_certificates_file``
  - ``api_insecure``
  - ``http_timeout``

.. releasenotes/notes/remove-deprecated-destroy_after_evacuate-option-2557d0634e78abd1.yaml @ b'50b1f1fc267517b5eb4d3da567d6d76c83568f7f'

- The 'destroy_after_evacuate' workaround option has been removed as the workaround is no longer necessary.

.. releasenotes/notes/remove-deprecated-legacy_api-config-options-f3f096df3a03d956.yaml @ b'c05d08b6fda348e48c92eef1aecd386f460a9158'

- The config options 'osapi_compute_ext_list' and 'osapi_compute_extension' were deprecated in mitaka. Hence these options were completely removed in newton, as v2 API is removed and v2.1 API doesn't provide the option of configuring extensions.

.. releasenotes/notes/remove-deprecated-remove_unused_kernels-b663aa6829761f1e.yaml @ b'547dc45044e3c0b8d25ab8f584e8a5141f541547'

- The deprecated config option ``remove_unused_kernels`` has been removed from the ``[libvirt]`` config section. No replacement is required, as this behaviour is no longer relevant.

.. releasenotes/notes/remove-extensible-resource-tracker-37e8fdac46ec6eba.yaml @ b'49d9433c62d74f6ebdcf0832e3a03e544b1d6c83'

- The extensible resource tracker was deprecated in the 13.0.0 release and has now been removed. Custom resources in the nova.compute.resources namespace selected by the compute_resources configuration parameter will not be loaded.

.. releasenotes/notes/remove-legacy-v2-api-7ac6d74edaedf011.yaml @ b'58bac4735d96aebc2af4da256f8616ce79e5d076'

- The legacy v2 API code was deprecated since Liberty release. The legacy v2 API code was removed in Newton release. We suggest that users should move to v2.1 API which compatible v2 API with more restrict input validation and microversions support. If users are still looking for v2 compatible API before switch to v2.1 API, users can use v2.1 API code as v2 API compatible mode. That compatible mode is closer to v2 API behaviour which is v2 API compatible without restrict input validation and microversions support. So if using openstack_compute_api_legacy_v2 in /etc/nova/api-paste.ini for the API endpoint /v2, users need to switch the endpoint to openstack_compute_api_v21_legacy_v2_compatible instead.

.. releasenotes/notes/remove-libvirt-migration-flags-config-8bf909c1295cc53f.yaml @ b'a48b6146af93dd0cb1b43ec7d83867df8b347df2'

- The 'live_migration_flag' and 'block_migration_flag' options in libvirt section that were deprecated in Mitaka have been completely removed in Newton, because nova automatically sets correct migration flags. New config options has been added to retain possibility to turn tunnelling, auto-converge and post-copy on/off, respectively named `live_migration_tunnelled`, `live_migration_permit_auto_converge` and `live_migration_permit_post_copy`.

.. releasenotes/notes/remove-memcached-default-option-e0e50d54cef17ac4.yaml @ b'505bc44615d922c0e9054c3ca48721b26b924caa'

- The 'memcached_server' option in DEFAULT section which was deprecated in Mitaka has been completely removed in Newton. This has been replaced by options from oslo cache section.

.. releasenotes/notes/remove-nova-manage-service-subcommand-2a11ed662864341c.yaml @ b'0fca575bc779962a7dfb97443f49e27c43d93039'

- The service subcommand of nova-manage was deprecated in 13.0. Now in 14.0 the service subcommand is removed. Use service-* commands from python-novaclient or the os-services REST resource instead.

.. releasenotes/notes/remove_config_network_device_mtu-75780f727c322ff3.yaml @ b'14da85ac95ce63e11ad2ba63053f122de9a066ec'

- The network_device_mtu option in Nova is deprecated for removal in 13.0.0 since network MTU should be specified when creating the network.

.. releasenotes/notes/remove_legacy_v2_api_policy_rules-033fa77420ed6362.yaml @ b'31547f551c3d081b0d88cd6af8e6f1045fab948f'

- Legacy v2 API code is already removed. A set of policy rules in the policy.json, which are only used by legacy v2 API, are removed. Both v2.1 API and v2.1 compatible mode API are using same set of new policy rules which are with prefix `os_compute_api`.

.. releasenotes/notes/remove_security_group_api-6fefb1a355876e83.yaml @ b'34eed4a4d48772e509261d9098a09185061a0ce0'

- Removed the ``security_group_api`` configuration option that was deprecated in Mitaka. The correct security_group_api option will be chosen based on the value of ``use_neutron`` which provides a more coherent user experience.

.. releasenotes/notes/remove_volume_api_class-a3c618228c89f57b.yaml @ b'6af8d2c8e9bd66956b03f946a86daf1c567821a2'

- The deprecated ``volume_api_class`` config option has been removed. We only have one sensible backend for it, so don't need it anymore.

.. releasenotes/notes/rename-iscsi-multipath-opt-eabbafccd2b74a0a.yaml @ b'720e5af1e08cc829e98db10da4b93795771a927e'

- The libvirt option 'iscsi_use_multipath' has been renamed to 'volume_use_multipath'.

.. releasenotes/notes/rename-wsgi-prefixed-opts-9075ff9c2215e61c.yaml @ b'235864008ba7c58159918620040d2425f48a8a8f'

- The 'wsgi_default_pool_size' and 'wsgi_keep_alive' options have been renamed to 'default_pool_size' and 'keep_alive' respectively.

.. releasenotes/notes/rm-deprecated-neutron-opts-newton-a09ecfb0775339e6.yaml @ b'efe193ceed05474ba959cae5311c516c360f5d25'

- The following deprecated configuration options have been removed from the
  ``neutron`` section of nova.conf:

  - ``ca_certificates_file``
  - ``api_insecure``
  - ``url_timeout``

.. releasenotes/notes/rm-sched-host-mgr-class-load-2a86749a38f0688d.yaml @ b'7e2f5c7d340a0131ac083ed036e417976d6342da'

- The ability to load a custom scheduler host manager via the ``scheduler_host_manager`` configuration option was deprecated in the 13.0.0 Mitaka release and is now removed in the 14.0.0 Newton release.

.. releasenotes/notes/rm_db2-926e38cbda44a55f.yaml @ b'cdf74c57a6755619acaabd2e3a2559f25b2fbe0f'

- DB2 database support was removed from tree. This is a non open source database that had no 3rd party CI, and a set of constraints that meant we had to keep special casing it in code. It also made the online data migrations needed for cells v2 and placement engine much more difficult. With 0% of OpenStack survey users reporting usage we decided it was time to remove this to focus on features needed by the larger community.

.. releasenotes/notes/rm_glance_opts-360c94ac27328dc9.yaml @ b'b90f2bb4fcb3f980644a952543770684c8aa3b8c'

- Delete the deprecated ``glance.host``, ``glance.port``, ``glance.protocol`` configuration options. ``glance.api_servers`` must be set to have a working config. There is currently no default for this config option, so a value must be set.

.. releasenotes/notes/rm_import_object_ns-5344a390b0af465e.yaml @ b'ed308b99ca3c2e92ce8def4e8fe1ba1648f9a68d'

- Only virt drivers in the nova.virt namespace may be loaded. This has been the case according to nova docs for several releases, but a quirk in some library code meant that loading things outside the namespace continued to work unintentionally. That has been fixed, which means "compute_driver = nova.virt.foo" is invalid (and now enforced as such), and should be "compute_driver = foo" instead.

.. releasenotes/notes/swap-volume-policy-9464e97aba12d1e0.yaml @ b'f738483e843fc27379b85c5401859ccc854adc5e'

- The default policy for updating volume attachments, commonly referred to as swap volume, has been changed from ``rule:admin_or_owner`` to ``rule:admin_api``. This is because it is called from the volume service when migrating volumes, which is an admin-only operation by default, and requires calling an admin-only API in the volume service upon completion. So by default it would not work for non-admins.

.. releasenotes/notes/v21enable-8454d6eca3ec604f.yaml @ b'e65557c1933a563a106763e06d0d4f564d7a4174'

- The deprecated osapi_v21.enabled config option has been removed. This previously allowed you a way to disable the v2.1 API. That is no longer something we support, v2.1 is mandatory.

.. releasenotes/notes/vmware_disk_enableuuid_true-99b88e00fc168dd3.yaml @ b'2a6bdf8f0e0e22fc7703faa9669ace7380dc73c3'

- Now VMwareVCDriver will set disk.EnableUUID=True by default in all guest VM configuration file. To enable udev to generate /dev/disk/by-id


.. _Release Notes_14.0.0_stable_newton_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/deprecate-barbican-config-options-68ae65643ac41e2f.yaml @ b'899a140f32880cf33472f792e542ba0db15b4aac'

- All barbican config options in Nova are now deprecated and may be removed as early as 15.0.0 release. All of these options are moved to the Castellan library.

.. releasenotes/notes/deprecate-cells-driver-options-473893e4e87f95c2.yaml @ b'579c98a2eba26d65031385e6e46bda96e2f5131d'

- The cells.driver configuration option is now deprecated and
  will be removed at Ocata cycle.

.. releasenotes/notes/deprecate-config-image-file-url-46c20999756afce0.yaml @ b'9931ef9ca23dfaba3fc69d1e0f0d1913e4236009'

- The feature to download *Glance* images via file transfer instead of HTTP is now deprecated and may be removed as early as the 15.0.0 release. The config options ``filesystems`` in the section ``image_file_url`` are affected as well as the derived sections ``image_file_url:<list entry name>`` and their config options ``id`` and ``mountpoint``.

.. releasenotes/notes/deprecate-config-s3-image-adb7c86c9b9220a5.yaml @ b'be86b27e020438566da9e05516654b5a2aea47ab'

- As mentioned in the release notes of the Mitaka release (version 13.0.0), the EC2API support was fully removed. The *s3* image service related config options were still there but weren't used anywhere in the code since Mitaka. These are now deprecated and may be removed as early as the 15.0.0 release. This affects ``image_decryption_dir``, ``s3_host``, ``s3_port``, ``s3_access_key``, ``s3_secret_key``, ``s3_use_ssl``, ``s3_affix_tenant``.

.. releasenotes/notes/deprecate-default-flavor-6c144f67f8032dfa.yaml @ b'b7660e0d7bba3c4d0aaf22e7235f2643109477d2'

- The ``default_flavor`` config option is now deprecated and may be removed as early as the 15.0.0 release. It is an option which was only relevant for the deprecated EC2 API and is not used in the Nova API.

.. releasenotes/notes/deprecate-fatal-exception-format-errors-a5d2bf64e3404c39.yaml @ b'6919b25ce0b9ae780074c6e2efe5c4b9fdead8c9'

- The ``fatal_exception_format_errors`` config option is now deprecated and may be removed as early as the 15.0.0 release. It is an option which was only relevant for Nova internal testing purposes to ensure that errors in formatted exception messages got detected.

.. releasenotes/notes/deprecate-image-cache-checksumming-80e52279881ebc71.yaml @ b'2c389ccc8c266175a71a29358bec7fe219e64fe0'

- The ``image_info_filename_pattern``, ``checksum_base_images``, and ``checksum_interval_seconds`` options have been deprecated in the ``[libvirt]`` config section. They are no longer used. Any value given will be ignored.

.. releasenotes/notes/deprecate-nova-manage-network-commands-212726e67bffdfc4.yaml @ b'b82b987b76f8d67b058a7c902d1124a3d16f63f5'

- The following nova-manage commands are deprecated for removal in the
  Nova 15.0.0 Ocata release:

  * nova-maange account scrub
  * nova-manage fixed *
  * nova-manage floating *
  * nova-manage network *
  * nova-manage project scrub
  * nova-manage vpn *

  These commands only work with nova-network which is itself deprecated in
  favor of Neutron.

.. releasenotes/notes/deprecate-nova-manage-vm-list-571162f55173cccc.yaml @ b'5a5b06fb24fc6e392eb5381f1348e475f1302e1e'

- The ``nova-manage vm list`` command is deprecated and will be removed in the 15.0.0 Ocata release. Use the ``nova list`` command from python-novaclient instead.

.. releasenotes/notes/deprecate-old-auth-parameters-948d70045335b312.yaml @ b'2ea2399ec3e4b976beadfbcd1cab78b94382eca3'

- The auth parameters `admin_username`, `admin_password`, `admin_tenant_name` and `admin_url` of the [ironic] config option group are now deprecated and will be removed in a future release. Using these parameters will log a warning. Please use `username`, `password`, `project_id` (or `project_name`) and `auth_url` instead. If you are using Keystone v3 API, please note that the name uniqueness for project and user only holds inside the same hierarchy level, so you must also specify domain information for user (i.e. `user_domain_id` or `user_domain_name`) and for project, if you are using `project_name` (i.e. `project_domain_id` or `project_domain_name`).

.. releasenotes/notes/deprecate-snapshot-name-template-46966b0f5e6cabeb.yaml @ b'aeee4547b80013564e634cb7c1bde63f3c55d1f1'

- The config option ``snapshot_name_template`` in the ``DEFAULT`` group
  is now deprecated and may be removed as early as the 15.0.0 release.
  The code which used this option isn't used anymore since late 2012.

.. releasenotes/notes/deprecate_nova_all-eee03c2b0e944699.yaml @ b'5f996d4786c11a587364cfa9a6acf5922f5245a6'

- The ``nova-all`` binary is deprecated. This was an all in one binary for nova services used for testing in the early days of OpenStack, but was never intended for real use.

.. releasenotes/notes/deprecate_nova_network-093e937dcdb7fc57.yaml @ b'7d5fc486823117ba7a0a9005142ef87059ef74cd'

- Nova network is now deprecated. Based on the results of the current OpenStack User Survey less than 10% of our users remain on Nova network. This is the signal that it is time migrate to Neutron. No new features will be added to Nova network, and bugs will only be fixed on a case by case basis.

.. releasenotes/notes/deprecate_os_cert-f0aa07bab1a229aa.yaml @ b'5afc8e5745fff1caa31aeb23aae25e30819cd736'

- The ``/os-certificates`` API is deprecated, as well as the ``nova-cert`` service which powers it. The related config option ``cert_topic`` is also now marked for deprecation and may be removed as early as 15.0.0 Ocata release. This is a vestigial part of the Nova API that existed only for EC2 support, which is now maintained out of tree. It does not interact with any of the rest of nova, and should not just be used as a certificates as a service, which is all it is currently good for.

.. releasenotes/notes/deprecates-proxy-apis-5e11d7c4ae5227d2.yaml @ b'4a7deee95f70aed22e64a1f1ecbfe2e31c14a19f'

- All the APIs which proxy to other services were deprecated in this API
  version. Those APIs will return 404 on Microversion 2.36 or higher. The API
  user should use native API as instead of using those pure proxy for other
  REST APIs. The quotas and limits related to network resources 'fixed_ips',
  'floating ips', 'security_groups', 'security_group_rules', 'networks' are
  filtered out of os-quotas and limit APIs respectively and those quotas
  should be managed through OpenStack network service. For using
  nova-network, you only can use API and manage quotas under Microversion
  '2.36'. The 'os-fping' API was deprecated also, this API is only related to
  nova-network and depend on the deployment. The deprecated APIs are as
  below:

  - /images
  - /os-networks
  - /os-fixed-ips
  - /os-floating-ips
  - /os-floating-ips-bulk
  - /os-floating-ip-pools
  - /os-floating-ip-dns
  - /os-security-groups
  - /os-security-group-rules
  - /os-security-group-default-rules
  - /os-volumes
  - /os-snapshots
  - /os-baremetal-nodes
  - /os-fping

.. releasenotes/notes/pointer-model-b4a1828c43e8d523.yaml @ b'ed6a82ee227acd0c3d4294e8a868fe6b7f7b313f'

- Nova option 'use_usb_tablet' will be deprecated in favor of the global 'pointer_model'.

.. releasenotes/notes/quota-driver-is-deprecated-a915edf8777f3ddb.yaml @ b'430638888c987a99e537e2ac956087a7310ecdc6'

- The quota_driver configuration option is now deprecated and will be removed in a subsequent release.


.. _Release Notes_14.0.0_stable_newton_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-8813f7a333ebdf69.yaml @ b'068d851561addfefb2b812d91dc2011077cb6e1d'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Release Notes_14.0.0_stable_newton_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/list-invalid-status-af07af378728bc57.yaml @ b'984d00919ffe5ac5d41edb194740f6f33ca3e78f'

- Corrected response for the case where an invalid status value is passed as a filter to the list servers API call. As there are sufficient statuses defined already, any invalid status should not be accepted. As of microversion 2.38, the API will return 400 HTTPBadRequest if an invalid status is passed to list servers API for both admin as well as non admin user.

.. releasenotes/notes/list-server-bad-status-fix-7db504b38c8d732f.yaml @ b'ee4d69e28dfb3d4764186d0c0212d53c99bda3ca'

- Fixed bug #1579706: "Listing nova instances with invalid status raises 500
  InternalServerError for admin user". Now passing an invalid status as a
  filter will return an empty list. A subsequent patch will then correct this
  to raise a 400 Bad Request when an invalid status is received.

.. releasenotes/notes/multiqueue-on-tap-interface-2c9e1504fa4590f4.yaml @ b'b9303e67640ac2052c0a79189b29f60bde6b8fdc'

- When instantiating an instance based on an image with the metadata
  hw_vif_multiqueue_enabled=true, if flavor.vcpus is less than the limit
  of the number of queues on a tap interface in the kernel, nova uses
  flavor.vcpus as the number of queues. if not, nova uses the limit.
  The limits are as follows:

  * kernels prior to 3.0: 1
  * kernels 3.x: 8
  * kernels 4.x: 256

.. releasenotes/notes/set_migration_status_to_error_on_live-migration_failure-d1f6f29ceafdd598.yaml @ b'6641852b8ed63bad0917d355f9563f5e9e9bbf75'

- To make live-migration consistent with resize, confirm-resize and revert-resize operations, the migration status is changed to 'error' instead of 'failed' in case of live-migration failure. With this change the periodic task '_cleanup_incomplete_migrations' is now able to remove orphaned instance files from compute nodes in case of live-migration failures. There is no impact since migration status 'error' and 'failed' refer to the same failed state.

.. releasenotes/notes/vhost-user-mtu-23d0af36a8adfa56.yaml @ b'adf7ba61dd73fe4bfffa20295be9a4b1006a1fe6'

- When plugging virtual interfaces of type vhost-user the MTU value will not be applied to the interface by nova. vhost-user ports exist only in userspace and are not backed by kernel netdevs, for this reason it is not possible to set the mtu on a vhost-user interface using standard tools such as ifconfig or ip link.


.. _Release Notes_14.0.0_stable_newton_Other Notes:

Other Notes
-----------

.. releasenotes/notes/empty-sample-policy-abfb7d467d2ebd4c.yaml @ b'625f203610f17f2b968e5f78a46d398953637174'

- The API policy defaults are now defined in code like configuration options.
  Because of this, the sample policy.json file that is shipped with Nova is
  empty and should only be necessary if you want to override the API policy
  from the defaults in the code. To generate the policy file you can run::

    oslopolicy-sample-generator --config-file=etc/nova/nova-policy-generator.conf

.. releasenotes/notes/network-allocate-retries-min-a5288476b11bfe55.yaml @ b'883bae38c329abe4a54fba88b642c20a11529193'

- network_allocate_retries config param now allows only
  positive integer values or 0.

.. releasenotes/notes/remove-api-rate-limit-option-91a17e057081381a.yaml @ b'3dd9d05d0e5facd8704e056c6af4c73847cedbe4'

- The ``api_rate_limit`` configuration option has been removed. The option was disabled by default back in the Havana release since it's effectively broken for more than one API worker. It has been removed because the legacy v2 API code that was using it has also been removed.

.. releasenotes/notes/remove-default-flavors-5238c2d9673c61e2.yaml @ b'1a1a41bdbe0dc16ca594236925e77ce99f432b9d'

- The default flavors that nova has previously had are no longer created as part of the first database migration. New deployments will need to create appropriate flavors before first use.

.. releasenotes/notes/remove-unused-config-opt-fake-call-37a56f6ec15f7d90.yaml @ b'b8fea0351895f468d0b5e72087adde5e8a788ab1'

- The network configuration option 'fake_call' has been removed. It hasn't been used for several cycles, and has no effect on any code, so there should be no impact.

.. releasenotes/notes/remove-unused-config-opt-iqn_prefix-defb44120dae93e3.yaml @ b'9c238c113008df459b7e24bb32f618a7e9386a05'

- The XenServer configuration option 'iqn_prefix' has been removed. It was not used anywhere and has no effect on any code, so there should be no impact.

.. releasenotes/notes/rm_import_object_ns-5344a390b0af465e.yaml @ b'ed308b99ca3c2e92ce8def4e8fe1ba1648f9a68d'

- Virt drivers are no longer loaded with the import_object_ns function, which means that only virt drivers in the nova.virt namespace can be loaded.

.. releasenotes/notes/sync_power_state_pool_size-81d2d142bffa055b.yaml @ b'386812e287198cd2d340d273753ef06075f7c05d'

- New configuration option sync_power_state_pool_size has been added to set the number of greenthreads available for use to sync power states. Default value (1000) matches the previous implicit default value provided by Greenpool. This option can be used to reduce the number of concurrent requests made to the hypervisor or system with real instance power states for performance reasons.


