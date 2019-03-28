# needs:check_deprecation_status

# Copyright 2015 Huawei Technology corp.
# Copyright 2015 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import socket

from oslo_config import cfg
from oslo_config import types

from nova.conf import paths

compute_group = cfg.OptGroup(
    'compute',
    title='Compute Manager Options',
    help="""
A collection of options specific to the nova-compute service.
""")
compute_opts = [
    cfg.StrOpt('compute_driver',
        help="""
Defines which driver to use for controlling virtualization.

Possible values:

* ``libvirt.LibvirtDriver``
* ``xenapi.XenAPIDriver``
* ``fake.FakeDriver``
* ``ironic.IronicDriver``
* ``vmwareapi.VMwareVCDriver``
* ``hyperv.HyperVDriver``
"""),
    cfg.BoolOpt('allow_resize_to_same_host',
        default=False,
        help="""
Allow destination machine to match source for resize. Useful when
testing in single-host environments. By default it is not allowed
to resize to the same host. Setting this option to true will add
the same host to the destination options. Also set to true
if you allow the ServerGroupAffinityFilter and need to resize.
"""),
    cfg.ListOpt('non_inheritable_image_properties',
        default=['cache_in_nova', 'bittorrent',
                 'img_signature_hash_method', 'img_signature',
                 'img_signature_key_type', 'img_signature_certificate_uuid'],
        help="""
Image properties that should not be inherited from the instance
when taking a snapshot.

This option gives an opportunity to select which image-properties
should not be inherited by newly created snapshots.

Possible values:

* A list whose item is an image property. Usually only the image
  properties that are only needed by base images can be included
  here, since the snapshots that are created from the base images
  doesn't need them.
* Default list: cache_in_nova, bittorrent, img_signature_hash_method,
                img_signature, img_signature_key_type,
                img_signature_certificate_uuid
"""),
    cfg.StrOpt('null_kernel',
        default='nokernel',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
When an image is booted with the property 'kernel_id' with the value
'nokernel', Nova assumes the image doesn't require an external kernel and
ramdisk. This option allows user to change the API behaviour which should not
be allowed and this value "nokernel" should be hard coded.
""",
        help="""
This option is used to decide when an image should have no external
ramdisk or kernel. By default this is set to 'nokernel', so when an
image is booted with the property 'kernel_id' with the value
'nokernel', Nova assumes the image doesn't require an external kernel
and ramdisk.
"""),
    cfg.StrOpt('multi_instance_display_name_template',
        default='%(name)s-%(count)d',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
This config changes API behaviour. All changes in API behaviour should be
discoverable.
""",
        help="""
When creating multiple instances with a single request using the
os-multiple-create API extension, this template will be used to build
the display name for each instance. The benefit is that the instances
end up with different hostnames. Example display names when creating
two VM's: name-1, name-2.

Possible values:

* Valid keys for the template are: name, uuid, count.
"""),
    cfg.IntOpt('max_local_block_devices',
        default=3,
        help="""
Maximum number of devices that will result in a local image being
created on the hypervisor node.

A negative number means unlimited. Setting max_local_block_devices
to 0 means that any request that attempts to create a local disk
will fail. This option is meant to limit the number of local discs
(so root local disc that is the result of --image being used, and
any other ephemeral and swap disks). 0 does not mean that images
will be automatically converted to volumes and boot instances from
volumes - it just means that all requests that attempt to create a
local disk will fail.

Possible values:

* 0: Creating a local disk is not allowed.
* Negative number: Allows unlimited number of local discs.
* Positive number: Allows only these many number of local discs.
                       (Default value is 3).
"""),
    cfg.ListOpt('compute_monitors',
        default=[],
        help="""
A list of monitors that can be used for getting compute metrics.
You can use the alias/name from the setuptools entry points for
nova.compute.monitors.* namespaces. If no namespace is supplied,
the "cpu." namespace is assumed for backwards-compatibility.

Possible values:

* An empty list will disable the feature(Default).
* An example value that would enable both the CPU and NUMA memory
  bandwidth monitors that used the virt driver variant:
  ["cpu.virt_driver", "numa_mem_bw.virt_driver"]
"""),
    cfg.StrOpt('default_ephemeral_format',
        help="""
The default format an ephemeral_volume will be formatted with on creation.

Possible values:

* ``ext2``
* ``ext3``
* ``ext4``
* ``xfs``
* ``ntfs`` (only for Windows guests)
"""),
    cfg.BoolOpt('vif_plugging_is_fatal',
        default=True,
        help="""
Determine if instance should boot or fail on VIF plugging timeout.

Nova sends a port update to Neutron after an instance has been scheduled,
providing Neutron with the necessary information to finish setup of the port.
Once completed, Neutron notifies Nova that it has finished setting up the
port, at which point Nova resumes the boot of the instance since network
connectivity is now supposed to be present. A timeout will occur if the reply
is not received after a given interval.

This option determines what Nova does when the VIF plugging timeout event
happens. When enabled, the instance will error out. When disabled, the
instance will continue to boot on the assumption that the port is ready.

Possible values:

* True: Instances should fail after VIF plugging timeout
* False: Instances should continue booting after VIF plugging timeout
"""),
    cfg.IntOpt('vif_plugging_timeout',
        default=300,
        min=0,
        help="""
Timeout for Neutron VIF plugging event message arrival.

Number of seconds to wait for Neutron vif plugging events to
arrive before continuing or failing (see 'vif_plugging_is_fatal').

Related options:

* vif_plugging_is_fatal - If ``vif_plugging_timeout`` is set to zero and
  ``vif_plugging_is_fatal`` is False, events should not be expected to
  arrive at all.
"""),
    cfg.StrOpt('injected_network_template',
        default=paths.basedir_def('nova/virt/interfaces.template'),
        help="""Path to '/etc/network/interfaces' template.

The path to a template file for the '/etc/network/interfaces'-style file, which
will be populated by nova and subsequently used by cloudinit. This provides a
method to configure network connectivity in environments without a DHCP server.

The template will be rendered using Jinja2 template engine, and receive a
top-level key called ``interfaces``. This key will contain a list of
dictionaries, one for each interface.

Refer to the cloudinit documentaion for more information:

  https://cloudinit.readthedocs.io/en/latest/topics/datasources.html

Possible values:

* A path to a Jinja2-formatted template for a Debian '/etc/network/interfaces'
  file. This applies even if using a non Debian-derived guest.

Related options:

* ``flat_inject``: This must be set to ``True`` to ensure nova embeds network
  configuration information in the metadata provided through the config drive.
"""),
    cfg.StrOpt('preallocate_images',
        default='none',
        choices=('none', 'space'),
        help="""
The image preallocation mode to use.

Image preallocation allows storage for instance images to be allocated up front
when the instance is initially provisioned. This ensures immediate feedback is
given if enough space isn't available. In addition, it should significantly
improve performance on writes to new blocks and may even improve I/O
performance to prewritten blocks due to reduced fragmentation.

Possible values:

* "none"  => no storage provisioning is done up front
* "space" => storage is fully allocated at instance start
"""),
    cfg.BoolOpt('use_cow_images',
        default=True,
        help="""
Enable use of copy-on-write (cow) images.

QEMU/KVM allow the use of qcow2 as backing files. By disabling this,
backing files will not be used.
"""),
    cfg.BoolOpt('force_raw_images',
        default=True,
        help="""
Force conversion of backing images to raw format.

Possible values:

* True: Backing image files will be converted to raw image format
* False: Backing image files will not be converted

Related options:

* ``compute_driver``: Only the libvirt driver uses this option.
"""),
# NOTE(yamahata): ListOpt won't work because the command may include a comma.
# For example:
#
#     mkfs.ext4 -O dir_index,extent -E stride=8,stripe-width=16
#       --label %(fs_label)s %(target)s
#
# list arguments are comma separated and there is no way to escape such
# commas.
    cfg.MultiStrOpt('virt_mkfs',
        default=[],
        help="""
Name of the mkfs commands for ephemeral device.

The format is <os_type>=<mkfs command>
"""),
    cfg.BoolOpt('resize_fs_using_block_device',
        default=False,
        help="""
Enable resizing of filesystems via a block device.

If enabled, attempt to resize the filesystem by accessing the image over a
block device. This is done by the host and may not be necessary if the image
contains a recent version of cloud-init. Possible mechanisms require the nbd
driver (for qcow and raw), or loop (for raw).
"""),
    cfg.IntOpt('timeout_nbd',
        default=10,
        min=0,
        help='Amount of time, in seconds, to wait for NBD device start up.'),
    cfg.StrOpt('image_cache_subdirectory_name',
        default='_base',
        help="""
Location of cached images.

This is NOT the full path - just a folder name relative to '$instances_path'.
For per-compute-host cached images, set to '_base_$my_ip'
"""),
    cfg.BoolOpt('remove_unused_base_images',
        default=True,
        help='Should unused base images be removed?'),
    cfg.IntOpt('remove_unused_original_minimum_age_seconds',
        default=(24 * 3600),
        help="""
Unused unresized base images younger than this will not be removed.
"""),
    cfg.StrOpt('pointer_model',
        default='usbtablet',
        choices=[None, 'ps2mouse', 'usbtablet'],
        help="""
Generic property to specify the pointer type.

Input devices allow interaction with a graphical framebuffer. For
example to provide a graphic tablet for absolute cursor movement.

If set, the 'hw_pointer_model' image property takes precedence over
this configuration option.

Possible values:

* None: Uses default behavior provided by drivers (mouse on PS2 for
        libvirt x86)
* ps2mouse: Uses relative movement. Mouse connected by PS2
* usbtablet: Uses absolute movement. Tablet connect by USB

Related options:

* usbtablet must be configured with VNC enabled or SPICE enabled and SPICE
  agent disabled. When used with libvirt the instance mode should be
  configured as HVM.
 """),
]

