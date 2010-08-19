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

from nova import datastore
from nova.api.rackspace import base
from nova.api.services.image import ImageService
from webob import exc

#TODO(gundlach): Serialize return values
class Controller(base.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": [ "id", "name", "updated", "created", "status",
                           "serverId", "progress" ]
            }
        }
    }

    def __init__(self):
        self._svc = ImageService.load()
        self._id_xlator = RackspaceApiImageIdTranslator()

    def _to_rs_id(self, image_id):
        """
        Convert an image id from the format of our ImageService strategy
        to the Rackspace API format (an int).
        """
        strategy = self._svc.__class__.__name__
        return self._id_xlator.to_rs_id(strategy, image_id)

    def index(self, req):
        """Return all public images."""
        data = self._svc.list()
        for img in data:
            img['id'] = self._to_rs_id(img['id'])
        return dict(images=result)

    def show(self, req, id):
        """Return data about the given image id."""
        img = self._svc.show(id)
        img['id'] = self._to_rs_id(img['id'])
        return dict(image=img)

    def delete(self, req, id):
        # Only public images are supported for now.
        raise exc.HTTPNotFound()

    def create(self, req):
        # Only public images are supported for now, so a request to
        # make a backup of a server cannot be supproted.
        raise exc.HTTPNotFound()

    def update(self, req, id):
        # Users may not modify public images, and that's all that 
        # we support for now.
        raise exc.HTTPNotFound()


class RackspaceApiImageIdTranslator(object):
    """
    Converts Rackspace API image ids to and from the id format for a given
    strategy.
    """

    def __init__(self):
        self._store = datastore.Redis.instance()

    def to_rs_id(self, strategy_name, opaque_id):
        """Convert an id from a strategy-specific one to a Rackspace one."""
        key = "rsapi.idstrategies.image.%s" % strategy_name
        result = self._store.hget(key, str(opaque_id))
        if result: # we have a mapping from opaque to RS for this strategy
            return int(result)
        else:
            nextid = self._store.incr("%s.lastid" % key)
            self._store.hsetnx(key, str(opaque_id), nextid)
            return nextid
