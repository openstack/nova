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

import logging
import StringIO
import time
import unittest
from xml.etree import ElementTree

from nova import vendor
import mox
from tornado import ioloop
from twisted.internet import defer

from nova import cloud
from nova import exception
from nova import flags
from nova import node
from nova import rpc
from nova import test


FLAGS = flags.FLAGS


class AdminTestCase(test.BaseTestCase):
    def setUp(self):
        super(AdminTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_rabbit=True)

        self.conn = rpc.Connection.instance()

        logging.getLogger().setLevel(logging.INFO)

        # set up our cloud
        self.cloud = cloud.CloudController()
        self.cloud_consumer = rpc.AdapterConsumer(connection=self.conn,
                                                      topic=FLAGS.cloud_topic,
                                                      proxy=self.cloud)
        self.injected.append(self.cloud_consumer.attach_to_tornado(self.ioloop))
        
        # set up a node
        self.node = node.Node()
        self.node_consumer = rpc.AdapterConsumer(connection=self.conn,
                                                     topic=FLAGS.compute_topic,
                                                     proxy=self.node)
        self.injected.append(self.node_consumer.attach_to_tornado(self.ioloop))

    def test_flush_terminated(self):
        # Launch an instance

        # Wait until it's running

        # Terminate it

        # Wait until it's terminated

        # Flush terminated nodes

        # ASSERT that it's gone
        pass
