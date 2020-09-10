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
* ``fake.FakeDriver``
* ``ironic.IronicDriver``
* ``vmwareapi.VMwareVCDriver``
* ``hyperv.HyperVDriver``
* ``powervm.PowerVMDriver``
* ``zvm.ZVMDriver``
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
        default=['cache_in_nova', 'bittorrent'],
        help="""
Image properties that should not be inherited from the instance
when taking a snapshot.

This option gives an opportunity to select which image-properties
should not be inherited by newly created snapshots.

.. note::

   The following image properties are *never* inherited regardless of
   whether they are listed in this configuration option or not:

   * cinder_encryption_key_id
   * cinder_encryption_key_deletion_policy
   * img_signature
   * img_signature_hash_method
   * img_signature_key_type
   * img_signature_certificate_uuid

Possible values:

* A comma-separated list whose item is an image property. Usually only
  the image properties that are only needed by base images can be included
  here, since the snapshots that are created from the base images don't
  need them.
* Default list: cache_in_nova, bittorrent

"""),
    cfg.IntOpt('max_local_block_devices',
        default=3,
        help="""
Maximum number of devices that will result in a local image being
created on the hypervisor node.

A negative number means unlimited. Setting ``max_local_block_devices``
to 0 means that any request that attempts to create a local disk
will fail. This option is meant to limit the number of local discs
(so root local disc that is the result of ``imageRef`` being used when
creating a server, and any other ephemeral and swap disks). 0 does not
mean that images will be automatically converted to volumes and boot
instances from volumes - it just means that all requests that attempt
to create a local disk will fail.

Possible values:

* 0: Creating a local disk is not allowed.
* Negative number: Allows unlimited number of local discs.
* Positive number: Allows only these many number of local discs.
"""),
    cfg.ListOpt('compute_monitors',
        default=[],
        help="""
A comma-separated list of monitors that can be used for getting
compute metrics. You can use the alias/name from the setuptools
entry points for nova.compute.monitors.* namespaces. If no
namespace is supplied, the "cpu." namespace is assumed for
backwards-compatibility.

NOTE: Only one monitor per namespace (For example: cpu) can be loaded at
a time.

Possible values:

* An empty list will disable the feature (Default).
* An example value that would enable the CPU
  bandwidth monitor that uses the virt driver variant::

    compute_monitors = cpu.virt_driver
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

If you are hitting timeout failures at scale, consider running rootwrap
in "daemon mode" in the neutron agent via the ``[agent]/root_helper_daemon``
neutron configuration option.

Related options:

* vif_plugging_is_fatal - If ``vif_plugging_timeout`` is set to zero and
  ``vif_plugging_is_fatal`` is False, events should not be expected to
  arrive at all.
"""),
    cfg.IntOpt('arq_binding_timeout',
        default=300,
        min=1,
        help="""
Timeout for Accelerator Request (ARQ) bind event message arrival.

Number of seconds to wait for ARQ bind resolution event to arrive.
The event indicates that every ARQ for an instance has either bound
successfully or failed to bind. If it does not arrive, instance bringup
is aborted with an exception.
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
        choices=[
            ('none', 'No storage provisioning is done up front'),
            ('space', 'Storage is fully allocated at instance start')
        ],
        help="""
The image preallocation mode to use.

Image preallocation allows storage for instance images to be allocated up front
when the instance is initially provisioned. This ensures immediate feedback is
given if enough space isn't available. In addition, it should significantly
improve performance on writes to new blocks and may even improve I/O
performance to prewritten blocks due to reduced fragmentation.
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
* ``[libvirt]/images_type``: If images_type is rbd, setting this option
  to False is not allowed. See the bug
  https://bugs.launchpad.net/nova/+bug/1816686 for more details.
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
    cfg.StrOpt('pointer_model',
        default='usbtablet',
        choices=[
            ('ps2mouse', 'Uses relative movement. Mouse connected by PS2'),
            ('usbtablet', 'Uses absolute movement. Tablet connect by USB'),
            (None, 'Uses default behavior provided by drivers (mouse on PS2 '
             'for libvirt x86)'),
        ],
        help="""
Generic property to specify the pointer type.

Input devices allow interaction with a graphical framebuffer. For
example to provide a graphic tablet for absolute cursor movement.

If set, the 'hw_pointer_model' image property takes precedence over
this configuration option.

Related options:

* usbtablet must be configured with VNC enabled or SPICE enabled and SPICE
  agent disabled. When used with libvirt the instance mode should be
  configured as HVM.
 """),
]

