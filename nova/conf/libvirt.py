# needs:fix_opt_description
# needs:check_deprecation_status
# needs:check_opt_group_and_type
# needs:fix_opt_description_indentation
# needs:fix_opt_registration_consistency

# Copyright 2016 OpenStack Foundation
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

import itertools

from oslo_config import cfg

from oslo_config import types

from nova.conf import paths


libvirt_group = cfg.OptGroup("libvirt",
                             title="Libvirt Options",
                             help="""
Libvirt options allows cloud administrator to configure related
libvirt hypervisor driver to be used within an OpenStack deployment.

Almost all of the libvirt config options are influence by ``virt_type`` config
which describes the virtualization type (or so called domain type) libvirt
should use for specific features such as live migration, snapshot.
""")

libvirt_general_opts = [
    cfg.StrOpt('rescue_image_id',
               help="""
The ID of the image to boot from to rescue data from a corrupted instance.

If the rescue REST API operation doesn't provide an ID of an image to
use, the image which is referenced by this ID is used. If this
option is not set, the image from the instance is used.

Possible values:

* An ID of an image or nothing. If it points to an *Amazon Machine
  Image* (AMI), consider to set the config options ``rescue_kernel_id``
  and ``rescue_ramdisk_id`` too. If nothing is set, the image of the instance
  is used.

Related options:

* ``rescue_kernel_id``: If the chosen rescue image allows the separate
  definition of its kernel disk, the value of this option is used,
  if specified. This is the case when *Amazon*'s AMI/AKI/ARI image
  format is used for the rescue image.
* ``rescue_ramdisk_id``: If the chosen rescue image allows the separate
  definition of its RAM disk, the value of this option is used if,
  specified. This is the case when *Amazon*'s AMI/AKI/ARI image
  format is used for the rescue image.
"""),
    cfg.StrOpt('rescue_kernel_id',
               help="""
The ID of the kernel (AKI) image to use with the rescue image.

If the chosen rescue image allows the separate definition of its kernel
disk, the value of this option is used, if specified. This is the case
when *Amazon*'s AMI/AKI/ARI image format is used for the rescue image.

Possible values:

* An ID of an kernel image or nothing. If nothing is specified, the kernel
  disk from the instance is used if it was launched with one.

Related options:

* ``rescue_image_id``: If that option points to an image in *Amazon*'s
  AMI/AKI/ARI image format, it's useful to use ``rescue_kernel_id`` too.
"""),
    cfg.StrOpt('rescue_ramdisk_id',
               help="""
The ID of the RAM disk (ARI) image to use with the rescue image.

If the chosen rescue image allows the separate definition of its RAM
disk, the value of this option is used, if specified. This is the case
when *Amazon*'s AMI/AKI/ARI image format is used for the rescue image.

Possible values:

* An ID of a RAM disk image or nothing. If nothing is specified, the RAM
  disk from the instance is used if it was launched with one.

Related options:

* ``rescue_image_id``: If that option points to an image in *Amazon*'s
  AMI/AKI/ARI image format, it's useful to use ``rescue_ramdisk_id`` too.
"""),
    cfg.StrOpt('virt_type',
               default='kvm',
               choices=('kvm', 'lxc', 'qemu', 'uml', 'xen', 'parallels'),
               help="""
Describes the virtualization type (or so called domain type) libvirt should
use.

The choice of this type must match the underlying virtualization strategy
you have chosen for this host.

Possible values:

* See the predefined set of case-sensitive values.

Related options:

* ``connection_uri``: depends on this
* ``disk_prefix``: depends on this
* ``cpu_mode``: depends on this
* ``cpu_model``: depends on this
"""),
    cfg.StrOpt('connection_uri',
               default='',
               help="""
Overrides the default libvirt URI of the chosen virtualization type.

If set, Nova will use this URI to connect to libvirt.

Possible values:

* An URI like ``qemu:///system`` or ``xen+ssh://oirase/`` for example.
  This is only necessary if the URI differs to the commonly known URIs
  for the chosen virtualization type.

Related options:

* ``virt_type``: Influences what is used as default value here.
"""),
    cfg.BoolOpt('inject_password',
                default=False,
                help="""
Allow the injection of an admin password for instance only at ``create`` and
``rebuild`` process.

There is no agent needed within the image to do this. If *libguestfs* is
available on the host, it will be used. Otherwise *nbd* is used. The file
system of the image will be mounted and the admin password, which is provided
in the REST API call will be injected as password for the root user. If no
root user is available, the instance won't be launched and an error is thrown.
Be aware that the injection is *not* possible when the instance gets launched
from a volume.

Possible values:

* True: Allows the injection.
* False (default): Disallows the injection. Any via the REST API provided
admin password will be silently ignored.

Related options:

* ``inject_partition``: That option will decide about the discovery and usage
  of the file system. It also can disable the injection at all.
"""),
    cfg.BoolOpt('inject_key',
                default=False,
                help="""
Allow the injection of an SSH key at boot time.

There is no agent needed within the image to do this. If *libguestfs* is
available on the host, it will be used. Otherwise *nbd* is used. The file
system of the image will be mounted and the SSH key, which is provided
in the REST API call will be injected as SSH key for the root user and
appended to the ``authorized_keys`` of that user. The SELinux context will
be set if necessary. Be aware that the injection is *not* possible when the
instance gets launched from a volume.

This config option will enable directly modifying the instance disk and does
not affect what cloud-init may do using data from config_drive option or the
metadata service.

Related options:

* ``inject_partition``: That option will decide about the discovery and usage
  of the file system. It also can disable the injection at all.
"""),
    cfg.IntOpt('inject_partition',
               default=-2,
               min=-2,
               help="""
Determines the way how the file system is chosen to inject data into it.

*libguestfs* will be used a first solution to inject data. If that's not
available on the host, the image will be locally mounted on the host as a
fallback solution. If libguestfs is not able to determine the root partition
(because there are more or less than one root partition) or cannot mount the
file system it will result in an error and the instance won't be boot.

Possible values:

* -2 => disable the injection of data.
* -1 => find the root partition with the file system to mount with libguestfs
*  0 => The image is not partitioned
* >0 => The number of the partition to use for the injection

Related options:

* ``inject_key``: If this option allows the injection of a SSH key it depends
  on value greater or equal to -1 for ``inject_partition``.
* ``inject_password``: If this option allows the injection of an admin password
  it depends on value greater or equal to -1 for ``inject_partition``.
* ``guestfs`` You can enable the debug log level of libguestfs with this
  config option. A more verbose output will help in debugging issues.
* ``virt_type``: If you use ``lxc`` as virt_type it will be treated as a
  single partition image
"""),
    cfg.BoolOpt('use_usb_tablet',
                default=True,
                deprecated_for_removal=True,
                deprecated_reason="This option is being replaced by the "
                                  "'pointer_model' option.",
                deprecated_since='14.0.0',
                help="""
Enable a mouse cursor within a graphical VNC or SPICE sessions.

This will only be taken into account if the VM is fully virtualized and VNC
and/or SPICE is enabled. If the node doesn't support a graphical framebuffer,
then it is valid to set this to False.

Related options:
* ``[vnc]enabled``: If VNC is enabled, ``use_usb_tablet`` will have an effect.
* ``[spice]enabled`` + ``[spice].agent_enabled``: If SPICE is enabled and the
  spice agent is disabled, the config value of ``use_usb_tablet`` will have
  an effect.
"""),
    cfg.StrOpt('live_migration_inbound_addr',
               help="""
The IP address or hostname to be used as the target for live migration traffic.

If this option is set to None, the hostname of the migration target compute
node will be used.

This option is useful in environments where the live-migration traffic can
impact the network plane significantly. A separate network for live-migration
traffic can then use this config option and avoids the impact on the
management network.

Possible values:

* A valid IP address or hostname, else None.

Related options:

* ``live_migration_tunnelled``: The live_migration_inbound_addr value is
  ignored if tunneling is enabled.
"""),
    cfg.StrOpt('live_migration_uri',
               deprecated_for_removal=True,
               deprecated_since="15.0.0",
               deprecated_reason="""
live_migration_uri is deprecated for removal in favor of two other options that
allow to change live migration scheme and target URI: ``live_migration_scheme``
and ``live_migration_inbound_addr`` respectively.
""",
               help="""
Live migration target URI to use.

Override the default libvirt live migration target URI (which is dependent
on virt_type). Any included "%s" is replaced with the migration target
hostname.

If this option is set to None (which is the default), Nova will automatically
generate the `live_migration_uri` value based on only 4 supported `virt_type`
in following list:

* 'kvm': 'qemu+tcp://%s/system'
* 'qemu': 'qemu+tcp://%s/system'
* 'xen': 'xenmigr://%s/system'
* 'parallels': 'parallels+tcp://%s/system'

Related options:

* ``live_migration_inbound_addr``: If ``live_migration_inbound_addr`` value
  is not None and ``live_migration_tunnelled`` is False, the ip/hostname
  address of target compute node is used instead of ``live_migration_uri`` as
  the uri for live migration.
* ``live_migration_scheme``: If ``live_migration_uri`` is not set, the scheme
  used for live migration is taken from ``live_migration_scheme`` instead.
"""),
    cfg.StrOpt('live_migration_scheme',
               help="""
URI scheme used for live migration.

Override the default libvirt live migration scheme (which is dependent on
virt_type). If this option is set to None, nova will automatically choose a
sensible default based on the hypervisor. It is not recommended that you change
this unless you are very sure that hypervisor supports a particular scheme.

Related options:

* ``virt_type``: This option is meaningful only when ``virt_type`` is set to
  `kvm` or `qemu`.
* ``live_migration_uri``: If ``live_migration_uri`` value is not None, the
  scheme used for live migration is taken from ``live_migration_uri`` instead.
"""),
    cfg.BoolOpt('live_migration_tunnelled',
                default=False,
                help="""
Enable tunnelled migration.

This option enables the tunnelled migration feature, where migration data is
transported over the libvirtd connection. If enabled, we use the
VIR_MIGRATE_TUNNELLED migration flag, avoiding the need to configure
the network to allow direct hypervisor to hypervisor communication.
If False, use the native transport. If not set, Nova will choose a
sensible default based on, for example the availability of native
encryption support in the hypervisor. Enabling this option will definitely
impact performance massively.

Note that this option is NOT compatible with use of block migration.

Related options:

* ``live_migration_inbound_addr``: The live_migration_inbound_addr value is
  ignored if tunneling is enabled.
"""),
    cfg.IntOpt('live_migration_bandwidth',
               default=0,
               help="""
Maximum bandwidth(in MiB/s) to be used during migration.

If set to 0, the hypervisor will choose a suitable default. Some hypervisors
do not support this feature and will return an error if bandwidth is not 0.
Please refer to the libvirt documentation for further details.
"""),
    cfg.IntOpt('live_migration_downtime',
               default=500,
               min=100,
               help="""
Maximum permitted downtime, in milliseconds, for live migration
switchover.

Will be rounded up to a minimum of 100ms. You can increase this value
if you want to allow live-migrations to complete faster, or avoid
live-migration timeout errors by allowing the guest to be paused for
longer during the live-migration switch over.

Related options:

* live_migration_completion_timeout
"""),
    cfg.IntOpt('live_migration_downtime_steps',
               default=10,
               min=3,
               help="""
Number of incremental steps to reach max downtime value.

Will be rounded up to a minimum of 3 steps.
"""),
    cfg.IntOpt('live_migration_downtime_delay',
               default=75,
               min=3,
               help="""
Time to wait, in seconds, between each step increase of the migration
downtime.

Minimum delay is 3 seconds. Value is per GiB of guest RAM + disk to be
transferred, with lower bound of a minimum of 2 GiB per device.
"""),
    cfg.IntOpt('live_migration_completion_timeout',
               default=800,
               mutable=True,
               help="""
Time to wait, in seconds, for migration to successfully complete transferring
data before aborting the operation.

Value is per GiB of guest RAM + disk to be transferred, with lower bound of
a minimum of 2 GiB. Should usually be larger than downtime delay * downtime
steps. Set to 0 to disable timeouts.

Related options:

* live_migration_downtime
* live_migration_downtime_steps
* live_migration_downtime_delay
"""),
    cfg.IntOpt('live_migration_progress_timeout',
               default=0,
               deprecated_for_removal=True,
               deprecated_reason="Serious bugs found in this feature.",
               mutable=True,
               help="""
Time to wait, in seconds, for migration to make forward progress in
transferring data before aborting the operation.

Set to 0 to disable timeouts.

This is deprecated, and now disabled by default because we have found serious
bugs in this feature that caused false live-migration timeout failures. This
feature will be removed or replaced in a future release.
"""),
    cfg.BoolOpt('live_migration_permit_post_copy',
                default=False,
                help="""
This option allows nova to switch an on-going live migration to post-copy
mode, i.e., switch the active VM to the one on the destination node before the
migration is complete, therefore ensuring an upper bound on the memory that
needs to be transferred. Post-copy requires libvirt>=1.3.3 and QEMU>=2.5.0.

When permitted, post-copy mode will be automatically activated if a
live-migration memory copy iteration does not make percentage increase of at
least 10% over the last iteration.

The live-migration force complete API also uses post-copy when permitted. If
post-copy mode is not available, force complete falls back to pausing the VM
to ensure the live-migration operation will complete.

When using post-copy mode, if the source and destination hosts loose network
connectivity, the VM being live-migrated will need to be rebooted. For more
details, please see the Administration guide.

Related options:

    * live_migration_permit_auto_converge
"""),
    cfg.BoolOpt('live_migration_permit_auto_converge',
                default=False,
                help="""
This option allows nova to start live migration with auto converge on.

Auto converge throttles down CPU if a progress of on-going live migration
is slow. Auto converge will only be used if this flag is set to True and
post copy is not permitted or post copy is unavailable due to the version
of libvirt and QEMU in use.

Related options:

    * live_migration_permit_post_copy
"""),
    cfg.StrOpt('snapshot_image_format',
               choices=('raw', 'qcow2', 'vmdk', 'vdi'),
               help="""
Determine the snapshot image format when sending to the image service.

If set, this decides what format is used when sending the snapshot to the
image service.
If not set, defaults to same type as source image.

Possible values:

* ``raw``: RAW disk format
* ``qcow2``: KVM default disk format
* ``vmdk``: VMWare default disk format
* ``vdi``: VirtualBox default disk format
* If not set, defaults to same type as source image.
"""),
    cfg.StrOpt('disk_prefix',
               help="""
Override the default disk prefix for the devices attached to an instance.

If set, this is used to identify a free disk device name for a bus.

Possible values:

* Any prefix which will result in a valid disk device name like 'sda' or 'hda'
  for example. This is only necessary if the device names differ to the
  commonly known device name prefixes for a virtualization type such as: sd,
  xvd, uvd, vd.

Related options:

* ``virt_type``: Influences which device type is used, which determines
  the default disk prefix.
"""),
    cfg.IntOpt('wait_soft_reboot_seconds',
               default=120,
               help='Number of seconds to wait for instance to shut down after'
                    ' soft reboot request is made. We fall back to hard reboot'
                    ' if instance does not shutdown within this window.'),
    cfg.StrOpt('cpu_mode',
               choices=('host-model', 'host-passthrough', 'custom', 'none'),
               help="""
Is used to set the CPU mode an instance should have.

If virt_type="kvm|qemu", it will default to "host-model", otherwise it will
default to "none".

Possible values:

* ``host-model``: Clones the host CPU feature flags.
* ``host-passthrough``: Use the host CPU model exactly;
* ``custom``: Use a named CPU model;
* ``none``: Not set any CPU model.

Related options:

* ``cpu_model``: If ``custom`` is used for ``cpu_mode``, set this config
  option too, otherwise this would result in an error and the instance won't
  be launched.
"""),
    cfg.StrOpt('cpu_model',
               help="""
Set the name of the libvirt CPU model the instance should use.

Possible values:

* The names listed in /usr/share/libvirt/cpu_map.xml

Related options:

* ``cpu_mode``: Don't set this when ``cpu_mode`` is NOT set to ``custom``.
  This would result in an error and the instance won't be launched.
* ``virt_type``: Only the virtualization types ``kvm`` and ``qemu`` use this.
"""),
    cfg.ListOpt(
        'cpu_model_extra_flags',
        item_type=types.String(
            choices=['pcid', 'ssbd', 'virt-ssbd', 'amd-ssbd', 'amd-no-ssb'],
            ignore_case=True,
        ),
        default=[],
        help="""
This allows specifying granular CPU feature flags when specifying CPU
models.  For example, to explicitly specify the ``pcid``
(Process-Context ID, an Intel processor feature) flag to the "IvyBridge"
virtual CPU model::

    [libvirt]
    cpu_mode = custom
    cpu_model = IvyBridge
    cpu_model_extra_flags = pcid

Currently, the choice is restricted to a few options: ``pcid``,
``ssbd``, ``virt-ssbd``, ``amd-ssbd``, and ``amd-no-ssb`` (the options
are case-insensitive, so ``PCID`` is also valid, for example).  These
flags are now required to address the guest performance degradation as
a result of applying the "Meltdown" CVE fixes (``pcid``) and exposure
mitigation (``ssbd`` and related options) on affected CPU models.

Note that when using this config attribute to set the 'PCID' and
related CPU flags, not all virtual (i.e. libvirt / QEMU) CPU models
need it:

* The only virtual CPU models that include the 'PCID' capability are
  Intel "Haswell", "Broadwell", and "Skylake" variants.

* The libvirt / QEMU CPU models "Nehalem", "Westmere", "SandyBridge",
  and "IvyBridge" will _not_ expose the 'PCID' capability by default,
  even if the host CPUs by the same name include it.  I.e.  'PCID' needs
  to be explicitly specified when using the said virtual CPU models.

For more information about ``ssbd`` and related options,
please refer to the following security updates:

https://www.us-cert.gov/ncas/alerts/TA18-141A

https://www.redhat.com/archives/libvir-list/2018-May/msg01562.html

https://www.redhat.com/archives/libvir-list/2018-June/msg01111.html

For now, the ``cpu_model_extra_flags`` config attribute is valid only in
combination with ``cpu_mode`` + ``cpu_model`` options.

Besides ``custom``, the libvirt driver has two other CPU modes: The
default, ``host-model``, tells it to do the right thing with respect to
handling 'PCID' CPU flag for the guest -- *assuming* you are running
updated processor microcode, host and guest kernel, libvirt, and QEMU.
The other mode, ``host-passthrough``, checks if 'PCID' is available in
the hardware, and if so directly passes it through to the Nova guests.
Thus, in context of 'PCID', with either of these CPU modes
(``host-model`` or ``host-passthrough``), there is no need to use the
``cpu_model_extra_flags``.

Related options:

* cpu_mode
* cpu_model
"""),
    cfg.StrOpt('snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where libvirt driver will store snapshots '
                    'before uploading them to image service'),
    cfg.StrOpt('xen_hvmloader_path',
               default='/usr/lib/xen/boot/hvmloader',
               help='Location where the Xen hvmloader is kept'),
    cfg.ListOpt('disk_cachemodes',
                default=[],
                help="""
Specific cache modes to use for different disk types.

For example: file=directsync,block=none,network=writeback

For local or direct-attached storage, it is recommended that you use
writethrough (default) mode, as it ensures data integrity and has acceptable
I/O performance for applications running in the guest, especially for read
operations. However, caching mode none is recommended for remote NFS storage,
because direct I/O operations (O_DIRECT) perform better than synchronous I/O
operations (with O_SYNC). Caching mode none effectively turns all guest I/O
operations into direct I/O operations on the host, which is the NFS client in
this environment.

Possible cache modes:

* default: Same as writethrough.
* none: With caching mode set to none, the host page cache is disabled, but
  the disk write cache is enabled for the guest. In this mode, the write
  performance in the guest is optimal because write operations bypass the host
  page cache and go directly to the disk write cache. If the disk write cache
  is battery-backed, or if the applications or storage stack in the guest
  transfer data properly (either through fsync operations or file system
  barriers), then data integrity can be ensured. However, because the host
  page cache is disabled, the read performance in the guest would not be as
  good as in the modes where the host page cache is enabled, such as
  writethrough mode.
* writethrough: writethrough mode is the default caching mode. With
  caching set to writethrough mode, the host page cache is enabled, but the
  disk write cache is disabled for the guest. Consequently, this caching mode
  ensures data integrity even if the applications and storage stack in the
  guest do not transfer data to permanent storage properly (either through
  fsync operations or file system barriers). Because the host page cache is
  enabled in this mode, the read performance for applications running in the
  guest is generally better. However, the write performance might be reduced
  because the disk write cache is disabled.
* writeback: With caching set to writeback mode, both the host page cache
  and the disk write cache are enabled for the guest. Because of this, the
  I/O performance for applications running in the guest is good, but the data
  is not protected in a power failure. As a result, this caching mode is
  recommended only for temporary data where potential data loss is not a
  concern.
* directsync: Like "writethrough", but it bypasses the host page cache.
* unsafe: Caching mode of unsafe ignores cache transfer operations
  completely. As its name implies, this caching mode should be used only for
  temporary data where data loss is not a concern. This mode can be useful for
  speeding up guest installations, but you should switch to another caching
  mode in production environments.
"""),
    cfg.StrOpt('rng_dev_path',
               help='A path to a device that will be used as source of '
                    'entropy on the host. Permitted options are: '
                    '/dev/random or /dev/hwrng'),
    cfg.ListOpt('hw_machine_type',
                help='For qemu or KVM guests, set this option to specify '
                     'a default machine type per host architecture. '
                     'You can find a list of supported machine types '
                     'in your environment by checking the output of '
                     'the "virsh capabilities"command. The format of the '
                     'value for this config option is host-arch=machine-type. '
                     'For example: x86_64=machinetype1,armv7l=machinetype2'),
    cfg.StrOpt('sysinfo_serial',
               default='auto',
               choices=('none', 'os', 'hardware', 'auto'),
               help='The data source used to the populate the host "serial" '
                    'UUID exposed to guest in the virtual BIOS.'),
    cfg.IntOpt('mem_stats_period_seconds',
               default=10,
               help='A number of seconds to memory usage statistics period. '
                    'Zero or negative value mean to disable memory usage '
                    'statistics.'),
    cfg.ListOpt('uid_maps',
                default=[],
                help='List of uid targets and ranges.'
                     'Syntax is guest-uid:host-uid:count'
                     'Maximum of 5 allowed.'),
    cfg.ListOpt('gid_maps',
                default=[],
                help='List of guid targets and ranges.'
                     'Syntax is guest-gid:host-gid:count'
                     'Maximum of 5 allowed.'),
    cfg.IntOpt('realtime_scheduler_priority',
               default=1,
               help='In a realtime host context vCPUs for guest will run in '
                    'that scheduling priority. Priority depends on the host '
                    'kernel (usually 1-99)'),
    cfg.ListOpt('enabled_perf_events',
               default=[],
               help= """
This is a performance event list which could be used as monitor. These events
will be passed to libvirt domain xml while creating a new instances.
Then event statistics data can be collected from libvirt.  The minimum
libvirt version is 2.0.0. For more information about `Performance monitoring
events`, refer https://libvirt.org/formatdomain.html#elementsPerf .

Possible values:
* A string list. For example: ``enabled_perf_events = cmt, mbml, mbmt``
  The supported events list can be found in
  https://libvirt.org/html/libvirt-libvirt-domain.html ,
  which you may need to search key words ``VIR_PERF_PARAM_*``
"""),
]

