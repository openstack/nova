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
from keystoneauth1 import service_token

import nova.conf


CONF = nova.conf.CONF

_SERVICE_AUTH = None


def get_auth_plugin(context):
    user_auth = context.get_auth_plugin()

    if CONF.service_user.send_service_user_token:
        global _SERVICE_AUTH
        if not _SERVICE_AUTH:
            _SERVICE_AUTH = ks_loading.load_auth_from_conf_options(
                                CONF,
                                group=
                                nova.conf.service_token.SERVICE_USER_GROUP)
        return service_token.ServiceTokenAuthWrapper(
                   user_auth=user_auth,
                   service_auth=_SERVICE_AUTH)

    return user_auth
