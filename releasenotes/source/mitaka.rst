===================================
 Mitaka Series Release Notes
===================================

.. _Release Notes_13.1.4_stable_mitaka:

13.1.4
======

.. _Release Notes_13.1.4_stable_mitaka_Prelude:

Prelude
-------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'e193201fa1de5b08b29adefd8c149935c5529598'

This release includes fixes for security vulnerabilities.


.. _Release Notes_13.1.4_stable_mitaka_Security Issues:

Security Issues
---------------

.. releasenotes/notes/bug-1673569-cve-2017-7214-2d7644b356015c93.yaml @ b'e193201fa1de5b08b29adefd8c149935c5529598'

- [CVE-2017-7214] Failed notification payload is dumped in logs with auth secrets

  * `Bug 1673569 <https://bugs.launchpad.net/nova/+bug/1673569>`_


.. _Release Notes_13.1.3_stable_mitaka:

13.1.3
======

.. _Release Notes_13.1.3_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/bug-1662699-06203e7262e02aa6.yaml @ b'9b3c4736a35b0db6ceff38786fb706a6a312a7ab'

- Fixes `bug 1662699`_ which was a regression in the v2.1 API from the
  ``block_device_mapping_v2.boot_index`` validation that was performed in the
  legacy v2 API. With this fix, requests to create a server with
  ``boot_index=None`` will be treated as if ``boot_index`` was not specified,
  which defaults to meaning a non-bootable block device.

  .. _bug 1662699: https://bugs.launchpad.net/nova/+bug/1662699


.. _Release Notes_13.1.2_stable_mitaka:

13.1.2
======

.. _Release Notes_13.1.2_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/list-server-bad-status-fix-7db504b38c8d732f.yaml @ b'9a97047850e6febce090cee9a5f2224cdf02a2c3'

- Fixed bug #1579706: "Listing nova instances with invalid status raises 500
  InternalServerError for admin user". Now passing an invalid status as a
  filter will return an empty list. A subsequent patch will then correct this
  to raise a 400 Bad Request when an invalid status is received.


.. _Release Notes_13.1.1_stable_mitaka:

13.1.1
======

.. _Release Notes_13.1.1_stable_mitaka_Known Issues:

Known Issues
------------

.. releasenotes/notes/known-issue-on-api-1efca45440136f3e.yaml @ b'84d5697c9e614c2bf299e213f5398e4ecf160400'

- When using Neutron extension 'port_security' and booting an instance on a network with 'port_security_enabled=False' the Nova API response says there is a 'default' security group attached to the instance which is incorrect. However when listing security groups for the instance there are none listed, which is correct. The API response will be fixed separately with a microversion.


.. _Release Notes_13.1.0_stable_mitaka:

13.1.0
======

.. _Release Notes_13.1.0_stable_mitaka_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/bug-1559026-47c3fa3468d66b07.yaml @ b'3c008718e15f0d2da717f04ff211e9da6d80ff2d'

- The ``record`` configuration option for the console proxy services (like VNC, serial, spice) is changed from boolean to string. It specifies the filename that will be used for recording websocket frames.


.. _Release Notes_13.1.0_stable_mitaka_Security Issues:

Security Issues
---------------

.. releasenotes/notes/apply-limits-to-qemu-img-8813f7a333ebdf69.yaml @ b'c8ec9ebf379c61d73c5671a75dd2a4e4ae1403fb'

- The qemu-img tool now has resource limits applied which prevent it from using more than 1GB of address space or more than 2 seconds of CPU time. This provides protection against denial of service attacks from maliciously crafted or corrupted disk images.


.. _Release Notes_13.0.0_stable_mitaka:

13.0.0
======

.. _Release Notes_13.0.0_stable_mitaka_Prelude:

Prelude
-------

.. releasenotes/notes/add-aggregate-type-extra-specs-affinity-filter-79a2d3ee152b8ecd.yaml @ b'a5486b32a3c476f3ad584d8ff7c4eda2bb3e400d'



.. releasenotes/notes/api_servers_no_scheme-e4aa216d251022f2.yaml @ b'1c18f1838526de11ddd2ab42b4a49ab8df2ee8d1'



.. releasenotes/notes/disable_ec2_api_by_default-0ec0946433fc7119.yaml @ b'7b1fb84f68bbcef0c496d3990e5d6b99a5360bc8'



.. releasenotes/notes/lock_policy-75bea372036acbd5.yaml @ b'a5486b32a3c476f3ad584d8ff7c4eda2bb3e400d'



.. releasenotes/notes/mitaka_prelude-c8b955ed78a5ad65.yaml @ b'f4a8cdb91f96f7b5674a06c00c881fcae864b062'

Nova 13.0.0 release is including a lot of new features and bugfixes. It can
be extremely hard to mention all the changes we introduced during that
release but we beg you to read at least the upgrade section which describes
the required modifications that you need to do for upgrading your cloud
from 12.0.0 (Liberty) to 13.0.0 (Mitaka).

That said, a few major changes are worth to notice here. This is not an
exhaustive list of things to notice, rather just important things you need
to know :

    - Latest API microversion supported for Mitaka is v2.25
    - Nova now requires a second database (called 'API DB').
    - A new nova-manage script allows you to perform all online DB
      migrations once you upgrade your cloud
    - EC2 API support is fully removed.


.. releasenotes/notes/new-oslo-reports-option-619c3dbf3ae320fb.yaml @ b'a5486b32a3c476f3ad584d8ff7c4eda2bb3e400d'



.. releasenotes/notes/reserved-hugepages-per-nodes-f36225d5fca807e4.yaml @ b'7b1fb84f68bbcef0c496d3990e5d6b99a5360bc8'



