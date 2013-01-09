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
from nova.openstack.common import rpc


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


global_opts = [
    cfg.StrOpt('my_ip',
               default=_get_my_ip(),
               help='ip address of this host'),
    cfg.StrOpt('compute_topic',
               default='compute',
               help='the topic compute nodes listen on'),
    cfg.ListOpt('enabled_apis',
                default=['ec2', 'osapi_compute', 'metadata'],
                help='a list of APIs to enable by default'),
    cfg.StrOpt('osapi_compute_unique_server_name_scope',
               default='',
               help='When set, compute API will consider duplicate hostnames '
                    'invalid within the specified scope, regardless of case. '
                    'Should be empty, "project" or "global".'),
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
    cfg.ListOpt('memcached_servers',
                default=None,
                help='Memcached servers or None for in process cache.'),
    cfg.StrOpt('default_ephemeral_format',
               default=None,
               help='The default format an ephemeral_volume will be '
                    'formatted with on creation.'),
    cfg.BoolOpt('use_ipv6',
                default=False,
                help='use ipv6'),
    cfg.IntOpt('service_down_time',
               default=60,
               help='maximum time since last check-in for up service'),
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
]

cfg.CONF.register_opts(global_opts)


def parse_args(argv, default_config_files=None):
    rpc.set_defaults(control_exchange='nova')
    cfg.CONF(argv[1:],
             project='nova',
             default_config_files=default_config_files)
