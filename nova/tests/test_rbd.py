# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Josh Durgin
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

from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import test
from nova.tests.image import fake as fake_image
from nova.tests.test_volume import DriverTestCase
from nova.volume.driver import RBDDriver

LOG = logging.getLogger(__name__)


class RBDTestCase(test.TestCase):

    def setUp(self):
        super(RBDTestCase, self).setUp()

        def fake_execute(*args):
            pass
        self.driver = RBDDriver(execute=fake_execute)

    def test_good_locations(self):
        locations = [
            'rbd://fsid/pool/image/snap',
            'rbd://%2F/%2F/%2F/%2F',
            ]
        map(self.driver._parse_location, locations)

    def test_bad_locations(self):
        locations = [
            'rbd://image',
            'http://path/to/somewhere/else',
            'rbd://image/extra',
            'rbd://image/',
            'rbd://fsid/pool/image/',
            'rbd://fsid/pool/image/snap/',
            'rbd://///',
            ]
        for loc in locations:
            self.assertRaises(exception.ImageUnacceptable,
                              self.driver._parse_location,
                              loc)
            self.assertFalse(self.driver._is_cloneable(loc))

    def test_cloneable(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://abc/pool/image/snap'
        self.assertTrue(self.driver._is_cloneable(location))

    def test_uncloneable_different_fsid(self):
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        location = 'rbd://def/pool/image/snap'
        self.assertFalse(self.driver._is_cloneable(location))

    def test_uncloneable_unreadable(self):
        def fake_exc(*args):
            raise exception.ProcessExecutionError()
        self.stubs.Set(self.driver, '_get_fsid', lambda: 'abc')
        self.stubs.Set(self.driver, '_execute', fake_exc)
        location = 'rbd://abc/pool/image/snap'
        self.assertFalse(self.driver._is_cloneable(location))


class FakeRBDDriver(RBDDriver):

    def _clone(self):
        pass

    def _resize(self):
        pass


class ManagedRBDTestCase(DriverTestCase):
    driver_name = "nova.tests.test_rbd.FakeRBDDriver"

    def setUp(self):
        super(ManagedRBDTestCase, self).setUp()
        fake_image.stub_out_image_service(self.stubs)

    def _clone_volume_from_image(self, expected_status,
                                 clone_works=True):
        """Try to clone a volume from an image, and check the status
        afterwards"""
        def fake_clone_image(volume, image_location):
            pass

        def fake_clone_error(volume, image_location):
            raise exception.NovaException()

        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        if clone_works:
            self.stubs.Set(self.volume.driver, 'clone_image', fake_clone_image)
        else:
            self.stubs.Set(self.volume.driver, 'clone_image', fake_clone_error)

        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        volume_id = 1
        # creating volume testdata
        db.volume_create(self.context, {'id': volume_id,
                            'updated_at': timeutils.utcnow(),
                            'display_description': 'Test Desc',
                            'size': 20,
                            'status': 'creating',
                            'instance_uuid': None,
                            'host': 'dummy'})
        try:
            if clone_works:
                self.volume.create_volume(self.context,
                                          volume_id,
                                          image_id=image_id)
            else:
                self.assertRaises(exception.NovaException,
                                  self.volume.create_volume,
                                  self.context,
                                  volume_id,
                                  image_id=image_id)

            volume = db.volume_get(self.context, volume_id)
            self.assertEqual(volume['status'], expected_status)
        finally:
            # cleanup
            db.volume_destroy(self.context, volume_id)

    def test_clone_image_status_available(self):
        """Verify that before cloning, an image is in the available state."""
        self._clone_volume_from_image('available', True)

    def test_clone_image_status_error(self):
        """Verify that before cloning, an image is in the available state."""
        self._clone_volume_from_image('error', False)

    def test_clone_success(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        self.stubs.Set(self.volume.driver, 'clone_image', lambda a, b: True)
        image_id = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        self.assertTrue(self.volume.driver.clone_image({}, image_id))

    def test_clone_bad_image_id(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: True)
        self.assertFalse(self.volume.driver.clone_image({}, None))

    def test_clone_uncloneable(self):
        self.stubs.Set(self.volume.driver, '_is_cloneable', lambda x: False)
        self.assertFalse(self.volume.driver.clone_image({}, 'dne'))
