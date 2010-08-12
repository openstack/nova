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
import shutil
import tempfile

from twisted.internet import defer

from nova import compute
from nova import exception
from nova import flags
from nova import test
from nova.volume import service as volume_service


FLAGS = flags.FLAGS


class VolumeTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(VolumeTestCase, self).setUp()
        self.compute = compute.service.ComputeService()
        self.volume = None
        self.tempdir = tempfile.mkdtemp()
        self.flags(connection_type='fake',
                   fake_storage=True,
                   aoe_export_dir=self.tempdir)
        self.volume = volume_service.VolumeService()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    @defer.inlineCallbacks
    def test_run_create_volume(self):
        vol_size = '0'
        user_id = 'fake'
        project_id = 'fake'
        volume_id = yield self.volume.create_volume(vol_size, user_id, project_id)
        # TODO(termie): get_volume returns differently than create_volume
        self.assertEqual(volume_id,
                         volume_service.get_volume(volume_id)['volume_id'])

        rv = self.volume.delete_volume(volume_id)
        self.assertRaises(exception.Error, volume_service.get_volume, volume_id)

    @defer.inlineCallbacks
    def test_too_big_volume(self):
        vol_size = '1001'
        user_id = 'fake'
        project_id = 'fake'
        try:
            yield self.volume.create_volume(vol_size, user_id, project_id)
            self.fail("Should have thrown TypeError")
        except TypeError:
            pass

    @defer.inlineCallbacks
    def test_too_many_volumes(self):
        vol_size = '1'
        user_id = 'fake'
        project_id = 'fake'
        num_shelves = FLAGS.last_shelf_id - FLAGS.first_shelf_id + 1
        total_slots = FLAGS.blades_per_shelf * num_shelves
        vols = []
        from nova import datastore
        redis = datastore.Redis.instance()
        for i in xrange(total_slots):
            vid = yield self.volume.create_volume(vol_size, user_id, project_id)
            vols.append(vid)
        self.assertFailure(self.volume.create_volume(vol_size,
                                                     user_id,
                                                     project_id),
                           volume_service.NoMoreBlades)
        for id in vols:
            yield self.volume.delete_volume(id)

    @defer.inlineCallbacks
    def test_run_attach_detach_volume(self):
        # Create one volume and one compute to test with
        instance_id = "storage-test"
        vol_size = "5"
        user_id = "fake"
        project_id = 'fake'
        mountpoint = "/dev/sdf"
        volume_id = yield self.volume.create_volume(vol_size, user_id, project_id)
        volume_obj = volume_service.get_volume(volume_id)
        volume_obj.start_attach(instance_id, mountpoint)
        if FLAGS.fake_tests:
            volume_obj.finish_attach()
        else:
            rv = yield self.compute.attach_volume(instance_id,
                                                  volume_id,
                                                  mountpoint)
        self.assertEqual(volume_obj['status'], "in-use")
        self.assertEqual(volume_obj['attach_status'], "attached")
        self.assertEqual(volume_obj['instance_id'], instance_id)
        self.assertEqual(volume_obj['mountpoint'], mountpoint)

        self.assertFailure(self.volume.delete_volume(volume_id), exception.Error)
        volume_obj.start_detach()
        if FLAGS.fake_tests:
            volume_obj.finish_detach()
        else:
            rv = yield self.volume.detach_volume(instance_id,
                                                 volume_id)
        volume_obj = volume_service.get_volume(volume_id)
        self.assertEqual(volume_obj['status'], "available")

        rv = self.volume.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          volume_service.get_volume,
                          volume_id)

    @defer.inlineCallbacks
    def test_multiple_volume_race_condition(self):
        vol_size = "5"
        user_id = "fake"
        project_id = 'fake'
        shelf_blades = []
        def _check(volume_id):
            vol = volume_service.get_volume(volume_id)
            shelf_blade = '%s.%s' % (vol['shelf_id'], vol['blade_id'])
            self.assert_(shelf_blade not in shelf_blades)
            shelf_blades.append(shelf_blade)
            logging.debug("got %s" % shelf_blade)
            vol.destroy()
        deferreds = []
        for i in range(5):
            d = self.volume.create_volume(vol_size, user_id, project_id)
            d.addCallback(_check)
            d.addErrback(self.fail)
            deferreds.append(d)
        yield defer.DeferredList(deferreds)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
