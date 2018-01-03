# Copyright (c) 2016 OpenStack Foundation
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

SERVICEGROUP_OPTS = [
    cfg.StrOpt('servicegroup_driver',
        default='db',
        choices=[
            ('db', 'Database ServiceGroup driver'),
            ('mc', 'Memcache ServiceGroup driver'),
        ],
        help="""
This option specifies the driver to be used for the servicegroup service.

ServiceGroup API in nova enables checking status of a compute node. When a
compute worker running the nova-compute daemon starts, it calls the join API
to join the compute group. Services like nova scheduler can query the
ServiceGroup API to check if a node is alive. Internally, the ServiceGroup
client driver automatically updates the compute worker status. There are
multiple backend implementations for this service: Database ServiceGroup driver
and Memcache ServiceGroup driver.

Related Options:

* ``service_down_time`` (maximum time since last check-in for up service)
"""),
]


def register_opts(conf):
    conf.register_opts(SERVICEGROUP_OPTS)


def list_opts():
    return {'DEFAULT': SERVICEGROUP_OPTS}