resource_tracker_opts = [
    cfg.StrOpt('vcpu_pin_set',
        help="""
Defines which physical CPUs (pCPUs) can be used by instance
virtual CPUs (vCPUs).

Possible values:

* A comma-separated list of physical CPU numbers that virtual CPUs can be
  allocated to by default. Each element should be either a single CPU number,
  a range of CPU numbers, or a caret followed by a CPU number to be
  excluded from a previous range. For example:

    vcpu_pin_set = "4-12,^8,15"
"""),
    cfg.MultiOpt('reserved_huge_pages',
        item_type=types.Dict(),
        help="""
Number of huge/large memory pages to reserved per NUMA host cell.

Possible values:

* A list of valid key=value which reflect NUMA node ID, page size
  (Default unit is KiB) and number of pages to be reserved.

    reserved_huge_pages = node:0,size:2048,count:64
    reserved_huge_pages = node:1,size:1GB,count:1

  In this example we are reserving on NUMA node 0 64 pages of 2MiB
  and on NUMA node 1 1 page of 1GiB.
"""),
    cfg.IntOpt('reserved_host_disk_mb',
        min=0,
        default=0,
        help="""
Amount of disk resources in MB to make them always available to host. The
disk usage gets reported back to the scheduler from nova-compute running
on the compute nodes. To prevent the disk resources from being considered
as available, this option can be used to reserve disk space for that host.

Possible values:

* Any positive integer representing amount of disk in MB to reserve
  for the host.
"""),
    cfg.IntOpt('reserved_host_memory_mb',
        default=512,
        min=0,
        help="""
Amount of memory in MB to reserve for the host so that it is always available
to host processes. The host resources usage is reported back to the scheduler
continuously from nova-compute running on the compute node. To prevent the host
memory from being considered as available, this option is used to reserve
memory for the host.

Possible values:

* Any positive integer representing amount of memory in MB to reserve
  for the host.
"""),
    cfg.IntOpt('reserved_host_cpus',
        default=0,
        min=0,
        help="""
Number of physical CPUs to reserve for the host. The host resources usage is
reported back to the scheduler continuously from nova-compute running on the
compute node. To prevent the host CPU from being considered as available,
this option is used to reserve random pCPU(s) for the host.

Possible values:

* Any positive integer representing number of physical CPUs to reserve
  for the host.
"""),
]

