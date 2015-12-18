# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Metadata request handler."""
import hashlib
import hmac
import os

from oslo_config import cfg
from oslo_log import log as logging
import six
import webob.dec
import webob.exc

from nova.api.metadata import base
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LW
from nova.network.neutronv2 import api as neutronapi
from nova.openstack.common import memorycache
from nova import utils
from nova import wsgi

CONF = cfg.CONF
CONF.import_opt('use_forwarded_for', 'nova.api.auth')

metadata_proxy_opts = [
    cfg.BoolOpt(
        'service_metadata_proxy',
        default=False,
        help='Set flag to indicate Neutron will proxy metadata requests and '
             'resolve instance ids.'),
     cfg.StrOpt(
         'metadata_proxy_shared_secret',
         default='', secret=True,
         help='Shared secret to validate proxies Neutron metadata requests'),
]

metadata_opts = [
    cfg.IntOpt('metadata_cache_expiration',
               default=15,
               help='Time in seconds to cache metadata; 0 to disable '
                    'metadata caching entirely (not recommended). Increasing'
                    'this should improve response times of the metadata API '
                    'when under heavy load. Higher values may increase memory'
                    'usage and result in longer times for host metadata '
                    'changes to take effect.')
]

CONF.register_opts(metadata_proxy_opts, 'neutron')
CONF.register_opts(metadata_opts)

LOG = logging.getLogger(__name__)


