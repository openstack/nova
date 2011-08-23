# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import os
import random
import sys
import time
import tempfile
import shutil

# If ../nova/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'nova', '__init__.py')):
    sys.path.insert(0, possible_topdir)

from smoketests import flags
from smoketests import base

FLAGS = flags.FLAGS
flags.DEFINE_string('bundle_kernel', 'random.kernel',
              'Local kernel file to use for bundling tests')
flags.DEFINE_string('bundle_image', 'random.image',
              'Local image file to use for bundling tests')

TEST_PREFIX = 'test%s' % int(random.random() * 1000000)
TEST_BUCKET = '%s_bucket' % TEST_PREFIX
TEST_KEY = '%s_key' % TEST_PREFIX
TEST_GROUP = '%s_group' % TEST_PREFIX


class ImageTests(base.UserSmokeTestCase):
    def test_001_can_bundle_image(self):
        self.data['tempdir'] = tempfile.mkdtemp()
        self.assertTrue(self.bundle_image(FLAGS.bundle_image,
                                          self.data['tempdir']))

    def test_002_can_upload_image(self):
        try:
            self.assertTrue(self.upload_image(TEST_BUCKET,
                                              FLAGS.bundle_image,
                                              self.data['tempdir']))
        finally:
            if os.path.exists(self.data['tempdir']):
                shutil.rmtree(self.data['tempdir'])

    def test_003_can_register_image(self):
        image_id = self.conn.register_image('%s/%s.manifest.xml' %
                                            (TEST_BUCKET, FLAGS.bundle_image))
        self.assert_(image_id is not None)
        self.data['image_id'] = image_id

    def test_004_can_bundle_kernel(self):
        self.assertTrue(self.bundle_image(FLAGS.bundle_kernel, kernel=True))

    def test_005_can_upload_kernel(self):
        self.assertTrue(self.upload_image(TEST_BUCKET, FLAGS.bundle_kernel))

    def test_006_can_register_kernel(self):
        kernel_id = self.conn.register_image('%s/%s.manifest.xml' %
                                            (TEST_BUCKET, FLAGS.bundle_kernel))
        self.assert_(kernel_id is not None)
        self.data['kernel_id'] = kernel_id

    def test_007_images_are_available_within_10_seconds(self):
        for i in xrange(10):
            image = self.conn.get_image(self.data['image_id'])
            if image and image.state == 'available':
                break
            time.sleep(1)
        else:
            self.assert_(False)  # wasn't available within 10 seconds
        self.assert_(image.type == 'machine')

        for i in xrange(10):
            kernel = self.conn.get_image(self.data['kernel_id'])
            if kernel and kernel.state == 'available':
                break
            time.sleep(1)
        else:
            self.assert_(False)    # wasn't available within 10 seconds
        self.assert_(kernel.type == 'kernel')

    def test_008_can_describe_image_attribute(self):
        attrs = self.conn.get_image_attribute(self.data['image_id'],
                                               'launchPermission')
        self.assert_(attrs.name, 'launch_permission')

    def test_009_can_add_image_launch_permission(self):
        image = self.conn.get_image(self.data['image_id'])
        self.assertEqual(image.id, self.data['image_id'])
        self.assertEqual(image.is_public, False)
        self.conn.modify_image_attribute(image_id=self.data['image_id'],
                                         operation='add',
                                         attribute='launchPermission',
                                         groups='all')
        image = self.conn.get_image(self.data['image_id'])
        self.assertEqual(image.id, self.data['image_id'])
        self.assertEqual(image.is_public, True)

    def test_010_can_see_launch_permission(self):
        attrs = self.conn.get_image_attribute(self.data['image_id'],
                                              'launchPermission')
        self.assertEqual(attrs.name, 'launch_permission')
        self.assertEqual(attrs.attrs['groups'][0], 'all')

    def test_011_can_remove_image_launch_permission(self):
        image = self.conn.get_image(self.data['image_id'])
        self.assertEqual(image.id, self.data['image_id'])
        self.assertEqual(image.is_public, True)
        self.conn.modify_image_attribute(image_id=self.data['image_id'],
                                         operation='remove',
                                         attribute='launchPermission',
                                         groups='all')
        image = self.conn.get_image(self.data['image_id'])
        self.assertEqual(image.id, self.data['image_id'])
        self.assertEqual(image.is_public, False)

    def test_012_private_image_shows_in_list(self):
        images = self.conn.get_all_images()
        image_ids = [image.id for image in images]
        self.assertTrue(self.data['image_id'] in image_ids)

    def test_013_user_can_deregister_kernel(self):
        self.assertTrue(self.conn.deregister_image(self.data['kernel_id']))

    def test_014_can_deregister_image(self):
        self.assertTrue(self.conn.deregister_image(self.data['image_id']))

    def test_015_can_delete_bundle(self):
        self.assertTrue(self.delete_bundle_bucket(TEST_BUCKET))