.. releasenotes/notes/switch-to-oslo-cache-7114a0ab2dea52df.yaml @ b'205fb7c8b34e521bdc14b5c3698d1597753b27d4'



.. _Release Notes_13.0.0_stable_mitaka_New Features:

New Features
------------

.. releasenotes/notes/1516578-628b417b372f4f0f.yaml @ b'1a2443ce67700c494275a3ea51e584c551f7490f'

- Enables NUMA topology reporting on PowerPC architecture
  from the libvirt driver in Nova but with a caveat as mentioned below.
  NUMA cell affinity and dedicated cpu pinning
  code assumes that the host operating system is exposed to threads.
  PowerPC based hosts use core based scheduling for processes.
  Due to this, the cores on the PowerPC architecture are treated as
  threads. Since cores are always less than or equal
  to the threads on a system, this leads to non-optimal resource usage
  while pinning. This feature is supported from libvirt version 1.2.19
  for PowerPC.

.. releasenotes/notes/abort-live-migration-cb902bb0754b11b6.yaml @ b'fa002925460e70d988d1b4dd1ea594c680a43740'

- A new REST API to cancel an ongoing live migration has been added in microversion 2.24. Initially this operation will only work with the libvirt virt driver.

.. releasenotes/notes/attach-detach-vol-for-shelved-and-shelved-offloaded-instances-93f70cfd49299f05.yaml @ b'cf34a32820cc21dd9b9075d5476e050ecd8b34ac'

- It is possible to call attach and detach volume API operations for instances which are in shelved and shelved_offloaded state. For an instance in shelved_offloaded state Nova will set to None the value for the device_name field, the right value for that field will be set once the instance will be unshelved as it will be managed by a specific compute manager.

.. releasenotes/notes/block-live-migrate-with-attached-volumes-ee02afbfe46937c7.yaml @ b'f99077cf24ceee79d0abe84b5a53b82c7d64c5cb'

- It is possible to block live migrate instances with additional cinder volumes attached. This requires libvirt version to be >=1.2.17 and does not work when live_migration_tunnelled is set to True.

.. releasenotes/notes/bp-add-project-and-user-id-a560d087656157d4.yaml @ b'6c74a145bc3f412b0f5ef1965b00c8542963ed26'

- Project-id and user-id are now also returned in
  the return data of os-server-groups APIs. In order
  to use this new feature, user have to contain the
  header of request microversion v2.13 in the API
  request.

.. releasenotes/notes/bp-boot-from-uefi-b413b96017db76dd.yaml @ b'9e2dfb61ed1c8f8c891c34ca4da2b46b69abd661'

- Add support for enabling uefi boot with libvirt.

.. releasenotes/notes/bp-get-valid-server-state-a817488f4c8d3822.yaml @ b'9345d5835fb8ff6a3534122c3c13620547862e95'

- A new host_status attribute for servers/detail and servers/{server_id}.
  In order to use this new feature, user have to contain the header of
  request microversion v2.16 in the API request. A new policy
  ``os_compute_api:servers:show:host_status`` added to enable the feature.
  By default, this is only exposed to cloud administrators.

.. releasenotes/notes/bp-instance-crash-dump-7ccbba7799dc66f9.yaml @ b'30c6f498175112048bef3efdabe6bb979dd694f7'

- A new server action trigger_crash_dump has been added to the REST API in microversion 2.17.

.. releasenotes/notes/bp-rbd-instance-snapshots-130e860b726ddc16.yaml @ b'824c3706a3ea691781f4fcc4453881517a9e1c55'

- When RBD is used for ephemeral disks and image storage, make snapshot use Ceph directly, and update Glance with the new location. In case of failure, it will gracefully fallback to the "generic" snapshot method.  This requires changing the typical permissions for the Nova Ceph user (if using authx) to allow writing to the pool where vm images are stored, and it also requires configuring Glance to provide a v2 endpoint with direct_url support enabled (there are security implications to doing this). See http://docs.ceph.com/docs/master/rbd/rbd-openstack/ for more information on configuring OpenStack with RBD.

.. releasenotes/notes/bp-split-network-plane-for-live-migration-40bc127734173759.yaml @ b'af41accff9456748a3106bc1206cfc22d10a8cf4'

- A new option "live_migration_inbound_addr" has been added
  in the configuration file, set None as default value.
  If this option is present in pre_migration_data, the ip
  address/hostname provided will be used instead of
  the migration target compute node's hostname as the
  uri for live migration, if it's None, then the
  mechanism remains as it is before.

.. releasenotes/notes/bp-virt-driver-cpu-thread-pinning-1aaeeb6648f8e009.yaml @ b'6769460156b3de48093b078a668d94e179ca2d39'

- Added support for CPU thread policies, which can be used to control how the libvirt virt driver places guests with respect to CPU SMT "threads". These are provided as instance and image metadata options, 'hw:cpu_thread_policy' and 'hw_cpu_thread_policy' respectively, and provide an additional level of control over CPU pinning policy, when compared to the existing CPU policy feature. These changes were introduced in commits '83cd67c' and 'aaaba4a'.

.. releasenotes/notes/cinder-backend-report-discard-1def1c28140def9b.yaml @ b'6bc074587a96ca5810ca6674ad0710bcd8de6b58'

- Add support for enabling discard support for block devices with libvirt. This will be enabled for Cinder volume attachments that specify support for the feature in their connection properties. This requires support to be present in the version of libvirt (v1.0.6+) and qemu (v1.6.0+) used along with the configured virtual drivers for the instance. The virtio-blk driver does not support this functionality.

.. releasenotes/notes/compute_upgrade_levels_auto-97acebc7b45b76df.yaml @ b'86fb45c0724ae0afd39a0e44314b74b31327ea63'