allocation_ratio_opts = [
    cfg.FloatOpt('cpu_allocation_ratio',
        default=0.0,
        min=0.0,
        help="""
This option helps you specify virtual CPU to physical CPU allocation ratio.

From Ocata (15.0.0) this is used to influence the hosts selected by
the Placement API. Note that when Placement is used, the CoreFilter
is redundant, because the Placement API will have already filtered
out hosts that would have failed the CoreFilter.

This configuration specifies ratio for CoreFilter which can be set
per compute node. For AggregateCoreFilter, it will fall back to this
configuration value if no per-aggregate setting is found.

NOTE: This can be set per-compute, or if set to 0.0, the value
set on the scheduler node(s) or compute node(s) will be used
and defaulted to 16.0. Once set to a non-default value, it is not possible
to "unset" the config to get back to the default behavior. If you want
to reset back to the default, explicitly specify 16.0.

NOTE: As of the 16.0.0 Pike release, this configuration option is ignored
for the ironic.IronicDriver compute driver and is hardcoded to 1.0.

Possible values:

* Any valid positive integer or float value
"""),
    cfg.FloatOpt('ram_allocation_ratio',
        default=0.0,
        min=0.0,
        help="""
This option helps you specify virtual RAM to physical RAM
allocation ratio.

From Ocata (15.0.0) this is used to influence the hosts selected by
the Placement API. Note that when Placement is used, the RamFilter
is redundant, because the Placement API will have already filtered
out hosts that would have failed the RamFilter.

This configuration specifies ratio for RamFilter which can be set
per compute node. For AggregateRamFilter, it will fall back to this
configuration value if no per-aggregate setting found.

NOTE: This can be set per-compute, or if set to 0.0, the value
set on the scheduler node(s) or compute node(s) will be used and
defaulted to 1.5. Once set to a non-default value, it is not possible
to "unset" the config to get back to the default behavior. If you want
to reset back to the default, explicitly specify 1.5.

NOTE: As of the 16.0.0 Pike release, this configuration option is ignored
for the ironic.IronicDriver compute driver and is hardcoded to 1.0.

Possible values:

* Any valid positive integer or float value
"""),
    cfg.FloatOpt('disk_allocation_ratio',
        default=0.0,
        min=0.0,
        help="""
This option helps you specify virtual disk to physical disk
allocation ratio.

From Ocata (15.0.0) this is used to influence the hosts selected by
the Placement API. Note that when Placement is used, the DiskFilter
is redundant, because the Placement API will have already filtered
out hosts that would have failed the DiskFilter.

A ratio greater than 1.0 will result in over-subscription of the
available physical disk, which can be useful for more
efficiently packing instances created with images that do not
use the entire virtual disk, such as sparse or compressed
images. It can be set to a value between 0.0 and 1.0 in order
to preserve a percentage of the disk for uses other than
instances.

NOTE: This can be set per-compute, or if set to 0.0, the value
set on the scheduler node(s) or compute node(s) will be used and
defaulted to 1.0. Once set to a non-default value, it is not possible
to "unset" the config to get back to the default behavior. If you want
to reset back to the default, explicitly specify 1.0.

NOTE: As of the 16.0.0 Pike release, this configuration option is ignored
for the ironic.IronicDriver compute driver and is hardcoded to 1.0.

Possible values:

* Any valid positive integer or float value
""")
]

