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

#Note that this test should run from
#public network (outside of private network segments)
#Please set EC2_URL correctly
#You should use admin account in this test

FLAGS = flags.FLAGS

TEST_PREFIX = 'test%s' % int(random.random() * 1000000)
TEST_BUCKET = '%s_bucket' % TEST_PREFIX
TEST_KEY = '%s_key' % TEST_PREFIX
TEST_KEY2 = '%s_key2' % TEST_PREFIX
TEST_DATA = {}


class InstanceTestsFromPublic(base.UserSmokeTestCase):
    def test_001_can_create_keypair(self):
        key = self.create_key_pair(self.conn, TEST_KEY)
        self.assertEqual(key.name, TEST_KEY)

    def test_002_security_group(self):
        security_group_name = "".join(random.choice("sdiuisudfsdcnpaqwertasd")
                                      for x in range(random.randint(4, 8)))
        group = self.conn.create_security_group(security_group_name,
                                               'test group')
        group.connection = self.conn
        group.authorize('tcp', 22, 22, '0.0.0.0/0')
        if FLAGS.use_ipv6:
            group.authorize('tcp', 22, 22, '::/0')

        reservation = self.conn.run_instances(FLAGS.test_image,
                                        key_name=TEST_KEY,
                                        security_groups=[security_group_name],
                                        instance_type='m1.tiny')
        self.data['security_group_name'] = security_group_name
        self.data['group'] = group
        self.data['instance_id'] = reservation.instances[0].id

    def test_003_instance_with_group_runs_within_60_seconds(self):
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

    def test_004_can_ssh_to_ipv6(self):
        if FLAGS.use_ipv6:
            for x in xrange(20):
                try:
                    conn = self.connect_ssh(
                                        self.data['ip_v6'], TEST_KEY)
                    conn.close()
                except Exception as ex:
                    print ex
                    time.sleep(1)
                else:
                    break
            else:
                self.fail('could not ssh to instance')

    def test_012_can_create_instance_with_keypair(self):
        if 'instance_id' in self.data:
            self.conn.terminate_instances([self.data['instance_id']])
        reservation = self.conn.run_instances(FLAGS.test_image,
                                              key_name=TEST_KEY,
                                              instance_type='m1.tiny')
        self.assertEqual(len(reservation.instances), 1)
        self.data['instance_id'] = reservation.instances[0].id

    def test_013_instance_runs_within_60_seconds(self):
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

    def test_014_can_not_ping_private_ip(self):
        for x in xrange(4):
            # ping waits for 1 second
            status, output = commands.getstatusoutput(
                'ping -c1 %s' % self.data['private_ip'])
            if status == 0:
                self.fail('can ping private ip from public network')
            if FLAGS.use_ipv6:
                status, output = commands.getstatusoutput(
                    'ping6 -c1 %s' % self.data['ip_v6'])
                if status == 0:
                    self.fail('can ping ipv6 from public network')
        else:
            pass

    def test_015_can_not_ssh_to_private_ip(self):
        for x in xrange(1):
            try:
                conn = self.connect_ssh(self.data['private_ip'], TEST_KEY)
                conn.close()
            except Exception:
                time.sleep(1)
            else:
                self.fail('can ssh for ipv4 address from public network')

        if FLAGS.use_ipv6:
            for x in xrange(1):
                try:
                    conn = self.connect_ssh(
                                        self.data['ip_v6'], TEST_KEY)
                    conn.close()
                except Exception:
                    time.sleep(1)
                else:
                    self.fail('can ssh for ipv6 address from public network')

    def test_999_tearDown(self):
        self.delete_key_pair(self.conn, TEST_KEY)
        security_group_name = self.data['security_group_name']
        group = self.data['group']
        if group:
            group.revoke('tcp', 22, 22, '0.0.0.0/0')
            if FLAGS.use_ipv6:
                group.revoke('tcp', 22, 22, '::/0')
        self.conn.delete_security_group(security_group_name)
        if 'instance_id' in self.data:
            self.conn.terminate_instances([self.data['instance_id']])