resource_tracker_opts = [
    cfg.StrOpt('vcpu_pin_set',
        deprecated_for_removal=True,
        deprecated_since='20.0.0',
        deprecated_reason="""
This option has been superseded by the ``[compute] cpu_dedicated_set`` and
``[compute] cpu_shared_set`` options, which allow things like the co-existence
of pinned and unpinned instances on the same host (for the libvirt driver).
""",
        help="""
Mask of host CPUs that can be used for ``VCPU`` resources.

The behavior of this option depends on the definition of the ``[compute]
cpu_dedicated_set`` option and affects the behavior of the ``[compute]
cpu_shared_set`` option.

* If ``[compute] cpu_dedicated_set`` is defined, defining this option will
  result in an error.

* If ``[compute] cpu_dedicated_set`` is not defined, this option will be used
  to determine inventory for ``VCPU`` resources and to limit the host CPUs
  that both pinned and unpinned instances can be scheduled to, overriding the
  ``[compute] cpu_shared_set`` option.

Possible values:

* A comma-separated list of physical CPU numbers that virtual CPUs can be
  allocated from. Each element should be either a single CPU number, a range of
  CPU numbers, or a caret followed by a CPU number to be excluded from a
  previous range. For example::

    vcpu_pin_set = "4-12,^8,15"

Related options:

* ``[compute] cpu_dedicated_set``
* ``[compute] cpu_shared_set``
"""),
    cfg.MultiOpt('reserved_huge_pages',
        item_type=types.Dict(),
        help="""
Number of huge/large memory pages to reserved per NUMA host cell.

Possible values:

* A list of valid key=value which reflect NUMA node ID, page size
  (Default unit is KiB) and number of pages to be reserved. For example::

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
Number of host CPUs to reserve for host processes.

The host resources usage is reported back to the scheduler continuously from
nova-compute running on the compute node. This value is used to determine the
``reserved`` value reported to placement.

This option cannot be set if the ``[compute] cpu_shared_set`` or ``[compute]
cpu_dedicated_set`` config options have been defined. When these options are
defined, any host CPUs not included in these values are considered reserved for
the host.

Possible values:

* Any positive integer representing number of physical CPUs to reserve
  for the host.

Related options:

* ``[compute] cpu_shared_set``
* ``[compute] cpu_dedicated_set``
"""),
]

