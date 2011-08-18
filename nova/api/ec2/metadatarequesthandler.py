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

from nova import log as logging
from nova import flags
from nova import utils
from nova import wsgi
from nova.api.ec2 import cloud


LOG = logging.getLogger('nova.api.ec2.metadata')
FLAGS = flags.FLAGS
flags.DECLARE('use_forwarded_for', 'nova.api.auth')


class MetadataRequestHandler(wsgi.Application):
    """Serve metadata from the EC2 API."""

    def __init__(self):
        self.cc = cloud.CloudController()

    def print_data(self, data):
        if isinstance(data, dict):
            output = ''
            for key in data:
                if key == '_name':
                    continue
                output += key
                if isinstance(data[key], dict):
                    if '_name' in data[key]:
                        output += '=' + str(data[key]['_name'])
                    else:
                        output += '/'
                output += '\n'
            # Cut off last \n
            return output[:-1]
        elif isinstance(data, list):
            return '\n'.join(data)
        else:
            return str(data)

    def lookup(self, path, data):
        items = path.split('/')
        for item in items:
            if item:
                if not isinstance(data, dict):
                    return data
                if not item in data:
                    return None
                data = data[item]
        return data

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        remote_address = req.remote_addr
        if FLAGS.use_forwarded_for:
            remote_address = req.headers.get('X-Forwarded-For', remote_address)
        try:
            meta_data = self.cc.get_metadata(remote_address)
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
        data = self.lookup(req.path_info, meta_data)
        if data is None:
            raise webob.exc.HTTPNotFound()
        return self.print_data(data)
