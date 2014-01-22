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

import mock

from nova import test
from nova.virt.libvirt import imagehandler


IMAGE_ID = '155d900f-4e14-4e4c-a73d-069cbf4541e6'
IMAGE_PATH = '/var/run/instances/_base/img'


class RBDTestCase(test.NoDBTestCase):

    def setUp(self):
        super(RBDTestCase, self).setUp()
        self.imagehandler = imagehandler.RBDCloneImageHandler(
            rbd=mock.Mock(),
            rados=mock.Mock())
        self.imagehandler.driver.is_cloneable = mock.Mock()
        self.imagehandler.driver.clone = mock.Mock()

    def tearDown(self):
        super(RBDTestCase, self).tearDown()

    def test_fetch_image_no_snapshot(self):
        url = 'rbd://old_image'
        self.imagehandler.driver.is_cloneable.return_value = False
        handled = self.imagehandler._fetch_image(None, IMAGE_ID,
                                                 dict(disk_format='raw'),
                                                 IMAGE_PATH,
                                                 backend_type='rbd',
                                                 backend_location=('a', 'b'),
                                                 location=dict(url=url))
        self.assertFalse(handled)
        self.imagehandler.driver.is_cloneable.assert_called_once_with(url,
                                                                      mock.ANY)
        self.assertFalse(self.imagehandler.driver.clone.called)

    def test_fetch_image_non_rbd_backend(self):
        url = 'rbd://fsid/pool/image/snap'
        self.imagehandler.driver.is_cloneable.return_value = True
        handled = self.imagehandler._fetch_image(None, IMAGE_ID,
                                                 dict(disk_format='raw'),
                                                 IMAGE_PATH,
                                                 backend_type='lvm',
                                                 backend_location='/path',
                                                 location=dict(url=url))
        self.assertFalse(handled)
        self.assertFalse(self.imagehandler.driver.clone.called)

    def test_fetch_image_rbd_not_cloneable(self):
        url = 'rbd://fsid/pool/image/snap'
        dest_pool = 'foo'
        dest_image = 'bar'
        self.imagehandler.driver.is_cloneable.return_value = False
        handled = self.imagehandler._fetch_image(None, IMAGE_ID,
                                                 dict(disk_format='raw'),
                                                 IMAGE_PATH,
                                                 backend_type='rbd',
                                                 backend_location=(dest_pool,
                                                                   dest_image),
                                                 location=dict(url=url))
        self.imagehandler.driver.is_cloneable.assert_called_once_with(url,
                                                                      mock.ANY)
        self.assertFalse(handled)

    def test_fetch_image_cloneable(self):
        url = 'rbd://fsid/pool/image/snap'
        dest_pool = 'foo'
        dest_image = 'bar'
        self.imagehandler.driver.is_cloneable.return_value = True
        handled = self.imagehandler._fetch_image(None, IMAGE_ID,
                                                 dict(disk_format='raw'),
                                                 IMAGE_PATH,
                                                 backend_type='rbd',
                                                 backend_location=(dest_pool,
                                                                   dest_image),
                                                 location=dict(url=url))
        self.imagehandler.driver.is_cloneable.assert_called_once_with(url,
                                                                      mock.ANY)
        self.imagehandler.driver.clone.assert_called_once_with(dest_pool,
                                                               dest_image,
                                                               'pool',
                                                               'image',
                                                               'snap')
        self.assertTrue(handled)

    def test_remove_image(self):
        url = 'rbd://fsid/pool/image/snap'
        pool = 'foo'
        image = 'bar'
        self.imagehandler.driver.remove = mock.Mock()
        self.imagehandler.driver.is_cloneable.return_value = True
        handled = self.imagehandler._remove_image(None, IMAGE_ID,
                                                  dict(disk_format='raw'),
                                                  IMAGE_PATH,
                                                  backend_type='rbd',
                                                  backend_location=(pool,
                                                                    image),
                                                  backend_dest='baz',
                                                  location=dict(url=url))
        self.imagehandler.driver.is_cloneable.assert_called_once_with(url,
                                                                      mock.ANY)
        self.imagehandler.driver.remove.assert_called_once_with(image)
        self.assertTrue(handled)

    def test_move_image(self):
        url = 'rbd://fsid/pool/image/snap'
        pool = 'foo'
        image = 'bar'
        dest_image = 'baz'
        self.imagehandler.driver.rename = mock.Mock()
        self.imagehandler.driver.is_cloneable.return_value = True
        handled = self.imagehandler._move_image(None, IMAGE_ID,
                                                dict(disk_format='raw'),
                                                IMAGE_PATH, IMAGE_PATH,
                                                backend_type='rbd',
                                                backend_location=(pool, image),
                                                backend_dest='baz',
                                                location=dict(url=url))
        self.imagehandler.driver.is_cloneable.assert_called_once_with(url,
                                                                      mock.ANY)
        self.imagehandler.driver.rename.assert_called_once_with(image,
                                                                dest_image)
        self.assertTrue(handled)