- A new ``auto`` value for the configuration option
  ``upgrade_levels.compute`` is accepted, that allows automatic determination
  of the compute service version to use for RPC communication. By default, we
  still use the newest version if not set in the config, a specific version
  if asked, and only do this automatic behavior if 'auto' is
  configured. When 'auto' is used, sending a SIGHUP to the service
  will cause the value to be re-calculated. Thus, after an upgrade
  is complete, sending SIGHUP to all services will cause them to
  start sending messages compliant with the newer RPC version.

.. releasenotes/notes/disco_volume_libvirt_driver-916428b8bd852732.yaml @ b'caac64f1a73aa9cf973e37ce4f4628f55ffa379d'

- Libvirt driver in Nova now supports Cinder DISCO volume driver.

.. releasenotes/notes/disk-weight-scheduler-98647f9c6317d21d.yaml @ b'818c5064a5cad693873254605dfbf45962b317cc'

- A disk space scheduling filter is now available, which prefers compute nodes with the most available disk space.  By default, free disk space is given equal importance to available RAM.  To increase the priority of free disk space in scheduling, increase the disk_weight_multiplier option.

.. releasenotes/notes/force-live-migration-be5a10cd9c8eb981.yaml @ b'c9091d0871948377685feca0eb2e41d8ad38228a'

- A new REST API to force live migration to complete has been added in microversion 2.22.

.. releasenotes/notes/instance-actions-read-deleted-instances-18bbb327924b66c7.yaml @ b'934a0e4ede41a9a132bb22f7f3fcf15f8c72e66b'

- The os-instance-actions methods now read actions from deleted instances. This means that 'GET /v2.1/{tenant-id}/servers/{server-id}/os-instance-actions' and 'GET /v2.1/{tenant-id}/servers/{server-id}/os-instance-actions/{req-id}' will return instance-action items even if the instance corresponding to '{server-id}' has been deleted.

.. releasenotes/notes/instance-hostname-used-to-populate-ports-dns-name-08341ec73dc076c0.yaml @ b'997d8f516cee99b4e16429d13ca5cf7fc05166aa'

- When booting an instance, its sanitized 'hostname' attribute is now used to populate the 'dns_name' attribute of the Neutron ports the instance is attached to. This functionality enables the Neutron internal DNS service to know the ports by the instance's hostname. As a consequence, commands like 'hostname -f' will work as expected when executed in the instance. When a port's network has a non-blank 'dns_domain' attribute, the port's 'dns_name' combined with the network's 'dns_domain' will be published by Neutron in an external DNS as a service like Designate. As a consequence, the instance's hostname is published in the external DNS as a service. This functionality is added to Nova when the 'DNS Integration' extension is enabled in Neutron. The publication of 'dns_name' and 'dns_domain' combinations to an external DNS as a service additionaly requires the configuration of the appropriate driver in Neutron. When the 'Port Binding' extension is also enabled in Neutron, the publication of a 'dns_name' and 'dns_domain' combination to the external DNS as a service will require one additional update operation when Nova allocates the port during the instance boot. This may have a noticeable impact on the performance of the boot process.

.. releasenotes/notes/libvirt-live-migration-new-tunneled-option-d7ebb1eb1e95e683.yaml @ b'621594fc41d0e07fd63dfe7c3c5cfee9edc380ad'

- The libvirt driver now has a live_migration_tunnelled configuration option which should be used where the VIR_MIGRATE_TUNNELLED flag would previously have been set or unset in the live_migration_flag and block_migration_flag configuration options.

.. releasenotes/notes/libvirt_hardware_policy_from_libosinfo-19e261851d1ad93a.yaml @ b'fd34e0cda4a5ef0841e04dee27d0d857167a1076'

- For the libvirt driver, by default hardware properties will be retrieved from the Glance image and if such haven't been provided, it will use a libosinfo database to get those values. If users want to force a specific guest OS ID for the image, they can now use a new glance image property ``os_distro`` (eg. ``--property os_distro=fedora21``). In order to use the libosinfo database, you need to separately install the related native package provided for your operating system distribution.

.. releasenotes/notes/neutron-ovs-bridge-name-7b3477103622f4cc.yaml @ b'e912f5e54785d77b4fabd1113c16b19d0981f003'

- Add support for allowing Neutron to specify the bridge name for the OVS, Linux Bridge, and vhost-user VIF types.

.. releasenotes/notes/online-data-migrations-48dde6a1d8661e47.yaml @ b'c2bd7e4cdcb3c81700977155c93561f50c6b415d'

- Added a `nova-manage db online_data_migrations` command for forcing online data migrations, which will run all registered migrations for the release, instead of there being a separate command for each logical data migration. Operators need to make sure all data is migrated before upgrading to the next release, and the new command provides a unified interface for doing it.

.. releasenotes/notes/optional_project_id-6aebf1cb394d498f.yaml @ b'eea7169474d3cf6b9ac27036ae3ca5a95b461b8d'

- Provides API 2.18, which makes the use of project_ids in API urls optional.

.. releasenotes/notes/parallels_support_snapshot-29b4ffae300c1f05.yaml @ b'f615bfa572ca701259421a053ac4efd48053cc06'

- Libvirt with Virtuozzo virtualisation type now supports snapshot operations

.. releasenotes/notes/remove-on-shared-storage-flag-from-evacuate-api-76a3d58616479fe9.yaml @ b'c01d16e81af6cd9453ffe7133bdc6a4c82e4f6d5'

- Remove ``onSharedStorage`` parameter from server's evacuate action in microversion 2.14. Nova will automatically detect if the instance is on shared storage. Also adminPass is removed from the response body which makes the response body empty. The user can get the password with the server's os-server-password action.

.. releasenotes/notes/server_migrations-30519b35d3ea6763.yaml @ b'98e4a64ad3f1f975e78224d19e729787b902e84c'

