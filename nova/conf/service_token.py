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

SERVICE_USER_GROUP = 'service_user'

service_user = cfg.OptGroup(
    SERVICE_USER_GROUP,
    title = 'Service token authentication type options',
    help = """
Configuration options for service to service authentication using a service
token. These options allow to send a service token along with the
user's token when contacting external REST APIs.
"""
)

service_user_opts = [
    cfg.BoolOpt('send_service_user_token',
                default=False,
                help="""
When True, if sending a user token to an REST API, also send a service token.

Nova often reuses the user token provided to the nova-api to talk to other
REST APIs, such as Cinder, Glance and Neutron. It is possible that while the
user token was valid when the request was made to Nova, the token may expire
before it reaches the other service. To avoid any failures, and to
make it clear it is Nova calling the service on the users behalf, we include
a server token along with the user token. Should the user's token have
expired, a valid service token ensures the REST API request will still be
accepted by the keystone middleware.

This feature is currently experimental, and as such is turned off by default
while full testing and performance tuning of this feature is completed.
"""),
]


def register_opts(conf):
    conf.register_group(service_user)
    conf.register_opts(service_user_opts, group=service_user)

    ks_loading.register_session_conf_options(conf, SERVICE_USER_GROUP)
    ks_loading.register_auth_conf_options(conf, SERVICE_USER_GROUP)


def list_opts():
    return {
        service_user: (
            service_user_opts +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password'))
    }
