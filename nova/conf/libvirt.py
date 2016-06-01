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

from nova.conf import paths

from oslo_config import cfg

# Downtime period in milliseconds
LIVE_MIGRATION_DOWNTIME_MIN = 100
# Step count
LIVE_MIGRATION_DOWNTIME_STEPS_MIN = 3
# Delay in seconds
LIVE_MIGRATION_DOWNTIME_DELAY_MIN = 10

libvirt_group = cfg.OptGroup("libvirt",
                             title="Libvirt Options",
                             help="""
Libvirt options allows cloud administrator to configure related
libvirt hypervisor driver to be used within an OpenStack deployment.
""")

libvirt_general_opts = [
    cfg.StrOpt('rescue_image_id',
               help='Rescue ami image. This will not be used if an image id '
                    'is provided by the user.'),
    cfg.StrOpt('rescue_kernel_id',
               help='Rescue aki image'),
    cfg.StrOpt('rescue_ramdisk_id',
               help='Rescue ari image'),
    cfg.StrOpt('virt_type',
               default='kvm',
               choices=('kvm', 'lxc', 'qemu', 'uml', 'xen', 'parallels'),
               help='Libvirt domain type'),
    cfg.StrOpt('connection_uri',
               default='',
               help='Override the default libvirt URI '
                    '(which is dependent on virt_type)'),
    cfg.BoolOpt('inject_password',
                default=False,
                help='Inject the admin password at boot time, '
                     'without an agent.'),
    cfg.BoolOpt('inject_key',
                default=False,
                help='Inject the ssh public key at boot time'),
    cfg.IntOpt('inject_partition',
               default=-2,
               help='The partition to inject to : '
                    '-2 => disable, -1 => inspect (libguestfs only), '
                    '0 => not partitioned, >0 => partition number'),
    cfg.BoolOpt('use_usb_tablet',
                default=True,
                help='Sync virtual and real mouse cursors in Windows VMs'),
    cfg.StrOpt('live_migration_inbound_addr',
               help='Live migration target ip or hostname '
                    '(if this option is set to None, which is the default, '
                    'the hostname of the migration target '
                    'compute node will be used)'),
    cfg.StrOpt('live_migration_uri',
               help='Override the default libvirt live migration target URI '
                    '(which is dependent on virt_type) '
                    '(any included "%s" is replaced with '
                    'the migration target hostname)'),
    cfg.StrOpt('live_migration_flag',
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER, '
                       'VIR_MIGRATE_LIVE, VIR_MIGRATE_TUNNELLED',
               help='Migration flags to be set for live migration',
               deprecated_for_removal=True,
               deprecated_reason='The correct live migration flags can be '
                                 'inferred from the new '
                                 'live_migration_tunnelled config option. '
                                 'live_migration_flag will be removed to '
                                 'avoid potential misconfiguration.'),
    cfg.StrOpt('block_migration_flag',
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER, '
                       'VIR_MIGRATE_LIVE, VIR_MIGRATE_TUNNELLED, '
                       'VIR_MIGRATE_NON_SHARED_INC',
               help='Migration flags to be set for block migration',
               deprecated_for_removal=True,
               deprecated_reason='The correct block migration flags can be '
                                 'inferred from the new '
                                 'live_migration_tunnelled config option. '
                                 'block_migration_flag will be removed to '
                                 'avoid potential misconfiguration.'),
    cfg.BoolOpt('live_migration_tunnelled',
                help='Whether to use tunnelled migration, where migration '
                     'data is transported over the libvirtd connection. If '
                     'True, we use the VIR_MIGRATE_TUNNELLED migration flag, '
                     'avoiding the need to configure the network to allow '
                     'direct hypervisor to hypervisor communication. If '
                     'False, use the native transport. If not set, Nova '
                     'will choose a sensible default based on, for example '
                     'the availability of native encryption support in the '
                     'hypervisor.'),
    cfg.IntOpt('live_migration_bandwidth',
               default=0,
               help='Maximum bandwidth(in MiB/s) to be used during migration. '
                    'If set to 0, will choose a suitable default. Some '
                    'hypervisors do not support this feature and will return '
                    'an error if bandwidth is not 0. Please refer to the '
                    'libvirt documentation for further details'),
    cfg.IntOpt('live_migration_downtime',
               default=500,
               help='Maximum permitted downtime, in milliseconds, for live '
                    'migration switchover. Will be rounded up to a minimum '
                    'of %dms. Use a large value if guest liveness is '
                    'unimportant.' % LIVE_MIGRATION_DOWNTIME_MIN),
    cfg.IntOpt('live_migration_downtime_steps',
               default=10,
               help='Number of incremental steps to reach max downtime value. '
                    'Will be rounded up to a minimum of %d steps' %
                    LIVE_MIGRATION_DOWNTIME_STEPS_MIN),
    cfg.IntOpt('live_migration_downtime_delay',
               default=75,
               help='Time to wait, in seconds, between each step increase '
                    'of the migration downtime. Minimum delay is %d seconds. '
                    'Value is per GiB of guest RAM + disk to be transferred, '
                    'with lower bound of a minimum of 2 GiB per device' %
                    LIVE_MIGRATION_DOWNTIME_DELAY_MIN),
    cfg.IntOpt('live_migration_completion_timeout',
               default=800,
               help='Time to wait, in seconds, for migration to successfully '
                    'complete transferring data before aborting the '
                    'operation. Value is per GiB of guest RAM + disk to be '
                    'transferred, with lower bound of a minimum of 2 GiB. '
                    'Should usually be larger than downtime delay * downtime '
                    'steps. Set to 0 to disable timeouts.'),
    cfg.IntOpt('live_migration_progress_timeout',
               default=150,
               help='Time to wait, in seconds, for migration to make forward '
                    'progress in transferring data before aborting the '
                    'operation. Set to 0 to disable timeouts.'),
    cfg.StrOpt('snapshot_image_format',
               choices=('raw', 'qcow2', 'vmdk', 'vdi'),
               help='Snapshot image format. Defaults to same as source image'),
    cfg.StrOpt('disk_prefix',
               help='Override the default disk prefix for the devices attached'
                    ' to a server, which is dependent on virt_type. '
                    '(valid options are: sd, xvd, uvd, vd)'),
    cfg.IntOpt('wait_soft_reboot_seconds',
               default=120,
               help='Number of seconds to wait for instance to shut down after'
                    ' soft reboot request is made. We fall back to hard reboot'
                    ' if instance does not shutdown within this window.'),
    cfg.StrOpt('cpu_mode',
               choices=('host-model', 'host-passthrough', 'custom', 'none'),
               help='Set to "host-model" to clone the host CPU feature flags; '
                    'to "host-passthrough" to use the host CPU model exactly; '
                    'to "custom" to use a named CPU model; '
                    'to "none" to not set any CPU model. '
                    'If virt_type="kvm|qemu", it will default to '
                    '"host-model", otherwise it will default to "none"'),
    cfg.StrOpt('cpu_model',
               help='Set to a named libvirt CPU model (see names listed '
                    'in /usr/share/libvirt/cpu_map.xml). Only has effect if '
                    'cpu_mode="custom" and virt_type="kvm|qemu"'),
    cfg.StrOpt('snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where libvirt driver will store snapshots '
                    'before uploading them to image service'),
    cfg.StrOpt('xen_hvmloader_path',
               default='/usr/lib/xen/boot/hvmloader',
               help='Location where the Xen hvmloader is kept'),
    cfg.ListOpt('disk_cachemodes',
                default=[],
                help='Specific cachemodes to use for different disk types '
                     'e.g: file=directsync,block=none'),
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
                    'kernel (usually 1-99)')
]

