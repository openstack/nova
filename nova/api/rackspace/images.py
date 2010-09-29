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

from nova import wsgi
from nova.api.rackspace import _id_translator
import nova.api.rackspace
import nova.image.service
from nova.api.rackspace import faults

class Controller(wsgi.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": [ "id", "name", "updated", "created", "status",
                           "serverId", "progress" ]
            }
        }
    }

    def __init__(self):
        self._service = nova.image.service.ImageService.load()
        self._id_translator = _id_translator.RackspaceAPIIdTranslator(
                "image", self._service.__class__.__name__)

    def index(self, req):
        """Return all public images in brief."""
        return dict(images=[dict(id=img['id'], name=img['name'])
                            for img in self.detail(req)['images']])

    def detail(self, req):
        """Return all public images in detail."""
        data = self._service.index()
        data = nova.api.rackspace.limited(data, req)
        for img in data:
            img['id'] = self._id_translator.to_rs_id(img['id'])
        return dict(images=data)

    def show(self, req, id):
        """Return data about the given image id."""
        opaque_id = self._id_translator.from_rs_id(id)
        img = self._service.show(opaque_id)
        img['id'] = id
        return dict(image=img)

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