- Add two new list/show API for server-migration.
  The list API will return the in progress live migratons
  information of a server. The show API will return
  a specified in progress live migration of a server.
  This has been added in microversion 2.23.

.. releasenotes/notes/service-status-notification-e137297f5d5aa45d.yaml @ b'05adc8d006b482e0aed2fcc9dc4885924aca74d0'

- A new service.status versioned notification has been introduced. When the status of the Service object is changed nova will send a new service.update notification with versioned payload according to bp versioned-notification-api. The new notification is documented in http://docs.openstack.org/developer/nova/notifications.html

.. releasenotes/notes/soft-affinity-for-server-group-f45e191bd8cdbd15.yaml @ b'5dcbc848514adde7d3907e436d8cca08a6ad800a'

- Two new policies soft-affinty and soft-anti-affinity have been implemented for the server-group feature of Nova. This means that POST  /v2.1/{tenant_id}/os-server-groups API resource now accepts 'soft-affinity' and 'soft-anti-affinity' as value of the 'policies' key of the request body.

.. releasenotes/notes/user-settable-server-description-89dcfc75677e31bc.yaml @ b'4841cab03e9b9052b1d8f786fb2d31166dc5e4fd'

- In Nova Compute API microversion 2.19, you can specify a "description" attribute when creating, rebuilding, or updating a server instance.  This description can be retrieved by getting server details, or list details for servers.
  Refer to the Nova Compute API documentation for more information.
  Note that the description attribute existed in prior Nova versions, but was set to the server name by Nova, and was not visible to the user.  So, servers you created with microversions prior to 2.19 will return the description equals the name on server details microversion 2.19.

.. releasenotes/notes/versioned-notifications-423f4d8d2a3992c6.yaml @ b'05adc8d006b482e0aed2fcc9dc4885924aca74d0'

- As part of refactoring the notification interface of Nova a new config option 'notification_format' has been added to specifies which notification format shall be used by nova. The possible values are 'unversioned' (e.g. legacy), 'versioned', 'both'. The default value is 'both'. The new versioned notifications are documented in http://docs.openstack.org/developer/nova/notifications.html

.. releasenotes/notes/vmware_limits-16edee7a9ad023bc.yaml @ b'd0264372fee4fde1fe07852a5835d739ee4c9f9b'

- For the VMware driver, the flavor extra specs for quotas has been extended
  to support:

  - quota:cpu_limit - The cpu of a virtual machine will not
    exceed this limit, even if there are available resources. This is
    typically used to ensure a consistent performance of virtual machines
    independent of available resources. Units are MHz.
  - quota:cpu_reservation - guaranteed minimum reservation (MHz)
  - quota:cpu_shares_level - the allocation level. This can be
    'custom', 'high', 'normal' or 'low'.
  - quota:cpu_shares_share - in the event that 'custom' is used,
    this is the number of shares.
  - quota:memory_limit - The memory utilization of a virtual
    machine will not exceed this limit, even if there are available
    resources. This is typically used to ensure a consistent performance of
    virtual machines independent of available resources. Units are MB.
  - quota:memory_reservation - guaranteed minimum reservation (MB)
  - quota:memory_shares_level - the allocation level. This can be
    'custom', 'high', 'normal' or 'low'.
  - quota:memory_shares_share - in the event that 'custom' is used,
    this is the number of shares.
  - quota:disk_io_limit - The I/O utilization of a virtual machine
    will not exceed this limit. The unit is number of I/O per second.
  - quota:disk_io_reservation - Reservation control is used to
    provide guaranteed allocation in terms of IOPS
  - quota:disk_io_shares_level - the allocation level. This can be
    'custom', 'high', 'normal' or 'low'.
  - quota:disk_io_shares_share - in the event that 'custom' is used,
    this is the number of shares.
  - quota:vif_limit - The bandwidth limit for the virtual network
    adapter. The utilization of the virtual network adapter will not exceed
    this limit, even if there are available resources. Units in Mbits/sec.
  - quota:vif_reservation - Amount of network bandwidth that is
    guaranteed to the virtual network adapter. If utilization is less than
    reservation, the resource can be used by other virtual network adapters.
    Reservation is not allowed to exceed the value of limit if limit is set.
    Units in Mbits/sec.
  - quota:vif_shares_level - the allocation level. This can be
    'custom', 'high', 'normal' or 'low'.
  - quota:vif_shares_share - in the event that 'custom' is used,
    this is the number of shares.


.. _Release Notes_13.0.0_stable_mitaka_Upgrade Notes:

Upgrade Notes
-------------

.. releasenotes/notes/add-novnc-proxy-config-to-vnc-group-f5bb68740f623744.yaml @ b'11a42d40306f56105447a32cc521bb44f6678b59'

- All noVNC proxy configuration options have been added to the 'vnc' group. They should no longer be included in the 'DEFAULT' group.

.. releasenotes/notes/add-xvp-config-to-vnc-group-349cca99f05fcfd3.yaml @ b'e17be81ed87a90dfb28f23f75133d225df3f1acc'

- All VNC XVP configuration options have been added to the 'vnc' group. They should no longer be included in the 'DEFAULT' group.

.. releasenotes/notes/aggregate-uuid-generation-1f029af7a9af519b.yaml @ b'67324e61e052de96e2df8c1f47ea8241730c519a'

- Upon first startup of the scheduler service in Mitaka, all defined aggregates will have UUIDs generated and saved back to the database. If you have a significant number of aggregates, this may delay scheduler start as that work is completed, but it should be minor for most deployments.

.. releasenotes/notes/api-database-now-required-6245f39d36885d1c.yaml @ b'7b1fb84f68bbcef0c496d3990e5d6b99a5360bc8'

