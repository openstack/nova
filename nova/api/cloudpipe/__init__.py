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

"""
REST API Request Handlers for CloudPipe
"""

import logging
import urllib
import webob
import webob.dec
import webob.exc

from nova import crypto
from nova import wsgi
from nova.auth import manager
from nova.api.ec2 import cloud


_log = logging.getLogger("api")
_log.setLevel(logging.DEBUG)


class API(wsgi.Application):

    def __init__(self):
        self.controller = cloud.CloudController()

    @webob.dec.wsgify
    def __call__(self, req):
        if req.method == 'POST':
            return self.sign_csr(req)
        _log.debug(_("Cloudpipe path is %s") % req.path_info)
        if req.path_info.endswith("/getca/"):
            return self.send_root_ca(req)
        return webob.exc.HTTPNotFound()

    def get_project_id_from_ip(self, ip):
        # TODO(eday): This was removed with the ORM branch, fix!
        instance = self.controller.get_instance_by_ip(ip)
        return instance['project_id']

    def send_root_ca(self, req):
        _log.debug(_("Getting root ca"))
        project_id = self.get_project_id_from_ip(req.remote_addr)
        res = webob.Response()
        res.headers["Content-Type"] = "text/plain"
        res.body = crypto.fetch_ca(project_id)
        return res

    def sign_csr(self, req):
        project_id = self.get_project_id_from_ip(req.remote_addr)
        cert = self.str_params['cert']
        return crypto.sign_csr(urllib.unquote(cert), project_id)
