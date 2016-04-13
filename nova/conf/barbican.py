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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

barbican_group = cfg.OptGroup(
    'barbican',
    title='Barbican options')

barbican_opts = [
     cfg.StrOpt('catalog_info',
                default='key-manager:barbican:public',
                help='Info to match when looking for barbican in the service '
                     'catalog. Format is: separated values of the form: '
                     '<service_type>:<service_name>:<endpoint_type>'),
    cfg.StrOpt('endpoint_template',
               help='Override service catalog lookup with template for '
                    'barbican endpoint e.g. '
                    'http://localhost:9311/v1/%(project_id)s'),
    cfg.StrOpt('os_region_name',
               help='Region name of this node'),
]


def register_opts(conf):
    conf.register_group(barbican_group)
    conf.register_opts(barbican_opts, group=barbican_group)
    ks_loading.register_session_conf_options(conf, barbican_group.name)


def list_opts():
    return {
        barbican_group.name: barbican_opts
    }
