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

from nova import compute
from nova import flags
from nova import utils
from nova import wsgi
import nova.api.openstack
from nova.api.openstack import common
from nova.api.openstack import faults
import nova.image.service


FLAGS = flags.FLAGS


def _translate_keys(item):
    """
    Maps key names to Rackspace-like attributes for return
    also pares down attributes to those we want
    item is a dict

    Note: should be removed when the set of keys expected by the api
    and the set of keys returned by the image service are equivalent

    """
    # TODO(tr3buchet): this map is specific to s3 object store,
    # replace with a list of keys for _filter_keys later
    mapped_keys = {'status': 'imageState',
                   'id': 'imageId',
                   'name': 'imageLocation'}

    mapped_item = {}
    # TODO(tr3buchet):
    # this chunk of code works with s3 and the local image service/glance
    # when we switch to glance/local image service it can be replaced with
    # a call to _filter_keys, and mapped_keys can be changed to a list
    try:
        for k, v in mapped_keys.iteritems():
            # map s3 fields
            mapped_item[k] = item[v]
    except KeyError:
        # return only the fields api expects
        mapped_item = _filter_keys(item, mapped_keys.keys())

    return mapped_item


def _translate_status(item):
    """
    Translates status of image to match current Rackspace api bindings
    item is a dict

    Note: should be removed when the set of statuses expected by the api
    and the set of statuses returned by the image service are equivalent

    """
    status_mapping = {
        'pending': 'queued',
        'decrypting': 'preparing',
        'untarring': 'saving',
        'available': 'active'}
    try:
        item['status'] = status_mapping[item['status']]
    except KeyError:
        # TODO(sirp): Performing translation of status (if necessary) here for
        # now. Perhaps this should really be done in EC2 API and
        # S3ImageService
        pass

    return item


def _filter_keys(item, keys):
    """
    Filters all model attributes except for keys
    item is a dict

    """
    return dict((k, v) for k, v in item.iteritems() if k in keys)


def _convert_image_id_to_hash(image):
    if 'imageId' in image:
        # Convert EC2-style ID (i-blah) to Rackspace-style (int)
        image_id = abs(hash(image['imageId']))
        image['imageId'] = image_id
        image['id'] = image_id


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
        items = common.limited(items, req)
        items = [_filter_keys(item, ('id', 'name')) for item in items]
        return dict(images=items)

    def detail(self, req):
        """Return all public images in detail"""
        try:
            items = self._service.detail(req.environ['nova.context'])
        except NotImplementedError:
            items = self._service.index(req.environ['nova.context'])
        for image in items:
            _convert_image_id_to_hash(image)

        items = common.limited(items, req)
        items = [_translate_keys(item) for item in items]
        items = [_translate_status(item) for item in items]
        return dict(images=items)

    def show(self, req, id):
        """Return data about the given image id"""
        image_id = common.get_image_id_from_image_hash(self._service,
                    req.environ['nova.context'], id)

        image = self._service.show(req.environ['nova.context'], image_id)
        _convert_image_id_to_hash(image)
        self._format_image_dates(image)
        return dict(image=image)

    def delete(self, req, id):
        # Only public images are supported for now.
        raise faults.Fault(exc.HTTPNotFound())

    def create(self, req):
        context = req.environ['nova.context']
        env = self._deserialize(req.body, req.get_content_type())
        instance_id = env["image"]["serverId"]
        name = env["image"]["name"]

        image_meta = compute.API().snapshot(
            context, instance_id, name)

        return dict(image=image_meta)

    def update(self, req, id):
        # Users may not modify public images, and that's all that
        # we support for now.
        raise faults.Fault(exc.HTTPNotFound())

    def _format_image_dates(self, image):
        for attr in ['created_at', 'updated_at', 'deleted_at']:
            if image[attr] is not None:
                image[attr] = image[attr].strftime('%Y-%m-%dT%H:%M:%SZ')
