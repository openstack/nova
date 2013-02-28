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

from oslo.config import cfg
from quantumclient.v2_0 import client

from nova.openstack.common import excutils
from nova.openstack.common import log as logging

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


cached_admin_client = None


def _fill_admin_details(params):
    params['username'] = CONF.quantum_admin_username
    params['tenant_name'] = CONF.quantum_admin_tenant_name
    params['region_name'] = CONF.quantum_region_name
    params['password'] = CONF.quantum_admin_password
    params['auth_url'] = CONF.quantum_admin_auth_url
    params['timeout'] = CONF.quantum_url_timeout
    params['auth_strategy'] = CONF.quantum_auth_strategy
    params['insecure'] = CONF.quantum_api_insecure


def _get_client(token=None):
    global cached_admin_client

    should_cache = False
    params = {
        'endpoint_url': CONF.quantum_url,
        'timeout': CONF.quantum_url_timeout,
        'insecure': CONF.quantum_api_insecure,
    }
    if token:
        params['token'] = token
    else:
        if CONF.quantum_auth_strategy:
            should_cache = True
            _fill_admin_details(params)
        else:
            params['auth_strategy'] = None

    new_client = client.Client(**params)
    if should_cache:
        # in this case, we don't have the token yet
        try:
            new_client.httpclient.authenticate()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("quantum authentication failed"))

        cached_admin_client = new_client
    return new_client


def get_client(context, admin=False):
    if admin:
        if cached_admin_client is not None:
            return cached_admin_client

        token = None
    else:
        token = context.auth_token
    return _get_client(token=token)
