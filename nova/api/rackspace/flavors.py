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

from nova.api.rackspace import base
from nova.api.rackspace import _id_translator
from nova import flavor
from webob import exc

class Controller(base.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "flavor": [ "id", "name", "ram", "disk" ]
            }
        }
    }

    def __init__(self):
        self._service = flavor.service.FlavorService.load()
        self._id_translator = self._id_translator.RackspaceAPIIdTranslator(
                "flavor", self._service.__class__.__name__)

    def index(self, req):
        """Return all flavors."""
        items = self._service.index()
        for flavor in items:
            flavor['id'] = self._id_translator.to_rs_id(flavor['id'])
        return dict(flavors=items)

    def show(self, req, id):
        """Return data about the given flavor id."""
        opaque_id = self._id_translator.from_rs_id(id)
        item = self._service.show(opaque_id)
        item['id'] = id
        return dict(flavor=item)
