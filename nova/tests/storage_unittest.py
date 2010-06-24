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
import StringIO
import time
import unittest
from xml.etree import ElementTree

from nova import vendor
import mox
from tornado import ioloop
from twisted.internet import defer

from nova import exception
from nova import flags
from nova import test
from nova.compute import node
from nova.volume import storage


FLAGS = flags.FLAGS


class StorageTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(StorageTestCase, self).setUp()
        self.mynode = node.Node()
        self.mystorage = None
        self.flags(fake_libvirt=True,
                   fake_storage=True)
        if FLAGS.fake_storage:
            self.mystorage = storage.FakeBlockStore()
        else:
            self.mystorage = storage.BlockStore()

    def test_run_create_volume(self):
        vol_size = '0'
        user_id = 'fake'
        volume_id = self.mystorage.create_volume(vol_size, user_id)
        # TODO(termie): get_volume returns differently than create_volume
        self.assertEqual(volume_id,
                         storage.get_volume(volume_id)['volume_id'])

        rv = self.mystorage.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          storage.get_volume,
                          volume_id)

    def test_run_attach_detach_volume(self):
        # Create one volume and one node to test with
        instance_id = "storage-test"
        vol_size = "5"
        user_id = "fake"
        mountpoint = "/dev/sdf"
        volume_id = self.mystorage.create_volume(vol_size, user_id)
        
        volume_obj = storage.get_volume(volume_id)
        volume_obj.start_attach(instance_id, mountpoint)
        rv = yield self.mynode.attach_volume(volume_id,
                                          instance_id,
                                          mountpoint)
        self.assertEqual(volume_obj['status'], "in-use")
        self.assertEqual(volume_obj['attachStatus'], "attached")
        self.assertEqual(volume_obj['instance_id'], instance_id)
        self.assertEqual(volume_obj['mountpoint'], mountpoint)
        
        self.assertRaises(exception.Error,
                          self.mystorage.delete_volume,
                          volume_id)

        rv = yield self.mystorage.detach_volume(volume_id)
        volume_obj = storage.get_volume(volume_id)
        self.assertEqual(volume_obj['status'], "available")
        
        rv = self.mystorage.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          storage.get_volume,
                          volume_id)
                          
    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
