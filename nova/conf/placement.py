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


DEFAULT_SERVICE_TYPE = 'placement'

placement_group = cfg.OptGroup(
    'placement',
    title='Placement Service Options',
    help="Configuration options for connecting to the placement API service")

placement_opts = [
    cfg.StrOpt(
        'os_region_name',
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason='Endpoint lookup uses the service catalog via '
                          'common keystoneauth1 Adapter configuration '
                          'options.  Use the region_name option instead.',
        help="""
Region name of this node. This is used when picking the URL in the service
catalog.

Possible values:

* Any string representing region name
"""),
    cfg.StrOpt(
        'os_interface',
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason='Endpoint lookup uses the service catalog via '
                          'common keystoneauth1 Adapter configuration '
                          'options.  Use the valid_interfaces option instead.',
        help="""
Endpoint interface for this node. This is used when picking the URL in the
service catalog.
"""),
    cfg.BoolOpt('randomize_allocation_candidates',
                default=False,
                help="""
If True, when limiting allocation candidate results, the results will be
a random sampling of the full result set. If False, allocation candidates
are returned in a deterministic but undefined order. That is, all things
being equal, two requests for allocation candidates will return the same
results in the same order; but no guarantees are made as to how that order
is determined.
"""),
]

deprecated_opts = {
    'region_name': [cfg.DeprecatedOpt('os_region_name',
                                      group=placement_group.name)],
    'valid_interfaces': [cfg.DeprecatedOpt('os_interface',
                                           group=placement_group.name)]
}


def register_opts(conf):
    conf.register_group(placement_group)
    conf.register_opts(placement_opts, group=placement_group)
    confutils.register_ksa_opts(conf, placement_group, DEFAULT_SERVICE_TYPE,
                                deprecated_opts=deprecated_opts)


def list_opts():
    return {
        placement_group.name: (
            placement_opts +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password') +
            confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE,
                                           deprecated_opts=deprecated_opts))
    }