libvirt_imagebackend_opts = [
    cfg.StrOpt('images_type',
               default='default',
               choices=('raw', 'flat', 'qcow2', 'lvm', 'rbd', 'ploop',
                        'default'),
               help="""
VM Images format.

If default is specified, then use_cow_images flag is used instead of this
one.

Related options:

* virt.use_cow_images
* images_volume_group
"""),
    cfg.StrOpt('images_volume_group',
               help="""
LVM Volume Group that is used for VM images, when you specify images_type=lvm

Related options:

* images_type
"""),
    cfg.BoolOpt('sparse_logical_volumes',
                default=False,
                help="""
Create sparse logical volumes (with virtualsize) if this flag is set to True.
"""),
    cfg.StrOpt('images_rbd_pool',
               default='rbd',
               help='The RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('images_rbd_ceph_conf',
               default='',  # default determined by librados
               help='Path to the ceph configuration file to use'),
    cfg.StrOpt('hw_disk_discard',
               choices=('ignore', 'unmap'),
               help="""
Discard option for nova managed disks.

Requires:

* Libvirt >= 1.0.6
* Qemu >= 1.5 (raw format)
* Qemu >= 1.6 (qcow2 format)
"""),
]

libvirt_imagecache_opts = [
    cfg.StrOpt('image_info_filename_pattern',
               default='$instances_path/$image_cache_subdirectory_name/'
                       '%(image)s.info',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='Image info files are no longer used by the '
                                 'image cache',
               help='Allows image information files to be stored in '
                    'non-standard locations'),
    cfg.IntOpt('remove_unused_resized_minimum_age_seconds',
               default=3600,
               help='Unused resized base images younger than this will not be '
                    'removed'),
    cfg.BoolOpt('checksum_base_images',
                default=False,
                deprecated_for_removal=True,
                deprecated_since='14.0.0',
                deprecated_reason='The image cache no longer periodically '
                                  'calculates checksums of stored images. '
                                  'Data integrity can be checked at the block '
                                  'or filesystem level.',
                help='Write a checksum for files in _base to disk'),
    cfg.IntOpt('checksum_interval_seconds',
               default=3600,
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='The image cache no longer periodically '
                                 'calculates checksums of stored images. '
                                 'Data integrity can be checked at the block '
                                 'or filesystem level.',
               help='How frequently to checksum base images'),
]