libvirt_imagebackend_opts = [
    cfg.StrOpt('images_type',
               default='default',
               choices=('raw', 'flat', 'qcow2', 'lvm', 'rbd', 'ploop',
                        'default'),
               help='VM Images format. If default is specified, then'
                    ' use_cow_images flag is used instead of this one.'),
    cfg.StrOpt('images_volume_group',
               help='LVM Volume Group that is used for VM images, when you'
                    ' specify images_type=lvm.'),
    cfg.BoolOpt('sparse_logical_volumes',
                default=False,
                help='Create sparse logical volumes (with virtualsize)'
                     ' if this flag is set to True.'),
    cfg.StrOpt('images_rbd_pool',
               default='rbd',
               help='The RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('images_rbd_ceph_conf',
               default='',  # default determined by librados
               help='Path to the ceph configuration file to use'),
    cfg.StrOpt('hw_disk_discard',
               choices=('ignore', 'unmap'),
               help='Discard option for nova managed disks. Need'
                    ' Libvirt(1.0.6) Qemu1.5 (raw format) Qemu1.6(qcow2'
                    ' format)'),
]

libvirt_imagecache_opts = [
    cfg.StrOpt('image_info_filename_pattern',
               default='$instances_path/$image_cache_subdirectory_name/'
                       '%(image)s.info',
               help='Allows image information files to be stored in '
                    'non-standard locations',
               deprecated_for_removal=True,
               deprecated_reason='Image info files are no longer used by the '
                                 'image cache'),
    cfg.IntOpt('remove_unused_resized_minimum_age_seconds',
               default=3600,
               help='Unused resized base images younger than this will not be '
                    'removed'),
    cfg.BoolOpt('checksum_base_images',
                default=False,
                help='Write a checksum for files in _base to disk',
                deprecated_for_removal=True,
                deprecated_reason='The image cache no longer periodically '
                                  'calculates checksums of stored images. '
                                  'Data integrity can be checked at the block '
                                  'or filesystem level.'),
    cfg.IntOpt('checksum_interval_seconds',
               default=3600,
               help='How frequently to checksum base images',
               deprecated_for_removal=True,
               deprecated_reason='The image cache no longer periodically '
                                 'calculates checksums of stored images. '
                                 'Data integrity can be checked at the block '
                                 'or filesystem level.'),
]

