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

from datetime import datetime, timedelta
import logging
import time

from nova import flags
from nova import test
from nova import utils
from nova.compute import model


FLAGS = flags.FLAGS


class ModelTestCase(test.TrialTestCase):
    def setUp(self):
        super(ModelTestCase, self).setUp()
        self.flags(connection_type='fake',
                   fake_storage=True)

    def tearDown(self):
        model.Instance('i-test').destroy()
        model.Host('testhost').destroy()
        model.Daemon('testhost', 'nova-testdaemon').destroy()

    def create_instance(self):
        inst = model.Instance('i-test')
        inst['reservation_id'] = 'r-test'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        inst['private_dns_name'] = '10.0.0.1'
        inst.save()
        return inst

    def create_host(self):
        host = model.Host('testhost')
        host.save()
        return host

    def create_daemon(self):
        daemon = model.Daemon('testhost', 'nova-testdaemon')
        daemon.save()
        return daemon

    def create_session_token(self):
        session_token = model.SessionToken('tk12341234')
        session_token['user'] = 'testuser'
        session_token.save()
        return session_token

    def test_create_instance(self):
        """store with create_instace, then test that a load finds it"""
        instance = self.create_instance()
        old = model.Instance(instance.identifier)
        self.assertFalse(old.is_new_record())

    def test_delete_instance(self):
        """create, then destroy, then make sure loads a new record"""
        instance = self.create_instance()
        instance.destroy()
        newinst = model.Instance('i-test')
        self.assertTrue(newinst.is_new_record())

    def test_instance_added_to_set(self):
        """create, then check that it is listed in global set"""
        instance = self.create_instance()
        found = False
        for x in model.InstanceDirectory().all:
            if x.identifier == 'i-test':
                found = True
        self.assert_(found)

    def test_instance_associates_project(self):
        """create, then check that it is listed for the project"""
        instance = self.create_instance()
        found = False
        for x in model.InstanceDirectory().by_project(instance.project):
            if x.identifier == 'i-test':
                found = True
        self.assert_(found)

    def test_instance_associates_ip(self):
        """create, then check that it is listed for the ip"""
        instance = self.create_instance()
        found = False
        x = model.InstanceDirectory().by_ip(instance['private_dns_name'])
        self.assertEqual(x.identifier, 'i-test')

    def test_instance_associates_node(self):
        """create, then check that it is listed for the node_name"""
        instance = self.create_instance()
        found = False
        for x in model.InstanceDirectory().by_node(FLAGS.node_name):
            if x.identifier == 'i-test':
                found = True
        self.assertFalse(found)
        instance['node_name'] = 'test_node'
        instance.save()
        for x in model.InstanceDirectory().by_node('test_node'):
            if x.identifier == 'i-test':
                found = True
        self.assert_(found)


    def test_host_class_finds_hosts(self):
        host = self.create_host()
        self.assertEqual('testhost', model.Host.lookup('testhost').identifier)

    def test_host_class_doesnt_find_missing_hosts(self):
        rv = model.Host.lookup('woahnelly')
        self.assertEqual(None, rv)

    def test_create_host(self):
        """store with create_host, then test that a load finds it"""
        host = self.create_host()
        old = model.Host(host.identifier)
        self.assertFalse(old.is_new_record())

    def test_delete_host(self):
        """create, then destroy, then make sure loads a new record"""
        instance = self.create_host()
        instance.destroy()
        newinst = model.Host('testhost')
        self.assertTrue(newinst.is_new_record())

    def test_host_added_to_set(self):
        """create, then check that it is included in list"""
        instance = self.create_host()
        found = False
        for x in model.Host.all():
            if x.identifier == 'testhost':
                found = True
        self.assert_(found)

    def test_create_daemon_two_args(self):
        """create a daemon with two arguments"""
        d = self.create_daemon()
        d = model.Daemon('testhost', 'nova-testdaemon')
        self.assertFalse(d.is_new_record())

    def test_create_daemon_single_arg(self):
        """Create a daemon using the combined host:bin format"""
        d = model.Daemon("testhost:nova-testdaemon")
        d.save()
        d = model.Daemon('testhost:nova-testdaemon')
        self.assertFalse(d.is_new_record())

    def test_equality_of_daemon_single_and_double_args(self):
        """Create a daemon using the combined host:bin arg, find with 2"""
        d = model.Daemon("testhost:nova-testdaemon")
        d.save()
        d = model.Daemon('testhost', 'nova-testdaemon')
        self.assertFalse(d.is_new_record())

    def test_equality_daemon_of_double_and_single_args(self):
        """Create a daemon using the combined host:bin arg, find with 2"""
        d = self.create_daemon()
        d = model.Daemon('testhost:nova-testdaemon')
        self.assertFalse(d.is_new_record())

    def test_delete_daemon(self):
        """create, then destroy, then make sure loads a new record"""
        instance = self.create_daemon()
        instance.destroy()
        newinst = model.Daemon('testhost', 'nova-testdaemon')
        self.assertTrue(newinst.is_new_record())

    def test_daemon_heartbeat(self):
        """Create a daemon, sleep, heartbeat, check for update"""
        d = self.create_daemon()
        ts = d['updated_at']
        time.sleep(2)
        d.heartbeat()
        d2 = model.Daemon('testhost', 'nova-testdaemon')
        ts2 = d2['updated_at']
        self.assert_(ts2 > ts)

    def test_daemon_added_to_set(self):
        """create, then check that it is included in list"""
        instance = self.create_daemon()
        found = False
        for x in model.Daemon.all():
            if x.identifier == 'testhost:nova-testdaemon':
                found = True
        self.assert_(found)

    def test_daemon_associates_host(self):
        """create, then check that it is listed for the host"""
        instance = self.create_daemon()
        found = False
        for x in model.Daemon.by_host('testhost'):
            if x.identifier == 'testhost:nova-testdaemon':
                found = True
        self.assertTrue(found)

    def test_create_session_token(self):
        """create"""
        d = self.create_session_token()
        d = model.SessionToken(d.token)
        self.assertFalse(d.is_new_record())

    def test_delete_session_token(self):
        """create, then destroy, then make sure loads a new record"""
        instance = self.create_session_token()
        instance.destroy()
        newinst = model.SessionToken(instance.token)
        self.assertTrue(newinst.is_new_record())

    def test_session_token_added_to_set(self):
        """create, then check that it is included in list"""
        instance = self.create_session_token()
        found = False
        for x in model.SessionToken.all():
            if x.identifier == instance.token:
                found = True
        self.assert_(found)

    def test_session_token_associates_user(self):
        """create, then check that it is listed for the user"""
        instance = self.create_session_token()
        found = False
        for x in model.SessionToken.associated_to('user', 'testuser'):
            if x.identifier == instance.identifier:
                found = True
        self.assertTrue(found)

    def test_session_token_generation(self):
        instance = model.SessionToken.generate('username', 'TokenType')
        self.assertFalse(instance.is_new_record())

    def test_find_generated_session_token(self):
        instance = model.SessionToken.generate('username', 'TokenType')
        found = model.SessionToken.lookup(instance.identifier)
        self.assert_(found)

    def test_update_session_token_expiry(self):
        instance = model.SessionToken('tk12341234')
        oldtime = datetime.utcnow()
        instance['expiry'] = oldtime.strftime(utils.TIME_FORMAT)
        instance.update_expiry()
        expiry = utils.parse_isotime(instance['expiry'])
        self.assert_(expiry > datetime.utcnow())

    def test_session_token_lookup_when_expired(self):
        instance = model.SessionToken.generate("testuser")
        instance['expiry'] = datetime.utcnow().strftime(utils.TIME_FORMAT)
        instance.save()
        inst = model.SessionToken.lookup(instance.identifier)
        self.assertFalse(inst)

    def test_session_token_lookup_when_not_expired(self):
        instance = model.SessionToken.generate("testuser")
        inst = model.SessionToken.lookup(instance.identifier)
        self.assert_(inst)

    def test_session_token_is_expired_when_expired(self):
        instance = model.SessionToken.generate("testuser")
        instance['expiry'] = datetime.utcnow().strftime(utils.TIME_FORMAT)
        self.assert_(instance.is_expired())

    def test_session_token_is_expired_when_not_expired(self):
        instance = model.SessionToken.generate("testuser")
        self.assertFalse(instance.is_expired())

    def test_session_token_ttl(self):
        instance = model.SessionToken.generate("testuser")
        now = datetime.utcnow()
        delta = timedelta(hours=1)
        instance['expiry'] = (now + delta).strftime(utils.TIME_FORMAT)
        # give 5 seconds of fuzziness
        self.assert_(abs(instance.ttl() - FLAGS.auth_token_ttl) < 5)
