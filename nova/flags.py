# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2012 Red Hat, Inc.
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

"""Command-line flag library.

Emulates gflags by wrapping cfg.ConfigOpts.

The idea is to move fully to cfg eventually, and this wrapper is a
stepping stone.

"""

import os
import socket
import sys

from nova.openstack.common import cfg


class NovaConfigOpts(cfg.CommonConfigOpts):

    def __init__(self, *args, **kwargs):
        if 'project' not in kwargs:
            kwargs['project'] = 'nova'
        super(NovaConfigOpts, self).__init__(*args, **kwargs)
        self.disable_interspersed_args()

    def __call__(self, argv):
        return argv[:1] + super(NovaConfigOpts, self).__call__(argv[1:])


FLAGS = NovaConfigOpts()


class UnrecognizedFlag(Exception):
    pass


def DECLARE(name, module_string, flag_values=FLAGS):
    if module_string not in sys.modules:
        __import__(module_string, globals(), locals())
    if name not in flag_values:
        raise UnrecognizedFlag('%s not defined by %s' % (name, module_string))


def _get_my_ip():
    """
    Returns the actual ip of the local machine.

    This code figures out what source address would be used if some traffic
    were to be sent out to some well known address on the Internet. In this
    case, a Google DNS server is used, but the specific address does not
    matter much.  No traffic is actually sent.
    """
    try:
        csock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        csock.connect(('8.8.8.8', 80))
        (addr, port) = csock.getsockname()
        csock.close()
        return addr
    except socket.error:
        return "127.0.0.1"


log_opts = [
    cfg.StrOpt('logdir',
               default=None,
               help='Log output to a per-service log file in named directory'),
    cfg.StrOpt('logfile',
               default=None,
               help='Log output to a named file'),
    cfg.BoolOpt('use_stderr',
                default=True,
                help='Log output to standard error'),
    ]

core_opts = [
    cfg.StrOpt('connection_type',
               default=None,
               help='Virtualization api connection type : libvirt, xenapi, '
                    'or fake'),
    cfg.StrOpt('sql_connection',
               default='sqlite:///$state_path/$sqlite_db',
               help='The SQLAlchemy connection string used to connect to the '
                    'database'),
    cfg.IntOpt('sql_connection_debug',
               default=0,
               help='Verbosity of SQL debugging information. 0=None, '
                    '100=Everything'),
    cfg.StrOpt('api_paste_config',
               default="api-paste.ini",
               help='File name for the paste.deploy config for nova-api'),
    cfg.StrOpt('pybasedir',
               default=os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                    '../')),
               help='Directory where the nova python module is installed'),
    cfg.StrOpt('bindir',
               default='$pybasedir/bin',
               help='Directory where nova binaries are installed'),
    cfg.StrOpt('state_path',
               default='$pybasedir',
               help="Top-level directory for maintaining nova's state"),
    cfg.StrOpt('lock_path',
               default='$pybasedir',
               help='Directory to use for lock files'),
    ]

debug_opts = [
    cfg.BoolOpt('fake_network',
                default=False,
                help='If passed, use fake network devices and addresses'),
]

FLAGS.register_cli_opts(log_opts)
FLAGS.register_cli_opts(core_opts)
FLAGS.register_cli_opts(debug_opts)

