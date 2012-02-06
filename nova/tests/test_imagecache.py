#!/usr/bin/python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Michael Still and Canonical Inc
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


import hashlib
import os
import shutil
import tempfile
import time

from nova import test

from nova import db
from nova import flags
from nova import log as logging
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import utils as virtutils


flags.DECLARE('instances_path', 'nova.compute.manager')
FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.test_imagecache')


class ImageCacheManagerTestCase(test.TestCase):

    def test_read_stored_checksum_missing(self):
        self.stubs.Set(os.path, 'exists', lambda x: False)

        csum = imagecache.read_stored_checksum('/tmp/foo')
        self.assertEquals(csum, None)

    def test_read_stored_checksum(self):
        try:
            dirname = tempfile.mkdtemp()
            fname = os.path.join(dirname, 'aaa')

            csum_input = 'fdghkfhkgjjksfdgjksjkghsdf'
            f = open('%s.sha1' % fname, 'w')
            f.write('%s\n' % csum_input)
            f.close()

            csum_output = imagecache.read_stored_checksum(fname)

            self.assertEquals(csum_input, csum_output)

        finally:
            shutil.rmtree(dirname)

    def test_list_base_images(self):
        listing = ['00000001',
                   'ephemeral_0_20_None',
                   'e97222e91fc4241f49a7f520d1dcf446751129b3_sm',
                   'e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm',
                   'e97222e91fc4241f49a7f520d1dcf446751129b3',
                   '00000004']

        self.stubs.Set(os, 'listdir', lambda x: listing)
        self.stubs.Set(os.path, 'isfile', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_base_images(base_dir)

        self.assertEquals(len(image_cache_manager.unexplained_images), 3)

        expected = os.path.join(base_dir,
                                'e97222e91fc4241f49a7f520d1dcf446751129b3')
        self.assertTrue(expected in image_cache_manager.unexplained_images)

        unexpected = os.path.join(base_dir, '00000004')
        self.assertFalse(unexpected in image_cache_manager.unexplained_images)

        for ent in image_cache_manager.unexplained_images:
            self.assertTrue(ent.startswith(base_dir))

    def test_list_running_instances(self):
        self.stubs.Set(db, 'instance_get_all',
                       lambda x: [{'image_ref': 'image-1',
                                   'host': FLAGS.host,
                                   'name': 'inst-1'},
                                  {'image_ref': 'image-2',
                                   'host': FLAGS.host,
                                   'name': 'inst-2'},
                                  {'image_ref': 'image-2',
                                   'host': 'remotehost',
                                   'name': 'inst-3'}])

        image_cache_manager = imagecache.ImageCacheManager()

        # The argument here should be a context, but its mocked out
        image_cache_manager._list_running_instances(None)

        self.assertEqual(len(image_cache_manager.used_images), 2)
        self.assertTrue(image_cache_manager.used_images['image-1'] ==
                        (1, 0, ['inst-1']))
        self.assertTrue(image_cache_manager.used_images['image-2'] ==
                        (1, 1, ['inst-2', 'inst-3']))

        self.assertEqual(len(image_cache_manager.image_popularity), 2)
        self.assertEqual(image_cache_manager.image_popularity['image-1'], 1)
        self.assertEqual(image_cache_manager.image_popularity['image-2'], 2)

    def test_list_backing_images(self):
        self.stubs.Set(os, 'listdir',
                       lambda x: ['_base', 'instance-00000001',
                                  'instance-00000002', 'instance-00000003'])
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.find('instance-') != -1)
        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: 'e97222e91fc4241f49a7f520d1dcf446751129b3_sm')

        found = os.path.join(FLAGS.instances_path, '_base',
                             'e97222e91fc4241f49a7f520d1dcf446751129b3_sm')

        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager.unexplained_images = [found]

        inuse_images = image_cache_manager._list_backing_images()

        self.assertEquals(inuse_images, [found])
        self.assertEquals(len(image_cache_manager.unexplained_images), 0)

    def test_find_base_file_nothing(self):
        self.stubs.Set(os.path, 'exists', lambda x: False)

        base_dir = '/var/lib/nova/instances/_base'
        fingerprint = '549867354867'
        image_cache_manager = imagecache.ImageCacheManager()
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        self.assertEqual(0, len(res))

    def test_find_base_file_small(self):
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.endswith('549867354867_sm'))

        base_dir = '/var/lib/nova/instances/_base'
        fingerprint = '549867354867'
        image_cache_manager = imagecache.ImageCacheManager()
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        base_file = os.path.join(base_dir, fingerprint + '_sm')
        self.assertTrue(res == [(base_file, True)])

    def test_find_base_file_both(self):
        self.stubs.Set(os.path, 'exists', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        fingerprint = '549867354867'
        image_cache_manager = imagecache.ImageCacheManager()
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        base_file1 = os.path.join(base_dir, fingerprint)
        base_file2 = os.path.join(base_dir, fingerprint + '_sm')
        self.assertTrue(res == [(base_file1, False), (base_file2, True)])

    def test_verify_checksum(self):
        testdata = ('OpenStack Software delivers a massively scalable cloud '
                    'operating system.')
        img = {'container_format': 'ami', 'id': '42'}

        try:
            dirname = tempfile.mkdtemp()
            fname = os.path.join(dirname, 'aaa')

            f = open(fname, 'w')
            f.write(testdata)
            f.close()

            # Checksum is valid
            f = open('%s.sha1' % fname, 'w')
            csum = hashlib.sha1()
            csum.update(testdata)
            f.write(csum.hexdigest())
            f.close()

            image_cache_manager = imagecache.ImageCacheManager()
            res = image_cache_manager._verify_checksum(img, fname)
            self.assertTrue(res)

            # Checksum is invalid
            f = open('%s.sha1' % fname, 'w')
            f.write('banana')
            f.close()

            image_cache_manager = imagecache.ImageCacheManager()
            res = image_cache_manager._verify_checksum(img, fname)
            self.assertFalse(res)

            # Checksum file missing
            os.remove('%s.sha1' % fname)
            image_cache_manager = imagecache.ImageCacheManager()
            res = image_cache_manager._verify_checksum(img, fname)
            self.assertEquals(res, None)

        finally:
            shutil.rmtree(dirname)

    def test_remove_base_file(self):
        try:
            dirname = tempfile.mkdtemp()
            fname = os.path.join(dirname, 'aaa')

            f = open(fname, 'w')
            f.write('data')
            f.close()

            f = open('%s.sha1' % fname, 'w')
            f.close()

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager._remove_base_file(fname)

            # Files are initially too new to delete
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists('%s.sha1' % fname))

            # Old files get cleaned up though
            os.utime(fname, (-1, time.time() - 100000))
            image_cache_manager._remove_base_file(fname)

            self.assertFalse(os.path.exists(fname))
            self.assertFalse(os.path.exists('%s.sha1' % fname))

        finally:
            shutil.rmtree(dirname)
