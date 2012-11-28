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

import os
import socket

from nova.openstack.common import cfg


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


core_opts = [
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
    ]

debug_opts = [
    cfg.BoolOpt('fake_network',
                default=False,
                help='If passed, use fake network devices and addresses'),
]

cfg.CONF.register_cli_opts(core_opts)
cfg.CONF.register_cli_opts(debug_opts)

global_opts = [
    cfg.StrOpt('my_ip',
               default=_get_my_ip(),
               help='ip address of this host'),
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
    cfg.StrOpt('glance_protocol',
                default='http',
                help='Default protocol to use when connecting to glance. '
                     'Set to https for SSL.'),
    cfg.ListOpt('glance_api_servers',
                default=['$glance_host:$glance_port'],
                help='A list of the glance api servers available to nova. '
                     'Prefix with https:// for ssl-based glance api servers. '
                     '([hostname|ip]:port)'),
    cfg.BoolOpt('glance_api_insecure',
                default=False,
                help='Allow to perform insecure SSL (https) requests to '
                     'glance'),
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
    cfg.StrOpt('network_topic',
               default='network',
               help='the topic network nodes listen on'),
    cfg.BoolOpt('api_rate_limit',
                default=True,
                help='whether to rate limit the api'),
    cfg.ListOpt('enabled_apis',
                default=['ec2', 'osapi_compute', 'metadata'],
                help='a list of APIs to enable by default'),
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
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
               default='',
               help='When set, compute API will consider duplicate hostnames '
                    'invalid within the specified scope, regardless of case. '
                    'Should be empty, "project" or "global".'),
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
    cfg.StrOpt('default_image',
               default='ami-11111',
               help='default image to use, testing only'),
    cfg.StrOpt('default_instance_type',
               default='m1.small',
               help='default instance type to use, testing only'),
    cfg.StrOpt('vpn_image_id',
               default='0',
               help='image id used when starting up a cloudpipe vpn server'),
    cfg.StrOpt('vpn_key_suffix',
               default='-vpn',
               help='Suffix to add to project name for vpn key and secgroups'),
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
    cfg.StrOpt('scheduler_manager',
               default='nova.scheduler.manager.SchedulerManager',
               help='full class name for the Manager for scheduler'),
    cfg.StrOpt('host',
               default=socket.getfqdn(),
               help='Name of this node.  This can be an opaque identifier.  '
                    'It is not necessarily a hostname, FQDN, or IP address. '
                    'However, the node name must be valid within '
                    'an AMQP key, and if using ZeroMQ, a valid '
                    'hostname, FQDN, or IP address'),
    cfg.StrOpt('node_availability_zone',
               default='nova',
               help='availability zone of this node'),
    cfg.ListOpt('memcached_servers',
                default=None,
                help='Memcached servers or None for in process cache.'),
    cfg.StrOpt('instance_usage_audit_period',
               default='month',
               help='time period to generate instance usages for.  '
                    'Time period must be hour, day, month or year'),
    cfg.StrOpt('default_ephemeral_format',
               default=None,
               help='The default format an ephemeral_volume will be '
                    'formatted with on creation.'),
    cfg.StrOpt('rootwrap_config',
               default="/etc/nova/rootwrap.conf",
               help='Path to the rootwrap configuration file to use for '
                    'running commands as root'),
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
    cfg.IntOpt('zombie_instance_updated_at_window',
               default=172800,
               help='Number of seconds zombie instances are cleaned up.'),
    cfg.IntOpt('service_down_time',
               default=60,
               help='maximum time since last check-in for up service'),
    cfg.ListOpt('isolated_images',
                default=[],
                help='Images to run on isolated host'),
    cfg.ListOpt('isolated_hosts',
                default=[],
                help='Host reserved for specific images'),
    cfg.StrOpt('cache_images',
                default='all',
                help='Cache glance images locally. `all` will cache all'
                     ' images, `some` will only cache images that have the'
                     ' image_property `cache_in_nova=True`, and `none` turns'
                     ' off caching entirely'),
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
                default='nova.volume.cinder.API',
                help='The full class name of the volume API class to use'),
    cfg.StrOpt('auth_strategy',
               default='noauth',
               help='The strategy to use for auth: noauth or keystone.'),
]

cfg.CONF.register_opts(global_opts)


def parse_args(argv, default_config_files=None):
    cfg.CONF.disable_interspersed_args()
    return argv[:1] + cfg.CONF(argv[1:],
                               project='nova',
                               default_config_files=default_config_files)
