# Copyright 2011 Justin Santa Barbara
# Copyright 2012 OpenStack Foundation
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

"""Implementation of a fake image service."""

import copy
import datetime

from oslo_log import log as logging
from oslo_utils import uuidutils

import nova.conf
from nova import exception
from nova import objects
from nova.objects import fields as obj_fields
from nova.tests import fixtures as nova_fixtures

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID = '70a599e0-31e7-49b7-b260-868f441e862b'


class _FakeImageService(object):
    """Mock (fake) image service for unit testing."""

    def __init__(self):
        self.images = {}
        # NOTE(justinsb): The OpenStack API can't upload an image?
        # So, make sure we've got one..
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)

        image1 = {'id': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'raw',
                 'disk_format': 'raw',
                 'size': '25165824',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': ['tag1', 'tag2'],
                 'properties': {
                    'kernel_id': 'nokernel',
                    'ramdisk_id': 'nokernel',
                    'architecture': obj_fields.Architecture.X86_64}}

        image2 = {'id': 'a2459075-d96c-40d5-893e-577ff92e721c',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'size': '58145823',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': [],
                 'properties': {'kernel_id': 'nokernel',
                                'ramdisk_id': 'nokernel'}}

        image3 = {'id': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'bare',
                 'disk_format': 'raw',
                 'size': '83594576',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': ['tag3', 'tag4'],
                 'properties': {
                     'kernel_id': 'nokernel',
                     'ramdisk_id': 'nokernel',
                     'architecture': obj_fields.Architecture.X86_64}}

        image4 = {'id': 'cedef40a-ed67-4d10-800e-17455edce175',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'size': '84035174',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': [],
                 'properties': {'kernel_id': 'nokernel',
                                'ramdisk_id': 'nokernel'}}

        image5 = {'id': 'c905cedb-7281-47e4-8a62-f26bc5fc4c77',
                 'name': 'fakeimage123456',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': True,
                 'container_format': 'ami',
                 'disk_format': 'ami',
                 'size': '26360814',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': [],
                 'properties': {'kernel_id':
                                    '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                                'ramdisk_id': None}}

        image6 = {'id': 'a440c04b-79fa-479c-bed1-0b816eaec379',
                 'name': 'fakeimage6',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'ova',
                 'disk_format': 'vhd',
                 'size': '49163826',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': [],
                 'properties': {
                    'kernel_id': 'nokernel',
                    'ramdisk_id': 'nokernel',
                    'architecture': obj_fields.Architecture.X86_64,
                    'auto_disk_config': 'False'}}

        image7 = {'id': AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
                 'name': 'fakeimage7',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'ova',
                 'disk_format': 'vhd',
                 'size': '74185822',
                 'min_ram': 0,
                 'min_disk': 0,
                 'protected': False,
                 'visibility': 'public',
                 'tags': [],
                 'properties': {
                    'kernel_id': 'nokernel',
                    'ramdisk_id': 'nokernel',
                    'architecture': obj_fields.Architecture.X86_64,
                    'auto_disk_config': 'True'}}

        self.create(None, image1)
        self.create(None, image2)
        self.create(None, image3)
        self.create(None, image4)
        self.create(None, image5)
        self.create(None, image6)
        self.create(None, image7)
        self._imagedata = {}
        super(_FakeImageService, self).__init__()

    # TODO(bcwaldon): implement optional kwargs such as limit, sort_dir
    def detail(self, context, **kwargs):
        """Return list of detailed image information."""
        return copy.deepcopy(list(self.images.values()))

    def download(self, context, image_id, data=None, dst_path=None,
                 trusted_certs=None):
        self.show(context, image_id)
        if data:
            data.write(self._imagedata.get(image_id, b''))
        elif dst_path:
            with open(dst_path, 'wb') as data:
                data.write(self._imagedata.get(image_id, b''))

    def show(self, context, image_id, include_locations=False,
             show_deleted=True):
        """Get data about specified image.

        Returns a dict containing image data for the given opaque image id.

        """
        image = self.images.get(str(image_id))
        if image:
            return copy.deepcopy(image)
        LOG.warning('Unable to find image id %s.  Have images: %s',
                    image_id, self.images)
        raise exception.ImageNotFound(image_id=image_id)

    def create(self, context, metadata, data=None):
        """Store the image data and return the new image id.

        :raises: Duplicate if the image already exist.

        """
        image_id = str(metadata.get('id', uuidutils.generate_uuid()))
        metadata['id'] = image_id
        if image_id in self.images:
            raise exception.CouldNotUploadImage(image_id=image_id)
        image_meta = copy.deepcopy(metadata)
        # Glance sets the size value when an image is created, so we
        # need to do that here to fake things out if it's not provided
        # by the caller. This is needed to avoid a KeyError in the
        # image-size API.
        if 'size' not in image_meta:
            image_meta['size'] = None
        # Similarly, Glance provides the status on the image once it's created
        # and this is checked in the compute API when booting a server from
        # this image, so we just fake it out to be 'active' even though this
        # is mostly a lie on a newly created image.
        if 'status' not in metadata:
            image_meta['status'] = 'active'
        # The owner of the image is by default the request context project_id.
        if context and 'owner' not in image_meta.get('properties', {}):
            # Note that normally "owner" is a top-level field in an image
            # resource in glance but we have to fake this out for the images
            # proxy API by throwing it into the generic "properties" dict.
            image_meta.get('properties', {})['owner'] = context.project_id
        self.images[image_id] = image_meta
        if data:
            self._imagedata[image_id] = data.read()
        return self.images[image_id]

    def update(self, context, image_id, metadata, data=None,
               purge_props=False):
        """Replace the contents of the given image with the new data.

        :raises: ImageNotFound if the image does not exist.

        """
        if not self.images.get(image_id):
            raise exception.ImageNotFound(image_id=image_id)
        if purge_props:
            self.images[image_id] = copy.deepcopy(metadata)
        else:
            image = self.images[image_id]
            try:
                image['properties'].update(metadata.pop('properties'))
            except KeyError:
                pass
            image.update(metadata)
        return self.images[image_id]

    def delete(self, context, image_id):
        """Delete the given image.

        :raises: ImageNotFound if the image does not exist.

        """
        removed = self.images.pop(image_id, None)
        if not removed:
            raise exception.ImageNotFound(image_id=image_id)

    def get_location(self, context, image_id):
        if image_id in self.images:
            return 'fake_location'
        return None


_fakeImageService = _FakeImageService()


def FakeImageService():
    return _fakeImageService


def FakeImageService_reset():
    global _fakeImageService
    _fakeImageService = _FakeImageService()


def get_valid_image_id():
    return AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID


def stub_out_image_service(test):
    """Stubs out the image service for the test with the FakeImageService

    :param test: instance of nova.test.TestCase
    :returns: The stubbed out FakeImageService object
    """
    image_service = FakeImageService()
    test.stub_out('nova.image.glance.get_remote_image_service',
                  lambda x, y: (image_service, y))
    test.stub_out('nova.image.glance.get_default_image_service',
                  lambda: image_service)
    test.useFixture(nova_fixtures.ConfPatcher(
        group="glance", api_servers=['http://localhost:9292']))
    return image_service


def fake_image_obj(default_image_meta=None, default_image_props=None,
                   variable_image_props=None):
    """Helper for constructing a test ImageMeta object with attributes and
    properties coming from a combination of (probably hard-coded)
    values within a test, and (optionally) variable values from the
    test's caller, if the test is actually a helper written to be
    reusable and run multiple times with different parameters from
    different "wrapper" tests.
    """
    image_meta_props = default_image_props or {}
    if variable_image_props:
        image_meta_props.update(variable_image_props)

    test_image_meta = default_image_meta or {"disk_format": "raw"}
    if 'name' not in test_image_meta:
        # NOTE(aspiers): the name is specified here in case it's needed
        # by the logging in nova.virt.hardware.get_mem_encryption_constraint()
        test_image_meta['name'] = 'fake_image'
    test_image_meta.update({
        'properties': image_meta_props,
    })

    return objects.ImageMeta.from_dict(test_image_meta)
