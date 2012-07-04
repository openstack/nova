# Copyright 2012 OpenStack LLC.
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from nova import exception
from nova import flags
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from quantumclient import client
from quantumclient.v2_0 import client as clientv20

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def _get_auth_token():
    try:
        httpclient = client.HTTPClient(
            username=FLAGS.quantum_admin_username,
            tenant_name=FLAGS.quantum_admin_tenant_name,
            password=FLAGS.quantum_admin_password,
            auth_url=FLAGS.quantum_admin_auth_url,
            timeout=FLAGS.quantum_url_timeout,
            auth_strategy=FLAGS.quantum_auth_strategy)
        httpclient.authenticate()
    except Exception:
        with excutils.save_and_reraise_exception():
            LOG.exception(_("_get_auth_token() failed"))
    return httpclient.auth_token


def get_client(context):
    token = context.auth_token
    if not token:
        if FLAGS.quantum_auth_strategy:
            token = _get_auth_token()
    if token:
        my_client = clientv20.Client(
            endpoint_url=FLAGS.quantum_url,
            token=token, timeout=FLAGS.quantum_url_timeout)
    else:
        my_client = clientv20.Client(
            endpoint_url=FLAGS.quantum_url,
            auth_strategy=None, timeout=FLAGS.quantum_url_timeout)
    return my_client
