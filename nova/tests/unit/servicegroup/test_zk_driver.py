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

import mock

from nova import servicegroup
from nova.servicegroup.drivers import zk
from nova import test


class ZKServiceGroupTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ZKServiceGroupTestCase, self).setUp()
        self.flags(servicegroup_driver='zk')
        self.flags(address='localhost:2181', group="zookeeper")
        try:
            __import__('evzookeeper')
            __import__('zookeeper')
        except ImportError:
            self.skipTest("Unable to test due to lack of ZooKeeper")

    # Need to do this here, as opposed to the setUp() method, otherwise
    # the decorate will cause an import error...
    @mock.patch('evzookeeper.ZKSession')
    def _setup_sg_api(self, zk_sess_mock):
        self.zk_sess = mock.MagicMock()
        zk_sess_mock.return_value = self.zk_sess
        self.flags(servicegroup_driver='zk')
        self.flags(address='ignored', group="zookeeper")
        self.servicegroup_api = servicegroup.API()

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

    @mock.patch('evzookeeper.membership.Membership')
    def test_join(self, mem_mock):
        self._setup_sg_api()
        mem_mock.return_value = mock.sentinel.zk_mem
        self.servicegroup_api.join('fake-host', 'fake-topic')
        mem_mock.assert_called_once_with(self.zk_sess,
                                         '/fake-topic',
                                         'fake-host')
