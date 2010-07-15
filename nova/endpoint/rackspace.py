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


# TODO(todd): subclass Exception so we can bubble meaningful errors


class Api(object):

    def __init__(self, rpc_mechanism):
        self.controllers = {
            "v1.0":   RackspaceAuthenticationApi(),
            "servers": RackspaceCloudServerApi()
        }
        self.rpc_mechanism = rpc_mechanism

    def handler(self, environ, responder):
        environ['nova.context'] = self.build_context(environ)
        controller, path = wsgi.Util.route(
                             environ['PATH_INFO'],
                             self.controllers
                           )
        if not controller:
            # TODO(todd): Exception (404)
            raise Exception("Missing Controller")
        rv = controller.process(path, environ)
        if type(rv) is tuple:
            responder(rv[0], rv[1])
            rv = rv[2]
        else:
            responder("200 OK", [])
        return rv

    def build_context(self, env):
        rv = {}
        if env.has_key("HTTP_X_AUTH_TOKEN"):
            rv['user'] = users.UserManager.instance().get_user_from_access_key(
                           env['HTTP_X_AUTH_TOKEN']
                         )
            if rv['user']:
                rv['project'] = users.UserManager.instance().get_project(
                                  rv['user'].name
                                )
        return rv


class RackspaceApiEndpoint(object):
    def process(self, path, env):
        if not self.check_authentication(env):
            # TODO(todd): Exception (Unauthorized)
            raise Exception("Unable to authenticate")

        if len(path) == 0:
            return self.index(env)

        action = path.pop(0)
        if hasattr(self, action):
            method = getattr(self, action)
            return method(path, env)
        else:
            # TODO(todd): Exception (404)
            raise Exception("Missing method %s" % path[0])

    def check_authentication(self, env):
        if hasattr(self, "process_without_authentication") \
        and getattr(self, "process_without_authentication"):
            return True
        if not env['nova.context']['user']:
            return False
        return True


class RackspaceAuthenticationApi(RackspaceApiEndpoint):

    def __init__(self):
        self.process_without_authentication = True

    # TODO(todd): make a actual session with a unique token
    # just pass the auth key back through for now
    def index(self, env):
        response = '204 No Content'
        headers = [
            ('X-Server-Management-Url', 'http://%s' % env['HTTP_HOST']),
            ('X-Storage-Url', 'http://%s' % env['HTTP_HOST']),
            ('X-CDN-Managment-Url', 'http://%s' % env['HTTP_HOST']),
            ('X-Auth-Token', env['HTTP_X_AUTH_KEY'])
        ]
        body = ""
        return (response, headers, body)


class RackspaceCloudServerApi(RackspaceApiEndpoint):

    def __init__(self):
        self.instdir = model.InstanceDirectory()
        self.network = network.PublicNetworkController()

    def index(self, env):
        if env['REQUEST_METHOD'] == 'GET':
            return self.detail(env)
        elif env['REQUEST_METHOD'] == 'POST':
            return self.launch_server(env)

    def detail(self, args, env):
        value = {
            "servers":
                []
        }
        for inst in self.instdir.all:
            value["servers"].append(self.instance_details(inst))

        return json.dumps(value)

    ##
    ##

    def launch_server(self, env):
        data = json.loads(env['wsgi.input'].read(int(env['CONTENT_LENGTH'])))
        inst = self.build_server_instance(data, env['nova.context'])
        self.schedule_launch_of_instance(inst)
        return json.dumps({"server": self.instance_details(inst)})

    def instance_details(self, inst):
        return {
            "id": inst.get("instance_id", None),
            "imageId": inst.get("image_id", None),
            "flavorId": inst.get("instacne_type", None),
            "hostId": inst.get("node_name", None),
            "status": inst.get("state", "pending"),
            "addresses": {
                "public": [self.network.get_public_ip_for_instance(
                            inst.get("instance_id", None)
                          )],
                "private": [inst.get("private_dns_name", None)]
            },

            # implemented only by Rackspace, not AWS
            "name": inst.get("name", "Not-Specified"),

            # not supported
            "progress": "Not-Supported",
            "metadata": {
                "Server Label": "Not-Supported",
                "Image Version": "Not-Supported"
            }
        }

    def build_server_instance(self, env, context):
        reservation = utils.generate_uid('r')
        ltime = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        inst = self.instdir.new()
        inst['name'] = env['server']['name']
        inst['image_id'] = env['server']['imageId']
        inst['instance_type'] = env['server']['flavorId']
        inst['user_id'] = context['user'].id
        inst['project_id'] = context['project'].id
        inst['reservation_id'] = reservation
        inst['launch_time'] = ltime
        inst['mac_address'] = utils.generate_mac()
        address = network.allocate_ip(
                    inst['user_id'],
                    inst['project_id'],
                    mac=inst['mac_address']
                  )
        inst['private_dns_name'] = str(address)
        inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(
                                inst['user_id'],
                                inst['project_id'],
                                'default' # security group
                              )['bridge_name']
        # key_data, key_name, ami_launch_index
        # TODO(todd): key data or root password
        inst.save()
        return inst

    def schedule_launch_of_instance(self, inst):
        rpc.cast(
            FLAGS.compute_topic,
            {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}
            }
        )
