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
from oslo_utils import units

xenserver_group = cfg.OptGroup('xenserver', title='Xenserver Options')

xenapi_agent_opts = [
    cfg.IntOpt('agent_timeout',
               default=30,
               help="""
               Number of seconds to wait for agent's reply to a request.

               Nova configures/performs certain administrative actions on a
               server with the help of an agent that's installed on the server.
               The communication between Nova and the agent is achieved via
               sharing messages, called records, over xenstore, a shared
               storage across all the domains on a Xenserver host.
               Operations performed by the agent on behalf of nova are:
               'version',' key_init', 'password','resetnetwork','inject_file',
               and 'agentupdate'.

               To perform one of the above operations, the xapi 'agent' plugin
               writes the command and its associated parameters to a certain
               location known to the domain and awaits response. On being
               notified of the message, the agent performs appropriate actions
               on the server and writes the result back to xenstore.
               This result is then read by the xapi 'agent' plugin to
               determine the success/failure of the operation.

               This config option determines how long the xapi 'agent' plugin
               shall wait to read the response off of xenstore for a given
               request/command. If the agent on the instance fails to write
               the result in this time period, the operation is considered to
               have timed out.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * ``agent_version_timeout``
               * ``agent_resetnetwork_timeout``

               """),
    cfg.IntOpt('agent_version_timeout',
               default=300,
               help="""
               Number of seconds to wait for agent't reply to version request.

               This indicates the amount of time xapi 'agent' plugin waits
               for the agent to respond to the 'version' request specifically.
               The generic timeout for agent communication ``agent_timeout``
               is ignored in this case.

               During the build process the 'version' request is used to
               determine if the agent is available/operational to perform
               other requests such as 'resetnetwork', 'password', 'key_init'
               and 'inject_file'. If the 'version' call fails, the other
               configuration is skipped. So, this configuration option can
               also be interpreted as time in which agent is expected to be
               fully operational.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * None

               """),
    cfg.IntOpt('agent_resetnetwork_timeout',
               default=60,
               help="""
               Number of seconds to wait for agent's reply to resetnetwork
               request.

               This indicates the amount of time xapi 'agent' plugin waits
               for the agent to respond to the 'resetnetwork' request
               specifically. The generic timeout for agent communication
               ``agent_timeout`` is ignored in this case.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * None

               """),
    cfg.StrOpt('agent_path',
               default='usr/sbin/xe-update-networking',
               help="""
               Path to locate guest agent on the server.

               Specifies the path in which the XenAPI guest agent should be
               located. If the agent is present, network configuration is not
               injected into the image.
               Used if compute_driver=xenapi.XenAPIDriver and
               flat_injected=True.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * A valid path

               Related options:
               * ``flat_injected``
               * ``compute_driver``

               """),
    cfg.BoolOpt('disable_agent',
                default=False,
                help="""
                Disables the use of XenAPI agent.

                This configuration option suggests whether the use of agent
                should be enabled or not regardless of what image properties
                are present. Image properties have an effect only when this
                is set to ``True``. Read description of config option
                ``use_agent_default`` for more information.

                Services which consume this:
                * ``nova-compute``

                Possible values:
                * True
                * False

                Related options:
                * ``use_agent_default``

                """),
    cfg.BoolOpt('use_agent_default',
                default=False,
                help="""
                Whether or not to use the agent by default when its usage is
                enabled but not indicated by the image.

                The use of XenAPI agent can be disabled altogether using the
                configuration option ``disable_agent``. However, if it is not
                disabled, the use of an agent can still be controlled by the
                image in use through one of its properties,
                ``xenapi_use_agent``. If this property is either not present
                or specified incorrectly on the image, the use of agent is
                determined by this configuration option.

                Note that if this configuration is set to ``True`` when the
                agent is not present, the boot times will increase
                significantly.

                Services which consume this:
                * ``nova-compute``

                Possible values:
                * True
                * False

                Related options:
                * ``disable_agent``

                """),
]


