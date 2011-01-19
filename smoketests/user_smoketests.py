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

import commands
import os
import random
import socket
import sys
import time
import unittest

# If ../nova/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
possible_topdir = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(possible_topdir, 'nova', '__init__.py')):
    sys.path.insert(0, possible_topdir)

from smoketests import flags
from smoketests import base


SUITE_NAMES = '[image, instance, volume]'

FLAGS = flags.FLAGS
flags.DEFINE_string('suite', None, 'Specific test suite to run ' + SUITE_NAMES)
flags.DEFINE_string('bundle_kernel', 'openwrt-x86-vmlinuz',
              'Local kernel file to use for bundling tests')
flags.DEFINE_string('bundle_image', 'openwrt-x86-ext2.image',
              'Local image file to use for bundling tests')

TEST_PREFIX = 'test%s' % int(random.random() * 1000000)
TEST_BUCKET = '%s_bucket' % TEST_PREFIX
TEST_KEY = '%s_key' % TEST_PREFIX
TEST_GROUP = '%s_group' % TEST_PREFIX
TEST_DATA = {}


class UserSmokeTestCase(base.SmokeTestCase):
    def setUp(self):
        global TEST_DATA
        self.conn = self.connection_for_env()
        self.data = TEST_DATA


class ImageTests(UserSmokeTestCase):
    def test_001_can_bundle_image(self):
        self.assertTrue(self.bundle_image(FLAGS.bundle_image))

    def test_002_can_upload_image(self):
        self.assertTrue(self.upload_image(TEST_BUCKET, FLAGS.bundle_image))

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
            print image.state
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

    def test_009_can_modify_image_launch_permission(self):
        self.conn.modify_image_attribute(image_id=self.data['image_id'],
                                         operation='add',
                                         attribute='launchPermission',
                                         groups='all')
        image = self.conn.get_image(self.data['image_id'])
        self.assertEqual(image.id, self.data['image_id'])

    def test_010_can_see_launch_permission(self):
        attrs = self.conn.get_image_attribute(self.data['image_id'],
                                              'launchPermission')
        self.assert_(attrs.name, 'launch_permission')
        self.assert_(attrs.attrs['groups'][0], 'all')

    def test_011_user_can_deregister_kernel(self):
        self.assertTrue(self.conn.deregister_image(self.data['kernel_id']))

    def test_012_can_deregister_image(self):
        self.assertTrue(self.conn.deregister_image(self.data['image_id']))

    def test_013_can_delete_bundle(self):
        self.assertTrue(self.delete_bundle_bucket(TEST_BUCKET))


class InstanceTests(UserSmokeTestCase):
    def test_001_can_create_keypair(self):
        key = self.create_key_pair(self.conn, TEST_KEY)
        self.assertEqual(key.name, TEST_KEY)

    def test_002_can_create_instance_with_keypair(self):
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              key_name=TEST_KEY,
                                              instance_type='m1.tiny')
        self.assertEqual(len(reservation.instances), 1)
        self.data['instance_id'] = reservation.instances[0].id

    def test_003_instance_runs_within_60_seconds(self):
        reservations = self.conn.get_all_instances([self.data['instance_id']])
        instance = reservations[0].instances[0]
        # allow 60 seconds to exit pending with IP
        for x in xrange(60):
            instance.update()
            if instance.state == u'running':
                break
            time.sleep(1)
        else:
            self.fail('instance failed to start')
        ip = reservations[0].instances[0].private_dns_name
        self.failIf(ip == '0.0.0.0')
        self.data['private_ip'] = ip
        if FLAGS.use_ipv6:
            ipv6 = reservations[0].instances[0].dns_name_v6
            self.failIf(ipv6 is None)
            self.data['ip_v6'] = ipv6

    def test_004_can_ping_private_ip(self):
        for x in xrange(120):
            # ping waits for 1 second
            status, output = commands.getstatusoutput(
                'ping -c1 %s' % self.data['private_ip'])
            if status == 0:
                break
        else:
            self.fail('could not ping instance')

        if FLAGS.use_ipv6:
            for x in xrange(120):
            # ping waits for 1 second
                status, output = commands.getstatusoutput(
                    'ping6 -c1 %s' % self.data['ip_v6'])
                if status == 0:
                    break
            else:
                self.fail('could not ping instance')

    def test_005_can_ssh_to_private_ip(self):
        for x in xrange(30):
            try:
                conn = self.connect_ssh(self.data['private_ip'], TEST_KEY)
                conn.close()
            except Exception:
                time.sleep(1)
            else:
                break
        else:
            self.fail('could not ssh to instance')

        if FLAGS.use_ipv6:
            for x in xrange(30):
                try:
                    conn = self.connect_ssh(
                                        self.data['ip_v6'], TEST_KEY)
                    conn.close()
                except Exception:
                    time.sleep(1)
                else:
                    break
            else:
                self.fail('could not ssh to instance v6')

    def test_006_can_allocate_elastic_ip(self):
        result = self.conn.allocate_address()
        self.assertTrue(hasattr(result, 'public_ip'))
        self.data['public_ip'] = result.public_ip

    def test_007_can_associate_ip_with_instance(self):
        result = self.conn.associate_address(self.data['instance_id'],
                                             self.data['public_ip'])
        self.assertTrue(result)

    def test_008_can_ssh_with_public_ip(self):
        for x in xrange(30):
            try:
                conn = self.connect_ssh(self.data['public_ip'], TEST_KEY)
                conn.close()
            except socket.error:
                time.sleep(1)
            else:
                break
        else:
            self.fail('could not ssh to instance')

    def test_009_can_disassociate_ip_from_instance(self):
        result = self.conn.disassociate_address(self.data['public_ip'])
        self.assertTrue(result)

    def test_010_can_deallocate_elastic_ip(self):
        result = self.conn.release_address(self.data['public_ip'])
        self.assertTrue(result)

    def test_999_tearDown(self):
        self.delete_key_pair(self.conn, TEST_KEY)
        if self.data.has_key('instance_id'):
            self.conn.terminate_instances([self.data['instance_id']])