class MetadataRequestHandler(wsgi.Application):
    """Serve metadata."""

    def __init__(self):
        self._cache = memorycache.get_client()

    def get_metadata_by_remote_address(self, address):
        if not address:
            raise exception.FixedIpNotFoundForAddress(address=address)

        cache_key = 'metadata-%s' % address
        data = self._cache.get(cache_key)
        if data:
            LOG.debug("Using cached metadata for %s", address)
            return data

        try:
            data = base.get_metadata_by_address(address)
        except exception.NotFound:
            return None

        if CONF.metadata_cache_expiration > 0:
            self._cache.set(cache_key, data, CONF.metadata_cache_expiration)

        return data

    def get_metadata_by_instance_id(self, instance_id, address):
        cache_key = 'metadata-%s' % instance_id
        data = self._cache.get(cache_key)
        if data:
            LOG.debug("Using cached metadata for instance %s", instance_id)
            return data

        try:
            data = base.get_metadata_by_instance_id(instance_id, address)
        except exception.NotFound:
            return None

        if CONF.metadata_cache_expiration > 0:
            self._cache.set(cache_key, data, CONF.metadata_cache_expiration)

        return data

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        if os.path.normpath(req.path_info) == "/":
            resp = base.ec2_md_print(base.VERSIONS + ["latest"])
            req.response.body = resp
            req.response.content_type = base.MIME_TYPE_TEXT_PLAIN
            return req.response

        if CONF.neutron.service_metadata_proxy:
            if req.headers.get('X-Metadata-Provider'):
                meta_data = self._handle_instance_id_request_from_lb(req)
            else:
                meta_data = self._handle_instance_id_request(req)
        else:
            if req.headers.get('X-Instance-ID'):
                LOG.warning(
                    _LW("X-Instance-ID present in request headers. The "
                        "'service_metadata_proxy' option must be "
                        "enabled to process this header."))
            meta_data = self._handle_remote_ip_request(req)

        if meta_data is None:
            raise webob.exc.HTTPNotFound()

        try:
            data = meta_data.lookup(req.path_info)
        except base.InvalidMetadataPath:
            raise webob.exc.HTTPNotFound()

        if callable(data):
            return data(req, meta_data)

        resp = base.ec2_md_print(data)
        if isinstance(resp, six.text_type):
            req.response.text = resp
        else:
            req.response.body = resp

        req.response.content_type = meta_data.get_mimetype()
        return req.response

    def _handle_remote_ip_request(self, req):
        remote_address = req.remote_addr
        if CONF.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        try:
            meta_data = self.get_metadata_by_remote_address(remote_address)
        except Exception:
            LOG.exception(_LE('Failed to get metadata for IP: %s'),
                          remote_address)
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            raise webob.exc.HTTPInternalServerError(
                                               explanation=six.text_type(msg))

        if meta_data is None:
            LOG.error(_LE('Failed to get metadata for IP: %s'),
                      remote_address)

        return meta_data

    def _handle_instance_id_request(self, req):
        instance_id = req.headers.get('X-Instance-ID')
        tenant_id = req.headers.get('X-Tenant-ID')
        signature = req.headers.get('X-Instance-ID-Signature')
        remote_address = req.headers.get('X-Forwarded-For')

        # Ensure that only one header was passed

        if instance_id is None:
            msg = _('X-Instance-ID header is missing from request.')
        elif signature is None:
            msg = _('X-Instance-ID-Signature header is missing from request.')
        elif tenant_id is None:
            msg = _('X-Tenant-ID header is missing from request.')
        elif not isinstance(instance_id, six.string_types):
            msg = _('Multiple X-Instance-ID headers found within request.')
        elif not isinstance(tenant_id, six.string_types):
            msg = _('Multiple X-Tenant-ID headers found within request.')
        else:
            msg = None

        if msg:
            raise webob.exc.HTTPBadRequest(explanation=msg)

        self._validate_shared_secret(instance_id, signature,
                                     remote_address)

        return self._get_meta_by_instance_id(instance_id, tenant_id,
                                             remote_address)

    def _get_instance_id_from_lb(self, provider_id, instance_address):
        # We use admin context, admin=True to lookup the
        # inter-Edge network port
        context = nova_context.get_admin_context()
        neutron = neutronapi.get_client(context, admin=True)

        # Tenant, instance ids are found in the following method:
        #  X-Metadata-Provider contains id of the metadata provider, and since
        #  overlapping networks cannot be connected to the same metadata
        #  provider, the combo of tenant's instance IP and the metadata
        #  provider has to be unique.
        #
        #  The networks which are connected to the metadata provider are
        #  retrieved in the 1st call to neutron.list_subnets()
        #  In the 2nd call we read the ports which belong to any of the
        #  networks retrieved above, and have the X-Forwarded-For IP address.
        #  This combination has to be unique as explained above, and we can
        #  read the instance_id, tenant_id from that port entry.

        # Retrieve networks which are connected to metadata provider
        md_subnets = neutron.list_subnets(
            context,
            advanced_service_providers=[provider_id],
            fields=['network_id'])

        md_networks = [subnet['network_id']
                       for subnet in md_subnets['subnets']]

        try:
            # Retrieve the instance data from the instance's port
            instance_data = neutron.list_ports(
                context,
                fixed_ips='ip_address=' + instance_address,
                network_id=md_networks,
                fields=['device_id', 'tenant_id'])['ports'][0]
        except Exception as e:
            LOG.error(_LE('Failed to get instance id for metadata '
                          'request, provider %(provider)s '
                          'networks %(networks)s '
                          'requester %(requester)s. Error: %(error)s'),
                      {'provider': provider_id,
                       'networks': md_networks,
                       'requester': instance_address,
                       'error': e})
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        instance_id = instance_data['device_id']
        tenant_id = instance_data['tenant_id']

        # instance_data is unicode-encoded, while memorycache doesn't like
        # that. Therefore we convert to str
        if isinstance(instance_id, six.text_type):
            instance_id = instance_id.encode('utf-8')
        return instance_id, tenant_id

    def _handle_instance_id_request_from_lb(self, req):
        remote_address = req.headers.get('X-Forwarded-For')
        if remote_address is None:
            msg = _('X-Forwarded-For is missing from request.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        provider_id = req.headers.get('X-Metadata-Provider')
        if provider_id is None:
            msg = _('X-Metadata-Provider is missing from request.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        instance_address = remote_address.split(',')[0]

        # If authentication token is set, authenticate
        if CONF.neutron.metadata_proxy_shared_secret:
            signature = req.headers.get('X-Metadata-Provider-Signature')
            self._validate_shared_secret(provider_id, signature,
                                         instance_address)

        instance_id, tenant_id = self._get_instance_id_from_lb(
            provider_id, instance_address)

        return self._get_meta_by_instance_id(instance_id, tenant_id,
                                             instance_address)

    def _validate_shared_secret(self, requestor_id, signature,
                                requestor_address):
        expected_signature = hmac.new(
            CONF.neutron.metadata_proxy_shared_secret,
            requestor_id, hashlib.sha256).hexdigest()

        if not utils.constant_time_compare(expected_signature, signature):
            if requestor_id:
                LOG.warning(_LW('X-Instance-ID-Signature: %(signature)s does '
                                'not match the expected value: '
                                '%(expected_signature)s for id: '
                                '%(requestor_id)s. Request From: '
                                '%(requestor_address)s'),
                            {'signature': signature,
                             'expected_signature': expected_signature,
                             'requestor_id': requestor_id,
                             'requestor_address': requestor_address})

            msg = _('Invalid proxy request signature.')
            raise webob.exc.HTTPForbidden(explanation=msg)

    def _get_meta_by_instance_id(self, instance_id, tenant_id, remote_address):
        try:
            meta_data = self.get_metadata_by_instance_id(instance_id,
                                                         remote_address)
        except Exception:
            LOG.exception(_LE('Failed to get metadata for instance id: %s'),
                          instance_id)
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            raise webob.exc.HTTPInternalServerError(
                                               explanation=six.text_type(msg))

        if meta_data is None:
            LOG.error(_LE('Failed to get metadata for instance id: %s'),
                      instance_id)
        elif meta_data.instance.project_id != tenant_id:
            LOG.warning(_LW("Tenant_id %(tenant_id)s does not match tenant_id "
                            "of instance %(instance_id)s."),
                        {'tenant_id': tenant_id, 'instance_id': instance_id})
            # causes a 404 to be raised
            meta_data = None

        return meta_data