libvirt_lvm_opts = [
    cfg.StrOpt('volume_clear',
               default='zero',
               choices=('none', 'zero', 'shred'),
               help="""
Method used to wipe ephemeral disks when they are deleted. Only takes effect
if LVM is set as backing storage.

Possible values:

* none - do not wipe deleted volumes
* zero - overwrite volumes with zeroes
* shred - overwrite volume repeatedly

Related options:

* images_type - must be set to ``lvm``
* volume_clear_size
"""),
    cfg.IntOpt('volume_clear_size',
               default=0,
               min=0,
               help="""
Size of area in MiB, counting from the beginning of the allocated volume,
that will be cleared using method set in ``volume_clear`` option.

Possible values:

* 0 - clear whole volume
* >0 - clear specified amount of MiB

Related options:

* images_type - must be set to ``lvm``
* volume_clear - must be set and the value must be different than ``none``
  for this option to have any impact
"""),
]

libvirt_utils_opts = [
    cfg.BoolOpt('snapshot_compression',
                default=False,
                help="""
Enable snapshot compression for ``qcow2`` images.

Note: you can set ``snapshot_image_format`` to ``qcow2`` to force all
snapshots to be in ``qcow2`` format, independently from their original image
type.

Related options:

* snapshot_image_format
"""),
]

