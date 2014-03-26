# Copyright 2012 OpenStack Foundation
# All Rights Reserved
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

from neutronclient.common import exceptions
from neutronclient.v2_0 import client as clientv20
from oslo.config import cfg

from nova.openstack.common import lockutils
from nova.openstack.common import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class AdminTokenStore(object):

    _instance = None

    def __init__(self):
        self.admin_auth_token = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def _get_client(token=None, admin=False):
    params = {
        'endpoint_url': CONF.neutron_url,
        'timeout': CONF.neutron_url_timeout,
        'insecure': CONF.neutron_api_insecure,
        'ca_cert': CONF.neutron_ca_certificates_file,
        'auth_strategy': CONF.neutron_auth_strategy,
        'token': token,
    }

    if admin:
        params['username'] = CONF.neutron_admin_username
        if CONF.neutron_admin_tenant_id:
            params['tenant_id'] = CONF.neutron_admin_tenant_id
        else:
            params['tenant_name'] = CONF.neutron_admin_tenant_name
        params['password'] = CONF.neutron_admin_password
        params['auth_url'] = CONF.neutron_admin_auth_url
    return clientv20.Client(**params)


class ClientWrapper(clientv20.Client):
    '''A neutron client wrapper class.
       Wraps the callable methods, executes it and updates the token,
       as it might change when expires.
    '''

    def __init__(self, base_client):
        # Expose all attributes from the base_client instance
        self.__dict__ = base_client.__dict__
        self.base_client = base_client

    def __getattribute__(self, name):
        obj = object.__getattribute__(self, name)
        if callable(obj):
            obj = object.__getattribute__(self, 'proxy')(obj)
        return obj

    def proxy(self, obj):
        def wrapper(*args, **kwargs):
            ret = obj(*args, **kwargs)
            new_token = self.base_client.get_auth_info()['auth_token']
            _update_token(new_token)
            return ret
        return wrapper


def _update_token(new_token):
    with lockutils.lock('neutron_admin_auth_token_lock'):
        token_store = AdminTokenStore.get()
        token_store.admin_auth_token = new_token


def get_client(context, admin=False):
    # NOTE(dprince): In the case where no auth_token is present
    # we allow use of neutron admin tenant credentials if
    # it is an admin context.
    # This is to support some services (metadata API) where
    # an admin context is used without an auth token.
    if admin or (context.is_admin and not context.auth_token):
        with lockutils.lock('neutron_admin_auth_token_lock'):
            orig_token = AdminTokenStore.get().admin_auth_token
        client = _get_client(orig_token, admin=True)
        return ClientWrapper(client)

    # We got a user token that we can use that as-is
    if context.auth_token:
        token = context.auth_token
        return _get_client(token=token)

    # We did not get a user token and we should not be using
    # an admin token so log an error
    raise exceptions.Unauthorized()