libvirt_lvm_opts = [
    cfg.StrOpt('volume_clear',
               default='zero',
               choices=('none', 'zero', 'shred'),
               help='Method used to wipe old volumes.'),
    cfg.IntOpt('volume_clear_size',
               default=0,
               help='Size in MiB to wipe at start of old volumes. 0 => all'),
]

libvirt_utils_opts = [
    cfg.BoolOpt('snapshot_compression',
                default=False,
                help='Compress snapshot images when possible. This '
                     'currently applies exclusively to qcow2 images'),
]

libvirt_vif_opts = [
    cfg.BoolOpt('use_virtio_for_bridges',
                default=True,
                help='Use virtio for bridge interfaces with KVM/QEMU'),
]

libvirt_volume_opts = [
    cfg.ListOpt('qemu_allowed_storage_drivers',
                default=[],
                help='Protocols listed here will be accessed directly '
                     'from QEMU. Currently supported protocols: [gluster]'),
]

libvirt_volume_aoe_opts = [
    cfg.IntOpt('num_aoe_discover_tries',
               default=3,
               help='Number of times to rediscover AoE target to find volume'),
]

libvirt_volume_glusterfs_opts = [
    cfg.StrOpt('glusterfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the glusterfs volume is mounted on the '
                    'compute node'),
]

libvirt_volume_iscsi_opts = [
    cfg.IntOpt('num_iscsi_scan_tries',
               default=5,
               help='Number of times to rescan iSCSI target to find volume'),
    cfg.BoolOpt('iscsi_use_multipath',
                default=False,
                help='Use multipath connection of the iSCSI or FC volume'),
    cfg.StrOpt('iscsi_iface',
               deprecated_name='iscsi_transport',
               help='The iSCSI transport iface to use to connect to target in '
                    'case offload support is desired. Default format is of '
                    'the form <transport_name>.<hwaddress> where '
                    '<transport_name> is one of (be2iscsi, bnx2i, cxgb3i, '
                    'cxgb4i, qla4xxx, ocs) and <hwaddress> is the MAC address '
                    'of the interface and can be generated via the '
                    'iscsiadm -m iface command. Do not confuse the '
                    'iscsi_iface parameter to be provided here with the '
                    'actual transport name.'),
    # iser is also supported, but use LibvirtISERVolumeDriver
    # instead
]

libvirt_volume_iser_opts = [
    cfg.IntOpt('num_iser_scan_tries',
               default=5,
               help='Number of times to rescan iSER target to find volume'),
    cfg.BoolOpt('iser_use_multipath',
                default=False,
                help='Use multipath connection of the iSER volume'),
]

libvirt_volume_net_opts = [
    cfg.StrOpt('rbd_user',
               help='The RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               help='The libvirt UUID of the secret for the rbd_user'
                    'volumes'),
]

libvirt_volume_nfs_opts = [
    cfg.StrOpt('nfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the NFS volume is mounted on the'
                    ' compute node'),
    cfg.StrOpt('nfs_mount_options',
               help='Mount options passed to the NFS client. See section '
                    'of the nfs man page for details'),
]

libvirt_volume_quobyte_opts = [
    cfg.StrOpt('quobyte_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the Quobyte volume is mounted on the '
                    'compute node'),
    cfg.StrOpt('quobyte_client_cfg',
               help='Path to a Quobyte Client configuration file.'),
]

libvirt_volume_scality_opts = [
    cfg.StrOpt('scality_sofs_config',
               help='Path or URL to Scality SOFS configuration file'),
    cfg.StrOpt('scality_sofs_mount_point',
               default='$state_path/scality',
               help='Base dir where Scality SOFS shall be mounted'),
]

libvirt_volume_smbfs_opts = [
    cfg.StrOpt('smbfs_mount_point_base',
               default=paths.state_path_def('mnt'),
               help='Directory where the SMBFS shares are mounted on the '
                    'compute node'),
    cfg.StrOpt('smbfs_mount_options',
               default='',
               help='Mount options passed to the SMBFS client. See '
                    'mount.cifs man page for details. Note that the '
                    'libvirt-qemu uid and gid must be specified.'),
]

libvirt_remotefs_opts = [
    cfg.StrOpt('remote_filesystem_transport',
               default='ssh',
               choices=('ssh', 'rsync'),
               help='Use ssh or rsync transport for creating, copying, '
                    'removing files on the remote host.'),
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
    libvirt_volume_glusterfs_opts,
    libvirt_volume_iscsi_opts,
    libvirt_volume_iser_opts,
    libvirt_volume_net_opts,
    libvirt_volume_nfs_opts,
    libvirt_volume_quobyte_opts,
    libvirt_volume_scality_opts,
    libvirt_volume_smbfs_opts,
    libvirt_remotefs_opts
))


def register_opts(conf):
    conf.register_group(libvirt_group)
    conf.register_opts(ALL_OPTS, group=libvirt_group)


def list_opts():
    return {libvirt_group: ALL_OPTS}
