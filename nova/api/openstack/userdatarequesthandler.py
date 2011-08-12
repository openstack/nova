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

"""User data request handler."""

import base64
import webob.dec
import webob.exc

from nova import log as logging
from nova import context
from nova import exception
from nova import db
from nova import flags
from nova import wsgi


LOG = logging.getLogger('nova.api.openstack.userdata')
FLAGS = flags.FLAGS


class Controller(object):
    """ The server user-data API controller for the Openstack API """

    def __init__(self):
        super(Controller, self).__init__()

    @staticmethod
    def _format_user_data(instance_ref):
        return base64.b64decode(instance_ref['user_data'])

    def get_user_data(self, address):
        ctxt = context.get_admin_context()
        try:
            instance_ref = db.instance_get_by_fixed_ip(ctxt, address)
        except exception.NotFound:
            instance_ref = None
        if not instance_ref:
            return None

        data = {'user-data': self._format_user_data(instance_ref)}
        return data


class UserdataRequestHandler(wsgi.Application):
    """Serve user-data from the OS API."""

    def __init__(self):
        self.cc = Controller()

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

        data = self.cc.get_user_data(remote_address)
        if data is None:
            LOG.error(_('Failed to get user data for ip: %s'), remote_address)
            raise webob.exc.HTTPNotFound()
        data = self.lookup(req.path_info, data)
        if data is None:
            raise webob.exc.HTTPNotFound()
        return self.print_data(data)