allocation_ratio_opts = [
    cfg.FloatOpt('cpu_allocation_ratio',
        default=None,
        min=0.0,
        help="""
Virtual CPU to physical CPU allocation ratio.

This option is used to influence the hosts selected by the Placement API by
configuring the allocation ratio for ``VCPU`` inventory. In addition, the
``AggregateCoreFilter`` (deprecated) will fall back to this configuration value
if no per-aggregate setting is found.

.. note::

   This option does not affect ``PCPU`` inventory, which cannot be
   overcommitted.

.. note::

   If this option is set to something *other than* ``None`` or ``0.0``, the
   allocation ratio will be overwritten by the value of this option, otherwise,
   the allocation ratio will not change. Once set to a non-default value, it is
   not possible to "unset" the config to get back to the default behavior. If
   you want to reset back to the initial value, explicitly specify it to the
   value of ``initial_cpu_allocation_ratio``.

Possible values:

* Any valid positive integer or float value

Related options:

* ``initial_cpu_allocation_ratio``
"""),
    cfg.FloatOpt('ram_allocation_ratio',
        default=None,
        min=0.0,
        help="""
Virtual RAM to physical RAM allocation ratio.

This option is used to influence the hosts selected by the Placement API by
configuring the allocation ratio for ``MEMORY_MB`` inventory. In addition, the
``AggregateRamFilter`` (deprecated) will fall back to this configuration value
if no per-aggregate setting is found.

.. note::

   If this option is set to something *other than* ``None`` or ``0.0``, the
   allocation ratio will be overwritten by the value of this option, otherwise,
   the allocation ratio will not change. Once set to a non-default value, it is
   not possible to "unset" the config to get back to the default behavior. If
   you want to reset back to the initial value, explicitly specify it to the
   value of ``initial_ram_allocation_ratio``.

Possible values:

* Any valid positive integer or float value

Related options:

* ``initial_ram_allocation_ratio``
"""),
    cfg.FloatOpt('disk_allocation_ratio',
        default=None,
        min=0.0,
        help="""
Virtual disk to physical disk allocation ratio.

This option is used to influence the hosts selected by the Placement API by
configuring the allocation ratio for ``DISK_GB`` inventory. In addition, the
``AggregateDiskFilter`` (deprecated) will fall back to this configuration value
if no per-aggregate setting is found.

When configured, a ratio greater than 1.0 will result in over-subscription of
the available physical disk, which can be useful for more efficiently packing
instances created with images that do not use the entire virtual disk, such as
sparse or compressed images. It can be set to a value between 0.0 and 1.0 in
order to preserve a percentage of the disk for uses other than instances.

.. note::

   If the value is set to ``>1``, we recommend keeping track of the free disk
   space, as the value approaching ``0`` may result in the incorrect
   functioning of instances using it at the moment.

.. note::

   If this option is set to something *other than* ``None`` or ``0.0``, the
   allocation ratio will be overwritten by the value of this option, otherwise,
   the allocation ratio will not change. Once set to a non-default value, it is
   not possible to "unset" the config to get back to the default behavior. If
   you want to reset back to the initial value, explicitly specify it to the
   value of ``initial_disk_allocation_ratio``.

Possible values:

* Any valid positive integer or float value

Related options:

* ``initial_disk_allocation_ratio``
"""),
    cfg.FloatOpt('initial_cpu_allocation_ratio',
                 default=16.0,
                 min=0.0,
                 help="""
Initial virtual CPU to physical CPU allocation ratio.

This is only used when initially creating the ``computes_nodes`` table record
for a given nova-compute service.

See https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html
for more details and usage scenarios.

Related options:

* ``cpu_allocation_ratio``
"""),
    cfg.FloatOpt('initial_ram_allocation_ratio',
                 default=1.5,
                 min=0.0,
                 help="""
Initial virtual RAM to physical RAM allocation ratio.

This is only used when initially creating the ``computes_nodes`` table record
for a given nova-compute service.

See https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html
for more details and usage scenarios.

Related options:

* ``ram_allocation_ratio``
"""),
    cfg.FloatOpt('initial_disk_allocation_ratio',
                 default=1.0,
                 min=0.0,
                 help="""
Initial virtual disk to physical disk allocation ratio.

This is only used when initially creating the ``computes_nodes`` table record
for a given nova-compute service.

See https://docs.openstack.org/nova/latest/admin/configuration/schedulers.html
for more details and usage scenarios.

Related options:

* ``disk_allocation_ratio``
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

Related options:

* ``[workarounds]/ensure_libvirt_rbd_instance_dir_cleanup``
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
    cfg.IntOpt('max_concurrent_snapshots',
        default=5,
        min=0,
        help="""
Maximum number of instance snapshot operations to run concurrently.
This limit is enforced to prevent snapshots overwhelming the
host/network/storage and causing failure. This value can be set per
compute node.

Possible Values:

* 0 : treated as unlimited.
* Any positive integer representing maximum concurrent snapshots.
"""),
    cfg.IntOpt('max_concurrent_live_migrations',
        default=1,
        min=0,
        help="""
Maximum number of live migrations to run concurrently. This limit is enforced
to avoid outbound live migrations overwhelming the host/network and causing
failures. It is not recommended that you change this unless you are very sure
that doing so is safe and stable in your environment.

Possible values:

* 0 : treated as unlimited.
* Any positive integer representing maximum number of live migrations
  to run concurrently.
"""),
    cfg.IntOpt('block_device_allocate_retries',
        default=60,
        min=0,
        help="""
The number of times to check for a volume to be "available" before attaching
it during server create.

When creating a server with block device mappings where ``source_type`` is
one of ``blank``, ``image`` or ``snapshot`` and the ``destination_type`` is
``volume``, the ``nova-compute`` service will create a volume and then attach
it to the server. Before the volume can be attached, it must be in status
"available". This option controls how many times to check for the created
volume to be "available" before it is attached.

If the operation times out, the volume will be deleted if the block device
mapping ``delete_on_termination`` value is True.

It is recommended to configure the image cache in the block storage service
to speed up this operation. See
https://docs.openstack.org/cinder/latest/admin/blockstorage-image-volume-cache.html
for details.

Possible values:

* 60 (default)
* If value is 0, then one attempt is made.
* For any value > 0, total attempts are (value + 1)

Related options:

* ``block_device_allocate_retries_interval`` - controls the interval between
  checks
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
    cfg.IntOpt("shutdown_retry_interval",
        default=10,
        min=1,
        help="""
Time to wait in seconds before resending an ACPI shutdown signal to
instances.

The overall time to wait is set by ``shutdown_timeout``.

Possible values:

* Any integer greater than 0 in seconds

Related options:

* ``shutdown_timeout``
"""),
    cfg.IntOpt('resource_provider_association_refresh',
        default=300,
        min=0,
        mutable=True,
        # TODO(efried): Provide more/better explanation of what this option is
        # all about. Reference bug(s). Unless we're just going to remove it.
        help="""
Interval for updating nova-compute-side cache of the compute node resource
provider's inventories, aggregates, and traits.

This option specifies the number of seconds between attempts to update a
provider's inventories, aggregates and traits in the local cache of the compute
node.

A value of zero disables cache refresh completely.

The cache can be cleared manually at any time by sending SIGHUP to the compute
process, causing it to be repopulated the next time the data is accessed.

Possible values:

* Any positive integer in seconds, or zero to disable refresh.
"""),
   cfg.StrOpt('cpu_shared_set',
        help="""
Mask of host CPUs that can be used for ``VCPU`` resources and offloaded
emulator threads.

The behavior of this option depends on the definition of the deprecated
``vcpu_pin_set`` option.

* If ``vcpu_pin_set`` is not defined, ``[compute] cpu_shared_set`` will be be
  used to provide ``VCPU`` inventory and to determine the host CPUs that
  unpinned instances can be scheduled to. It will also be used to determine the
  host CPUS that instance emulator threads should be offloaded to for instances
  configured with the ``share`` emulator thread policy
  (``hw:emulator_threads_policy=share``).

* If ``vcpu_pin_set`` is defined, ``[compute] cpu_shared_set`` will only be
  used to determine the host CPUs that instance emulator threads should be
  offloaded to for instances configured with the ``share`` emulator thread
  policy (``hw:emulator_threads_policy=share``). ``vcpu_pin_set`` will be used
  to provide ``VCPU`` inventory and to determine the host CPUs that both pinned
  and unpinned instances can be scheduled to.

This behavior will be simplified in a future release when ``vcpu_pin_set`` is
removed.

Possible values:

* A comma-separated list of physical CPU numbers that instance VCPUs can be
  allocated from. Each element should be either a single CPU number, a range of
  CPU numbers, or a caret followed by a CPU number to be excluded from a
  previous range. For example::

    cpu_shared_set = "4-12,^8,15"

Related options:

* ``[compute] cpu_dedicated_set``: This is the counterpart option for defining
  where ``PCPU`` resources should be allocated from.
* ``vcpu_pin_set``: A legacy option whose definition may change the behavior of
  this option.
"""),
   cfg.StrOpt('cpu_dedicated_set',
        help="""
Mask of host CPUs that can be used for ``PCPU`` resources.

The behavior of this option affects the behavior of the deprecated
``vcpu_pin_set`` option.

* If this option is defined, defining ``vcpu_pin_set`` will result in an error.

* If this option is not defined, ``vcpu_pin_set`` will be used to determine
  inventory for ``VCPU`` resources and to limit the host CPUs that both pinned
  and unpinned instances can be scheduled to.

This behavior will be simplified in a future release when ``vcpu_pin_set`` is
removed.

Possible values:

* A comma-separated list of physical CPU numbers that instance VCPUs can be
  allocated from. Each element should be either a single CPU number, a range of
  CPU numbers, or a caret followed by a CPU number to be excluded from a
  previous range. For example::

    cpu_dedicated_set = "4-12,^8,15"

Related options:

* ``[compute] cpu_shared_set``: This is the counterpart option for defining
  where ``VCPU`` resources should be allocated from.
* ``vcpu_pin_set``: A legacy option that this option partially replaces.
"""),
    cfg.BoolOpt('live_migration_wait_for_vif_plug',
        default=True,
        help="""
Determine if the source compute host should wait for a ``network-vif-plugged``
event from the (neutron) networking service before starting the actual transfer
of the guest to the destination compute host.

Note that this option is read on the destination host of a live migration.
If you set this option the same on all of your compute hosts, which you should
do if you use the same networking backend universally, you do not have to
worry about this.

Before starting the transfer of the guest, some setup occurs on the destination
compute host, including plugging virtual interfaces. Depending on the
networking backend **on the destination host**, a ``network-vif-plugged``
event may be triggered and then received on the source compute host and the
source compute can wait for that event to ensure networking is set up on the
destination host before starting the guest transfer in the hypervisor.

.. note::

   The compute service cannot reliably determine which types of virtual
   interfaces (``port.binding:vif_type``) will send ``network-vif-plugged``
   events without an accompanying port ``binding:host_id`` change.
   Open vSwitch and linuxbridge should be OK, but OpenDaylight is at least
   one known backend that will not currently work in this case, see bug
   https://launchpad.net/bugs/1755890 for more details.

Possible values:

* True: wait for ``network-vif-plugged`` events before starting guest transfer
* False: do not wait for ``network-vif-plugged`` events before starting guest
  transfer (this is the legacy behavior)

Related options:

* [DEFAULT]/vif_plugging_is_fatal: if ``live_migration_wait_for_vif_plug`` is
  True and ``vif_plugging_timeout`` is greater than 0, and a timeout is
  reached, the live migration process will fail with an error but the guest
  transfer will not have started to the destination host
* [DEFAULT]/vif_plugging_timeout: if ``live_migration_wait_for_vif_plug`` is
  True, this controls the amount of time to wait before timing out and either
  failing if ``vif_plugging_is_fatal`` is True, or simply continuing with the
  live migration
"""),
    cfg.IntOpt('max_concurrent_disk_ops',
        default=0,
        min=0,
        help="""
Number of concurrent disk-IO-intensive operations (glance image downloads,
image format conversions, etc.) that we will do in parallel.  If this is set
too high then response time suffers.
The default value of 0 means no limit.
 """),
    cfg.IntOpt('max_disk_devices_to_attach',
        default=-1,
        min=-1,
        help="""
Maximum number of disk devices allowed to attach to a single server. Note
that the number of disks supported by an server depends on the bus used. For
example, the ``ide`` disk bus is limited to 4 attached devices. The configured
maximum is enforced during server create, rebuild, evacuate, unshelve, live
migrate, and attach volume.

Usually, disk bus is determined automatically from the device type or disk
device, and the virtualization type. However, disk bus
can also be specified via a block device mapping or an image property.
See the ``disk_bus`` field in :doc:`/user/block-device-mapping` for more
information about specifying disk bus in a block device mapping, and
see https://docs.openstack.org/glance/latest/admin/useful-image-properties.html
for more information about the ``hw_disk_bus`` image property.

Operators changing the ``[compute]/max_disk_devices_to_attach`` on a compute
service that is hosting servers should be aware that it could cause rebuilds to
fail, if the maximum is decreased lower than the number of devices already
attached to servers. For example, if server A has 26 devices attached and an
operators changes ``[compute]/max_disk_devices_to_attach`` to 20, a request to
rebuild server A will fail and go into ERROR state because 26 devices are
already attached and exceed the new configured maximum of 20.

Operators setting ``[compute]/max_disk_devices_to_attach`` should also be aware
that during a cold migration, the configured maximum is only enforced in-place
and the destination is not checked before the move. This means if an operator
has set a maximum of 26 on compute host A and a maximum of 20 on compute host
B, a cold migration of a server with 26 attached devices from compute host A to
compute host B will succeed. Then, once the server is on compute host B, a
subsequent request to rebuild the server will fail and go into ERROR state
because 26 devices are already attached and exceed the configured maximum of 20
on compute host B.

The configured maximum is not enforced on shelved offloaded servers, as they
have no compute host.

Possible values:

* -1 means unlimited
* Any integer >= 0 represents the maximum allowed
"""),
    cfg.StrOpt('provider_config_location',
        default='/etc/nova/provider_config/',
        help="""
Location of YAML files containing resource provider configuration data.

These files allow the operator to specify additional custom inventory and
traits to assign to one or more resource providers.

Additional documentation is available here:

  https://docs.openstack.org/nova/latest/admin/managing-resource-providers.html

"""),
]

interval_opts = [
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

* If ``handle_virt_lifecycle_events`` in the ``workarounds`` group is
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

.. note:: When using this option, you should also configure the ``[cinder]``
          auth options, e.g. ``auth_type``, ``auth_url``, ``username``, etc.
          Since the reclaim happens in a periodic task, there is no user token
          to cleanup volumes attached to any SOFT_DELETED servers so nova must
          be configured with administrator role access to cleanup those
          resources in cinder.

Possible values:

* Any positive integer(in seconds) greater than 0 will enable
  this option.
* Any value <=0 will disable the option.

Related options:

* [cinder] auth options for cleaning up volumes attached to servers during
  the reclaim process
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
    # NOTE(melwitt): We're also using this option as the interval for cleaning
    # up expired console authorizations from the database. It's related to the
    # delete_instance_interval in that it's another task for cleaning up
    # resources related to an instance.
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
consecutive retries. The ``block_device_allocate_retries`` option specifies
the maximum number of retries.

Possible values:

* 0: Disables the option.
* Any positive integer in seconds enables the option.

Related options:

* ``block_device_allocate_retries`` - controls the number of retries
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

This option specifies how often the update_available_resource
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
        min=0,
        help="""
Total time to wait in seconds for an instance to perform a clean
shutdown.

It determines the overall period (in seconds) a VM is allowed to
perform a clean shutdown. While performing stop, rescue and shelve,
rebuild operations, configuring this option gives the VM a chance
to perform a controlled shutdown before the instance is powered off.
The default timeout is 60 seconds. A value of 0 (zero) means the guest
will be powered off immediately with no opportunity for guest OS clean-up.

The timeout value can be overridden on a per image basis by means
of os_shutdown_timeout that is an image metadata setting allowing
different types of operating systems to specify how much time they
need to shut down cleanly.

Possible values:

* A positive integer or 0 (default value is 60).
""")
]