class InstanceTests(base.UserSmokeTestCase):
    def test_001_can_create_keypair(self):
        key = self.create_key_pair(self.conn, TEST_KEY)
        self.assertEqual(key.name, TEST_KEY)

    def test_002_can_create_instance_with_keypair(self):
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              key_name=TEST_KEY,
                                              instance_type='m1.tiny')
        self.assertEqual(len(reservation.instances), 1)
        self.data['instance'] = reservation.instances[0]

    def test_003_instance_runs_within_60_seconds(self):
        instance = self.data['instance']
        # allow 60 seconds to exit pending with IP
        if not self.wait_for_running(self.data['instance']):
            self.fail('instance failed to start')
        self.data['instance'].update()
        ip = self.data['instance'].private_dns_name
        self.failIf(ip == '0.0.0.0')
        if FLAGS.use_ipv6:
            ipv6 = self.data['instance'].dns_name_v6
            self.failIf(ipv6 is None)

    def test_004_can_ping_private_ip(self):
        if not self.wait_for_ping(self.data['instance'].private_dns_name):
            self.fail('could not ping instance')

        if FLAGS.use_ipv6:
            if not self.wait_for_ping(self.data['instance'].dns_name_v6,
                                      "ping6"):
                self.fail('could not ping instance v6')

    def test_005_can_ssh_to_private_ip(self):
        if not self.wait_for_ssh(self.data['instance'].private_dns_name,
                                 TEST_KEY):
            self.fail('could not ssh to instance')

        if FLAGS.use_ipv6:
            if not self.wait_for_ssh(self.data['instance'].dns_name_v6,
                                     TEST_KEY):
                self.fail('could not ssh to instance v6')

    def test_999_tearDown(self):
        self.delete_key_pair(self.conn, TEST_KEY)
        self.conn.terminate_instances([self.data['instance'].id])


class VolumeTests(base.UserSmokeTestCase):
    def setUp(self):
        super(VolumeTests, self).setUp()
        self.device = '/dev/vdb'

    def test_000_setUp(self):
        self.create_key_pair(self.conn, TEST_KEY)
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              instance_type='m1.tiny',
                                              key_name=TEST_KEY)
        self.data['instance'] = reservation.instances[0]
        if not self.wait_for_running(self.data['instance']):
            self.fail('instance failed to start')
        self.data['instance'].update()
        if not self.wait_for_ping(self.data['instance'].private_dns_name):
            self.fail('could not ping instance')
        if not self.wait_for_ssh(self.data['instance'].private_dns_name,
                                 TEST_KEY):
            self.fail('could not ssh to instance')

    def test_001_can_create_volume(self):
        volume = self.conn.create_volume(1, 'nova')
        self.assertEqual(volume.size, 1)
        self.data['volume'] = volume
        # Give network time to find volume.
        time.sleep(5)

    def test_002_can_attach_volume(self):
        volume = self.data['volume']

        for x in xrange(10):
            volume.update()
            if volume.status.startswith('available'):
                break
            time.sleep(1)
        else:
            self.fail('cannot attach volume with state %s' % volume.status)

        # Give volume some time to be ready.
        time.sleep(5)
        volume.attach(self.data['instance'].id, self.device)

        # wait
        for x in xrange(10):
            volume.update()
            if volume.status.startswith('in-use'):
                break
            time.sleep(1)
        else:
            self.fail('volume never got to in use')

        self.assertTrue(volume.status.startswith('in-use'))

        # Give instance time to recognize volume.
        time.sleep(5)

    def test_003_can_mount_volume(self):
        ip = self.data['instance'].private_dns_name
        conn = self.connect_ssh(ip, TEST_KEY)
        # NOTE(vish): this will create an dev for images that don't have
        #             udev rules
        stdin, stdout, stderr = conn.exec_command(
                'grep %s /proc/partitions | '
                '`awk \'{print "mknod /dev/"\\$4" b "\\$1" "\\$2}\'`'
                % self.device.rpartition('/')[2])
        exec_list = []
        exec_list.append('mkdir -p /mnt/vol')
        exec_list.append('/sbin/mke2fs %s' % self.device)
        exec_list.append('mount %s /mnt/vol' % self.device)
        exec_list.append('echo success')
        stdin, stdout, stderr = conn.exec_command(' && '.join(exec_list))
        out = stdout.read()
        conn.close()
        if not out.strip().endswith('success'):
            self.fail('Unable to mount: %s %s' % (out, stderr.read()))

    def test_004_can_write_to_volume(self):
        ip = self.data['instance'].private_dns_name
        conn = self.connect_ssh(ip, TEST_KEY)
        # FIXME(devcamcar): This doesn't fail if the volume hasn't been mounted
        stdin, stdout, stderr = conn.exec_command(
            'echo hello > /mnt/vol/test.txt')
        err = stderr.read()
        conn.close()
        if len(err) > 0:
            self.fail('Unable to write to mount: %s' % (err))

    def test_005_volume_is_correct_size(self):
        ip = self.data['instance'].private_dns_name
        conn = self.connect_ssh(ip, TEST_KEY)
        stdin, stdout, stderr = conn.exec_command(
            "cat /sys/class/block/%s/size" % self.device.rpartition('/')[2])
        out = stdout.read().strip()
        conn.close()
        # NOTE(vish): 1G bytes / 512 bytes per block
        expected_size = 1024 * 1024 * 1024 / 512
        self.assertEquals('%s' % (expected_size,), out,
                          'Volume is not the right size: %s %s. Expected: %s' %
                          (out, stderr.read(), expected_size))

    def test_006_me_can_umount_volume(self):
        ip = self.data['instance'].private_dns_name
        conn = self.connect_ssh(ip, TEST_KEY)
        stdin, stdout, stderr = conn.exec_command('umount /mnt/vol')
        err = stderr.read()
        conn.close()
        if len(err) > 0:
            self.fail('Unable to unmount: %s' % (err))

    def test_007_me_can_detach_volume(self):
        result = self.conn.detach_volume(volume_id=self.data['volume'].id)
        self.assertTrue(result)
        time.sleep(5)

    def test_008_me_can_delete_volume(self):
        result = self.conn.delete_volume(self.data['volume'].id)
        self.assertTrue(result)

    def test_999_tearDown(self):
        self.conn.terminate_instances([self.data['instance'].id])
        self.conn.delete_key_pair(TEST_KEY)
