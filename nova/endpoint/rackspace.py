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
Rackspace API Endpoint
"""

import json
import time

import webob.dec
import webob.exc

from nova import flags
from nova import rpc
from nova import utils
from nova import wsgi
from nova.auth import manager
from nova.compute import model as compute
from nova.network import model as network


FLAGS = flags.FLAGS
flags.DEFINE_string('cloud_topic', 'cloud', 'the topic clouds listen on')


class API(wsgi.Middleware):
    """Entry point for all requests."""

    def __init__(self):
        super(API, self).__init__(Router(webob.exc.HTTPNotFound()))

    def __call__(self, environ, start_response):
        context = {}
        if "HTTP_X_AUTH_TOKEN" in environ:
            context['user'] = manager.AuthManager().get_user_from_access_key(
                              environ['HTTP_X_AUTH_TOKEN'])
            if context['user']:
                context['project'] = manager.AuthManager().get_project(
                                     context['user'].name)
        if "user" not in context:
            return webob.exc.HTTPForbidden()(environ, start_response)
        environ['nova.context'] = context
        return self.application(environ, start_response)


class Router(wsgi.Router):
    """Route requests to the next WSGI application."""

    def _build_map(self):
        """Build routing map for authentication and cloud."""
        self._connect("/v1.0", controller=AuthenticationAPI())
        cloud = CloudServerAPI()
        self._connect("/servers", controller=cloud.launch_server,
                      conditions={"method": ["POST"]})
        self._connect("/servers/{server_id}", controller=cloud.delete_server,
                      conditions={'method': ["DELETE"]})
        self._connect("/servers", controller=cloud)


class AuthenticationAPI(wsgi.Application):
    """Handle all authorization requests through WSGI applications."""

    @webob.dec.wsgify
    def __call__(self, req): # pylint: disable-msg=W0221
        # TODO(todd): make a actual session with a unique token
        # just pass the auth key back through for now
        res = webob.Response()
        res.status = '204 No Content'
        res.headers.add('X-Server-Management-Url', req.host_url)
        res.headers.add('X-Storage-Url', req.host_url)
        res.headers.add('X-CDN-Managment-Url', req.host_url)
        res.headers.add('X-Auth-Token', req.headers['X-Auth-Key'])
        return res


class CloudServerAPI(wsgi.Application):
    """Handle all server requests through WSGI applications."""

    def __init__(self):
        super(CloudServerAPI, self).__init__()
        self.instdir = compute.InstanceDirectory()
        self.network = network.PublicNetworkController()

    @webob.dec.wsgify
    def __call__(self, req): # pylint: disable-msg=W0221
        value = {"servers": []}
        for inst in self.instdir.all:
            value["servers"].append(self.instance_details(inst))
        return json.dumps(value)

    def instance_details(self, inst): # pylint: disable-msg=R0201
        """Build the data structure to represent details for an instance."""
        return {
            "id": inst.get("instance_id", None),
            "imageId": inst.get("image_id", None),
            "flavorId": inst.get("instacne_type", None),
            "hostId": inst.get("node_name", None),
            "status": inst.get("state", "pending"),
            "addresses": {
                "public": [network.get_public_ip_for_instance(
                            inst.get("instance_id", None))],
                "private": [inst.get("private_dns_name", None)]},

            # implemented only by Rackspace, not AWS
            "name": inst.get("name", "Not-Specified"),

            # not supported
            "progress": "Not-Supported",
            "metadata": {
                "Server Label": "Not-Supported",
                "Image Version": "Not-Supported"}}

    @webob.dec.wsgify
    def launch_server(self, req):
        """Launch a new instance."""
        data = json.loads(req.body)
        inst = self.build_server_instance(data, req.environ['nova.context'])
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}})

        return json.dumps({"server": self.instance_details(inst)})

    def build_server_instance(self, env, context):
        """Build instance data structure and save it to the data store."""
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
        address = self.network.allocate_ip(
                    inst['user_id'],
                    inst['project_id'],
                    mac=inst['mac_address'])
        inst['private_dns_name'] = str(address)
        inst['bridge_name'] = network.BridgedNetwork.get_network_for_project(
                                inst['user_id'],
                                inst['project_id'],
                                'default')['bridge_name']
        # key_data, key_name, ami_launch_index
        # TODO(todd): key data or root password
        inst.save()
        return inst

    @webob.dec.wsgify
    @wsgi.route_args
    def delete_server(self, req, route_args): # pylint: disable-msg=R0201
        """Delete an instance."""
        owner_hostname = None
        instance = compute.Instance.lookup(route_args['server_id'])
        if instance:
            owner_hostname = instance["node_name"]
        if not owner_hostname:
            return webob.exc.HTTPNotFound("Did not find image, or it was "
                                          "not in a running state.")
        rpc_transport = "%s:%s" % (FLAGS.compute_topic, owner_hostname)
        rpc.cast(rpc_transport,
                 {"method": "reboot_instance",
                  "args": {"instance_id": route_args['server_id']}})
        req.status = "202 Accepted"