compute_manager_opts = [
    cfg.StrOpt('console_host',
        default=socket.gethostname(),
        sample_default="<current_hostname>",
        help="""
Console proxy host to be used to connect to instances on this host. It is the
publicly visible name for the console host.

Possible values:

* Current hostname (default) or any string representing hostname.
"""),
    cfg.StrOpt('default_access_ip_network_name',
        help="""
Name of the network to be used to set access IPs for instances. If there are
multiple IPs to choose from, an arbitrary one will be chosen.

Possible values:

* None (default)
* Any string representing network name.
"""),
    cfg.BoolOpt('defer_iptables_apply',
        default=False,
        help="""
Whether to batch up the application of IPTables rules during a host restart
and apply all at the end of the init phase.
"""),
    cfg.StrOpt('instances_path',
        default=paths.state_path_def('instances'),
        sample_default="$state_path/instances",
        help="""
Specifies where instances are stored on the hypervisor's disk.
It can point to locally attached storage or a directory on NFS.

Possible values:

* $state_path/instances where state_path is a config option that specifies
  the top-level directory for maintaining nova's state. (default) or
  Any string representing directory path.
"""),
    cfg.BoolOpt('instance_usage_audit',
        default=False,
        help="""
This option enables periodic compute.instance.exists notifications. Each
compute node must be configured to generate system usage data. These
notifications are consumed by OpenStack Telemetry service.
"""),
    cfg.IntOpt('live_migration_retry_count',
        default=30,
        min=0,
        help="""
Maximum number of 1 second retries in live_migration. It specifies number
of retries to iptables when it complains. It happens when an user continuously
sends live-migration request to same host leading to concurrent request
to iptables.

Possible values:

* Any positive integer representing retry count.
"""),
    cfg.BoolOpt('resume_guests_state_on_host_boot',
        default=False,
        help="""
This option specifies whether to start guests that were running before the
host rebooted. It ensures that all of the instances on a Nova compute node
resume their state each time the compute node boots or restarts.
"""),
    cfg.IntOpt('network_allocate_retries',
        default=0,
        min=0,
        help="""
Number of times to retry network allocation. It is required to attempt network
allocation retries if the virtual interface plug fails.

Possible values:

* Any positive integer representing retry count.
"""),
    cfg.IntOpt('max_concurrent_builds',
        default=10,
        min=0,
        help="""
Limits the maximum number of instance builds to run concurrently by
nova-compute. Compute service can attempt to build an infinite number of
instances, if asked to do so. This limit is enforced to avoid building
unlimited instance concurrently on a compute node. This value can be set
per compute node.

Possible Values:

* 0 : treated as unlimited.
* Any positive integer representing maximum concurrent builds.
"""),
    # TODO(sfinucan): Add min parameter
    cfg.IntOpt('max_concurrent_live_migrations',
        default=1,
        help="""
Maximum number of live migrations to run concurrently. This limit is enforced
to avoid outbound live migrations overwhelming the host/network and causing
failures. It is not recommended that you change this unless you are very sure
that doing so is safe and stable in your environment.

Possible values:

* 0 : treated as unlimited.
* Negative value defaults to 0.
* Any positive integer representing maximum number of live migrations
  to run concurrently.
"""),
    cfg.IntOpt('block_device_allocate_retries',
        default=60,
        help="""
Number of times to retry block device allocation on failures. Starting with
Liberty, Cinder can use image volume cache. This may help with block device
allocation performance. Look at the cinder image_volume_cache_enabled
configuration option.

Possible values:

* 60 (default)
* If value is 0, then one attempt is made.
* Any negative value is treated as 0.
* For any value > 0, total attempts are (value + 1)
"""),
    cfg.IntOpt('sync_power_state_pool_size',
        default=1000,
        help="""
Number of greenthreads available for use to sync power states.

This option can be used to reduce the number of concurrent requests
made to the hypervisor or system with real instance power states
for performance reasons, for example, with Ironic.

Possible values:

* Any positive integer representing greenthreads count.
""")
]