xenapi_session_opts = [
    cfg.IntOpt('login_timeout',
               default=10,
               help='Timeout in seconds for XenAPI login.'),
    cfg.IntOpt('connection_concurrent',
               default=5,
               help='Maximum number of concurrent XenAPI connections. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
]


xenapi_torrent_opts = [
    cfg.StrOpt('torrent_base_url',
               help='Base URL for torrent files; must contain a slash'
                    ' character (see RFC 1808, step 6)'),
    cfg.FloatOpt('torrent_seed_chance',
                 default=1.0,
                 help='Probability that peer will become a seeder.'
                      ' (1.0 = 100%)'),
    cfg.IntOpt('torrent_seed_duration',
               default=3600,
               help='Number of seconds after downloading an image via'
                    ' BitTorrent that it should be seeded for other peers.'),
    cfg.IntOpt('torrent_max_last_accessed',
               default=86400,
               help='Cached torrent files not accessed within this number of'
                    ' seconds can be reaped'),
    cfg.IntOpt('torrent_listen_port_start',
               default=6881,
               min=1,
               max=65535,
               help='Beginning of port range to listen on'),
    cfg.IntOpt('torrent_listen_port_end',
               default=6891,
               min=1,
               max=65535,
               help='End of port range to listen on'),
    cfg.IntOpt('torrent_download_stall_cutoff',
               default=600,
               help='Number of seconds a download can remain at the same'
                    ' progress percentage w/o being considered a stall'),
    cfg.IntOpt('torrent_max_seeder_processes_per_host',
               default=1,
               help='Maximum number of seeder processes to run concurrently'
                    ' within a given dom0. (-1 = no limit)')
]


xenapi_vm_utils_opts = [
    cfg.StrOpt('cache_images',
               default='all',
               choices=('all', 'some', 'none'),
               help='Cache glance images locally. `all` will cache all'
                    ' images, `some` will only cache images that have the'
                    ' image_property `cache_in_nova=True`, and `none` turns'
                    ' off caching entirely'),
    cfg.IntOpt('image_compression_level',
               min=1,
               max=9,
               help='Compression level for images, e.g., 9 for gzip -9.'
                    ' Range is 1-9, 9 being most compressed but most CPU'
                    ' intensive on dom0.'),
    cfg.StrOpt('default_os_type',
               default='linux',
               help='Default OS type'),
    cfg.IntOpt('block_device_creation_timeout',
               default=10,
               help='Time to wait for a block device to be created'),
    cfg.IntOpt('max_kernel_ramdisk_size',
               default=16 * units.Mi,
               help='Maximum size in bytes of kernel or ramdisk images'),
    cfg.StrOpt('sr_matching_filter',
               default='default-sr:true',
               help='Filter for finding the SR to be used to install guest '
                    'instances on. To use the Local Storage in default '
                    'XenServer/XCP installations set this flag to '
                    'other-config:i18n-key=local-storage. To select an SR '
                    'with a different matching criteria, you could set it to '
                    'other-config:my_favorite_sr=true. On the other hand, to '
                    'fall back on the Default SR, as displayed by XenCenter, '
                    'set this flag to: default-sr:true'),
    cfg.BoolOpt('sparse_copy',
                default=True,
                help='Whether to use sparse_copy for copying data on a '
                     'resize down (False will use standard dd). This speeds '
                     'up resizes down considerably since large runs of zeros '
                     'won\'t have to be rsynced'),
    cfg.IntOpt('num_vbd_unplug_retries',
               default=10,
               help='Maximum number of retries to unplug VBD. if <=0, '
                    'should try once and no retry'),
    cfg.StrOpt('torrent_images',
               default='none',
               choices=('all', 'some', 'none'),
               help='Whether or not to download images via Bit Torrent.'),
    cfg.StrOpt('ipxe_network_name',
               help='Name of network to use for booting iPXE ISOs'),
    cfg.StrOpt('ipxe_boot_menu_url',
               help='URL to the iPXE boot menu'),
    cfg.StrOpt('ipxe_mkisofs_cmd',
               default='mkisofs',
               help='Name and optionally path of the tool used for '
                    'ISO image creation'),
    ]


xenapi_opts = [
    cfg.StrOpt('connection_url',
               help='URL for connection to XenServer/Xen Cloud Platform. '
                    'A special value of unix://local can be used to connect '
                    'to the local unix socket.  '
                    'Required if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('connection_username',
               default='root',
               help='Username for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('connection_password',
               help='Password for connection to XenServer/Xen Cloud Platform. '
                    'Used only if compute_driver=xenapi.XenAPIDriver',
               secret=True),
    cfg.FloatOpt('vhd_coalesce_poll_interval',
                 default=5.0,
                 help='The interval used for polling of coalescing vhds. '
                      'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.BoolOpt('check_host',
                default=True,
                help='Ensure compute service is running on host XenAPI '
                     'connects to.'),
    cfg.IntOpt('vhd_coalesce_max_attempts',
               default=20,
               help='Max number of times to poll for VHD to coalesce. '
                    'Used only if compute_driver=xenapi.XenAPIDriver'),
    cfg.StrOpt('sr_base_path',
               default='/var/run/sr-mount',
               help='Base path to the storage repository'),
    cfg.StrOpt('target_host',
               help='The iSCSI Target Host'),
    cfg.StrOpt('target_port',
               default='3260',
               help='The iSCSI Target Port, default is port 3260'),
    cfg.StrOpt('iqn_prefix',
               default='iqn.2010-10.org.openstack',
               help='IQN Prefix'),
    # NOTE(sirp): This is a work-around for a bug in Ubuntu Maverick,
    # when we pull support for it, we should remove this
    cfg.BoolOpt('remap_vbd_dev',
                default=False,
                help='Used to enable the remapping of VBD dev '
                     '(Works around an issue in Ubuntu Maverick)'),
    cfg.StrOpt('remap_vbd_dev_prefix',
               default='sd',
               help='Specify prefix to remap VBD dev to '
                    '(ex. /dev/xvdb -> /dev/sdb)'),
]

xenapi_vmops_opts = [
    cfg.IntOpt('running_timeout',
               default=60,
               help='Number of seconds to wait for instance '
                    'to go to running state'),
    cfg.StrOpt('vif_driver',
               default='nova.virt.xenapi.vif.XenAPIBridgeDriver',
               help='The XenAPI VIF driver using XenServer Network APIs.'),
    cfg.StrOpt('image_upload_handler',
                default='nova.virt.xenapi.image.glance.GlanceStore',
               help='Dom0 plugin driver used to handle image uploads.'),
    ]

xenapi_volume_utils_opts = [
    cfg.IntOpt('introduce_vdi_retry_wait',
               default=20,
               help='Number of seconds to wait for an SR to settle '
                    'if the VDI does not exist when first introduced'),
    ]

xenapi_ovs_integration_bridge_opts = [
    cfg.StrOpt('ovs_integration_bridge',
               default='xapi1',
               help='Name of Integration Bridge used by Open vSwitch'),
    ]

xenapi_pool_opts = [
    cfg.BoolOpt('use_join_force',
                default=True,
                help='To use for hosts with different CPUs'),
    ]


ALL_XENSERVER_OPTS = (xenapi_agent_opts +
                      xenapi_session_opts +
                      xenapi_torrent_opts +
                      xenapi_vm_utils_opts +
                      xenapi_opts +
                      xenapi_vmops_opts +
                      xenapi_volume_utils_opts +
                      xenapi_ovs_integration_bridge_opts +
                      xenapi_pool_opts)


def register_opts(conf):
    conf.register_group(xenserver_group)
    conf.register_opts(ALL_XENSERVER_OPTS, group=xenserver_group)


def list_opts():
    return {xenserver_group: ALL_XENSERVER_OPTS}
