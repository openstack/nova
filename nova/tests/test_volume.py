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
"""
Tests for Volume Code.

"""

from nova import context
from nova import exception
from nova import db
from nova import flags
from nova import log as logging
from nova import test
from nova import utils

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.volume')


class VolumeTestCase(test.TestCase):
    """Test Case for volumes."""

    def setUp(self):
        super(VolumeTestCase, self).setUp()
        self.compute = utils.import_object(FLAGS.compute_manager)
        self.flags(connection_type='fake')
        self.volume = utils.import_object(FLAGS.volume_manager)
        self.context = context.get_admin_context()

    @staticmethod
    def _create_volume(size='0'):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['user_id'] = 'fake'
        vol['project_id'] = 'fake'
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating"
        vol['attach_status'] = "detached"
        return db.volume_create(context.get_admin_context(), vol)['id']

    def test_create_delete_volume(self):
        """Test volume can be created and deleted."""
        volume_id = self._create_volume()
        self.volume.create_volume(self.context, volume_id)
        self.assertEqual(volume_id, db.volume_get(context.get_admin_context(),
                         volume_id).id)

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.NotFound,
                          db.volume_get,
                          self.context,
                          volume_id)

    def test_too_big_volume(self):
        """Ensure failure if a too large of a volume is requested."""
        # FIXME(vish): validation needs to move into the data layer in
        #              volume_create
        return True
        try:
            volume_id = self._create_volume('1001')
            self.volume.create_volume(self.context, volume_id)
            self.fail("Should have thrown TypeError")
        except TypeError:
            pass

    def test_too_many_volumes(self):
        """Ensure that NoMoreTargets is raised when we run out of volumes."""
        vols = []
        total_slots = FLAGS.iscsi_num_targets
        for _index in xrange(total_slots):
            volume_id = self._create_volume()
            self.volume.create_volume(self.context, volume_id)
            vols.append(volume_id)
        volume_id = self._create_volume()
        self.assertRaises(db.NoMoreTargets,
                          self.volume.create_volume,
                          self.context,
                          volume_id)
        db.volume_destroy(context.get_admin_context(), volume_id)
        for volume_id in vols:
            self.volume.delete_volume(self.context, volume_id)

    def test_run_attach_detach_volume(self):
        """Make sure volume can be attached and detached from instance."""
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        instance_id = db.instance_create(self.context, inst)['id']
        mountpoint = "/dev/sdf"
        volume_id = self._create_volume()
        self.volume.create_volume(self.context, volume_id)
        if FLAGS.fake_tests:
            db.volume_attached(self.context, volume_id, instance_id,
                               mountpoint)
        else:
            self.compute.attach_volume(self.context,
                                       instance_id,
                                       volume_id,
                                       mountpoint)
        vol = db.volume_get(context.get_admin_context(), volume_id)
        self.assertEqual(vol['status'], "in-use")
        self.assertEqual(vol['attach_status'], "attached")
        self.assertEqual(vol['mountpoint'], mountpoint)
        instance_ref = db.volume_get_instance(self.context, volume_id)
        self.assertEqual(instance_ref['id'], instance_id)

        self.assertRaises(exception.Error,
                          self.volume.delete_volume,
                          self.context,
                          volume_id)
        if FLAGS.fake_tests:
            db.volume_detached(self.context, volume_id)
        else:
            self.compute.detach_volume(self.context,
                                       instance_id,
                                       volume_id)
        vol = db.volume_get(self.context, volume_id)
        self.assertEqual(vol['status'], "available")

        self.volume.delete_volume(self.context, volume_id)
        self.assertRaises(exception.Error,
                          db.volume_get,
                          self.context,
                          volume_id)
        db.instance_destroy(self.context, instance_id)

    def test_concurrent_volumes_get_different_targets(self):
        """Ensure multiple concurrent volumes get different targets."""
        volume_ids = []
        targets = []

        def _check(volume_id):
            """Make sure targets aren't duplicated."""
            volume_ids.append(volume_id)
            admin_context = context.get_admin_context()
            iscsi_target = db.volume_get_iscsi_target_num(admin_context,
                                                          volume_id)
            self.assert_(iscsi_target not in targets)
            targets.append(iscsi_target)
            LOG.debug(_("Target %s allocated"), iscsi_target)
        total_slots = FLAGS.iscsi_num_targets
        for _index in xrange(total_slots):
            volume_id = self._create_volume()
            d = self.volume.create_volume(self.context, volume_id)
            _check(d)
        for volume_id in volume_ids:
            self.volume.delete_volume(self.context, volume_id)

    def test_multi_node(self):
        # TODO(termie): Figure out how to test with two nodes,
        # each of them having a different FLAG for storage_node
        # This will allow us to test cross-node interactions
        pass