global_opts = [
    cfg.StrOpt('my_ip',
               default=_get_my_ip(),
               help='ip address of this host'),
    cfg.ListOpt('region_list',
                default=[],
                help='list of region=fqdn pairs separated by commas'),
    cfg.StrOpt('aws_access_key_id',
               default='admin',
               help='AWS Access ID'),
    cfg.StrOpt('aws_secret_access_key',
               default='admin',
               help='AWS Access Key'),
    cfg.StrOpt('glance_host',
               default='$my_ip',
               help='default glance hostname or ip'),
    cfg.IntOpt('glance_port',
               default=9292,
               help='default glance port'),
    cfg.ListOpt('glance_api_servers',
                default=['$glance_host:$glance_port'],
                help='A list of the glance api servers available to nova '
                     '([hostname|ip]:port)'),
    cfg.IntOpt('glance_num_retries',
               default=0,
               help='Number retries when downloading an image from glance'),
    cfg.IntOpt('s3_port',
               default=3333,
               help='port used when accessing the s3 api'),
    cfg.StrOpt('s3_host',
               default='$my_ip',
               help='hostname or ip for openstack to use when accessing '
                    'the s3 api'),
    cfg.StrOpt('s3_dmz',
               default='$my_ip',
               help='hostname or ip for the instances to use when accessing '
                    'the s3 api'),
    cfg.StrOpt('cert_topic',
               default='cert',
               help='the topic cert nodes listen on'),
    cfg.StrOpt('compute_topic',
               default='compute',
               help='the topic compute nodes listen on'),
    cfg.StrOpt('console_topic',
               default='console',
               help='the topic console proxy nodes listen on'),
    cfg.StrOpt('scheduler_topic',
               default='scheduler',
               help='the topic scheduler nodes listen on'),
    cfg.StrOpt('volume_topic',
               default='volume',
               help='the topic volume nodes listen on'),
    cfg.StrOpt('network_topic',
               default='network',
               help='the topic network nodes listen on'),
    cfg.BoolOpt('api_rate_limit',
                default=True,
                help='whether to rate limit the api'),
    cfg.ListOpt('enabled_apis',
                default=['ec2', 'osapi_compute', 'osapi_volume', 'metadata'],
                help='a list of APIs to enable by default'),
    cfg.StrOpt('ec2_host',
               default='$my_ip',
               help='the ip of the ec2 api server'),
    cfg.StrOpt('ec2_dmz_host',
               default='$my_ip',
               help='the internal ip of the ec2 api server'),
    cfg.IntOpt('ec2_port',
               default=8773,
               help='the port of the ec2 api server'),
    cfg.StrOpt('ec2_scheme',
               default='http',
               help='the protocol to use when connecting to the ec2 api '
                    'server (http, https)'),
    cfg.StrOpt('ec2_path',
               default='/services/Cloud',
               help='the path prefix used to call the ec2 api server'),
    cfg.ListOpt('osapi_compute_ext_list',
                default=[],
                help='Specify list of extensions to load when using osapi_'
                     'compute_extension option with nova.api.openstack.'
                     'compute.contrib.select_extensions'),
    cfg.MultiStrOpt('osapi_compute_extension',
                    default=[
                      'nova.api.openstack.compute.contrib.standard_extensions'
                      ],
                    help='osapi compute extension to load'),
    cfg.ListOpt('osapi_volume_ext_list',
                default=[],
                help='Specify list of extensions to load when using osapi_'
                     'volume_extension option with nova.api.openstack.'
                     'volume.contrib.select_extensions'),
    cfg.MultiStrOpt('osapi_volume_extension',
                    default=[
                      'nova.api.openstack.volume.contrib.standard_extensions'
                      ],
                    help='osapi volume extension to load'),
    cfg.StrOpt('osapi_scheme',
               default='http',
               help='the protocol to use when connecting to the openstack api '
                    'server (http, https)'),
    cfg.StrOpt('osapi_path',
               default='/v1.1/',
               help='the path prefix used to call the openstack api server'),
    cfg.StrOpt('osapi_compute_link_prefix',
               default=None,
               help='Base URL that will be presented to users in links '
                    'to the OpenStack Compute API'),
    cfg.StrOpt('osapi_glance_link_prefix',
               default=None,
               help='Base URL that will be presented to users in links '
                    'to glance resources'),
    cfg.IntOpt('osapi_max_limit',
               default=1000,
               help='the maximum number of items returned in a single '
                    'response from a collection resource'),
    cfg.StrOpt('metadata_host',
               default='$my_ip',
               help='the ip for the metadata api server'),
    cfg.IntOpt('metadata_port',
               default=8775,
               help='the port for the metadata api port'),
    cfg.StrOpt('default_project',
               default='openstack',
               help='the default project to use for openstack'),
    cfg.StrOpt('default_image',
               default='ami-11111',
               help='default image to use, testing only'),
    cfg.StrOpt('default_instance_type',
               default='m1.small',
               help='default instance type to use, testing only'),
    cfg.StrOpt('null_kernel',
               default='nokernel',
               help='kernel image that indicates not to use a kernel, but to '
                    'use a raw disk image instead'),
    cfg.StrOpt('vpn_image_id',
               default='0',
               help='image id used when starting up a cloudpipe vpn server'),
    cfg.StrOpt('vpn_key_suffix',
               default='-vpn',
               help='Suffix to add to project name for vpn key and secgroups'),
    cfg.IntOpt('auth_token_ttl',
               default=3600,
               help='Seconds for auth tokens to linger'),
    cfg.StrOpt('logfile_mode',
               default='0644',
               help='Default file mode used when creating log files'),
    cfg.StrOpt('sqlite_db',
               default='nova.sqlite',
               help='the filename to use with sqlite'),
    cfg.BoolOpt('sqlite_synchronous',
                default=True,
                help='If passed, use synchronous mode for sqlite'),
    cfg.IntOpt('sql_idle_timeout',
               default=3600,
               help='timeout before idle sql connections are reaped'),
    cfg.IntOpt('sql_max_retries',
               default=10,
               help='maximum db connection retries during startup. '
                    '(setting -1 implies an infinite retry count)'),
    cfg.IntOpt('sql_retry_interval',
               default=10,
               help='interval between retries of opening a sql connection'),
    cfg.StrOpt('compute_manager',
               default='nova.compute.manager.ComputeManager',
               help='full class name for the Manager for compute'),
    cfg.StrOpt('console_manager',
               default='nova.console.manager.ConsoleProxyManager',
               help='full class name for the Manager for console proxy'),
    cfg.StrOpt('cert_manager',
               default='nova.cert.manager.CertManager',
               help='full class name for the Manager for cert'),
    cfg.StrOpt('instance_dns_manager',
               default='nova.network.dns_driver.DNSDriver',
               help='full class name for the DNS Manager for instance IPs'),
    cfg.StrOpt('instance_dns_domain',
               default='',
               help='full class name for the DNS Zone for instance IPs'),
    cfg.StrOpt('floating_ip_dns_manager',
               default='nova.network.dns_driver.DNSDriver',
               help='full class name for the DNS Manager for floating IPs'),
    cfg.StrOpt('network_manager',
               default='nova.network.manager.VlanManager',
               help='full class name for the Manager for network'),
    cfg.StrOpt('volume_manager',
               default='nova.volume.manager.VolumeManager',
               help='full class name for the Manager for volume'),
    cfg.StrOpt('scheduler_manager',
               default='nova.scheduler.manager.SchedulerManager',
               help='full class name for the Manager for scheduler'),
    cfg.StrOpt('firewall_driver',
               default='nova.virt.firewall.IptablesFirewallDriver',
               help='Firewall driver (defaults to iptables)'),
    cfg.StrOpt('image_service',
               default='nova.image.glance.GlanceImageService',
               help='The service to use for retrieving and searching images.'),
    cfg.StrOpt('host',
               default=socket.gethostname(),
               help='Name of this node.  This can be an opaque identifier.  '
                    'It is not necessarily a hostname, FQDN, or IP address.'),
    cfg.StrOpt('node_availability_zone',
               default='nova',
               help='availability zone of this node'),
    cfg.StrOpt('notification_driver',
               default='nova.notifier.no_op_notifier',
               help='Default driver for sending notifications'),
    cfg.ListOpt('memcached_servers',
                default=None,
                help='Memcached servers or None for in process cache.'),
    cfg.StrOpt('instance_usage_audit_period',
               default='month',
               help='time period to generate instance usages for.  '
                    'Time period must be hour, day, month or year'),
    cfg.IntOpt('bandwith_poll_interval',
               default=600,
               help='interval to pull bandwidth usage info'),
    cfg.BoolOpt('start_guests_on_host_boot',
                default=False,
                help='Whether to restart guests when the host reboots'),
    cfg.BoolOpt('resume_guests_state_on_host_boot',
                default=False,
                help='Whether to start guests that were running before the '
                     'host rebooted'),
    cfg.StrOpt('default_ephemeral_format',
               default=None,
               help='The default format a ephemeral_volume will be '
                    'formatted with on creation.'),
    cfg.StrOpt('root_helper',
               default='sudo',
               help='Command prefix to use for running commands as root'),
    cfg.StrOpt('network_driver',
               default='nova.network.linux_net',
               help='Driver to use for network creation'),
    cfg.BoolOpt('use_ipv6',
                default=False,
                help='use ipv6'),
    cfg.BoolOpt('enable_instance_password',
                default=True,
                help='Allows use of instance password during '
                     'server creation'),
    cfg.IntOpt('password_length',
               default=12,
               help='Length of generated instance admin passwords'),
    cfg.BoolOpt('monkey_patch',
                default=False,
                help='Whether to log monkey patching'),
    cfg.ListOpt('monkey_patch_modules',
                default=[
                  'nova.api.ec2.cloud:nova.notifier.api.notify_decorator',
                  'nova.compute.api:nova.notifier.api.notify_decorator'
                  ],
                help='List of modules/decorators to monkey patch'),
    cfg.BoolOpt('allow_resize_to_same_host',
                default=False,
                help='Allow destination machine to match source for resize. '
                     'Useful when testing in single-host environments.'),
    cfg.BoolOpt('stub_network',
                default=False,
                help='Stub network related code'),
    cfg.IntOpt('reclaim_instance_interval',
               default=0,
               help='Interval in seconds for reclaiming deleted instances'),
    cfg.IntOpt('zombie_instance_updated_at_window',
               default=172800,
               help='Number of seconds zombie instances are cleaned up.'),
    cfg.IntOpt('service_down_time',
               default=60,
               help='maximum time since last check-in for up service'),
    cfg.StrOpt('default_schedule_zone',
               default=None,
               help='availability zone to use when user doesn\'t specify one'),
    cfg.ListOpt('isolated_images',
                default=[],
                help='Images to run on isolated host'),
    cfg.ListOpt('isolated_hosts',
                default=[],
                help='Host reserved for specific images'),
    cfg.BoolOpt('cache_images',
                default=True,
                help='Cache glance images locally'),
    cfg.BoolOpt('use_cow_images',
                default=True,
                help='Whether to use cow images'),
    cfg.StrOpt('compute_api_class',
                default='nova.compute.api.API',
                help='The full class name of the compute API class to use'),
    cfg.StrOpt('network_api_class',
                default='nova.network.api.API',
                help='The full class name of the network API class to use'),
    cfg.StrOpt('volume_api_class',
                default='nova.volume.api.API',
                help='The full class name of the volume API class to use'),
    cfg.StrOpt('security_group_handler',
               default='nova.network.quantum.sg.NullSecurityGroupHandler',
               help='The full class name of the security group handler class'),
    cfg.StrOpt('default_access_ip_network_name',
               default=None,
               help='Name of network to use to set access ips for instances'),
    cfg.StrOpt('auth_strategy',
               default='noauth',
               help='The strategy to use for auth. Supports noauth, keystone, '
                    'and deprecated.'),
]

FLAGS.register_opts(global_opts)