running_deleted_opts = [
    cfg.StrOpt("running_deleted_instance_action",
        default="reap",
        choices=[
            ('reap', 'Powers down the instances and deletes them'),
            ('log', 'Logs warning message about deletion of the resource'),
            ('shutdown', 'Powers down instances and marks them as '
             'non-bootable which can be later used for debugging/analysis'),
            ('noop', 'Takes no action'),
        ],
        help="""
The compute service periodically checks for instances that have been
deleted in the database but remain running on the compute node. The
above option enables action to be taken when such instances are
identified.

Related options:

* ``running_deleted_instance_poll_interval``
* ``running_deleted_instance_timeout``
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
    cfg.IntOpt('maximum_instance_delete_attempts',
        default=5,
        min=1,
        help="""
The number of times to attempt to reap an instance's files.

This option specifies the maximum number of retry attempts
that can be made.

Possible values:

* Any positive integer defines how many attempts are made.

Related options:

* ``[DEFAULT] instance_delete_interval`` can be used to disable this option.
""")
]

db_opts = [
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
        default='',
        choices=[
            ('', 'An empty value means that no uniqueness check is done and '
             'duplicate names are possible'),
            ('project', 'The instance name check is done only for instances '
             'within the same project'),
            ('global', 'The instance name check is done for all instances '
             'regardless of the project'),
        ],
        help="""
Sets the scope of the check for unique instance names.

The default doesn't check for unique names. If a scope for the name check is
set, a launch of a new instance or an update of an existing instance with a
duplicate name will result in an ''InstanceExists'' error. The uniqueness is
case-insensitive. Setting this option can increase the usability for end
users as they don't have to distinguish among instances with the same name
by their IDs.
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
nova-scheduler, or nova-osapi_compute.

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
