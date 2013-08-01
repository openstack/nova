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
import json
import os
import time

from oslo.config import cfg

from nova.compute import vm_states
from nova import conductor
from nova import db
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova import test
from nova import utils
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import utils as virtutils

CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('host', 'nova.netconf')


@contextlib.contextmanager
def intercept_log_messages():
    try:
        mylog = logging.getLogger('nova')
        stream = cStringIO.StringIO()
        handler = logging.logging.StreamHandler(stream)
        handler.setFormatter(logging.ContextFormatter())
        mylog.logger.addHandler(handler)
        yield stream
    finally:
        mylog.logger.removeHandler(handler)


class ImageCacheManagerTestCase(test.TestCase):

    def setUp(self):
        super(ImageCacheManagerTestCase, self).setUp()
        self.stock_instance_names = set(['instance-00000001',
                                         'instance-00000002',
                                         'instance-00000003',
                                         'banana-42-hamster'])

    def test_read_stored_checksum_missing(self):
        self.stubs.Set(os.path, 'exists', lambda x: False)
        csum = imagecache.read_stored_checksum('/tmp/foo', timestamped=False)
        self.assertEquals(csum, None)

    def test_read_stored_checksum(self):
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))

            csum_input = '{"sha1": "fdghkfhkgjjksfdgjksjkghsdf"}\n'
            fname = os.path.join(tmpdir, 'aaa')
            info_fname = imagecache.get_info_filename(fname)
            f = open(info_fname, 'w')
            f.write(csum_input)
            f.close()

            csum_output = imagecache.read_stored_checksum(fname,
                                                          timestamped=False)
            self.assertEquals(csum_input.rstrip(),
                              '{"sha1": "%s"}' % csum_output)

    def test_read_stored_checksum_legacy_essex(self):
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))

            fname = os.path.join(tmpdir, 'aaa')
            old_fname = fname + '.sha1'
            f = open(old_fname, 'w')
            f.write('fdghkfhkgjjksfdgjksjkghsdf')
            f.close()

            csum_output = imagecache.read_stored_checksum(fname,
                                                          timestamped=False)
            self.assertEquals(csum_output, 'fdghkfhkgjjksfdgjksjkghsdf')
            self.assertFalse(os.path.exists(old_fname))
            info_fname = imagecache.get_info_filename(fname)
            self.assertTrue(os.path.exists(info_fname))

    def test_list_base_images(self):
        listing = ['00000001',
                   'ephemeral_0_20_None',
                   '17d1b00b81642842e514494a78e804e9a511637c_5368709120.info',
                    '00000004']
        images = ['e97222e91fc4241f49a7f520d1dcf446751129b3_sm',
                  'e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm',
                  'e97222e91fc4241f49a7f520d1dcf446751129b3',
                  '17d1b00b81642842e514494a78e804e9a511637c',
                  '17d1b00b81642842e514494a78e804e9a511637c_5368709120',
                  '17d1b00b81642842e514494a78e804e9a511637c_10737418240']
        listing.extend(images)

        self.stubs.Set(os, 'listdir', lambda x: listing)
        self.stubs.Set(os.path, 'isfile', lambda x: True)

        base_dir = '/var/lib/nova/instances/_base'
        self.flags(instances_path='/var/lib/nova/instances')

        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_base_images(base_dir)

        sanitized = []
        for ent in image_cache_manager.unexplained_images:
            sanitized.append(ent.replace(base_dir + '/', ''))

        sanitized = sanitized.sort()
        images = images.sort()
        self.assertEquals(sanitized, images)

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
        all_instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': '123',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'host': CONF.host,
                          'name': 'inst-2',
                          'uuid': '456',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'kernel_id': '21',
                          'ramdisk_id': '22',
                          'host': 'remotehost',
                          'name': 'inst-3',
                          'uuid': '789',
                          'vm_state': '',
                          'task_state': ''}]

        image_cache_manager = imagecache.ImageCacheManager()

        # The argument here should be a context, but it's mocked out
        image_cache_manager._list_running_instances(None, all_instances)

        self.assertEqual(len(image_cache_manager.used_images), 4)
        self.assertTrue(image_cache_manager.used_images['1'] ==
                        (1, 0, ['inst-1']))
        self.assertTrue(image_cache_manager.used_images['2'] ==
                        (1, 1, ['inst-2', 'inst-3']))
        self.assertTrue(image_cache_manager.used_images['21'] ==
                        (0, 1, ['inst-3']))
        self.assertTrue(image_cache_manager.used_images['22'] ==
                        (0, 1, ['inst-3']))

        self.assertTrue('inst-1' in image_cache_manager.instance_names)
        self.assertTrue('123' in image_cache_manager.instance_names)

        self.assertEqual(len(image_cache_manager.image_popularity), 4)
        self.assertEqual(image_cache_manager.image_popularity['1'], 1)
        self.assertEqual(image_cache_manager.image_popularity['2'], 2)
        self.assertEqual(image_cache_manager.image_popularity['21'], 1)
        self.assertEqual(image_cache_manager.image_popularity['22'], 1)

    def test_list_resizing_instances(self):
        all_instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': '123',
                          'vm_state': vm_states.RESIZED,
                          'task_state': None}]

        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager._list_running_instances(None, all_instances)

        self.assertEqual(len(image_cache_manager.used_images), 1)
        self.assertTrue(image_cache_manager.used_images['1'] ==
                        (1, 0, ['inst-1']))
        self.assertTrue(image_cache_manager.instance_names ==
                        set(['inst-1', '123', 'inst-1_resize', '123_resize']))

        self.assertEqual(len(image_cache_manager.image_popularity), 1)
        self.assertEqual(image_cache_manager.image_popularity['1'], 1)

    def test_list_backing_images_small(self):
        self.stubs.Set(os, 'listdir',
                       lambda x: ['_base', 'instance-00000001',
                                  'instance-00000002', 'instance-00000003'])
        self.stubs.Set(os.path, 'exists',
                       lambda x: x.find('instance-') != -1)
        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: 'e97222e91fc4241f49a7f520d1dcf446751129b3_sm')

        found = os.path.join(CONF.instances_path, CONF.base_dir_name,
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

        found = os.path.join(CONF.instances_path, CONF.base_dir_name,
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

        found = os.path.join(CONF.instances_path, CONF.base_dir_name,
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
        self.assertTrue(res == [(base_file1, False, False),
                                (base_file2, True, False),
                                (base_file3, False, True)])

    @contextlib.contextmanager
    def _make_base_file(self, checksum=True):
        """Make a base file for testing."""

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))
            fname = os.path.join(tmpdir, 'aaa')

            base_file = open(fname, 'w')
            base_file.write('data')
            base_file.close()
            base_file = open(fname, 'r')

            if checksum:
                imagecache.write_stored_checksum(fname)

            base_file.close()
            yield fname

    def test_remove_base_file(self):
        with self._make_base_file() as fname:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager._remove_base_file(fname)
            info_fname = imagecache.get_info_filename(fname)

            # Files are initially too new to delete
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists(info_fname))

            # Old files get cleaned up though
            os.utime(fname, (-1, time.time() - 3601))
            image_cache_manager._remove_base_file(fname)

            self.assertFalse(os.path.exists(fname))
            self.assertFalse(os.path.exists(info_fname))

    def test_remove_base_file_original(self):
        with self._make_base_file() as fname:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.originals = [fname]
            image_cache_manager._remove_base_file(fname)
            info_fname = imagecache.get_info_filename(fname)

            # Files are initially too new to delete
            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists(info_fname))

            # This file should stay longer than a resized image
            os.utime(fname, (-1, time.time() - 3601))
            image_cache_manager._remove_base_file(fname)

            self.assertTrue(os.path.exists(fname))
            self.assertTrue(os.path.exists(info_fname))

            # Originals don't stay forever though
            os.utime(fname, (-1, time.time() - 3600 * 25))
            image_cache_manager._remove_base_file(fname)

            self.assertFalse(os.path.exists(fname))
            self.assertFalse(os.path.exists(info_fname))

    def test_remove_base_file_dne(self):
        # This test is solely to execute the "does not exist" code path. We
        # don't expect the method being tested to do anything in this case.
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))

            fname = os.path.join(tmpdir, 'aaa')
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager._remove_base_file(fname)

    def test_remove_base_file_oserror(self):
        with intercept_log_messages() as stream:
            with utils.tempdir() as tmpdir:
                self.flags(instances_path=tmpdir)
                self.flags(image_info_filename_pattern=('$instances_path/'
                                                        '%(image)s.info'))

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
        img = '123'

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
        self.stubs.Set(virtutils, 'chown', lambda x, y: None)
        img = '123'

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
        self.stubs.Set(virtutils, 'chown', lambda x, y: None)
        img = '123'

        with self._make_base_file() as fname:
            os.utime(fname, (-1, time.time() - 3601))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (0, 1, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_absent(self):
        img = '123'

        with intercept_log_messages() as stream:
            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, None)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])
            self.assertNotEqual(stream.getvalue().find('an absent base file'),
                                -1)

    def test_handle_base_image_used_missing(self):
        img = '123'

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))

            fname = os.path.join(tmpdir, 'aaa')

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files, [])

    def test_handle_base_image_checksum_fails(self):
        self.flags(checksum_base_images=True)
        self.stubs.Set(virtutils, 'chown', lambda x, y: None)

        img = '123'

        with self._make_base_file() as fname:
            with open(fname, 'w') as f:
                f.write('banana')

            d = {'sha1': '21323454'}
            with open('%s.info' % fname, 'w') as f:
                f.write(json.dumps(d))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.unexplained_images = [fname]
            image_cache_manager.used_images = {'123': (1, 0, ['banana-42'])}
            image_cache_manager._handle_base_image(img, fname)

            self.assertEquals(image_cache_manager.unexplained_images, [])
            self.assertEquals(image_cache_manager.removable_base_files, [])
            self.assertEquals(image_cache_manager.corrupt_base_files,
                              [fname])

    def test_verify_base_images(self):
        hashed_1 = '356a192b7913b04c54574d18c28d46e6395428ab'
        hashed_21 = '472b07b9fcf2c2451e8781e944bf5f77cd8457c8'
        hashed_22 = '12c6fc06c99a462375eeb3f43dfd832b08ca9e17'
        hashed_42 = '92cfceb39d57d914ed8b14d0e37643de0797ae56'

        self.flags(instances_path='/instance_path')
        self.flags(base_dir_name='_base')
        self.flags(remove_unused_base_images=True)

        base_file_list = ['00000001',
                          'ephemeral_0_20_None',
                          'e97222e91fc4241f49a7f520d1dcf446751129b3_sm',
                          'e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm',
                          hashed_42,
                          hashed_1,
                          hashed_21,
                          hashed_22,
                          '%s_5368709120' % hashed_1,
                          '%s_10737418240' % hashed_1,
                          '00000004']

        def fq_path(path):
            return os.path.join('/instance_path/_base/', path)

        # Fake base directory existence
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
                        '/instance_path/_base/%s.info' % hashed_42]:
                return True

            for p in base_file_list:
                if path == fq_path(p):
                    return True
                if path == fq_path(p) + '.info':
                    return False

            if path in ['/instance_path/_base/%s_sm' % i for i in [hashed_1,
                                                                   hashed_21,
                                                                   hashed_22,
                                                                   hashed_42]]:
                return False

            self.fail('Unexpected path existence check: %s' % path)

        self.stubs.Set(os.path, 'exists', lambda x: exists(x))

        self.stubs.Set(virtutils, 'chown', lambda x, y: None)

        # We need to stub utime as well
        orig_utime = os.utime
        self.stubs.Set(os, 'utime', lambda x, y: None)

        # Fake up some instances in the instances directory
        orig_listdir = os.listdir

        def listdir(path):
            # The python coverage tool got angry with my overly broad mocks
            if not path.startswith('/instance_path'):
                return orig_listdir(path)

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
        all_instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'instance-1',
                          'uuid': '123',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '1',
                          'kernel_id': '21',
                          'ramdisk_id': '22',
                          'host': CONF.host,
                          'name': 'instance-2',
                          'uuid': '456',
                          'vm_state': '',
                          'task_state': ''}]

        image_cache_manager = imagecache.ImageCacheManager()

        # Fake the utils call which finds the backing image
        def get_disk_backing_file(path):
            if path in ['/instance_path/instance-1/disk',
                        '/instance_path/instance-2/disk']:
                return fq_path('%s_5368709120' % hashed_1)
            self.fail('Unexpected backing file lookup: %s' % path)

        self.stubs.Set(virtutils, 'get_disk_backing_file',
                       lambda x: get_disk_backing_file(x))

        # Fake out verifying checksums, as that is tested elsewhere
        self.stubs.Set(image_cache_manager, '_verify_checksum',
                       lambda x, y: y == hashed_42)

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
        image_cache_manager.verify_base_images(None, all_instances)

        # Verify
        active = [fq_path(hashed_1), fq_path('%s_5368709120' % hashed_1),
                  fq_path(hashed_21), fq_path(hashed_22)]
        self.assertEquals(image_cache_manager.active_base_files, active)

        for rem in [fq_path('e97222e91fc4241f49a7f520d1dcf446751129b3_sm'),
                    fq_path('e09c675c2d1cfac32dae3c2d83689c8c94bc693b_sm'),
                    fq_path(hashed_42),
                    fq_path('%s_10737418240' % hashed_1)]:
            self.assertTrue(rem in image_cache_manager.removable_base_files)

        # Ensure there are no "corrupt" images as well
        self.assertTrue(len(image_cache_manager.corrupt_base_files), 0)

    def test_verify_base_images_no_base(self):
        self.flags(instances_path='/tmp/no/such/dir/name/please')
        image_cache_manager = imagecache.ImageCacheManager()
        image_cache_manager.verify_base_images(None, [])

    def test_is_valid_info_file(self):
        hashed = 'e97222e91fc4241f49a7f520d1dcf446751129b3'

        self.flags(instances_path='/tmp/no/such/dir/name/please')
        self.flags(image_info_filename_pattern=('$instances_path/_base/'
                                                '%(image)s.info'))
        base_filename = os.path.join(CONF.instances_path, '_base', hashed)

        is_valid_info_file = imagecache.is_valid_info_file
        self.assertFalse(is_valid_info_file('banana'))
        self.assertFalse(is_valid_info_file(
                os.path.join(CONF.instances_path, '_base', '00000001')))
        self.assertFalse(is_valid_info_file(base_filename))
        self.assertFalse(is_valid_info_file(base_filename + '.sha1'))
        self.assertTrue(is_valid_info_file(base_filename + '.info'))

    def test_configured_checksum_path(self):
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))
            self.flags(remove_unused_base_images=True)

            # Ensure there is a base directory
            os.mkdir(os.path.join(tmpdir, '_base'))

            # Fake the database call which lists running instances
            all_instances = [{'image_ref': '1',
                              'host': CONF.host,
                              'name': 'instance-1',
                              'uuid': '123',
                              'vm_state': '',
                              'task_state': ''},
                             {'image_ref': '1',
                              'host': CONF.host,
                              'name': 'instance-2',
                              'uuid': '456',
                              'vm_state': '',
                              'task_state': ''}]

            def touch(filename):
                f = open(filename, 'w')
                f.write('Touched')
                f.close()

            old = time.time() - (25 * 3600)
            hashed = 'e97222e91fc4241f49a7f520d1dcf446751129b3'
            base_filename = os.path.join(tmpdir, hashed)
            touch(base_filename)
            touch(base_filename + '.info')
            os.utime(base_filename + '.info', (old, old))
            touch(base_filename + '.info')
            os.utime(base_filename + '.info', (old, old))

            image_cache_manager = imagecache.ImageCacheManager()
            image_cache_manager.verify_base_images(None, all_instances)

            self.assertTrue(os.path.exists(base_filename))
            self.assertTrue(os.path.exists(base_filename + '.info'))

    def test_compute_manager(self):
        was = {'called': False}

        def fake_get_all_by_filters(context, *args, **kwargs):
            was['called'] = True
            return [{'image_ref': '1',
                     'host': CONF.host,
                     'name': 'instance-1',
                     'uuid': '123',
                     'vm_state': '',
                     'task_state': ''},
                    {'image_ref': '1',
                     'host': CONF.host,
                     'name': 'instance-2',
                     'uuid': '456',
                     'vm_state': '',
                     'task_state': ''}]

        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)

            self.stubs.Set(db, 'instance_get_all_by_filters',
                           fake_get_all_by_filters)
            compute = importutils.import_object(CONF.compute_manager)
            self.flags(use_local=True, group='conductor')
            compute.conductor_api = conductor.API()
            compute._run_image_cache_manager_pass(None)
            self.assertTrue(was['called'])


