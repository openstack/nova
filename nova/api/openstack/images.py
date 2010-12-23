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

from webob import exc

from nova import flags
from nova import utils
from nova import wsgi
import nova.api.openstack
import nova.image.service

from nova.api.openstack import common
from nova.api.openstack import faults


FLAGS = flags.FLAGS


class Controller(wsgi.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": ["id", "name", "updated", "created", "status",
                          "serverId", "progress"]}}}

    def __init__(self):
        self._service = utils.import_object(FLAGS.image_service)

    def index(self, req):
        """Return all public images in brief."""
        return dict(images=[dict(id=img['id'], name=img['name'])
                            for img in self.detail(req)['images']])

    def detail(self, req):
        """Return all public images in detail."""
        try:
            images = self._service.detail(req.environ['nova.context'])
            images = common.limited(images, req)
        except NotImplementedError:
            # Emulate detail() using repeated calls to show()
            ctxt = req.environ['nova.context']
            images = self._service.index(ctxt)
            images = common.limited(images, req)
            images = [self._service.show(ctxt, i['id']) for i in images]
        return dict(images=images)

    def show(self, req, id):
        """Return data about the given image id."""
        return dict(image=self._service.show(req.environ['nova.context'], id))

    def delete(self, req, id):
        # Only public images are supported for now.
        raise faults.Fault(exc.HTTPNotFound())

    def create(self, req):
        # Only public images are supported for now, so a request to
        # make a backup of a server cannot be supproted.
        raise faults.Fault(exc.HTTPNotFound())

    def update(self, req, id):
        # Users may not modify public images, and that's all that
        # we support for now.
        raise faults.Fault(exc.HTTPNotFound())