compute_group_opts = [
    cfg.IntOpt('consecutive_build_service_disable_threshold',
        default=10,
        help="""
Enables reporting of build failures to the scheduler.

Any nonzero value will enable sending build failure statistics to the
scheduler for use by the BuildFailureWeigher.

Possible values:

* Any positive integer enables reporting build failures.
* Zero to disable reporting build failures.

Related options:

* [filter_scheduler]/build_failure_weight_multiplier

"""),
]

interval_opts = [
    cfg.IntOpt('image_cache_manager_interval',
        default=2400,
        min=-1,
        help="""
Number of seconds to wait between runs of the image cache manager.

Possible values:
* 0: run at the default rate.
* -1: disable
* Any other value
"""),
    cfg.IntOpt('bandwidth_poll_interval',
        default=600,
        help="""
Interval to pull network bandwidth usage info.

Not supported on all hypervisors. If a hypervisor doesn't support bandwidth
usage, it will not get the info in the usage events.

Possible values:

* 0: Will run at the default periodic interval.
* Any value < 0: Disables the option.
* Any positive integer in seconds.
"""),
    cfg.IntOpt('sync_power_state_interval',
        default=600,
        help="""
Interval to sync power states between the database and the hypervisor.

The interval that Nova checks the actual virtual machine power state
and the power state that Nova has in its database. If a user powers
down their VM, Nova updates the API to report the VM has been
powered down. Should something turn on the VM unexpectedly,
Nova will turn the VM back off to keep the system in the expected
state.

Possible values:

* 0: Will run at the default periodic interval.
* Any value < 0: Disables the option.
* Any positive integer in seconds.

Related options:

* If ``handle_virt_lifecycle_events`` in workarounds_group is
  false and this option is negative, then instances that get out
  of sync between the hypervisor and the Nova database will have
  to be synchronized manually.
"""),
    cfg.IntOpt('heal_instance_info_cache_interval',
        default=60,
        help="""
Interval between instance network information cache updates.

Number of seconds after which each compute node runs the task of
querying Neutron for all of its instances networking information,
then updates the Nova db with that information. Nova will never
update it's cache if this option is set to 0. If we don't update the
cache, the metadata service and nova-api endpoints will be proxying
incorrect network data about the instance. So, it is not recommended
to set this option to 0.

Possible values:

* Any positive integer in seconds.
* Any value <=0 will disable the sync. This is not recommended.
"""),
    cfg.IntOpt('reclaim_instance_interval',
        default=0,
        help="""
Interval for reclaiming deleted instances.

A value greater than 0 will enable SOFT_DELETE of instances.
This option decides whether the server to be deleted will be put into
the SOFT_DELETED state. If this value is greater than 0, the deleted
server will not be deleted immediately, instead it will be put into
a queue until it's too old (deleted time greater than the value of
reclaim_instance_interval). The server can be recovered from the
delete queue by using the restore action. If the deleted server remains
longer than the value of reclaim_instance_interval, it will be
deleted by a periodic task in the compute service automatically.

Note that this option is read from both the API and compute nodes, and
must be set globally otherwise servers could be put into a soft deleted
state in the API and never actually reclaimed (deleted) on the compute
node.

Possible values:

* Any positive integer(in seconds) greater than 0 will enable
  this option.
* Any value <=0 will disable the option.
"""),
    cfg.IntOpt('volume_usage_poll_interval',
        default=0,
        help="""
Interval for gathering volume usages.

This option updates the volume usage cache for every
volume_usage_poll_interval number of seconds.

Possible values:

* Any positive integer(in seconds) greater than 0 will enable
  this option.
* Any value <=0 will disable the option.
"""),
    cfg.IntOpt('shelved_poll_interval',
        default=3600,
        help="""
Interval for polling shelved instances to offload.

The periodic task runs for every shelved_poll_interval number
of seconds and checks if there are any shelved instances. If it
finds a shelved instance, based on the 'shelved_offload_time' config
value it offloads the shelved instances. Check 'shelved_offload_time'
config option description for details.

Possible values:

* Any value <= 0: Disables the option.
* Any positive integer in seconds.

Related options:

* ``shelved_offload_time``
"""),
    cfg.IntOpt('shelved_offload_time',
        default=0,
        help="""
Time before a shelved instance is eligible for removal from a host.

By default this option is set to 0 and the shelved instance will be
removed from the hypervisor immediately after shelve operation.
Otherwise, the instance will be kept for the value of
shelved_offload_time(in seconds) so that during the time period the
unshelve action will be faster, then the periodic task will remove
the instance from hypervisor after shelved_offload_time passes.

Possible values:

* 0: Instance will be immediately offloaded after being
     shelved.
* Any value < 0: An instance will never offload.
* Any positive integer in seconds: The instance will exist for
  the specified number of seconds before being offloaded.
"""),
    cfg.IntOpt('instance_delete_interval',
        default=300,
        help="""
Interval for retrying failed instance file deletes.

This option depends on 'maximum_instance_delete_attempts'.
This option specifies how often to retry deletes whereas
'maximum_instance_delete_attempts' specifies the maximum number
of retry attempts that can be made.

Possible values:

* 0: Will run at the default periodic interval.
* Any value < 0: Disables the option.
* Any positive integer in seconds.

Related options:

* ``maximum_instance_delete_attempts`` from instance_cleaning_opts
  group.
"""),
    cfg.IntOpt('block_device_allocate_retries_interval',
        default=3,
        min=0,
        help="""
Interval (in seconds) between block device allocation retries on failures.

This option allows the user to specify the time interval between
consecutive retries. 'block_device_allocate_retries' option specifies
the maximum number of retries.

Possible values:

* 0: Disables the option.
* Any positive integer in seconds enables the option.

Related options:

* ``block_device_allocate_retries`` in compute_manager_opts group.
"""),
    cfg.IntOpt('scheduler_instance_sync_interval',
        default=120,
        help="""
Interval between sending the scheduler a list of current instance UUIDs to
verify that its view of instances is in sync with nova.

If the CONF option 'scheduler_tracks_instance_changes' is
False, the sync calls will not be made. So, changing this option will
have no effect.

If the out of sync situations are not very common, this interval
can be increased to lower the number of RPC messages being sent.
Likewise, if sync issues turn out to be a problem, the interval
can be lowered to check more frequently.

Possible values:

* 0: Will run at the default periodic interval.
* Any value < 0: Disables the option.
* Any positive integer in seconds.

Related options:

* This option has no impact if ``scheduler_tracks_instance_changes``
  is set to False.
"""),
    cfg.IntOpt('update_resources_interval',
        default=0,
        help="""
Interval for updating compute resources.

This option specifies how often the update_available_resources
periodic task should run. A number less than 0 means to disable the
task completely. Leaving this at the default of 0 will cause this to
run at the default periodic interval. Setting it to any positive
value will cause it to run at approximately that number of seconds.

Possible values:

* 0: Will run at the default periodic interval.
* Any value < 0: Disables the option.
* Any positive integer in seconds.
""")
]

