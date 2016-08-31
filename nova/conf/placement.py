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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

placement_group = cfg.OptGroup(
    'placement',
    title='Placement Service Options',
    help="Configuration options for connecting to the placement API service")

placement_opts = [
    cfg.StrOpt('os_region_name',
               help="""
Region name of this node. This is used when picking the URL in the service
catalog.

Possible values:

* Any string representing region name
"""),
]


def register_opts(conf):
    conf.register_group(placement_group)
    conf.register_opts(placement_opts, group=placement_group)
    ks_loading.register_auth_conf_options(conf,
                                             placement_group.name)


def list_opts():
    return {
        placement_group.name: placement_opts
    }
