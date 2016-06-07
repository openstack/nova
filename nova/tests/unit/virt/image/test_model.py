#
# Copyright (C) 2014 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#

from nova import exception
from nova import test
from nova.virt.image import model as imgmodel


class ImageTest(test.NoDBTestCase):

    def test_local_file_image(self):
        img = imgmodel.LocalFileImage(
            "/var/lib/libvirt/images/demo.qcow2",
            imgmodel.FORMAT_QCOW2)

        self.assertIsInstance(img, imgmodel.Image)
        self.assertEqual("/var/lib/libvirt/images/demo.qcow2", img.path)
        self.assertEqual(imgmodel.FORMAT_QCOW2, img.format)

    def test_local_file_bad_format(self):
        self.assertRaises(exception.InvalidImageFormat,
                          imgmodel.LocalFileImage,
                          "/var/lib/libvirt/images/demo.qcow2",
                          "jpeg")

    def test_local_block_image(self):
        img = imgmodel.LocalBlockImage(
            "/dev/volgroup/demovol")

        self.assertIsInstance(img, imgmodel.Image)
        self.assertEqual("/dev/volgroup/demovol", img.path)
        self.assertEqual(imgmodel.FORMAT_RAW, img.format)

    def test_rbd_image(self):
        img = imgmodel.RBDImage(
            "demo",
            "openstack",
            "cthulu",
            "braanes",
            ["rbd.example.org"])

        self.assertIsInstance(img, imgmodel.Image)
        self.assertEqual("demo", img.name)
        self.assertEqual("openstack", img.pool)
        self.assertEqual("cthulu", img.user)
        self.assertEqual("braanes", img.password)
        self.assertEqual(["rbd.example.org"], img.servers)
        self.assertEqual(imgmodel.FORMAT_RAW, img.format)

    def test_equality(self):
        img1 = imgmodel.LocalFileImage(
            "/var/lib/libvirt/images/demo.qcow2",
            imgmodel.FORMAT_QCOW2)
        img2 = imgmodel.LocalFileImage(
            "/var/lib/libvirt/images/demo.qcow2",
            imgmodel.FORMAT_QCOW2)
        img3 = imgmodel.LocalFileImage(
            "/var/lib/libvirt/images/demo.qcow2",
            imgmodel.FORMAT_RAW)
        img4 = imgmodel.LocalImage(
            "/dev/mapper/vol",
            imgmodel.FORMAT_RAW)
        img5 = imgmodel.LocalBlockImage(
            "/dev/mapper/vol")

        self.assertEqual(img1, img1)
        self.assertEqual(img1, img2)
        self.assertEqual(img1.__hash__(), img2.__hash__())
        self.assertNotEqual(img1, img3)
        self.assertNotEqual(img4, img5)

    def test_stringify(self):
        img = imgmodel.RBDImage(
            "demo",
            "openstack",
            "cthulu",
            "braanes",
            ["rbd.example.org"])

        msg = str(img)
        self.assertEqual(msg.find("braanes"), -1)
        self.assertNotEqual(msg.find("***"), -1)
