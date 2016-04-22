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


def register_opts(conf):
    conf.register_group(libvirt_group)
    conf.register_opts(libvirt_general_opts, group=libvirt_group)


# TODO(hieulq): if not using group name, oslo config will generate duplicate
# config section. This need to be remove when completely move all libvirt
# options to this place.
def list_opts():
    return {libvirt_group.name: libvirt_general_opts}
