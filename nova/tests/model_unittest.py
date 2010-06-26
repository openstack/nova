# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

import logging
import time

from nova import vendor
from twisted.internet import defer

from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.compute import model
from nova.compute import node


FLAGS = flags.FLAGS


class ModelTestCase(test.TrialTestCase):
    def setUp(self):
        super(ModelTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_storage=True,
                   fake_users=True)

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
        inst['node_name'] = FLAGS.node_name
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
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

    @defer.inlineCallbacks
    def test_create_instance(self):
        """store with create_instace, then test that a load finds it"""
        instance = yield self.create_instance()
        old = yield model.Instance(instance.identifier)
        self.assertFalse(old.is_new_record())

    @defer.inlineCallbacks
    def test_delete_instance(self):
        """create, then destroy, then make sure loads a new record"""
        instance = yield self.create_instance()
        yield instance.destroy()
        newinst = yield model.Instance('i-test')
        self.assertTrue(newinst.is_new_record())

    @defer.inlineCallbacks
    def test_instance_added_to_set(self):
        """create, then check that it is listed for the project"""
        instance = yield self.create_instance()
        found = False
        for x in model.InstanceDirectory().all:
            if x.identifier == 'i-test':
                found = True
        self.assert_(found)

    @defer.inlineCallbacks
    def test_instance_associates_project(self):
        """create, then check that it is listed for the project"""
        instance = yield self.create_instance()
        found = False
        for x in model.InstanceDirectory().by_project(instance.project):
            if x.identifier == 'i-test':
                found = True
        self.assert_(found)

    @defer.inlineCallbacks
    def test_host_class_finds_hosts(self):
        host = yield self.create_host()
        self.assertEqual('testhost', model.Host.lookup('testhost').identifier)

    @defer.inlineCallbacks
    def test_host_class_doesnt_find_missing_hosts(self):
        rv = yield model.Host.lookup('woahnelly')
        self.assertEqual(None, rv)

    @defer.inlineCallbacks
    def test_create_host(self):
        """store with create_host, then test that a load finds it"""
        host = yield self.create_host()
        old = yield model.Host(host.identifier)
        self.assertFalse(old.is_new_record())

    @defer.inlineCallbacks
    def test_delete_host(self):
        """create, then destroy, then make sure loads a new record"""
        instance = yield self.create_host()
        yield instance.destroy()
        newinst = yield model.Host('testhost')
        self.assertTrue(newinst.is_new_record())

    @defer.inlineCallbacks
    def test_host_added_to_set(self):
        """create, then check that it is included in list"""
        instance = yield self.create_host()
        found = False
        for x in model.Host.all():
            if x.identifier == 'testhost':
                found = True
        self.assert_(found)

    @defer.inlineCallbacks
    def test_create_daemon_two_args(self):
        """create a daemon with two arguments"""
        d = yield self.create_daemon()
        d = model.Daemon('testhost', 'nova-testdaemon')
        self.assertFalse(d.is_new_record())

    @defer.inlineCallbacks
    def test_create_daemon_single_arg(self):
        """Create a daemon using the combined host:bin format"""
        d = yield model.Daemon("testhost:nova-testdaemon")
        d.save()
        d = model.Daemon('testhost:nova-testdaemon')
        self.assertFalse(d.is_new_record())

    @defer.inlineCallbacks
    def test_equality_of_daemon_single_and_double_args(self):
        """Create a daemon using the combined host:bin arg, find with 2"""
        d = yield model.Daemon("testhost:nova-testdaemon")
        d.save()
        d = model.Daemon('testhost', 'nova-testdaemon')
        self.assertFalse(d.is_new_record())

    @defer.inlineCallbacks
    def test_equality_daemon_of_double_and_single_args(self):
        """Create a daemon using the combined host:bin arg, find with 2"""
        d = yield self.create_daemon()
        d = model.Daemon('testhost:nova-testdaemon')
        self.assertFalse(d.is_new_record())

    @defer.inlineCallbacks
    def test_delete_daemon(self):
        """create, then destroy, then make sure loads a new record"""
        instance = yield self.create_daemon()
        yield instance.destroy()
        newinst = yield model.Daemon('testhost', 'nova-testdaemon')
        self.assertTrue(newinst.is_new_record())

    @defer.inlineCallbacks
    def test_daemon_heartbeat(self):
        """Create a daemon, sleep, heartbeat, check for update"""
        d = yield self.create_daemon()
        ts = d['updated_at']
        time.sleep(2)
        d.heartbeat()
        d2 = model.Daemon('testhost', 'nova-testdaemon')
        ts2 = d2['updated_at']
        self.assert_(ts2 > ts)

    @defer.inlineCallbacks
    def test_daemon_added_to_set(self):
        """create, then check that it is included in list"""
        instance = yield self.create_daemon()
        found = False
        for x in model.Daemon.all():
            if x.identifier == 'testhost:nova-testdaemon':
                found = True
        self.assert_(found)

    @defer.inlineCallbacks
    def test_daemon_associates_host(self):
        """create, then check that it is listed for the host"""
        instance = yield self.create_daemon()
        found = False
        for x in model.Daemon.by_host('testhost'):
            if x.identifier == 'testhost:nova-testdaemon':
                found = True
        self.assertTrue(found)
