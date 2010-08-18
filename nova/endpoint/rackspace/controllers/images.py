from nova.endpoint.rackspace.controllers.base import BaseController
from nova.endpoint import images
from webob import exc

#TODO(gundlach): Serialize return values
class ImagesController(BaseController):

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
