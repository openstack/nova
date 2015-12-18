# Copyright 2015 Rackspace Hosting, Inc.
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


import fixtures

from nova import test
from nova.virt.disk.mount import block
from nova.virt.image import model as imgmodel


class LoopTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LoopTestCase, self).setUp()

        device_path = '/dev/mapper/instances--instance-0000001_disk'
        self.image = imgmodel.LocalBlockImage(device_path)

    def test_get_dev(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        b = block.BlockMount(self.image, tempdir)

        self.assertTrue(b.get_dev())
        self.assertTrue(b.linked)
        self.assertEqual(self.image.path, b.device)

    def test_unget_dev(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        b = block.BlockMount(self.image, tempdir)

        b.unget_dev()

        self.assertIsNone(b.device)
        self.assertFalse(b.linked)