timeout_opts = [
    cfg.IntOpt("reboot_timeout",
        default=0,
        min=0,
        help="""
Time interval after which an instance is hard rebooted automatically.

When doing a soft reboot, it is possible that a guest kernel is
completely hung in a way that causes the soft reboot task
to not ever finish. Setting this option to a time period in seconds
will automatically hard reboot an instance if it has been stuck
in a rebooting state longer than N seconds.

Possible values:

* 0: Disables the option (default).
* Any positive integer in seconds: Enables the option.
"""),
    cfg.IntOpt("instance_build_timeout",
        default=0,
        min=0,
        help="""
Maximum time in seconds that an instance can take to build.

If this timer expires, instance status will be changed to ERROR.
Enabling this option will make sure an instance will not be stuck
in BUILD state for a longer period.

Possible values:

* 0: Disables the option (default)
* Any positive integer in seconds: Enables the option.
"""),
    cfg.IntOpt("rescue_timeout",
        default=0,
        min=0,
        help="""
Interval to wait before un-rescuing an instance stuck in RESCUE.

Possible values:

* 0: Disables the option (default)
* Any positive integer in seconds: Enables the option.
"""),
    cfg.IntOpt("resize_confirm_window",
        default=0,
        min=0,
        help="""
Automatically confirm resizes after N seconds.

Resize functionality will save the existing server before resizing.
After the resize completes, user is requested to confirm the resize.
The user has the opportunity to either confirm or revert all
changes. Confirm resize removes the original server and changes
server status from resized to active. Setting this option to a time
period (in seconds) will automatically confirm the resize if the
server is in resized state longer than that time.

Possible values:

* 0: Disables the option (default)
* Any positive integer in seconds: Enables the option.
"""),
    cfg.IntOpt("shutdown_timeout",
        default=60,
        min=1,
        help="""
Total time to wait in seconds for an instance toperform a clean
shutdown.

It determines the overall period (in seconds) a VM is allowed to
perform a clean shutdown. While performing stop, rescue and shelve,
rebuild operations, configuring this option gives the VM a chance
to perform a controlled shutdown before the instance is powered off.
The default timeout is 60 seconds.

The timeout value can be overridden on a per image basis by means
of os_shutdown_timeout that is an image metadata setting allowing
different types of operating systems to specify how much time they
need to shut down cleanly.

Possible values:

* Any positive integer in seconds (default value is 60).
""")
]

