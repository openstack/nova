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

from nova import datastore
from nova import exception
from nova import flags
from nova import rpc
from nova import utils
from nova.auth import manager
from nova.compute import model
from nova.network import model as network
from nova.endpoint import images
from nova.endpoint import wsgi


FLAGS = flags.FLAGS
flags.DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')


class Unauthorized(Exception):
    pass

class NotFound(Exception):
    pass


class Api(object):

    def __init__(self):
        """build endpoints here"""
        self.controllers = {
            "v1.0":   RackspaceAuthenticationApi(),
            "servers": RackspaceCloudServerApi()
        }

    def handler(self, environ, responder):
        """
        This is the entrypoint from wsgi.  Read PEP 333 and wsgi.org for
        more intormation.  The key points are responder is a callback that
        needs to run before you return, and takes two arguments, response
        code string ("200 OK") and headers (["X-How-Cool-Am-I: Ultra-Suede"])
        and the return value is the body of the response.
        """
        environ['nova.context'] = self.build_context(environ)
        controller, path = wsgi.Util.route(
                             environ['PATH_INFO'],
                             self.controllers
                           )
        logging.debug("Route %s to %s", str(path), str(controller))
        if not controller:
            responder("404 Not Found", [])
            return ""
        try:
            rv = controller.process(path, environ)
            if type(rv) is tuple:
                responder(rv[0], rv[1])
                rv = rv[2]
            else:
                responder("200 OK", [])
            return rv
        except Unauthorized:
            responder("401 Unauthorized", [])
            return ""
        except NotFound:
            responder("404 Not Found", [])
            return ""


    def build_context(self, env):
        rv = {}
        if env.has_key("HTTP_X_AUTH_TOKEN"):
            rv['user'] = manager.AuthManager().get_user_from_access_key(
                           env['HTTP_X_AUTH_TOKEN']
                         )
            if rv['user']:
                rv['project'] = manager.AuthManager().get_project(
                                  rv['user'].name
                                )
        return rv


class RackspaceApiEndpoint(object):
    def process(self, path, env):
        """
        Main entrypoint for all controllers (what gets run by the wsgi handler).
        Check authentication based on key, raise Unauthorized if invalid.

        Select the most appropriate action based on request type GET, POST, etc,
        then pass it through to the implementing controller.  Defalut to GET if
        the implementing child doesn't respond to a particular type.
        """
        if not self.check_authentication(env):
            raise Unauthorized("Unable to authenticate")

        method = env['REQUEST_METHOD'].lower()
        callback = getattr(self, method, None)
        if not callback:
            callback = getattr(self, "get")
        logging.debug("%s processing %s with %s", self, method, callback)
        return callback(path, env)

    def get(self, path, env):
        """
        The default GET will look at the path and call an appropriate
        action within this controller based on the the structure of the path.

        Given the following path lengths (with the first part stripped of by
        router, as it is the controller name):
            = 0  -> index
            = 1  -> first component (/servers/details -> details)
            >= 2 -> second path component (/servers/ID/ips/* -> ips)

        This should return
            A String if 200 OK and no additional headers
            (CODE, HEADERS, BODY) for custom response code and headers
        """
        if len(path) == 0 and hasattr(self, "index"):
            logging.debug("%s running index", self)
            return self.index(env)
        if len(path) >= 2:
            action = path[1]
        else:
            action = path.pop(0)

        logging.debug("%s running action %s", self, action)
        if hasattr(self, action):
            method = getattr(self, action)
            return method(path, env)
        else:
            raise NotFound("Missing method %s" % path[0])

    def check_authentication(self, env):
        if not env['nova.context']['user']:
            return False
        return True


class RackspaceAuthenticationApi(object):

    def process(self, path, env):
        return self.index(path, env)

    # TODO(todd): make a actual session with a unique token
    # just pass the auth key back through for now
    def index(self, _path, env):
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

    def post(self, path, env):
        if len(path) == 0:
             return self.launch_server(env)

    def delete(self, path_parts, env):
        if self.delete_server(path_parts[0]):
            return ("202 Accepted", [], "")
        else:
            return ("404 Not Found", [],
                    "Did not find image, or it was not in a running state")


    def index(self, env):
        return self.detail(env)

    def detail(self, args, env):
        value = {"servers": []}
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

    def delete_server(self, instance_id):
        owner_hostname = self.host_for_instance(instance_id)
        # it isn't launched?
        if not owner_hostname:
            return None
        rpc_transport = "%s:%s" % (FLAGS.compute_topic, owner_hostname)
        rpc.cast(rpc_transport,
                 {"method": "reboot_instance",
                  "args": {"instance_id": instance_id}})
        return True

    def host_for_instance(self, instance_id):
        instance = model.Instance.lookup(instance_id)
        if not instance:
            return None
        return instance["node_name"]

