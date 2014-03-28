# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

from nova.openstack.common import local
from nova.openstack.common import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def _get_client(token=None):
    params = {
        'endpoint_url': CONF.neutron_url,
        'timeout': CONF.neutron_url_timeout,
        'insecure': CONF.neutron_api_insecure,
        'ca_cert': CONF.neutron_ca_certificates_file,
    }

    if token:
        params['token'] = token
        params['auth_strategy'] = None
    else:
        params['username'] = CONF.neutron_admin_username
        params['tenant_name'] = CONF.neutron_admin_tenant_name
        params['password'] = CONF.neutron_admin_password
        params['auth_url'] = CONF.neutron_admin_auth_url
        params['auth_strategy'] = CONF.neutron_auth_strategy
    return clientv20.Client(**params)


def get_client(context, admin=False):
    # NOTE(dprince): In the case where no auth_token is present
    # we allow use of neutron admin tenant credentials if
    # it is an admin context.
    # This is to support some services (metadata API) where
    # an admin context is used without an auth token.
    if admin or (context.is_admin and not context.auth_token):
        # NOTE(dims): We need to use admin token, let us cache a
        # thread local copy for re-using this client
        # multiple times and to avoid excessive calls
        # to neutron to fetch tokens. Some of the hackiness in this code
        # will go away once BP auth-plugins is implemented.
        # That blue print will ensure that tokens can be shared
        # across clients as well
        if not hasattr(local.strong_store, 'neutron_client'):
            local.strong_store.neutron_client = _get_client(token=None)
        return local.strong_store.neutron_client

    # We got a user token that we can use that as-is
    if context.auth_token:
        token = context.auth_token
        return _get_client(token=token)

    # We did not get a user token and we should not be using
    # an admin token so log an error
    raise exceptions.Unauthorized()