libvirt_vif_opts = [
    cfg.BoolOpt('use_virtio_for_bridges',
                default=True,
                help='Use virtio for bridge interfaces with KVM/QEMU'),
]

libvirt_volume_opts = [
    cfg.BoolOpt('volume_use_multipath',
                default=False,
                deprecated_name='iscsi_use_multipath',
                help="""
Use multipath connection of the iSCSI or FC volume

Volumes can be connected in the LibVirt as multipath devices. This will
provide high availability and fault tolerance.
"""),
    cfg.IntOpt('num_volume_scan_tries',
               deprecated_name='num_iscsi_scan_tries',
               default=5,
               help="""
Number of times to scan given storage protocol to find volume.
"""),
]

libvirt_volume_aoe_opts = [
    cfg.IntOpt('num_aoe_discover_tries',
               default=3,
               help="""
Number of times to rediscover AoE target to find volume.

Nova provides support for block storage attaching to hosts via AOE (ATA over
Ethernet). This option allows the user to specify the maximum number of retry
attempts that can be made to discover the AoE device.
""")
]

libvirt_volume_iscsi_opts = [
    cfg.StrOpt('iscsi_iface',
               deprecated_name='iscsi_transport',
               help="""
The iSCSI transport iface to use to connect to target in case offload support
is desired.

Default format is of the form <transport_name>.<hwaddress> where
<transport_name> is one of (be2iscsi, bnx2i, cxgb3i, cxgb4i, qla4xxx, ocs) and
<hwaddress> is the MAC address of the interface and can be generated via the
iscsiadm -m iface command. Do not confuse the iscsi_iface parameter to be
provided here with the actual transport name.
""")
# iser is also supported, but use LibvirtISERVolumeDriver
# instead
]

