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

from twisted.internet import defer

from nova import exception
from nova import db
from nova import flags
from nova import models
from nova import test
from nova.compute import service as compute_service
from nova.volume import service as volume_service


FLAGS = flags.FLAGS


class VolumeTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(VolumeTestCase, self).setUp()
        self.compute = compute_service.ComputeService()
        self.flags(connection_type='fake',
                   fake_storage=True)
        self.volume = volume_service.VolumeService()
        self.total_slots = 10
        # FIXME this should test actual creation method
        self.devices = []
        for i in xrange(self.total_slots):
            export_device = models.ExportDevice()
            export_device.shelf_id = 0
            export_device.blade_id = i
            export_device.save()
            self.devices.append(export_device)

    def tearDown(self):
        super(VolumeTestCase, self).tearDown()
        for device in self.devices:
            device.delete()

    @defer.inlineCallbacks
    def test_run_create_volume(self):
        vol_size = '0'
        user_id = 'fake'
        project_id = 'fake'
        volume_id = yield self.volume.create_volume(vol_size, user_id, project_id)
        self.assertEqual(volume_id,
                         models.Volume.find(volume_id).id)

        yield self.volume.delete_volume(volume_id)
        self.assertRaises(exception.NotFound, models.Volume.find, volume_id)

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
        vols = []
        for i in xrange(self.total_slots):
            vid = yield self.volume.create_volume(vol_size, user_id, project_id)
            vols.append(vid)
        self.assertFailure(self.volume.create_volume(vol_size,
                                                     user_id,
                                                     project_id),
                           db.NoMoreBlades)
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
        if FLAGS.fake_tests:
            db.volume_attached(None, volume_id, instance_id, mountpoint)
        else:
            rv = yield self.compute.attach_volume(instance_id,
                                                  volume_id,
                                                  mountpoint)
        vol = db.volume_get(None, volume_id)
        self.assertEqual(vol.status, "in-use")
        self.assertEqual(vol.attach_status, "attached")
        self.assertEqual(vol.instance_id, instance_id)
        self.assertEqual(vol.mountpoint, mountpoint)

        self.assertFailure(self.volume.delete_volume(volume_id), exception.Error)
        if FLAGS.fake_tests:
            db.volume_detached(None, volume_id)
        else:
            rv = yield self.volume.detach_volume(instance_id,
                                                 volume_id)
        self.assertEqual(vol.status, "available")

        rv = self.volume.delete_volume(volume_id)
        self.assertRaises(exception.Error,
                          models.Volume.find,
                          volume_id)

    @defer.inlineCallbacks
    def test_concurrent_volumes_get_different_blades(self):
        vol_size = "5"
        user_id = "fake"
        project_id = 'fake'
        shelf_blades = []
        volume_ids = []
        def _check(volume_id):
            volume_ids.append(volume_id)
            vol = models.Volume.find(volume_id)
            shelf_blade = '%s.%s' % (vol.export_device.shelf_id,
                                     vol.export_device.blade_id)
            self.assert_(shelf_blade not in shelf_blades)
            shelf_blades.append(shelf_blade)
            logging.debug("got %s" % shelf_blade)
        deferreds = []
        for i in range(self.total_slots):
            d = self.volume.create_volume(vol_size, user_id, project_id)
            d.addCallback(_check)
            d.addErrback(self.fail)
            deferreds.append(d)
        yield defer.DeferredList(deferreds)
        for volume_id in volume_ids:
            vol = models.Volume.find(volume_id)
            vol.delete()

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
