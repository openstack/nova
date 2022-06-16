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

from nova.conf import utils as confutils

DEFAULT_SERVICE_TYPE = 'shared-file-system'

manila_group = cfg.OptGroup(
    'manila',
    title='Manila Options',
    help="Configuration options for the share-file-system service")

manila_opts = [
    cfg.IntOpt('share_apply_policy_timeout',
               default=10,
               help="""
Timeout period for share policy application.

Maximum duration to await a response from the Manila service for the
application of a share policy before experiencing a timeout.
0 means do not wait (0s).

Possible values:

* A positive integer or 0 (default value is 10).
"""),
]


def register_opts(conf):
    conf.register_group(manila_group)
    conf.register_opts(manila_opts, group=manila_group)
    ks_loading.register_session_conf_options(conf, manila_group.name)
    ks_loading.register_auth_conf_options(conf, manila_group.name)

    confutils.register_ksa_opts(conf, manila_group, DEFAULT_SERVICE_TYPE)


def list_opts():
    return {
        manila_group.name: (
            manila_opts +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('v3password'))
    }
