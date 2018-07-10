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
DEFAULT_CONSUMER_MISSING_ID = '00000000-0000-0000-0000-000000000000'

placement_group = cfg.OptGroup(
    'placement',
    title='Placement Service Options',
    help="Configuration options for connecting to the placement API service")

placement_opts = [
    cfg.BoolOpt(
        'randomize_allocation_candidates',
        default=False,
        help="""
If True, when limiting allocation candidate results, the results will be
a random sampling of the full result set. If False, allocation candidates
are returned in a deterministic but undefined order. That is, all things
being equal, two requests for allocation candidates will return the same
results in the same order; but no guarantees are made as to how that order
is determined.
"""),
    # TODO(mriedem): When placement is split out of nova, this should be
    # deprecated since then [oslo_policy]/policy_file can be used.
    cfg.StrOpt(
        'policy_file',
        # This default matches what is in
        # etc/nova/placement-policy-generator.conf
        default='placement-policy.yaml',
        help='The file that defines placement policies. This can be an '
             'absolute path or relative to the configuration file.'),
    cfg.StrOpt(
        'incomplete_consumer_project_id',
        default=DEFAULT_CONSUMER_MISSING_ID,
        help="""
Early API microversions (<1.8) allowed creating allocations and not specifying
a project or user identifier for the consumer. In cleaning up the data
modeling, we no longer allow missing project and user information. If an older
client makes an allocation, we'll use this in place of the information it
doesn't provide.
"""),
    cfg.StrOpt(
        'incomplete_consumer_user_id',
        default=DEFAULT_CONSUMER_MISSING_ID,
        help="""
Early API microversions (<1.8) allowed creating allocations and not specifying
a project or user identifier for the consumer. In cleaning up the data
modeling, we no longer allow missing project and user information. If an older
client makes an allocation, we'll use this in place of the information it
doesn't provide.
"""),
]


# Duplicate log_options from oslo_service so that we don't have to import
# that package into placement.
# NOTE(cdent): Doing so ends up requiring eventlet and other unnecessary
# packages for just this one setting.
service_opts = [
    cfg.BoolOpt('log_options',
                default=True,
                help='Enables or disables logging values of all registered '
                     'options when starting a service (at DEBUG level).'),
]


def register_opts(conf):
    conf.register_group(placement_group)
    conf.register_opts(placement_opts, group=placement_group)
    conf.register_opts(service_opts)
    confutils.register_ksa_opts(conf, placement_group, DEFAULT_SERVICE_TYPE)


def list_opts():
    return {
        placement_group.name: (
            placement_opts +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password') +
            confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE))
    }