libvirt_volume_iser_opts = [
    cfg.IntOpt('num_iser_scan_tries',
               default=5,
               help="""
Number of times to scan iSER target to find volume.

iSER is a server network protocol that extends iSCSI protocol to use Remote
Direct Memory Access (RDMA). This option allows the user to specify the maximum
number of scan attempts that can be made to find iSER volume.
"""),
    cfg.BoolOpt('iser_use_multipath',
                default=False,
                help="""
Use multipath connection of the iSER volume.

iSER volumes can be connected as multipath devices. This will provide high
availability and fault tolerance.
""")
]

libvirt_volume_net_opts = [
    cfg.StrOpt('rbd_user',
               help="""
The RADOS client name for accessing rbd(RADOS Block Devices) volumes.

Libvirt will refer to this user when connecting and authenticating with
the Ceph RBD server.
"""),
    cfg.StrOpt('rbd_secret_uuid',
               help="""
The libvirt UUID of the secret for the rbd_user volumes.
"""),
]

libvirt_volume_nfs_opts = [
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help="""
Directory where the NFS volume is mounted on the compute node.
The default is 'mnt' directory of the location where nova's Python module
is installed.

NFS provides shared storage for the OpenStack Block Storage service.

Possible values:

* A string representing absolute path of mount point.
"""),
    cfg.StrOpt('nfs_mount_options',
               help="""
Mount options passed to the NFS client. See section of the nfs man page
for details.

Mount options controls the way the filesystem is mounted and how the
NFS client behaves when accessing files on this mount point.

Possible values:

* Any string representing mount options separated by commas.
* Example string: vers=3,lookupcache=pos
"""),
]