class VerifyChecksumTestCase(test.TestCase):

    def setUp(self):
        super(VerifyChecksumTestCase, self).setUp()
        self.img = {'container_format': 'ami', 'id': '42'}
        self.flags(checksum_base_images=True)

    def _make_checksum(self, tmpdir):
        testdata = ('OpenStack Software delivers a massively scalable cloud '
                    'operating system.')

        fname = os.path.join(tmpdir, 'aaa')
        info_fname = imagecache.get_info_filename(fname)

        with open(fname, 'w') as f:
            f.write(testdata)

        return fname, info_fname, testdata

    def _write_file(self, info_fname, info_attr, testdata):
        f = open(info_fname, 'w')
        if info_attr == "csum valid":
            csum = hashlib.sha1()
            csum.update(testdata)
            f.write('{"sha1": "%s"}\n' % csum.hexdigest())
        elif info_attr == "csum invalid, not json":
            f.write('banana')
        else:
            f.write('{"sha1": "banana"}')
        f.close()

    def _check_body(self, tmpdir, info_attr):
        self.flags(instances_path=tmpdir)
        self.flags(image_info_filename_pattern=('$instances_path/'
                                                '%(image)s.info'))
        fname, info_fname, testdata = self._make_checksum(tmpdir)
        self._write_file(info_fname, info_attr, testdata)
        image_cache_manager = imagecache.ImageCacheManager()
        return image_cache_manager, fname

    def test_verify_checksum(self):
        with utils.tempdir() as tmpdir:
            image_cache_manager, fname = self._check_body(tmpdir, "csum valid")
            res = image_cache_manager._verify_checksum(self.img, fname)
            self.assertTrue(res)

    def test_verify_checksum_disabled(self):
        self.flags(checksum_base_images=False)
        with utils.tempdir() as tmpdir:
            image_cache_manager, fname = self._check_body(tmpdir, "csum valid")
            res = image_cache_manager._verify_checksum(self.img, fname)
            self.assertTrue(res is None)

    def test_verify_checksum_invalid_json(self):
        with intercept_log_messages() as stream:
            with utils.tempdir() as tmpdir:
                image_cache_manager, fname = (
                    self._check_body(tmpdir, "csum invalid, not json"))
                res = image_cache_manager._verify_checksum(
                    self.img, fname, create_if_missing=False)
                self.assertFalse(res)
                log = stream.getvalue()

                # NOTE(mikal): this is a skip not a fail because the file is
                # present, but is not in valid json format and therefore is
                # skipped.
                self.assertNotEqual(log.find('image verification skipped'), -1)

    def test_verify_checksum_invalid_repaired(self):
        with utils.tempdir() as tmpdir:
            image_cache_manager, fname = (
                self._check_body(tmpdir, "csum invalid, not json"))
            res = image_cache_manager._verify_checksum(
                self.img, fname, create_if_missing=True)
            self.assertTrue(res is None)

    def test_verify_checksum_invalid(self):
        with intercept_log_messages() as stream:
            with utils.tempdir() as tmpdir:
                image_cache_manager, fname = (
                    self._check_body(tmpdir, "csum invalid, valid json"))
                res = image_cache_manager._verify_checksum(self.img, fname)
                self.assertFalse(res)
                log = stream.getvalue()
                self.assertNotEqual(log.find('image verification failed'), -1)

    def test_verify_checksum_file_missing(self):
        with utils.tempdir() as tmpdir:
            self.flags(instances_path=tmpdir)
            self.flags(image_info_filename_pattern=('$instances_path/'
                                                    '%(image)s.info'))
            fname, info_fname, testdata = self._make_checksum(tmpdir)

            image_cache_manager = imagecache.ImageCacheManager()
            res = image_cache_manager._verify_checksum('aaa', fname)
            self.assertEquals(res, None)

            # Checksum requests for a file with no checksum now have the
            # side effect of creating the checksum
            self.assertTrue(os.path.exists(info_fname))