class VolumeTests(UserSmokeTestCase):
    def setUp(self):
        super(VolumeTests, self).setUp()
        self.device = '/dev/vdb'

    def test_000_setUp(self):
        self.create_key_pair(self.conn, TEST_KEY)
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              instance_type='m1.tiny',
                                              key_name=TEST_KEY)
        instance = reservation.instances[0]
        self.data['instance'] = instance
        for x in xrange(120):
            time.sleep(1)
            instance.update()
            #if self.can_ping(instance.private_dns_name):
            if instance.state == u'running':
                break
        else:
            self.fail('unable to start instance')
        time.sleep(10)
        instance.update()

    def test_001_can_create_volume(self):
        volume = self.conn.create_volume(1, 'nova')
        self.assertEqual(volume.size, 1)
        self.data['volume'] = volume
        # Give network time to find volume.
        time.sleep(5)

    def test_002_can_attach_volume(self):
        volume = self.data['volume']

        for x in xrange(30):
            print volume.status
            if volume.status.startswith('available'):
                break
            time.sleep(1)
            volume.update()
        else:
            self.fail('cannot attach volume with state %s' % volume.status)

        volume.attach(self.data['instance'].id, self.device)

        # Volumes seems to report "available" too soon.
        for x in xrange(10):
            if volume.status.startswith('in-use'):
                break
            time.sleep(5)
            volume.update()

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
        commands = []
        commands.append('mkdir -p /mnt/vol')
        commands.append('/sbin/mke2fs %s' % self.device)
        commands.append('mount %s /mnt/vol' % self.device)
        commands.append('echo success')
        stdin, stdout, stderr = conn.exec_command(' && '.join(commands))
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
            "df -h | grep %s | awk {'print $2'}" % self.device)
        out = stdout.read()
        conn.close()
        if not out.strip() == '1007.9M':
            self.fail('Volume is not the right size: %s %s' %
                      (out, stderr.read()))

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


class SecurityGroupTests(UserSmokeTestCase):

    def __public_instance_is_accessible(self):
        id_url = "latest/meta-data/instance-id"
        options = "-s --max-time 1"
        command = "curl %s %s/%s" % (options, self.data['public_ip'], id_url)
        instance_id = commands.getoutput(command).strip()
        if not instance_id:
            return False
        if instance_id != self.data['instance_id']:
            raise Exception("Wrong instance id")
        return True

    def test_001_can_create_security_group(self):
        self.conn.create_security_group(TEST_GROUP, description='test')

        groups = self.conn.get_all_security_groups()
        self.assertTrue(TEST_GROUP in [group.name for group in groups])

    def test_002_can_launch_instance_in_security_group(self):
        self.create_key_pair(self.conn, TEST_KEY)
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              key_name=TEST_KEY,
                                              security_groups=[TEST_GROUP],
                                              instance_type='m1.tiny')

        self.data['instance_id'] = reservation.instances[0].id

    def test_003_can_authorize_security_group_ingress(self):
        self.assertTrue(self.conn.authorize_security_group(TEST_GROUP,
                                                           ip_protocol='tcp',
                                                           from_port=80,
                                                           to_port=80))

    def test_004_can_access_instance_over_public_ip(self):
        result = self.conn.allocate_address()
        self.assertTrue(hasattr(result, 'public_ip'))
        self.data['public_ip'] = result.public_ip

        result = self.conn.associate_address(self.data['instance_id'],
                                             self.data['public_ip'])
        start_time = time.time()
        while not self.__public_instance_is_accessible():
            # 1 minute to launch
            if time.time() - start_time > 60:
                raise Exception("Timeout")
            time.sleep(1)

    def test_005_can_revoke_security_group_ingress(self):
        self.assertTrue(self.conn.revoke_security_group(TEST_GROUP,
                                                        ip_protocol='tcp',
                                                        from_port=80,
                                                        to_port=80))
        start_time = time.time()
        while self.__public_instance_is_accessible():
            # 1 minute to teardown
            if time.time() - start_time > 60:
                raise Exception("Timeout")
            time.sleep(1)

    def test_999_tearDown(self):
        self.conn.delete_key_pair(TEST_KEY)
        self.conn.delete_security_group(TEST_GROUP)
        groups = self.conn.get_all_security_groups()
        self.assertFalse(TEST_GROUP in [group.name for group in groups])
        self.conn.terminate_instances([self.data['instance_id']])
        self.assertTrue(self.conn.release_address(self.data['public_ip']))


if __name__ == "__main__":
    suites = {'image': unittest.makeSuite(ImageTests),
              'instance': unittest.makeSuite(InstanceTests),
              'security_group': unittest.makeSuite(SecurityGroupTests),
              'volume': unittest.makeSuite(VolumeTests)
              }
    sys.exit(base.run_tests(suites))
