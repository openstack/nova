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
    if admin or context.is_admin:
        token = None
    elif not context.auth_token:
        raise exceptions.Unauthorized()
    else:
        token = context.auth_token

    return _get_client(token=token)
