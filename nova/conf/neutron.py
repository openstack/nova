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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

from nova.conf import utils as confutils


DEFAULT_SERVICE_TYPE = 'network'
NEUTRON_GROUP = 'neutron'

neutron_group = cfg.OptGroup(
    NEUTRON_GROUP,
    title='Neutron Options',
    help="""
Configuration options for neutron (network connectivity as a service).
""")

neutron_opts = [
    cfg.URIOpt('url',
        sample_default='http://127.0.0.1:9696',
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason='Endpoint lookup uses the service catalog via '
                          'common keystoneauth1 Adapter configuration '
                          'options. In the current release, "url" will '
                          'override this behavior, but will be ignored and/or '
                          'removed in a future release. To achieve the same '
                          'result, use the endpoint_override option instead.',
        help="""
This option specifies the URL for connecting to Neutron.

Possible values:

* Any valid URL that points to the Neutron API service is appropriate here.
  This typically matches the URL returned for the 'network' service type
  from the Keystone service catalog.
"""),
    cfg.StrOpt('ovs_bridge',
         default='br-int',
         help="""
Default name for the Open vSwitch integration bridge.

Specifies the name of an integration bridge interface used by OpenvSwitch.
This option is only used if Neutron does not specify the OVS bridge name in
port binding responses.
"""),
    cfg.StrOpt('default_floating_pool',
        default='nova',
        help="""
Default name for the floating IP pool.

Specifies the name of floating IP pool used for allocating floating IPs. This
option is only used if Neutron does not specify the floating IP pool name in
port binding reponses.
"""),
    cfg.IntOpt('extension_sync_interval',
         default=600,
         min=0,
         help="""
Integer value representing the number of seconds to wait before querying
Neutron for extensions.  After this number of seconds the next time Nova
needs to create a resource in Neutron it will requery Neutron for the
extensions that it has loaded.  Setting value to 0 will refresh the
extensions with no wait.
"""),
]

metadata_proxy_opts = [
    cfg.BoolOpt("service_metadata_proxy",
        default=False,
        help="""
When set to True, this option indicates that Neutron will be used to proxy
metadata requests and resolve instance ids. Otherwise, the instance ID must be
passed to the metadata request in the 'X-Instance-ID' header.

Related options:

* metadata_proxy_shared_secret
"""),
     cfg.StrOpt("metadata_proxy_shared_secret",
        default="",
        secret=True,
        help="""
This option holds the shared secret string used to validate proxy requests to
Neutron metadata requests. In order to be used, the
'X-Metadata-Provider-Signature' header must be supplied in the request.

Related options:

* service_metadata_proxy
"""),
]

ALL_OPTS = (neutron_opts + metadata_proxy_opts)


def register_opts(conf):
    conf.register_group(neutron_group)
    conf.register_opts(ALL_OPTS, group=neutron_group)
    # NOTE(efried): We don't pass `url` as a deprecated opt because that would
    # make CONF.neutron.url indistinguishable from
    # CONF.neutron.endpoint_override in the code, and we need to be able to use
    # the former to trigger the legacy behavior.
    confutils.register_ksa_opts(conf, neutron_group, DEFAULT_SERVICE_TYPE)


def list_opts():
    return {
        neutron_group: (
            ALL_OPTS +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password') +
            confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE))
    }
