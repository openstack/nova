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
import sys
import time

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

TEST_PREFIX = 'test%s' % int(random.random() * 1000000)
TEST_BUCKET = '%s_bucket' % TEST_PREFIX
TEST_KEY = '%s_key' % TEST_PREFIX
TEST_GROUP = '%s_group' % TEST_PREFIX


class AddressTests(base.UserSmokeTestCase):
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

    def test_001_can_allocate_floating_ip(self):
        result = self.conn.allocate_address()
        self.assertTrue(hasattr(result, 'public_ip'))
        self.data['public_ip'] = result.public_ip

    def test_002_can_associate_ip_with_instance(self):
        result = self.conn.associate_address(self.data['instance'].id,
                                             self.data['public_ip'])
        self.assertTrue(result)

    def test_003_can_ssh_with_public_ip(self):
        ssh_authorized = False
        groups = self.conn.get_all_security_groups(['default'])
        for rule in groups[0].rules:
            if (rule.ip_protocol == 'tcp' and
                int(rule.from_port) <= 22 and
                int(rule.to_port) >= 22):
                ssh_authorized = True
                break
        if not ssh_authorized:
            self.conn.authorize_security_group('default',
                                               ip_protocol='tcp',
                                               from_port=22,
                                               to_port=22)
        try:
            if not self.wait_for_ssh(self.data['public_ip'], TEST_KEY):
                self.fail('could not ssh to public ip')
        finally:
            if not ssh_authorized:
                self.conn.revoke_security_group('default',
                                                ip_protocol='tcp',
                                                from_port=22,
                                                to_port=22)

    def test_004_can_disassociate_ip_from_instance(self):
        result = self.conn.disassociate_address(self.data['public_ip'])
        self.assertTrue(result)

    def test_005_can_deallocate_floating_ip(self):
        result = self.conn.release_address(self.data['public_ip'])
        self.assertTrue(result)

    def test_999_tearDown(self):
        self.delete_key_pair(self.conn, TEST_KEY)
        self.conn.terminate_instances([self.data['instance'].id])


class SecurityGroupTests(base.UserSmokeTestCase):

    def __get_metadata_item(self, category):
        id_url = "latest/meta-data/%s" % category
        options = "-f -s --max-time 1"
        command = "curl %s %s/%s" % (options, self.data['public_ip'], id_url)
        status, output = commands.getstatusoutput(command)
        value = output.strip()
        if status > 0:
            return False
        return value

    def __public_instance_is_accessible(self):
        instance_id = self.__get_metadata_item('instance-id')
        if not instance_id:
            return False
        if instance_id != self.data['instance'].id:
            raise Exception("Wrong instance id. Expected: %s, Got: %s" %
                               (self.data['instance'].id, instance_id))
        return True

    def test_001_can_create_security_group(self):
        self.conn.create_security_group(TEST_GROUP, description='test')

        groups = self.conn.get_all_security_groups()
        self.assertTrue(TEST_GROUP in [group.name for group in groups])

    def test_002_can_launch_instance_in_security_group(self):
        with open("proxy.sh") as f:
            user_data = f.read()
        self.create_key_pair(self.conn, TEST_KEY)
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              key_name=TEST_KEY,
                                              security_groups=[TEST_GROUP],
                                              user_data=user_data,
                                              instance_type='m1.tiny')

        self.data['instance'] = reservation.instances[0]
        if not self.wait_for_running(self.data['instance']):
            self.fail('instance failed to start')
        self.data['instance'].update()

    def test_003_can_authorize_security_group_ingress(self):
        self.assertTrue(self.conn.authorize_security_group(TEST_GROUP,
                                                           ip_protocol='tcp',
                                                           from_port=80,
                                                           to_port=80))

    def test_004_can_access_metadata_over_public_ip(self):
        result = self.conn.allocate_address()
        self.assertTrue(hasattr(result, 'public_ip'))
        self.data['public_ip'] = result.public_ip

        result = self.conn.associate_address(self.data['instance'].id,
                                             self.data['public_ip'])
        start_time = time.time()
        try:
            while not self.__public_instance_is_accessible():
                # 1 minute to launch
                if time.time() - start_time > 60:
                    raise Exception("Timeout")
                time.sleep(1)
        finally:
            result = self.conn.disassociate_address(self.data['public_ip'])

    def test_005_validate_metadata(self):

        instance = self.data['instance']
        self.assertTrue(instance.instance_type,
                            self.__get_metadata_item("instance-type"))
        #FIXME(dprince): validate more metadata here

    def test_006_can_revoke_security_group_ingress(self):
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
        self.conn.terminate_instances([self.data['instance'].id])
        self.assertTrue(self.conn.release_address(self.data['public_ip']))
