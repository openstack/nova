# Copyright (c) 2015 The Johns Hopkins University/Applied Physics Laboratory
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

"""
Key manager implementation for Barbican
"""

import array
import base64
import binascii

from barbicanclient import client as barbican_client
from keystoneauth1 import loading as ks_loading
from keystoneauth1 import session
from oslo_log import log as logging
from oslo_utils import excutils

import nova.conf

from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.keymgr import key as keymgr_key
from nova.keymgr import key_mgr


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class BarbicanKeyManager(key_mgr.KeyManager):
    """Key Manager Interface that wraps the Barbican client API."""

    def __init__(self):
        self._barbican_client = None
        self._current_context = None
        self._base_url = None

    def _get_barbican_client(self, ctxt):
        """Creates a client to connect to the Barbican service.

        :param ctxt: the user context for authentication
        :return: a Barbican Client object
        :raises Forbidden: if the ctxt is None
        """

        # Confirm context is provided, if not raise forbidden
        if not ctxt:
            msg = _("User is not authorized to use key manager.")
            LOG.error(msg)
            raise exception.Forbidden(msg)

        if not hasattr(ctxt, 'project_id') or ctxt.project_id is None:
            msg = _("Unable to create Barbican Client without project_id.")
            LOG.error(msg)
            raise exception.KeyManagerError(msg)

        # If same context, return cached barbican client
        if self._barbican_client and self._current_context == ctxt:
            return self._barbican_client

        try:
            _SESSION = ks_loading.load_session_from_conf_options(
                CONF,
                nova.conf.barbican.barbican_group)

            auth = ctxt.get_auth_plugin()
            service_type, service_name, interface = (CONF.
                                                     barbican.
                                                     catalog_info.
                                                     split(':'))
            region_name = CONF.barbican.os_region_name
            service_parameters = {'service_type': service_type,
                                  'service_name': service_name,
                                  'interface': interface,
                                  'region_name': region_name}

            if CONF.barbican.endpoint_template:
                self._base_url = (CONF.barbican.endpoint_template %
                                  ctxt.to_dict())
            else:
                self._base_url = _SESSION.get_endpoint(
                    auth, **service_parameters)

            # the barbican endpoint can't have the '/v1' on the end
            self._barbican_endpoint = self._base_url.rpartition('/')[0]

            sess = session.Session(auth=auth)
            self._barbican_client = barbican_client.Client(
                session=sess,
                endpoint=self._barbican_endpoint)
            self._current_context = ctxt

        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error creating Barbican client: %s"), e)

        return self._barbican_client

    def create_key(self, ctxt, expiration=None, name='Nova Compute Key',
                   payload_content_type='application/octet-stream', mode='CBC',
                   algorithm='AES', length=256):
        """Creates a key.

        :param ctxt: contains information of the user and the environment
                     for the request (nova/context.py)
        :param expiration: the date the key will expire
        :param name: a friendly name for the secret
        :param payload_content_type: the format/type of the secret data
        :param mode: the algorithm mode (e.g. CBC or CTR mode)
        :param algorithm: the algorithm associated with the secret
        :param length: the bit length of the secret

        :return: the UUID of the new key
        :raises Exception: if key creation fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            key_order = barbican_client.orders.create_key(
                name,
                algorithm,
                length,
                mode,
                payload_content_type,
                expiration)
            order_ref = key_order.submit()
            order = barbican_client.orders.get(order_ref)
            return self._retrieve_secret_uuid(order.secret_ref)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error creating key: %s"), e)

    def store_key(self, ctxt, key, expiration=None, name='Nova Compute Key',
                  payload_content_type='application/octet-stream',
                  payload_content_encoding='base64', algorithm='AES',
                  bit_length=256, mode='CBC', from_copy=False):
        """Stores (i.e., registers) a key with the key manager.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param key: the unencrypted secret data. Known as "payload" to the
                    barbicanclient api
        :param expiration: the expiration time of the secret in ISO 8601
                           format
        :param name: a friendly name for the key
        :param payload_content_type: the format/type of the secret data
        :param payload_content_encoding: the encoding of the secret data
        :param algorithm: the algorithm associated with this secret key
        :param bit_length: the bit length of this secret key
        :param mode: the algorithm mode used with this secret key
        :param from_copy: establishes whether the function is being used
                    to copy a key. In case of the latter, it does not
                    try to decode the key

        :returns: the UUID of the stored key
        :raises Exception: if key storage fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            if key.get_algorithm():
                algorithm = key.get_algorithm()
            if payload_content_type == 'text/plain':
                payload_content_encoding = None
                encoded_key = key.get_encoded()
            elif (payload_content_type == 'application/octet-stream' and
                  not from_copy):
                key_list = key.get_encoded()
                string_key = ''.join(map(lambda byte: "%02x" % byte, key_list))
                encoded_key = base64.b64encode(binascii.unhexlify(string_key))
            else:
                encoded_key = key.get_encoded()
            secret = barbican_client.secrets.create(name,
                                                    encoded_key,
                                                    payload_content_type,
                                                    payload_content_encoding,
                                                    algorithm,
                                                    bit_length,
                                                    mode,
                                                    expiration)
            secret_ref = secret.store()
            return self._retrieve_secret_uuid(secret_ref)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error storing key: %s"), e)

    def copy_key(self, ctxt, key_id):
        """Copies (i.e., clones) a key stored by barbican.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param key_id: the UUID of the key to copy
        :return: the UUID of the key copy
        :raises Exception: if key copying fails
        """

        try:
            secret = self._get_secret(ctxt, key_id)
            con_type = secret.content_types['default']
            secret_data = self._get_secret_data(secret,
                                                payload_content_type=con_type)
            key = keymgr_key.SymmetricKey(secret.algorithm, secret_data)
            copy_uuid = self.store_key(ctxt, key, secret.expiration,
                                       secret.name, con_type,
                                       'base64',
                                       secret.algorithm, secret.bit_length,
                                       secret.mode, True)
            return copy_uuid
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error copying key: %s"), e)

    def _create_secret_ref(self, key_id):
        """Creates the URL required for accessing a secret.

        :param key_id: the UUID of the key to copy

        :return: the URL of the requested secret
        """
        if not key_id:
            msg = "Key ID is None"
            raise exception.KeyManagerError(msg)
        return self._base_url + "/secrets/" + key_id

    def _retrieve_secret_uuid(self, secret_ref):
        """Retrieves the UUID of the secret from the secret_ref.

        :param secret_ref: the href of the secret

        :return: the UUID of the secret
        """

        # The secret_ref is assumed to be of a form similar to
        # http://host:9311/v1/secrets/d152fa13-2b41-42ca-a934-6c21566c0f40
        # with the UUID at the end. This command retrieves everything
        # after the last '/', which is the UUID.
        return secret_ref.rpartition('/')[2]

    def _get_secret_data(self,
                         secret,
                         payload_content_type='application/octet-stream'):
        """Retrieves the secret data given a secret and content_type.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param secret: the secret from barbican with the payload of data
        :param payload_content_type: the format/type of the secret data

        :returns: the secret data
        :raises Exception: if data cannot be retrieved
        """
        try:
            generated_data = secret.payload
            if payload_content_type == 'application/octet-stream':
                secret_data = base64.b64encode(generated_data)
            else:
                secret_data = generated_data
            return secret_data
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error getting secret data: %s"), e)

    def _get_secret(self, ctxt, key_id):
        """Returns the metadata of the secret.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param key_id: UUID of the secret

        :return: the secret's metadata
        :raises Exception: if there is an error retrieving the data
        """

        barbican_client = self._get_barbican_client(ctxt)

        try:
            secret_ref = self._create_secret_ref(key_id)
            return barbican_client.secrets.get(secret_ref)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error getting secret metadata: %s"), e)

    def get_key(self, ctxt, key_id,
                payload_content_type='application/octet-stream'):
        """Retrieves the specified key.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param key_id: the UUID of the key to retrieve
        :param payload_content_type: The format/type of the secret data

        :return: SymmetricKey representation of the key
        :raises Exception: if key retrieval fails
        """
        try:
            secret = self._get_secret(ctxt, key_id)
            secret_data = self._get_secret_data(secret,
                                                payload_content_type)
            if payload_content_type == 'application/octet-stream':
                # convert decoded string to list of unsigned ints for each byte
                key_data = array.array('B',
                                       base64.b64decode(secret_data)).tolist()
            else:
                key_data = secret_data
            key = keymgr_key.SymmetricKey(secret.algorithm, key_data)
            return key
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error getting key: %s"), e)

    def delete_key(self, ctxt, key_id):
        """Deletes the specified key.

        :param ctxt: contains information of the user and the environment for
                     the request (nova/context.py)
        :param key_id: the UUID of the key to delete
        :raises Exception: if key deletion fails
        """
        barbican_client = self._get_barbican_client(ctxt)

        try:
            secret_ref = self._create_secret_ref(key_id)
            barbican_client.secrets.delete(secret_ref)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deleting key: %s"), e)
