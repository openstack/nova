# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration. 
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
Tornado REST API Request Handlers for CloudPipe
"""

import logging
import urllib

from nova import vendor
import tornado.web

from nova import crypto
from nova.auth import users

_log = logging.getLogger("api")
_log.setLevel(logging.DEBUG)


class CloudPipeRequestHandler(tornado.web.RequestHandler):
    def get(self, path):
        path = self.request.path
        _log.debug( "Cloudpipe path is %s" % path)
        if path.endswith("/getca/"):
            self.send_root_ca()
        self.finish()

    def get_project_id_from_ip(self, ip):
        cc = self.application.controllers['Cloud']
        instance = cc.get_instance_by_ip(ip)
        instance['project_id']

    def send_root_ca(self):
        _log.debug( "Getting root ca")
        project_id = self.get_project_id_from_ip(self.request.remote_ip)
        self.set_header("Content-Type", "text/plain")
        self.write(crypto.fetch_ca(project_id))

    def post(self, *args, **kwargs):
        project_id = self.get_project_id_from_ip(self.request.remote_ip)
        cert = self.get_argument('cert', '')
        self.write(crypto.sign_csr(urllib.unquote(cert), project_id))
        self.finish()
