#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

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
        self.manager = users.UserManager.instance()
        if path.endswith("/getca/"):
            self.send_root_ca()
        elif path.endswith("/getcert/"):
            _log.debug( "Getting zip for %s" % (path[9:]))
            try:
                self.send_signed_zip(self.path[9:])
            except Exception, err:
                _log.debug('ERROR: %s\n' % str(err))
                raise tornado.web.HTTPError(404)
        self.finish()

    def get_username_from_ip(self, ip):
        cc = self.application.controllers['Cloud']
        instance = cc.get_instance_by_ip(ip)
        return instance['owner_id']

    def send_root_ca(self):
        _log.debug( "Getting root ca")
        username = self.get_username_from_ip(self.request.remote_ip)
        self.set_header("Content-Type", "text/plain")
        self.write(crypto.fetch_ca(username))

    def send_signed_zip(self, username):
        self.set_header("Content-Type", "application/zip")
        self.write(self.manager.get_signed_zip(username))

    def post(self, *args, **kwargs):
        self.manager = users.UserManager.instance()
        username = self.get_username_from_ip(self.request.remote_ip)
        cert = self.get_argument('cert', '')
        self.write(self.manager.sign_cert(urllib.unquote(cert), username))
        self.finish()