libvirt_volume_quobyte_opts = [
    cfg.StrOpt('quobyte_mount_point_base',
               default=paths.state_path_def('mnt'),
               help="""
Directory where the Quobyte volume is mounted on the compute node.

Nova supports Quobyte volume driver that enables storing Block Storage
service volumes on a Quobyte storage back end. This Option sepcifies the
path of the directory where Quobyte volume is mounted.

Possible values:

* A string representing absolute path of mount point.
"""),
    cfg.StrOpt('quobyte_client_cfg',
               help='Path to a Quobyte Client configuration file.'),
]

libvirt_volume_smbfs_opts = [
    cfg.StrOpt('smbfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help="""
Directory where the SMBFS shares are mounted on the compute node.
"""),
    cfg.StrOpt('smbfs_mount_options',
               default='',
               help="""
Mount options passed to the SMBFS client.

Provide SMBFS options as a single string containing all parameters.
See mount.cifs man page for  details. Note that the libvirt-qemu ``uid``
and ``gid`` must be specified.
"""),
]

libvirt_remotefs_opts = [
    cfg.StrOpt('remote_filesystem_transport',
               default='ssh',
               choices=('ssh', 'rsync'),
               help="""
libvirt's transport method for remote file operations.

Because libvirt cannot use RPC to copy files over network to/from other
compute nodes, other method must be used for:

* creating directory on remote host
* creating file on remote host
* removing file from remote host
* copying file to remote host
""")
]

libvirt_volume_vzstorage_opts = [
    cfg.StrOpt('vzstorage_mount_point_base',
               default=paths.state_path_def('mnt'),
               help="""
Directory where the Virtuozzo Storage clusters are mounted on the compute
node.

This option defines non-standard mountpoint for Vzstorage cluster.

Related options:

* vzstorage_mount_* group of parameters
"""
              ),
    cfg.StrOpt('vzstorage_mount_user',
               default='stack',
               help="""
Mount owner user name.

This option defines the owner user of Vzstorage cluster mountpoint.

Related options:

* vzstorage_mount_* group of parameters
"""
              ),
    cfg.StrOpt('vzstorage_mount_group',
               default='qemu',
               help="""
Mount owner group name.

This option defines the owner group of Vzstorage cluster mountpoint.

Related options:

* vzstorage_mount_* group of parameters
"""
              ),
    cfg.StrOpt('vzstorage_mount_perms',
               default='0770',
               help="""
Mount access mode.

This option defines the access bits of Vzstorage cluster mountpoint,
in the format similar to one of chmod(1) utility, like this: 0770.
It consists of one to four digits ranging from 0 to 7, with missing
lead digits assumed to be 0's.

Related options:

* vzstorage_mount_* group of parameters
"""
              ),
    cfg.StrOpt('vzstorage_log_path',
               default='/var/log/vstorage/%(cluster_name)s/nova.log.gz',
               help="""
Path to vzstorage client log.

This option defines the log of cluster operations,
it should include "%(cluster_name)s" template to separate
logs from multiple shares.

Related options:

* vzstorage_mount_opts may include more detailed logging options.
"""
              ),
    cfg.StrOpt('vzstorage_cache_path',
               default=None,
               help="""
Path to the SSD cache file.

You can attach an SSD drive to a client and configure the drive to store
a local cache of frequently accessed data. By having a local cache on a
client's SSD drive, you can increase the overall cluster performance by
up to 10 and more times.
WARNING! There is a lot of SSD models which are not server grade and
may loose arbitrary set of data changes on power loss.
Such SSDs should not be used in Vstorage and are dangerous as may lead
to data corruptions and inconsistencies. Please consult with the manual
on which SSD models are known to be safe or verify it using
vstorage-hwflush-check(1) utility.

This option defines the path which should include "%(cluster_name)s"
template to separate caches from multiple shares.

Related options:

* vzstorage_mount_opts may include more detailed cache options.
"""
              ),
    cfg.ListOpt('vzstorage_mount_opts',
                default=[],
               help="""
Extra mount options for pstorage-mount

For full description of them, see
https://static.openvz.org/vz-man/man1/pstorage-mount.1.gz.html
Format is a python string representation of arguments list, like:
"[\'-v\', \'-R\', \'500\']"
Shouldn\'t include -c, -l, -C, -u, -g and -m as those have
explicit vzstorage_* options.

Related options:

* All other vzstorage_* options
"""
),
]

ALL_OPTS = list(itertools.chain(
    libvirt_general_opts,
    libvirt_imagebackend_opts,
    libvirt_imagecache_opts,
    libvirt_lvm_opts,
    libvirt_utils_opts,
    libvirt_vif_opts,
    libvirt_volume_opts,
    libvirt_volume_aoe_opts,
    libvirt_volume_iscsi_opts,
    libvirt_volume_iser_opts,
    libvirt_volume_net_opts,
    libvirt_volume_nfs_opts,
    libvirt_volume_quobyte_opts,
    libvirt_volume_smbfs_opts,
    libvirt_remotefs_opts,
    libvirt_volume_vzstorage_opts,
))


def register_opts(conf):
    conf.register_group(libvirt_group)
    conf.register_opts(ALL_OPTS, group=libvirt_group)


def list_opts():
    return {libvirt_group: ALL_OPTS}
