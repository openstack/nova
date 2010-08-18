# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova.endpoint.rackspace.controllers.base import BaseController
from nova.endpoint import images
from webob import exc

#TODO(gundlach): Serialize return values
class Controller(BaseController):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": [ "id", "name", "updated", "created", "status",
                           "serverId", "progress" ]
            }
        }
    }

    def index(self, req):
        context = req.environ['nova.api_request_context']
        return images.list(context)

    def show(self, req, id):
        context = req.environ['nova.api_request_context']
        return images.list(context, filter_list=[id])

    def delete(self, req, id):
        context = req.environ['nova.api_request_context']
        # TODO(gundlach): make sure it's an image they may delete?
        return images.deregister(context, id)

    def create(self, **kwargs):
        # TODO(gundlach): no idea how to hook this up.  code below
        # is from servers.py.
        inst = self.build_server_instance(kwargs['server'])
        rpc.cast(
            FLAGS.compute_topic, {
                "method": "run_instance",
                "args": {"instance_id": inst.instance_id}})

    def update(self, **kwargs):
        # TODO (gundlach): no idea how to hook this up.  code below
        # is from servers.py.
        instance_id = kwargs['id']
        instance = compute.InstanceDirectory().get(instance_id)
        if not instance:
            raise ServerNotFound("The requested server was not found")
        instance.update(kwargs['server'])
        instance.save()