running_deleted_opts = [
    cfg.StrOpt("running_deleted_instance_action",
        default="reap",
        choices=('noop', 'log', 'shutdown', 'reap'),
        help="""
The compute service periodically checks for instances that have been
deleted in the database but remain running on the compute node. The
above option enables action to be taken when such instances are
identified.

Possible values:

* reap: Powers down the instances and deletes them(default)
* log: Logs warning message about deletion of the resource
* shutdown: Powers down instances and marks them as non-
  bootable which can be later used for debugging/analysis
* noop: Takes no action

Related options:

* running_deleted_instance_poll_interval
* running_deleted_instance_timeout
"""),
    cfg.IntOpt("running_deleted_instance_poll_interval",
        default=1800,
        help="""
Time interval in seconds to wait between runs for the clean up action.
If set to 0, above check will be disabled. If "running_deleted_instance
_action" is set to "log" or "reap", a value greater than 0 must be set.

Possible values:

* Any positive integer in seconds enables the option.
* 0: Disables the option.
* 1800: Default value.

Related options:

* running_deleted_instance_action
"""),
    cfg.IntOpt("running_deleted_instance_timeout",
        default=0,
        help="""
Time interval in seconds to wait for the instances that have
been marked as deleted in database to be eligible for cleanup.

Possible values:

* Any positive integer in seconds(default is 0).

Related options:

* "running_deleted_instance_action"
"""),
]

