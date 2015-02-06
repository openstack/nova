# Copyright (c) AT&T 2012-2013 Yun Mao <yunmao@gmail.com>
# Copyright 2012 IBM Corp.
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

"""Test the ZooKeeper driver for servicegroup.

You need to install ZooKeeper locally and related dependencies
to run the test. It's unclear how to install python-zookeeper lib
in venv so you might have to run the test without it.

To set up in Ubuntu 12.04:
$ sudo apt-get install zookeeper zookeeperd python-zookeeper
$ sudo pip install evzookeeper
$ nosetests nova.tests.unit.servicegroup.test_zk_driver
"""
import os

import eventlet

from nova import servicegroup
from nova.servicegroup.drivers import zk
from nova import test


class ZKServiceGroupTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ZKServiceGroupTestCase, self).setUp()
        servicegroup.API._driver = None
        self.flags(servicegroup_driver='zk')
        self.flags(address='localhost:2181', group="zookeeper")
        try:
            zk.ZooKeeperDriver()
        except ImportError:
            self.skipTest("Unable to test due to lack of ZooKeeper")

    def test_join_leave(self):
        self.servicegroup_api = servicegroup.API()
        service_id = {'topic': 'unittest', 'host': 'serviceA'}
        self.servicegroup_api.join(service_id['host'], service_id['topic'])
        self.assertTrue(self.servicegroup_api.service_is_up(service_id))
        self.servicegroup_api.leave(service_id['host'], service_id['topic'])
        # make sure zookeeper is updated and watcher is triggered
        eventlet.sleep(1)
        self.assertFalse(self.servicegroup_api.service_is_up(service_id))

    def test_stop(self):
        self.servicegroup_api = servicegroup.API()
        service_id = {'topic': 'unittest', 'host': 'serviceA'}
        pulse = self.servicegroup_api.join(service_id['host'],
                                         service_id['topic'], None)
        self.assertTrue(self.servicegroup_api.service_is_up(service_id))
        pulse.stop()
        eventlet.sleep(1)
        self.assertFalse(self.servicegroup_api.service_is_up(service_id))

    def test_zookeeper_hierarchy_structure(self):
        """Test that hierarchy created by join method contains process id."""
        from zookeeper import NoNodeException
        self.servicegroup_api = servicegroup.API()
        service_id = {'topic': 'unittest', 'host': 'serviceC'}
        # use existing session object
        session = self.servicegroup_api._driver._session
        # prepare a path that contains process id
        pid = os.getpid()
        path = '/servicegroups/%s/%s/%s' % (service_id['topic'],
                                              service_id['host'],
                                              pid)
        # assert that node doesn't exist yet
        self.assertRaises(NoNodeException, session.get, path)
        # join
        self.servicegroup_api.join(service_id['host'],
                                   service_id['topic'],
                                   None)
        # expected existing "process id" node
        self.assertTrue(session.get(path))

    def test_lazy_session(self):
        """Session object (contains zk handle) should be created in
        lazy manner, because handle cannot be shared by forked processes.
        """
        # insied import because this test runs conditionaly (look at setUp)
        import evzookeeper
        driver = zk.ZooKeeperDriver()
        # check that internal private attribute session is empty
        self.assertIsNone(driver.__dict__['_ZooKeeperDriver__session'])
        # after first use of property ...
        driver._session
        # check that internal private session attribute is ready
        self.assertIsInstance(driver.__dict__['_ZooKeeperDriver__session'],
                              evzookeeper.ZKSession)
