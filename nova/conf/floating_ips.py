# Copyright 2016 Huawei Technology corp.
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

default_floating_pool_opt = cfg.StrOpt('default_floating_pool',
        default='nova',
        help='Default pool for floating IPs')

auto_assign_opt = cfg.BoolOpt('auto_assign_floating_ip',
        default=False,
        help='Autoassigning floating IP to VM')

dns_mgr_opt = cfg.StrOpt('floating_ip_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        help='Full class name for the DNS Manager for '
        'floating IPs')

instance_dns_opt = cfg.StrOpt('instance_dns_manager',
        default='nova.network.noop_dns_driver.NoopDNSDriver',
        help='Full class name for the DNS Manager for '
        'instance IPs')

dns_domain_opt = cfg.StrOpt('instance_dns_domain',
        default='',
        help='Full class name for the DNS Zone '
        'for instance IPs')

ALL_OPTS = [
    default_floating_pool_opt,
    auto_assign_opt,
    dns_domain_opt,
    dns_mgr_opt,
    instance_dns_opt
]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