instance_cleaning_opts = [
    # TODO(macsz): add min=1 flag in P development cycle
    cfg.IntOpt('maximum_instance_delete_attempts',
        default=5,
        help="""
The number of times to attempt to reap an instance's files.

This option specifies the maximum number of retry attempts
that can be made.

Possible values:

* Any positive integer defines how many attempts are made.
* Any value <=0 means no delete attempts occur, but you should use
  ``instance_delete_interval`` to disable the delete attempts.

Related options:
* ``instance_delete_interval`` in interval_opts group can be used to disable
  this option.
""")
]

db_opts = [
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
        default='',
        choices=['', 'project', 'global'],
        help="""
Sets the scope of the check for unique instance names.

The default doesn't check for unique names. If a scope for the name check is
set, a launch of a new instance or an update of an existing instance with a
duplicate name will result in an ''InstanceExists'' error. The uniqueness is
case-insensitive. Setting this option can increase the usability for end
users as they don't have to distinguish among instances with the same name
by their IDs.

Possible values:

* '': An empty value means that no uniqueness check is done and duplicate
  names are possible.
* "project": The instance name check is done only for instances within the
  same project.
* "global": The instance name check is done for all instances regardless of
  the project.
"""),
    cfg.BoolOpt('enable_new_services',
        default=True,
        help="""
Enable new nova-compute services on this host automatically.

When a new nova-compute service starts up, it gets
registered in the database as an enabled service. Sometimes it can be useful
to register new compute services in disabled state and then enabled them at a
later point in time. This option only sets this behavior for nova-compute
services, it does not auto-disable other services like nova-conductor,
nova-scheduler, nova-consoleauth, or nova-osapi_compute.

Possible values:

* ``True``: Each new compute service is enabled as soon as it registers itself.
* ``False``: Compute services must be enabled via an os-services REST API call
  or with the CLI with ``nova service-enable <hostname> <binary>``, otherwise
  they are not ready to use.
"""),
    cfg.StrOpt('instance_name_template',
         default='instance-%08x',
         help="""
Template string to be used to generate instance names.

This template controls the creation of the database name of an instance. This
is *not* the display name you enter when creating an instance (via Horizon
or CLI). For a new deployment it is advisable to change the default value
(which uses the database autoincrement) to another value which makes use
of the attributes of an instance, like ``instance-%(uuid)s``. If you
already have instances in your deployment when you change this, your
deployment will break.

Possible values:

* A string which either uses the instance database ID (like the
  default)
* A string with a list of named database columns, for example ``%(id)d``
  or ``%(uuid)s`` or ``%(hostname)s``.

Related options:

* not to be confused with: ``multi_instance_display_name_template``
"""),
]


ALL_OPTS = (compute_opts +
            resource_tracker_opts +
            allocation_ratio_opts +
            compute_manager_opts +
            interval_opts +
            timeout_opts +
            running_deleted_opts +
            instance_cleaning_opts +
            db_opts)


def register_opts(conf):
    conf.register_opts(ALL_OPTS)
    conf.register_group(compute_group)
    conf.register_opts(compute_group_opts, group=compute_group)


def list_opts():
    return {'DEFAULT': ALL_OPTS,
            'compute': compute_group_opts}
