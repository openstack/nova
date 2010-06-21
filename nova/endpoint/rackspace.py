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
Rackspace API
"""

import base64
import json
import logging
import multiprocessing
import os
import time

from nova import vendor
import tornado.web
from twisted.internet import defer

from nova import datastore
from nova import flags
from nova import rpc
from nova import utils
from nova import exception
from nova.auth import users
from nova.compute import model
from nova.compute import network
from nova.endpoint import wsgi
from nova.endpoint import images
from nova.volume import storage

FLAGS = flags.FLAGS

flags.DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')

def _gen_key(user_id, key_name):
    """ Tuck this into UserManager """
    try:
        manager = users.UserManager.instance()
        private_key, fingerprint = manager.generate_key_pair(user_id, key_name)
    except Exception as ex:
        return {'exception': ex}
    return {'private_key': private_key, 'fingerprint': fingerprint}


class Api(object):

    def __init__(self, rpc_mechanism):
        self.controllers = {
            "v1.0":   RackspaceAuthenticationApi(),
            "server": RackspaceCloudServerApi()
        }
        self.rpc_mechanism = rpc_mechanism

    def handler(self, environ, responder):
        logging.error("*** %s" % environ)
        controller, path = wsgi.Util.route(environ['PATH_INFO'], self.controllers)
        if not controller:
            raise Exception("Missing Controller")
        rv = controller.process(path, environ)
        if type(rv) is tuple:
            responder(rv[0], rv[1])
            rv = rv[2]
        else:
            responder("200 OK", [])
        return rv

class RackspaceApiEndpoint(object):
    def process(self, path, env):
        if len(path) == 0:
            return self.index(env)

        action = path.pop(0)
        if hasattr(self, action):
            method = getattr(self, action)
            return method(path, env)
        else:
            raise Exception("Missing method %s" % path[0])


class RackspaceAuthenticationApi(RackspaceApiEndpoint):

    def index(self, env):
        response = '204 No Content'
        headers = [
            ('X-Server-Management-Url', 'http://localhost:8773/server'),
            ('X-Storage-Url', 'http://localhost:8773/server'),
            ('X-CDN-Managment-Url', 'http://localhost:8773/server'),
        ]
        body = ""
        return (response, headers, body)
        

class RackspaceCloudServerApi(object):

    def index(self):
        return "IDX"

    def list(self, args):
        return "%s" % args
