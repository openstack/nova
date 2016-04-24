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

neutron_group = cfg.OptGroup('neutron', title='Neutron Options')

neutron_opts = [
    cfg.StrOpt('url',
               default='http://127.0.0.1:9696',
               help='URL for connecting to neutron'),
    cfg.StrOpt('region_name',
               help='Region name for connecting to neutron in admin context'),
    cfg.StrOpt('ovs_bridge',
               default='br-int',
               help='Default OVS bridge name to use if not specified '
                    'by Neutron'),
    cfg.IntOpt('extension_sync_interval',
                default=600,
                help='Number of seconds before querying neutron for'
                     ' extensions'),
]

metadata_proxy_opts = [
    cfg.BoolOpt(
        'service_metadata_proxy',
        default=False,
        help='Set flag to indicate Neutron will proxy metadata requests and '
             'resolve instance ids.'),
    cfg.StrOpt(
         'metadata_proxy_shared_secret',
         default='', secret=True,
         help='Shared secret to validate proxies Neutron metadata requests'),
]

ALL_OPTS = list(itertools.chain(
    neutron_opts,
    metadata_proxy_opts
))


def register_opts(conf):
    conf.register_group(neutron_group)
    conf.register_opts(ALL_OPTS, group=neutron_group)


def list_opts():
    return {neutron_group: ALL_OPTS}
