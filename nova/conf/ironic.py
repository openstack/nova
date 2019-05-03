# Copyright 2015 Intel Corporation
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

from nova.conf import utils as confutils


DEFAULT_SERVICE_TYPE = 'baremetal'

ironic_group = cfg.OptGroup(
    'ironic',
    title='Ironic Options',
    help="""
Configuration options for Ironic driver (Bare Metal).
If using the Ironic driver following options must be set:
* auth_type
* auth_url
* project_name
* username
* password
* project_domain_id or project_domain_name
* user_domain_id or user_domain_name
""")

ironic_options = [
    cfg.IntOpt(
        'api_max_retries',
        # TODO(raj_singh): Change this default to some sensible number
        default=60,
        min=0,
        help="""
The number of times to retry when a request conflicts.
If set to 0, only try once, no retries.

Related options:

* api_retry_interval
"""),
    cfg.IntOpt(
        'api_retry_interval',
        default=2,
        min=0,
        help="""
The number of seconds to wait before retrying the request.

Related options:

* api_max_retries
"""),
    cfg.IntOpt(
        'serial_console_state_timeout',
        default=10,
        min=0,
        help='Timeout (seconds) to wait for node serial console state '
             'changed. Set to 0 to disable timeout.'),
    cfg.StrOpt(
        'partition_key',
        default=None,
        mutable=True,
        max_length=255,
        regex=r'^[a-zA-Z0-9_.-]*$',
        help='Case-insensitive key to limit the set of nodes that may be '
             'managed by this service to the set of nodes in Ironic which '
             'have a matching conductor_group property. If unset, all '
             'available nodes will be eligible to be managed by this '
             'service. Note that setting this to the empty string (``""``) '
             'will match the default conductor group, and is different than '
             'leaving the option unset.'),
    cfg.ListOpt(
        'peer_list',
        default=[],
        mutable=True,
        help='List of hostnames for all nova-compute services (including '
             'this host) with this partition_key config value. '
             'Nodes matching the partition_key value will be distributed '
             'between all services specified here. '
             'If partition_key is unset, this option is ignored.'),
]


def register_opts(conf):
    conf.register_group(ironic_group)
    conf.register_opts(ironic_options, group=ironic_group)
    confutils.register_ksa_opts(conf, ironic_group, DEFAULT_SERVICE_TYPE)


def list_opts():
    return {ironic_group: (
        ironic_options +
        ks_loading.get_session_conf_options() +
        ks_loading.get_auth_common_conf_options() +
        ks_loading.get_auth_plugin_conf_options('v3password') +
        confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE))
    }
