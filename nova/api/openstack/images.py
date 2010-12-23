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
from nova.api.openstack import faults


FLAGS = flags.FLAGS


def _entity_list(entities):
    """
    Coerces a list of images into proper dictionary format
    entities is a list of entities (dicts)

    """
    return dict(images=entities)


def _entity_detail(inst):
    """
    Maps everything to Rackspace-like attributes for return
    also pares down attributes to those we want
    inst is a single entity (dict)

    """
    status_mapping = {
        'pending': 'queued',
        'decrypting': 'preparing',
        'untarring': 'saving',
        'available': 'active'}

    # TODO(tr3buchet): this map is specific to s3 object store,
    # replace with a list of keys for _select_keys later
    mapped_keys = {'status': 'imageState',
                   'id': 'imageId',
                   'name': 'imageLocation'}

    mapped_inst = {}
    # TODO(tr3buchet):
    # this chunk of code works with s3 and the local image service/glance
    # when we switch to glance/local image service it can be replaced with
    # a call to _select_keys, and mapped_keys can be changed to a list
    try:
        for k, v in mapped_keys.iteritems():
            # map s3 fields
            mapped_inst[k] = inst[v]
    except KeyError:
        mapped_inst = _select_keys(inst, mapped_keys.keys())


    mapped_inst['status'] = status_mapping[mapped_inst['status']]

    return mapped_inst


def _entity_inst(inst):
    """
    Filters all model attributes save for id and name
    inst is a single entity (dict)

    """
    return _select_keys(inst, ['id', 'name'])


def _select_keys(inst, keys):
    """
    Filters all model attributes except for keys
    inst is a single entity (dict)

    """
    return dict((k, v) for k, v in inst.iteritems() if k in keys)


class Controller(wsgi.Controller):

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "image": ["id", "name", "updated", "created", "status",
                          "serverId", "progress"]}}}

    def __init__(self):
        self._service = utils.import_object(FLAGS.image_service)

    def index(self, req):
        """Return all public images in brief"""
        items = self._service.index(req.environ['nova.context'])
        items = common.limited(images, req)
        items = [_entity_inst(item) for item in items]
        return dict(images=items)

    def detail(self, req):
        """Return all public images in detail"""
        try:
            items = self._service.detail(req.environ['nova.context'])
        except NotImplementedError:
            items = self._service.index(req.environ['nova.context'])
        items = common.limited(images, req)
        items = [_entity_detail(item) for item in items]
        return dict(images=items)

    def show(self, req, id):
        """Return data about the given image id"""
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
