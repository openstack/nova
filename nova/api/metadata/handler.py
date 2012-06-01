# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import webob.dec
import webob.exc

from nova.api.metadata import base
from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS
flags.DECLARE('use_forwarded_for', 'nova.api.auth')

if FLAGS.memcached_servers:
    import memcache
else:
    from nova.common import memorycache as memcache


class MetadataRequestHandler(wsgi.Application):
    """Serve metadata."""

    def __init__(self):
        self._cache = memcache.Client(FLAGS.memcached_servers, debug=0)

    def get_metadata(self, address):
        if not address:
            raise exception.FixedIpNotFoundForAddress(address=address)

        cache_key = 'metadata-%s' % address
        data = self._cache.get(cache_key)
        if data:
            return data

        try:
            data = base.get_metadata_by_address(address)
        except exception.NotFound:
            return None

        self._cache.set(cache_key, data, 15)

        return data

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        remote_address = req.remote_addr
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)

        try:
            meta_data = self.get_metadata(remote_address)
        except Exception:
            LOG.exception(_('Failed to get metadata for ip: %s'),
                          remote_address)
            msg = _('An unknown error has occurred. '
                    'Please try your request again.')
            exc = webob.exc.HTTPInternalServerError(explanation=unicode(msg))
            return exc
        if meta_data is None:
            LOG.error(_('Failed to get metadata for ip: %s'), remote_address)
            raise webob.exc.HTTPNotFound()

        try:
            data = meta_data.lookup(req.path_info)
        except base.InvalidMetadataPath:
            raise webob.exc.HTTPNotFound()

        return base.ec2_md_print(data)