- During an upgrade to Mitaka, operators must create and initialize a database for the API service. Configure this in [api_database]/connection, and then run ``nova-manage api_db sync``

.. releasenotes/notes/bp-making-live-migration-api-friendly-3b547f4e0958ee05.yaml @ b'f18a46c072b964b6c9ceffc9832e4221f64dc9c4'

- We can not use microversion 2.25 to do live-migration during upgrade, nova-api will raise bad request if there is still old compute node in the cluster.

.. releasenotes/notes/config_scheduler_driver-e751ae392bc1a1d0.yaml @ b'33d906a2e060447778e95449a78e6583f18afcfd'

- The option ``scheduler_driver`` is now changed to use entrypoint instead of
  full class path. Set one of the entrypoints under the namespace
  'nova.scheduler.driver' in 'setup.cfg'. Its default value is
  'host_manager'. The full class path style is still supported in current
  release. But it is not recommended because class path can be changed and
  this support will be dropped in the next major release.

.. releasenotes/notes/config_scheduler_host_manager_driver-a543a74ea70f5e90.yaml @ b'158c6d64c2da48ec5fb3382eb64cd5c5e9c5c2d9'

- The option ``scheduler_host_manager`` is now changed to use entrypoint
  instead of full class path. Set one of the entrypoints under the namespace
  'nova.scheduler.host_manager' in 'setup.cfg'. Its default value is
  'host_manager'. The full class path style is still supported in current
  release. But it is not recommended because class path can be changed and
  this support will be dropped in the next major release.

.. releasenotes/notes/deprecate-local-conductor-9cb9f45728281eb0.yaml @ b'a067a4c9be524c90677f511c96764ab327a4da4c'

- The local conductor mode is now deprecated and may be removed as early as
  the 14.0.0 release.
  If you are using local conductor mode, plan on deploying remote conductor
  by the time you upgrade to the 14.0.0 release.

.. releasenotes/notes/deprecate_ert-449b16638c008457.yaml @ b'2274fd1f87ff8cc0cb3ce49aa40aee0018e5d1dd'

- The Extensible Resource Tracker is deprecated and will be removed in the
  14.0.0 release.
  If you use this functionality and have custom resources that are managed
  by the Extensible Resource Tracker, please contact the Nova development
  team by posting to the openstack-dev mailing list.
  There is no future planned support for the tracking of custom resources.

.. releasenotes/notes/disk_ratio_to_rt-b6224ab8c0272d86.yaml @ b'ad6654eaa7c44267ae3a4952a8359459fbec4c0c'

- For Liberty compute nodes, the disk_allocation_ratio works as before, you must set it on the scheduler if you want to change it. For Mitaka compute nodes, the disk_allocation_ratio set on the compute nodes will be used only if the configuration is not set on the scheduler. This is to allow, for backwards compatibility, the ability to still override the disk allocation ratio by setting the configuration on the scheduler node. In Newton, we plan to remove the ability to set the disk allocation ratio on the scheduler, at which point the compute nodes will always define the disk allocation ratio, and pass that up to the scheduler. None of this changes the default disk allocation ratio of 1.0. This matches the behaviour of the RAM and CPU allocation ratios.

.. releasenotes/notes/drop_instancev1_obj-4447ddd2bea644fa.yaml @ b'ae57abf3015b29294b429997db5a9261fdaf301e'

- (Only if you do continuous deployment)
  1337890ace918fa2555046c01c8624be014ce2d8 drops support for an instance
  major version, which means that you must have deployed at least commit
  713d8cb0777afb9fe4f665b9a40cac894b04aacb before deploying this one.

.. releasenotes/notes/ebtables-version-fde659fe18b0e0c0.yaml @ b'9f3d8e62ed24659105a8e86c511928f1805325cd'

- nova now requires ebtables 2.0.10 or later

.. releasenotes/notes/ebtables-version-fde659fe18b0e0c0.yaml @ b'9f3d8e62ed24659105a8e86c511928f1805325cd'

- nova recommends libvirt 1.2.11 or later

.. releasenotes/notes/filters_use_reqspec-9f92b9c0ead76093.yaml @ b'aeae7040c7b4533fd4d5521d4c5172cb2fb598e7'

- Filters internal interface changed using now the RequestSpec NovaObject
  instead of an old filter_properties dictionary.
  In case you run out-of-tree filters, you need to modify the host_passes()
  method to accept a new RequestSpec object and modify the filter internals
  to use that new object. You can see other in-tree filters for getting the
  logic or ask for help in #openstack-nova IRC channel.

.. releasenotes/notes/force_config_drive_opt-e087055e14c40d88.yaml @ b'2941d88ef28166cd0ebd677c4de8176e1befe044'

- The ``force_config_drive`` configuration option provided an ``always``
  value which was deprecated in the previous release. That ``always`` value
  is now no longer accepted and deployments using that value have to change
  it to ``True`` before upgrading.

.. releasenotes/notes/hyperv_2k8_drop-fb309f811767c7c4.yaml @ b'c3628d7a91bcab14ed795f8b89c9afc6ed15abe5'

- Support for Windows / Hyper-V Server 2008 R2 has been deprecated in Liberty (12.0.0) and it is no longer supported in Mitaka (13.0.0). If you have compute nodes running that version, please consider moving the running instances to other compute nodes before upgrading those to Mitaka.

.. releasenotes/notes/libvirt-live-migration-flags-mangling-a2407a31ddf17427.yaml @ b'3fd24ba528314b45fe5f91110638ada7bf7fcb96'

