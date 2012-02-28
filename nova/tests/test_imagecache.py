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


import contextlib
import cStringIO
import hashlib
import logging
import os
import time

from nova import test

from nova import db
from nova import flags
from nova import log
from nova import image
from nova import utils
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import utils as virtutils


flags.DECLARE('instances_path', 'nova.compute.manager')
FLAGS = flags.FLAGS

LOG = log.getLogger(__name__)


class ImageCacheManagerTestCase(test.TestCase):

    def setUp(self):
        super(ImageCacheManagerTestCase, self).setUp()
        self.stock_instance_names = {'instance-00000001': '123',
                                     'instance-00000002': '456',
                                     'instance-00000003': '789',
                                     'banana-42-hamster': '444'}

    def test_read_stored_checksum_missing(self):
        self.stubs.Set(os.path, 'exists', lambda x: False)

        csum = imagecache.read_stored_checksum('/tmp/foo')
        self.assertEquals(csum, None)

    def test_read_stored_checksum(self):
        with utils.tempdir() as tmpdir:
            fname = os.path.join(tmpdir, 'aaa')

            csum_input = 'fdghkfhkgjjksfdgjksjkghsdf'
            f = open('%s.sha1' % fname, 'w')
            f.write('%s\n' % csum_input)
            f.close()

            csum_output = imagecache.read_stored_checksum(fname)

            self.assertEquals(csum_input, csum_output)

    def test_list_base_images(self):
        listing = ['00000001',
                   'ephemeral_0_20_None',
                   'e97222e91fc4241f49a7f520d1dcf446751129b3_sm',
                   'e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm',
                   'e97222e91fc4241f49a7f520d1dcf446751129b3',
                   '17d1b00b81642842e514494a78e804e9a511637c',
                   '17d1b00b81642842e514494a78e804e9a511637c_5368709120',
                   '17d1b00b81642842e514494a78e804e9a511637c_10737418240',
                   '00000004']

        self.stubs.Set(os, 'listdir', lambda x: listing)
        self.stubs.Set(os.path, 'isfile', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_base_images(base_dir)

        self.assertEquals(len(image_cache_manager.unexplained_images), 6)

        expected = os.path.join(base_dir,
                                'e97222e91fc4241f49a7f520d1dcf446751129b3')
        self.assertTrue(expected in image_cache_manager.unexplained_images)

        expected = os.path.join(base_dir,
                                '17d1b00b81642842e514494a78e804e9a511637c_'
                                '10737418240')
        self.assertTrue(expected in image_cache_manager.unexplained_images)

        unexpected = os.path.join(base_dir, '00000004')
        self.assertFalse(unexpected in image_cache_manager.unexplained_images)

        for ent in image_cache_manager.unexplained_images:
            self.assertTrue(ent.startswith(base_dir))

        self.assertEquals(len(image_cache_manager.originals), 2)

        expected = os.path.join(base_dir,
                                '17d1b00b81642842e514494a78e804e9a511637c')
        self.assertTrue(expected in image_cache_manager.originals)

        unexpected = os.path.join(base_dir,
                                  '17d1b00b81642842e514494a78e804e9a511637c_'
                                '10737418240')
        self.assertFalse(unexpected in image_cache_manager.originals)

    def test_list_running_instances(self):
        self.stubs.Set(db, 'instance_get_all',
                       lambda x: [{'image_ref': 'image-1',
                                   'host': FLAGS.host,
                                   'name': 'inst-1',
                                   'uuid': '123'},
                                  {'image_ref': 'image-2',
                                   'host': FLAGS.host,
                                   'name': 'inst-2',
                                   'uuid': '456'},
                                  {'image_ref': 'image-2',
                                   'host': 'remotehost',
                                   'name': 'inst-3',
                                   'uuid': '789'}])

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

    def test_list_backing_images_small(self):
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
        image_cache_manager.instance_names = self.stock_instance_names

        inuse_images = image_cache_manager._list_backing_images()

        self.assertEquals(inuse_images, [found])
        self.assertEquals(len(image_cache_manager.unexplained_images), 0)

    def test_list_backing_images_resized(self):
        self.stubs.Set(os, 'listdir',
                       lambda x: ['_base', 'instance-00000001',
                                  'instance-00000002', 'instance-00000003'])
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.find('instance-') != -1)
        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: ('e97222e91fc4241f49a7f520d1dcf446751129b3_'
                                  '10737418240'))

        found = os.path.join(FLAGS.instances_path, '_base',
                             'e97222e91fc4241f49a7f520d1dcf446751129b3_'
                             '10737418240')

        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager.unexplained_images = [found]
        image_cache_manager.instance_names = self.stock_instance_names

        inuse_images = image_cache_manager._list_backing_images()

        self.assertEquals(inuse_images, [found])
        self.assertEquals(len(image_cache_manager.unexplained_images), 0)

    def test_list_backing_images_instancename(self):
        self.stubs.Set(os, 'listdir',
                       lambda x: ['_base', 'banana-42-hamster'])
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.find('banana-42-hamster') != -1)
        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: 'e97222e91fc4241f49a7f520d1dcf446751129b3_sm')

        found = os.path.join(FLAGS.instances_path, '_base',
                             'e97222e91fc4241f49a7f520d1dcf446751129b3_sm')

        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager.unexplained_images = [found]
        image_cache_manager.instance_names = self.stock_instance_names

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
        fingerprint = '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a'
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.endswith('%s_sm' % fingerprint))

        base_dir = '/var/lib/nova/instances/_base'
        image_cache_manager = imagecache.ImageCacheManager()
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        base_file = os.path.join(base_dir, fingerprint + '_sm')
        self.assertTrue(res == [(base_file, True, False)])

    def test_find_base_file_resized(self):
        fingerprint = '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a'
        listing = ['00000001',
                   'ephemeral_0_20_None',
                   '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a_10737418240',
                   '00000004']

        self.stubs.Set(os, 'listdir', lambda x: listing)
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.endswith('%s_10737418240' % fingerprint))
        self.stubs.Set(os.path, 'isfile', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_base_images(base_dir)
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        base_file = os.path.join(base_dir, fingerprint + '_10737418240')
        self.assertTrue(res == [(base_file, False, True)])

    def test_find_base_file_all(self):
        fingerprint = '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a'
        listing = ['00000001',
                   'ephemeral_0_20_None',
                   '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a_sm',
                   '968dd6cc49e01aaa044ed11c0cce733e0fa44a6a_10737418240',
                   '00000004']

        self.stubs.Set(os, 'listdir', lambda x: listing)
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.stubs.Set(os.path, 'isfile', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_base_images(base_dir)
        res = list(image_cache_manager._find_base_file(base_dir, fingerprint))

        base_file1 = os.path.join(base_dir, fingerprint)
        base_file2 = os.path.join(base_dir, fingerprint + '_sm')
        base_file3 = os.path.join(base_dir, fingerprint + '_10737418240')
        print res
        self.assertTrue(res == [(base_file1, False, False),
                                (base_file2, True, False),
                                (base_file3, False, True)])

    @contextlib.contextmanager
    def _intercept_log_messages(self):
        try:
            mylog = log.getLogger()
            stream = cStringIO.StringIO()
            handler = logging.StreamHandler(stream)
            handler.setFormatter(log.LegacyNovaFormatter())
            mylog.logger.addHandler(handler)
            yield stream
        finally:
            mylog.logger.removeHandler(handler)

    def test_verify_checksum(self):
        testdata = ('OpenStack Software delivers a massively scalable cloud '
                    'operating system.')
        img = {'container_format': 'ami', 'id': '42'}

        self.flags(checksum_base_images=True)

        with self._intercept_log_messages() as stream:
            with utils.tempdir() as tmpdir:
                fname = os.path.join(tmpdir, 'aaa')

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
                log = stream.getvalue()
                self.assertNotEqual(log.find('image verification failed'), -1)

                # Checksum file missing
                os.remove('%s.sha1' % fname)
                image_cache_manager = imagecache.ImageCacheManager()
                res = image_cache_manager._verify_checksum(img, fname)
                self.assertEquals(res, None)

                # Checksum requests for a file with no checksum now have the
                # side effect of creating the checksum
                self.assertTrue(os.path.exists('%s.sha1' % fname))

    @contextlib.contextmanager
    def _make_base_file(self, checksum=True):
        """Make a base file for testing."""

        with utils.tempdir() as tmpdir:
            fname = os.path.join(tmpdir, 'aaa')

            base_file = open(fname, 'w')
            base_file.write('data')
            base_file.close()
            base_file = open(fname, 'r')

            if checksum:
                checksum_file = open('%s.sha1' % fname, 'w')
                checksum_file.write(utils.hash_file(base_file))
                checksum_file.close()

            base_file.close()
            yield fname

    def test_remove_base_file(self):
        with self._make_base_file() as fname:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager._remove_base_file(fname)

            # Files are initially too new to delete
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists('%s.sha1' % fname))

            # Old files get cleaned up though
            os.utime(fname, (-1, time.time() - 3601))
            image_cache_manager._remove_base_file(fname)

            self.assertFalse(os.path.exists(fname))
            self.assertFalse(os.path.exists('%s.sha1' % fname))

    def test_remove_base_file_original(self):
        with self._make_base_file() as fname:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.originals = [fname]
            image_cache_manager._remove_base_file(fname)

            # Files are initially too new to delete
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists('%s.sha1' % fname))

            # This file should stay longer than a resized image
            os.utime(fname, (-1, time.time() - 3601))
            image_cache_manager._remove_base_file(fname)

            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists('%s.sha1' % fname))

            # Originals don't stay forever though
            os.utime(fname, (-1, time.time() - 3600 * 25))
            image_cache_manager._remove_base_file(fname)

            self.assertFalse(os.path.exists(fname))
            self.assertFalse(os.path.exists('%s.sha1' % fname))

    def test_remove_base_file_dne(self):
        # This test is solely to execute the "does not exist" code path. We
        # don't expect the method being tested to do anything in this case.
        with utils.tempdir() as tmpdir:
            fname = os.path.join(tmpdir, 'aaa')
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager._remove_base_file(fname)

    def test_remove_base_file_oserror(self):
        with self._intercept_log_messages() as stream:
            with utils.tempdir() as tmpdir:
                fname = os.path.join(tmpdir, 'aaa')

                os.mkdir(fname)
                os.utime(fname, (-1, time.time() - 3601))

                # This will raise an OSError because of file permissions
                image_cache_manager = imagecache.ImageCacheManager()
                image_cache_manager._remove_base_file(fname)

                self.assertTrue(os.path.exists(fname))
                self.assertNotEqual(stream.getvalue().find('Failed to remove'),
                                    -1)

    def test_handle_base_image_unused(self):
        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with self._make_base_file() as fname:
            os.utime(fname, (-1, time.time() - 3601))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files,
                              [fname])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_used(self):
        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with self._make_base_file() as fname:
            os.utime(fname, (-1, time.time() - 3601))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_used_remotely(self):
        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with self._make_base_file() as fname:
            os.utime(fname, (-1, time.time() - 3601))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.used_images = {'123': (0, 1, ['banana-42'])}
            image_cache_manager._handle_base_image(img, None)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_absent(self):
        """Ensure we warn for use of a missing base image."""

        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with self._intercept_log_messages() as stream:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, None)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])
            self.assertNotEqual(stream.getvalue().find('an absent base file'),
                                -1)

    def test_handle_base_image_used_missing(self):
        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with utils.tempdir() as tmpdir:
            fname = os.path.join(tmpdir, 'aaa')

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_checksum_fails(self):
        img = {'container_format': 'ami',
               'id': '123',
               'uuid': '1234-4567-2378'}

        with self._make_base_file() as fname:
            f = open(fname, 'w')
            f.write('banana')
            f.close()

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files,
                              [fname])

    def test_verify_base_images(self):
        self.flags(instances_path='/instance_path')
        self.flags(remove_unused_base_images=True)

        base_file_list = ['00000001',
                          'ephemeral_0_20_None',
                          'e97222e91fc4241f49a7f520d1dcf446751129b3_sm',
                          'e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm',
                          '92cfceb39d57d914ed8b14d0e37643de0797ae56',
                          '17d1b00b81642842e514494a78e804e9a511637c',
                          ('17d1b00b81642842e514494a78e804e9a511637c_'
                           '5368709120'),
                          ('17d1b00b81642842e514494a78e804e9a511637c_'
                           '10737418240'),
                          '00000004']

        def fq_path(path):
            return os.path.join('/instance_path/_base/', path)

        # Fake base directory existance
        orig_exists = os.path.exists

        def exists(path):
            # The python coverage tool got angry with my overly broad mocks
            if not path.startswith('/instance_path'):
                return orig_exists(path)

            if path in ['/instance_path',
                        '/instance_path/_base',
                        '/instance_path/instance-1/disk',
                        '/instance_path/instance-2/disk',
                        '/instance_path/instance-3/disk',
                        ('/instance_path/_base/'
                         '92cfceb39d57d914ed8b14d0e37643de0797ae56.sha1')]:
                return True

            for p in base_file_list:
                if path == fq_path(p):
                    return True
                if path == fq_path(p) + '.sha1':
                    return False

            if path in [('/instance_path/_base/'
                         '92cfceb39d57d914ed8b14d0e37643de0797ae56_sm')]:
                return False

            self.fail('Unexpected path existance check: %s' % path)

        self.stubs.Set(os.path, 'exists', lambda x: exists(x))

        # Fake up some instances in the instances directory
        orig_listdir = os.listdir

        def listdir(path):
            # The python coverage tool got angry with my overly broad mocks
            if not path.startswith('/instance_path'):
                return orig_list(path)

            if path == '/instance_path':
                return ['instance-1', 'instance-2', 'instance-3', '_base']

            if path == '/instance_path/_base':
                return base_file_list

            self.fail('Unexpected directory listed: %s' % path)

        self.stubs.Set(os, 'listdir', lambda x: listdir(x))

        # Fake isfile for these faked images in _base
        orig_isfile = os.path.isfile

        def isfile(path):
            # The python coverage tool got angry with my overly broad mocks
            if not path.startswith('/instance_path'):
                return orig_isfile(path)

            for p in base_file_list:
                if path == fq_path(p):
                    return True

            self.fail('Unexpected isfile call: %s' % path)

        self.stubs.Set(os.path, 'isfile', lambda x: isfile(x))

        # Fake the database call which lists running instances
        self.stubs.Set(db, 'instance_get_all',
                       lambda x: [{'image_ref': 'image-1',
                                   'host': FLAGS.host,
                                   'name': 'instance-1',
                                   'uuid': '123'},
                                  {'image_ref': 'image-2',
                                   'host': FLAGS.host,
                                   'name': 'instance-2',
                                   'uuid': '456'}])

        image_cache_manager = imagecache.ImageCacheManager()

        # Fake the image service call which lists all registered images
        class FakeImageService(object):
            def detail(self, _context):
                return [{'container_format': 'ami', 'id': '42'},
                        {'container_format': 'amk', 'id': '43'}]

        self.stubs.Set(image, 'get_default_image_service',
                       lambda: FakeImageService())

        # Fake the utils call which finds the backing image
        def get_disk_backing_file(path):
            if path in ['/instance_path/instance-1/disk',
                        '/instance_path/instance-2/disk']:
                return fq_path('17d1b00b81642842e514494a78e804e9a511637c_'
                               '5368709120')
            self.fail('Unexpected backing file lookup: %s' % path)

        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: get_disk_backing_file(x))

        # Fake out verifying checksums, as that is tested elsewhere
        self.stubs.Set(image_cache_manager, '_verify_checksum',
                       lambda x, y:
                           y == '92cfceb39d57d914ed8b14d0e37643de0797ae56')

        # Fake getmtime as well
        orig_getmtime = os.path.getmtime

        def getmtime(path):
            if not path.startswith('/instance_path'):
                return orig_getmtime(path)

            return 1000000

        self.stubs.Set(os.path, 'getmtime', lambda x: getmtime(x))

        # Make sure we don't accidentally remove a real file
        orig_remove = os.remove

        def remove(path):
            if not path.startswith('/instance_path'):
                return orig_remove(path)

            # Don't try to remove fake files
            return

        self.stubs.Set(os, 'remove', lambda x: remove(x))

        # And finally we can make the call we're actually testing...
        # The argument here should be a context, but it is mocked out
        image_cache_manager.verify_base_images(None)

        # Verify
        active = [fq_path('17d1b00b81642842e514494a78e804e9a511637c_'
                          '5368709120')]
        self.assertEquals(image_cache_manager.active_base_files, active)

        for rem in [fq_path('e97222e91fc4241f49a7f520d1dcf446751129b3_sm'),
                    fq_path('e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm'),
                    fq_path('92cfceb39d57d914ed8b14d0e37643de0797ae56'),
                    fq_path('17d1b00b81642842e514494a78e804e9a511637c'),
                    fq_path('17d1b00b81642842e514494a78e804e9a511637c_'
                            '10737418240')]:
            self.assertTrue(rem in image_cache_manager.removable_base_files)

    def test_verify_base_images_no_base(self):
        self.flags(instances_path='/tmp/no/such/dir/name/please')
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager.verify_base_images(None)
