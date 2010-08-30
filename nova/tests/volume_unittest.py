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
from nova import test
from nova import utils


FLAGS = flags.FLAGS


class VolumeTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(VolumeTestCase, self).setUp()
        self.compute = utils.import_object(FLAGS.compute_manager)
        self.flags(connection_type='fake',
                   fake_storage=True)
        self.volume = utils.import_object(FLAGS.volume_manager)
        self.context = None


    def _create_volume(self, size='0'):
        vol = {}
        vol['size'] = '0'
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(None, vol)['id']

    @defer.inlineCallbacks
    def test_run_create_volume(self):
        volume_id = self._create_volume()
        yield self.volume.create_volume(self.context, volume_id)
        self.assertEqual(volume_id, db.volume_get(None, volume_id).id)

        yield self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          None,
                          volume_id)

    @defer.inlineCallbacks
    def test_too_big_volume(self):
        # FIXME(vish): validation needs to move into the data layer in
        #              volume_create
        defer.returnValue(True)
        try:
            volume_id = self._create_volume('1001')
            yield self.volume.create_volume(self.context, volume_id)
            self.fail("Should have thrown TypeError")
        except TypeError:
            pass

    @defer.inlineCallbacks
    def test_too_many_volumes(self):
        vols = []
        total_slots = FLAGS.num_shelves * FLAGS.blades_per_shelf
        for i in xrange(total_slots):
            volume_id = self._create_volume()
            yield self.volume.create_volume(self.context, volume_id)
            vols.append(volume_id)
        volume_id = self._create_volume()
        self.assertFailure(self.volume.create_volume(self.context,
                                                     volume_id),
                           db.NoMoreBlades)
        db.volume_destroy(None, volume_id)
        for volume_id in vols:
            yield self.volume.delete_volume(self.context, volume_id)

    @defer.inlineCallbacks
    def test_run_attach_detach_volume(self):
        # Create one volume and one compute to test with
        instance_id = "storage-test"
        mountpoint = "/dev/sdf"
        volume_id = self._create_volume()
        yield self.volume.create_volume(self.context, volume_id)
        if FLAGS.fake_tests:
            db.volume_attached(None, volume_id, instance_id, mountpoint)
        else:
            rv = yield self.compute.attach_volume(instance_id,
                                                  volume_id,
                                                  mountpoint)
        vol = db.volume_get(None, volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['instance_id'], instance_id)
        self.assertEqual(vol['mountpoint'], mountpoint)

        self.assertFailure(self.volume.delete_volume(self.context, volume_id),
                           exception.Error)
        if FLAGS.fake_tests:
            db.volume_detached(None, volume_id)
        else:
            rv = yield self.compute.detach_volume(instance_id,
                                                 volume_id)
        vol = db.volume_get(None, volume_id)
        self.assertEqual(vol['status'], "available")

        rv = self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.Error,
                          db.volume_get,
                          None,
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
            (shelf_id, blade_id) = db.volume_get_shelf_and_blade(None,
                                                                 volume_id)
            shelf_blade = '%s.%s' % (shelf_id, blade_id)
            self.assert_(shelf_blade not in shelf_blades)
            shelf_blades.append(shelf_blade)
            logging.debug("got %s" % shelf_blade)
        deferreds = []
        total_slots = FLAGS.num_shelves * FLAGS.blades_per_shelf
        for i in range(total_slots):
            volume_id = self._create_volume()
            d = self.volume.create_volume(self.context, volume_id)
            d.addCallback(_check)
            d.addErrback(self.fail)
            deferreds.append(d)
        yield defer.DeferredList(deferreds)
        for volume_id in volume_ids:
            self.volume.delete_volume(self.context, volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