- The libvirt driver will now correct unsafe and invalid values for the live_migration_flag and block_migration_flag configuration options. The live_migration_flag must not contain VIR_MIGRATE_SHARED_INC but block_migration_flag must contain it. Both options must contain the VIR_MIGRATE_PEER2PEER, except when using the 'xen' virt type this flag is not supported. Both flags must contain the VIR_MIGRATE_UNDEFINE_SOURCE flag and not contain the VIR_MIGRATE_PERSIST_DEST flag.

.. releasenotes/notes/live_migration_uri-dependent-on-virt_type-595c46c2310f45c3.yaml @ b'3159c8fd5bea80c820e58bd38d96f5f8fe8f4503'

- The libvirt driver has changed the default value of the 'live_migration_uri' flag, that now is dependent on the 'virt_type'. The old default 'qemu+tcp://%s/system' now is adjusted for each of the configured hypervisors. For Xen this will be 'xenmigr://%s/system', for kvm/qemu this will be 'qemu+tcp://%s/system'.

.. releasenotes/notes/min_libvirt_bump-d9916d9c4512dd11.yaml @ b'5a359a3d241bf33dd8dd30c4b554240e2a88c9af'

- The minimum required libvirt is now version 0.10.2. The minimum libvirt for the N release has been set to 1.2.1.

.. releasenotes/notes/optional_project_id-6aebf1cb394d498f.yaml @ b'eea7169474d3cf6b9ac27036ae3ca5a95b461b8d'

- In order to make project_id optional in urls, we must constrain the set of allowed values for project_id in our urls. This defaults to a regex of ``[0-9a-f\-]+``, which will match hex uuids (with / without dashes), and integers. This covers all known project_id formats in the wild.
  If your site uses other values for project_id, you can set a site specific validation with ``project_id_regex`` config variable.

.. releasenotes/notes/remove-deprecated-neutron-options-5f3a782aa9082fb5.yaml @ b'a67394a05872c89699487fc3e1e6a1801a7714c2'

- The old neutron communication options that were slated for removal in Mitaka are no longer available. This means that going forward communication to neutron will need to be configured using auth plugins.

.. releasenotes/notes/remove_ec2_and_objectstore_api-4ccb539db1d171fa.yaml @ b'c711c6519a9dd97fd23a9d5417f99334bfdd16a5'

