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

import datetime

from webob import exc

from nova import compute
from nova import flags
from nova import log
from nova import utils
from nova import wsgi
import nova.api.openstack
from nova.api.openstack import common
from nova.api.openstack import faults
import nova.image.service


LOG = log.getLogger('nova.api.openstack.images')

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


def _translate_s3_like_images(image_metadata):
    """Work-around for leaky S3ImageService abstraction"""
    api_metadata = image_metadata.copy()
    _convert_image_id_to_hash(api_metadata)
    api_metadata = _translate_keys(api_metadata)
    _translate_status(api_metadata)
    return api_metadata


def _translate_from_image_service_to_api(image_metadata):
    """Translate from ImageService to OpenStack API style attribute names

    This involves 4 steps:

        1. Filter out attributes that the OpenStack API doesn't need

        2. Translate from base image attributes from names used by
           BaseImageService to names used by OpenStack API

        3. Add in any image properties

        4. Format values according to API spec (for example dates must
           look like "2010-08-10T12:00:00Z")
    """
    service_metadata = image_metadata.copy()
    properties = service_metadata.pop('properties', {})

    # 1. Filter out unecessary attributes
    api_keys = ['id', 'name', 'updated_at', 'created_at', 'status']
    api_metadata = utils.partition_dict(service_metadata, api_keys)[0]

    # 2. Translate base image attributes
    api_map = {'updated_at': 'updated', 'created_at': 'created'}
    api_metadata = utils.map_dict_keys(api_metadata, api_map)

    # 3. Add in any image properties
    # 3a. serverId is used for backups and snapshots
    try:
        api_metadata['serverId'] = int(properties['instance_id'])
    except KeyError:
        pass  # skip if it's not present
    except ValueError:
        pass  # skip if it's not an integer

    # 3b. Progress special case
    # TODO(sirp): ImageService doesn't have a notion of progress yet, so for
    # now just fake it
    if service_metadata['status'] == 'saving':
        api_metadata['progress'] = 0

    # 4. Format values
    # 4a. Format Image Status (API requires uppercase)
    status_service2api = {'queued': 'QUEUED',
                          'preparing': 'PREPARING',
                          'saving': 'SAVING',
                          'active': 'ACTIVE',
                          'killed': 'FAILED'}
    api_metadata['status'] = status_service2api[api_metadata['status']]

    # 4b. Format timestamps
    def _format_timestamp(dt_str):
        """Return a timestamp formatted for OpenStack API

        NOTE(sirp):

        ImageService (specifically GlanceImageService) is currently
        returning timestamps as strings. This should probably be datetime
        objects. In the mean time, we work around this by using strptime() to
        create datetime objects.
        """
        if dt_str is None:
            return None

        service_timestamp_fmt = "%Y-%m-%dT%H:%M:%S"
        api_timestamp_fmt = "%Y-%m-%dT%H:%M:%SZ"
        dt = datetime.datetime.strptime(dt_str, service_timestamp_fmt)
        return dt.strftime(api_timestamp_fmt)

    for ts_attr in ('created', 'updated'):
        if ts_attr in api_metadata:
            formatted_timestamp = _format_timestamp(api_metadata[ts_attr])
            api_metadata[ts_attr] = formatted_timestamp

    return api_metadata


def _safe_translate(image_metadata):
    """Translate attributes for OpenStack API, temporary workaround for
    S3ImageService attribute leakage.
    """
    # FIXME(sirp): The S3ImageService appears to be leaking implementation
    # details, including its internal attribute names, and internal
    # `status` values. Working around it for now.
    s3_like_image = ('imageId' in image_metadata)
    if s3_like_image:
        translate = _translate_s3_like_images
    else:
        translate = _translate_from_image_service_to_api
    return translate(image_metadata)


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
        context = req.environ['nova.context']
        image_metas = self._service.index(context)
        image_metas = common.limited(image_metas, req)
        return dict(images=image_metas)

    def detail(self, req):
        """Return all public images in detail"""
        context = req.environ['nova.context']
        image_metas = self._service.detail(context)
        image_metas = common.limited(image_metas, req)
        api_image_metas = [_safe_translate(image_meta)
                           for image_meta in image_metas]
        return dict(images=api_image_metas)

    def show(self, req, id):
        """Return data about the given image id"""
        context = req.environ['nova.context']
        image_id = common.get_image_id_from_image_hash(
            self._service, req.environ['nova.context'], id)

        image_meta = self._service.show(context, image_id)
        api_image_meta = _safe_translate(image_meta)
        return dict(image=api_image_meta)

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
        api_image_meta = _safe_translate(image_meta)
        return dict(image=api_image_meta)

    def update(self, req, id):
        # Users may not modify public images, and that's all that
        # we support for now.
        raise faults.Fault(exc.HTTPNotFound())