- All code and tests for Nova's EC2 and ObjectStore API support which
  was deprecated in Kilo
  (https://wiki.openstack.org/wiki/ReleaseNotes/Kilo#Upgrade_Notes_2) has
  been completely removed in Mitaka. This has been replaced by the new
  ec2-api project (http://opendev.org/openstack/ec2-api/).

  .. warning:: Some installation tools (such as ``packstack``) hardcode the
    value of ``enabled_apis`` in your nova.conf. While the defaults
    for ``enabled_apis`` dropped ``ec2`` as a value, if that is hard
    coded in your nova.conf, you will need to remove it before
    restarting Nova's API server, or it will not start.

.. releasenotes/notes/request-spec-api-db-b9cc6e0624d563c5.yaml @ b'8e8e839ef748be242fd0ad02e3ae233cc98da8b2'

- The commit with change-id Idd4bbbe8eea68b9e538fa1567efd304e9115a02a
  requires that the nova_api database is setup and Nova is configured to use
  it.  Instructions on doing that are provided below.

  Nova now requires that two databases are available and configured.  The
  existing nova database needs no changes, but a new nova_api database needs
  to be setup.  It is configured and managed very similarly to the nova
  database.  A new connection string configuration option is available in the
  api_database group.  An example::

      [api_database]
      connection = mysql+pymysql://user:secret@127.0.0.1/nova_api?charset=utf8

  And a new nova-manage command has been added to manage db migrations for
  this database.  "nova-manage api_db sync" and "nova-manage api_db version"
  are available and function like the parallel "nova-manage db ..." version.

.. releasenotes/notes/rm_volume_manager-78fed5be43d285b3.yaml @ b'6e8e322718529e50bf2035507b970058ddaa836a'

- A new ``use_neutron`` option is introduced which replaces the obtuse ``network_api_class`` option. This defaults to 'False' to match existing defaults, however if ``network_api_class`` is set to the known Neutron value Neutron networking will still be used as before.

.. releasenotes/notes/scheduling-to-disabled-hosts-79f5b5d20a42875a.yaml @ b'214b7550bca6b78c99660f257fc63d6ea4ccf212'

- The FilterScheduler is now including disabled hosts. Make sure you include the ComputeFilter in the ``scheduler_default_filters`` config option to avoid placing instances on disabled hosts.

.. releasenotes/notes/upgrade_rootwrap_compute_filters-428ca239f2e4e63d.yaml @ b'ec9d5e375e208686d33b9259b039cc009bded42e'

- Upgrade the rootwrap configuration for the compute service, so that patches requiring new rootwrap configuration can be tested with grenade.

.. releasenotes/notes/vmware_integration_bridge-249567087da5ecb2.yaml @ b'0c04dffcc43a3fa8eb32cd8ec09e703615bbd1b2'

- For backward compatible support the setting ``CONF.vmware.integration_bridge`` needs to be set when using the Neutron NSX|MH plugin. The default value has been set to ``None``.

.. releasenotes/notes/xen_rename-03edd9b78f3e81e5.yaml @ b'd8410950e130d09cd86a73da27e1305c0c3a9662'

- XenServer hypervisor type has been changed from ``xen`` to ``XenServer``. It could impact your aggregate metadata or your flavor extra specs if you provide only the former.

.. releasenotes/notes/xenserver-glance-plugin-1.3-11c3b70b8c928263.yaml @ b'89de4ed5e94620f7ca3716a888d7e26a0d23e98f'

- The glance xenserver plugin has been bumped to version 1.3 which includes new interfaces for referencing glance servers by url. All dom0 will need to be upgraded with this plugin before upgrading the nova code.


.. _Release Notes_13.0.0_stable_mitaka_Deprecation Notes:

Deprecation Notes
-----------------

.. releasenotes/notes/api_servers_no_scheme-e4aa216d251022f2.yaml @ b'1c18f1838526de11ddd2ab42b4a49ab8df2ee8d1'

- It is now deprecated to use [glance] api_servers without a protocol scheme (http / https). This is required to support urls throughout the system. Update any api_servers list with fully qualified https / http urls.

.. releasenotes/notes/deprecate-conductor-manager-class-03620676d939b0eb.yaml @ b'e683c41521647d1c67bbdeb9c7e126c603676fb4'

- The conductor.manager configuration option is now deprecated and will be removed.

.. releasenotes/notes/deprecate_compute_stats_class-229abfcb8816bdbd.yaml @ b'3be36fcb7bdc0f48eae06f5378f3ba2e4a4975bd'

- Deprecate ``compute_stats_class`` config option. This allowed loading an alternate implementation for collecting statistics for the local compute host. Deployments that felt the need to use this facility are encoraged to propose additions upstream so we can create a stable and supported interface here.

.. releasenotes/notes/deprecate_db_driver-91c76ca8011d663c.yaml @ b'c87ae92be56fa7f0f75749df5b8cbd527f539dcf'

- Deprecate the ``db_driver`` config option. Previously this let you replace our SQLAlchemy database layer with your own. This approach is deprecated. Deployments that felt the need to use the facility are encourage to work with upstream Nova to address db driver concerns in the main SQLAlchemy code paths.

.. releasenotes/notes/deprecate_glance_opts-eab01aba5dcda38a.yaml @ b'26262b7943542e8b2ffe93db165977e9f58da5a2'

- The host, port, and protocol options in the [glance] configuration section are deprecated, and will be removed in the N release. The api_servers value should be used instead.

.. releasenotes/notes/deprecate_hooks-6f6d60ac206a6da6.yaml @ b'7be56442703d071c9256267abb8acfabae642a1a'

- Deprecate the use of nova.hooks. This facility used to let arbitrary out of tree code be executed around certain internal actions, but is unsuitable for having a well maintained API. Anyone using this facility should bring forward their use cases in the Newton cycle as nova-specs.

.. releasenotes/notes/deprecate_pluggable_managers-ca0224bcd779454c.yaml @ b'7b1fb84f68bbcef0c496d3990e5d6b99a5360bc8'

- Nova used to support the concept that ``service managers`` were
  replaceable components. There are many config options where you can
  replace a manager by specifying a new class. This concept is
  deprecated in Mitaka as are the following config options.

    * [cells] manager
    * metadata_manager
    * compute_manager
    * console_manager
    * consoleauth_manager
    * cert_manager
    * scheduler_manager

  Many of these will be removed in Newton. Users of these options
  are encouraged to work with Nova upstream on any features missing
  in the default implementations that are needed.

.. releasenotes/notes/deprecate_security_group_api-3d96d683a3723e2c.yaml @ b'ef957eedde019f255ce363d71a644604cca8d8df'

- Deprecate ``security_group_api`` configuration option. The current values are ``nova`` and ``neutron``. In future the correct security_group_api option will be chosen based on the value of ``use_neutron`` which provides a more coherent user experience.

.. releasenotes/notes/deprecate_vendordata_driver-eefc745365a881c3.yaml @ b'21da1babce0a3f6a2e8e2b802e9cc0e8f491526b'

- Deprecate the ``vendordata_driver`` config option. This allowed creating a different class loader for defining vendordata metadata. The default driver loads from a json file that can be arbitrarily specified, so is still quite flexible. Deployments that felt the need to use this facility are encoraged to propose additions upstream so we can create a stable and supported interface here.

.. releasenotes/notes/ironic_api_version_opt_deprecated-50c9b0486e78fe6e.yaml @ b'05df44f2413e400b005abeab117afde3b3521c65'

- The configuration option ``api_version`` in the ``ironic`` group was marked as deprecated and will be removed in the future. The only possible value for that configuration was "1" (because Ironic only has 1 API version) and the Ironic team came to an agreement that setting the API version via configuration option should not be supported anymore. As the Ironic driver in Nova requests the Ironic v1.8 API, that means that Nova 13.0.0 ("Mitaka") requires Ironic 4.0.0 ("Liberty") or newer if you want to use the Ironic driver.

.. releasenotes/notes/libvirt-deprecate-migration-flags-config-4ba1e2d6c9ef09ff.yaml @ b'89dcf9d1d487b489b5c29301c57efced4538be25'

- The libvirt live_migration_flag and block_migration_flag
  config options are deprecated. These options gave too
  fine grained control over the flags used and, in some
  cases, misconfigurations could have dangerous side
  effects. Please note the availability of a new
  live_migration_tunnelled configuration option.

.. releasenotes/notes/neutron-mtu-6a7edd9e396107d7.yaml @ b'b3c64d1c64faf933243b53275d5e63e7e2e0fecb'

- The ``network_device_mtu`` option in Nova is deprecated for removal since network MTU should be specified when creating the network with nova-network. With Neutron networks, the MTU value comes from the ``segment_mtu`` configuration option in Neutron.

.. releasenotes/notes/os-migrations-ef225e5b309d5497.yaml @ b'98e4a64ad3f1f975e78224d19e729787b902e84c'

- The old top-level resource `/os-migrations` is deprecated, it won't be extended anymore. And migration_type for /os-migrations, also add ref link to the /servers/{uuid}/migrations/{id} for it when the migration is an in-progress live-migration. This has been added in microversion 2.23.

.. releasenotes/notes/rm_volume_manager-78fed5be43d285b3.yaml @ b'6e8e322718529e50bf2035507b970058ddaa836a'

- Deprecate ``volume_api_class`` and ``network_api_class`` config options. We only have one sensible backend for either of these. These options will be removed and turned into constants in Newton.

.. releasenotes/notes/switch-to-oslo-cache-7114a0ab2dea52df.yaml @ b'205fb7c8b34e521bdc14b5c3698d1597753b27d4'

- Option ``memcached_servers`` is deprecated in Mitaka. Operators should use oslo.cache configuration instead. Specifically ``enabled`` option under [cache] section should be set to True and the url(s) for the memcached servers should be in [cache]/memcache_servers option.

.. releasenotes/notes/zookeeper-servicegroup-driver-removed-c3bcaa6f9fe976ed.yaml @ b'7b1fb84f68bbcef0c496d3990e5d6b99a5360bc8'

- The Zookeeper Service Group driver has been removed.

  The driver has no known users and is not actively mantained. A warning log
  message about the driver's state was added for the Kilo release. Also,
  evzookeeper library that the driver depends on is unmaintained and
  `incompatible with recent eventlet releases`_.

  A future release of Nova will `use the Tooz library to track
  service liveliness`_, and Tooz supports Zookeeper.

  .. _`incompatible with recent eventlet releases`: https://bugs.launchpad.net/nova/+bug/1443910
  .. _`use the Tooz library to track service liveliness`: http://specs.openstack.org/openstack/nova-specs/specs/liberty/approved/service-group-using-tooz.html


.. _Release Notes_13.0.0_stable_mitaka_Security Issues:

Security Issues
---------------

.. releasenotes/notes/13.0.0-cve-bugs-fe43ef267a82f304.yaml @ b'9c0bbda07fdcf134308371644d09becbb18c62b1'

- [OSSA 2016-001] Nova host data leak through snapshot (CVE-2015-7548)

  * `Bug 1524274 <https://bugs.launchpad.net/nova/+bug/1524274>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-January/000911.html>`__

  [OSSA 2016-002] Xen connection password leak in logs via StorageError (CVE-2015-8749)

  * `Bug 1516765 <https://bugs.launchpad.net/nova/+bug/1516765>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-January/000916.html>`__

  [OSSA 2016-007] Host data leak during resize/migrate for raw-backed instances  (CVE-2016-2140)

  * `Bug 1548450 <https://bugs.launchpad.net/nova/+bug/1548450>`_
  * `Announcement <http://lists.openstack.org/pipermail/openstack-announce/2016-March/001009.html>`__


.. _Release Notes_13.0.0_stable_mitaka_Bug Fixes:

Bug Fixes
---------

.. releasenotes/notes/upgrade_rootwrap_compute_filters-428ca239f2e4e63d.yaml @ b'ec9d5e375e208686d33b9259b039cc009bded42e'

- In a race condition if base image is deleted by ImageCacheManager while imagebackend is copying the image to instance path, then the instance goes in to error state. In this case when libvirt has changed the base file ownership to libvirt-qemu while imagebackend is copying the image, then we get permission denied error on updating the file access time using os.utime. Fixed this issue by updating the base file access time with root user privileges using 'touch' command.

.. releasenotes/notes/vhost-user-mtu-23d0af36a8adfa56.yaml @ b'c7eb823fe73e3db5dca48df5879db18cbab5bd8d'

- When plugging virtual interfaces of type vhost-user the MTU value will not be applied to the interface by nova. vhost-user ports exist only in userspace and are not backed by kernel netdevs, for this reason it is not possible to set the mtu on a vhost-user interface using standard tools such as ifconfig or ip link.


.. _Release Notes_13.0.0_stable_mitaka_Other Notes:

Other Notes
-----------

.. releasenotes/notes/conductor_rpcapi_v2_drop-9893c27bb32d9786.yaml @ b'116cd3c0916630b53b31ee7494f412ac7a17fafb'

- Conductor RPC API no longer supports v2.x.

.. releasenotes/notes/deprecate-nova-manage-service-subcommand-7626f7692bd62e41.yaml @ b'df840b34570022c5e9f1c6024cbd895f43eac1ff'

- The service subcommand of nova-manage is deprecated. Use the nova service-* commands from python-novaclient instead or the os-services REST resource. The service subcommand will be removed in the 14.0 release.

.. releasenotes/notes/neutron-mtu-6a7edd9e396107d7.yaml @ b'b3c64d1c64faf933243b53275d5e63e7e2e0fecb'

- The Neutron network MTU value is now used when plugging virtual interfaces in nova-compute. If the value is 0, which is the default value for the ``segment_mtu`` configuration option in Neutron before Mitaka, then the (deprecated) ``network_device_mtu`` configuration option in Nova is used, which defaults to not setting an MTU value.

.. releasenotes/notes/policy-sample-defaults-changed-b5eea1daeb305251.yaml @ b'83467b8c68607d2f7551eaf283a354e1b0bb27fa'

- The sample policy file shipped with Nova contained many policies set to ""(allow all) which was not the proper default for many of those checks. It was also a source of confusion as some people thought "" meant to use the default rule. These empty policies have been updated to be explicit in all cases.
  Many of them were changed to match the default rule of "admin_or_owner" which is a more restrictive policy check but does not change the restrictiveness of the API calls overall because there are similar checks in the database already.
  This does not affect any existing deployment, just the sample file included for use by new deployments.

.. releasenotes/notes/remove-ec2-api-service-c17a35ed297355b8.yaml @ b'eec7a55319b3f22949735227199ce49b851519b8'

- Nova's EC2 API support which was deprecated in Kilo (https://wiki.openstack.org/wiki/ReleaseNotes/Kilo#Upgrade_Notes_2) is removed from Mitaka. This has been replaced by the new ec2-api project (http://opendev.org/openstack/ec2-api/).


