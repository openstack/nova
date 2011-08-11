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

import cStringIO

from nova import context
from nova import exception
from nova import db
from nova import flags
from nova import log as logging
from nova import rpc
from nova import test
from nova import utils
from nova import volume

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
        self.instance_id = db.instance_create(self.context, {})['id']

    def tearDown(self):
        db.instance_destroy(self.context, self.instance_id)
        super(VolumeTestCase, self).tearDown()

    @staticmethod
    def _create_volume(size='0', snapshot_id=None):
        """Create a volume object."""
        vol = {}
        vol['size'] = size
        vol['snapshot_id'] = snapshot_id
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

    def test_create_volume_from_snapshot(self):
        """Test volume can be created from a snapshot."""
        volume_src_id = self._create_volume()
        self.volume.create_volume(self.context, volume_src_id)
        snapshot_id = self._create_snapshot(volume_src_id)
        self.volume.create_snapshot(self.context, volume_src_id, snapshot_id)
        volume_dst_id = self._create_volume(0, snapshot_id)
        self.volume.create_volume(self.context, volume_dst_id, snapshot_id)
        self.assertEqual(volume_dst_id, db.volume_get(
                context.get_admin_context(),
                volume_dst_id).id)
        self.assertEqual(snapshot_id, db.volume_get(
                context.get_admin_context(),
                volume_dst_id).snapshot_id)

        self.volume.delete_volume(self.context, volume_dst_id)
        self.volume.delete_snapshot(self.context, snapshot_id)
        self.volume.delete_volume(self.context, volume_src_id)

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
        inst['image_id'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type_id'] = '2'  # m1.tiny
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
        self.assertRaises(exception.VolumeNotFound,
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

    @staticmethod
    def _create_snapshot(volume_id, size='0'):
        """Create a snapshot object."""
        snap = {}
        snap['volume_size'] = size
        snap['user_id'] = 'fake'
        snap['project_id'] = 'fake'
        snap['volume_id'] = volume_id
        snap['status'] = "creating"
        return db.snapshot_create(context.get_admin_context(), snap)['id']

    def test_create_delete_snapshot(self):
        """Test snapshot can be created and deleted."""
        volume_id = self._create_volume()
        self.volume.create_volume(self.context, volume_id)
        snapshot_id = self._create_snapshot(volume_id)
        self.volume.create_snapshot(self.context, volume_id, snapshot_id)
        self.assertEqual(snapshot_id,
                         db.snapshot_get(context.get_admin_context(),
                                         snapshot_id).id)

        self.volume.delete_snapshot(self.context, snapshot_id)
        self.assertRaises(exception.NotFound,
                          db.snapshot_get,
                          self.context,
                          snapshot_id)
        self.volume.delete_volume(self.context, volume_id)

    def test_create_snapshot_force(self):
        """Test snapshot in use can be created forcibly."""

        def fake_cast(ctxt, topic, msg):
            pass
        self.stubs.Set(rpc, 'cast', fake_cast)

        volume_id = self._create_volume()
        self.volume.create_volume(self.context, volume_id)
        db.volume_attached(self.context, volume_id, self.instance_id,
                           '/dev/sda1')

        volume_api = volume.api.API()
        self.assertRaises(exception.ApiError,
                          volume_api.create_snapshot,
                          self.context, volume_id,
                          'fake_name', 'fake_description')
        snapshot_ref = volume_api.create_snapshot_force(self.context,
                                                        volume_id,
                                                        'fake_name',
                                                        'fake_description')
        db.snapshot_destroy(self.context, snapshot_ref['id'])
        db.volume_destroy(self.context, volume_id)


class DriverTestCase(test.TestCase):
    """Base Test class for Drivers."""
    driver_name = "nova.volume.driver.FakeAOEDriver"

    def setUp(self):
        super(DriverTestCase, self).setUp()
        self.flags(volume_driver=self.driver_name,
                   logging_default_format_string="%(message)s")
        self.volume = utils.import_object(FLAGS.volume_manager)
        self.context = context.get_admin_context()
        self.output = ""

        def _fake_execute(_command, *_args, **_kwargs):
            """Fake _execute."""
            return self.output, None
        self.volume.driver._execute = _fake_execute
        self.volume.driver._sync_execute = _fake_execute

        log = logging.getLogger()
        self.stream = cStringIO.StringIO()
        log.addHandler(logging.StreamHandler(self.stream))

        inst = {}
        self.instance_id = db.instance_create(self.context, inst)['id']

    def tearDown(self):
        super(DriverTestCase, self).tearDown()

    def _attach_volume(self):
        """Attach volumes to an instance. This function also sets
           a fake log message."""
        return []

    def _detach_volume(self, volume_id_list):
        """Detach volumes from an instance."""
        for volume_id in volume_id_list:
            db.volume_detached(self.context, volume_id)
            self.volume.delete_volume(self.context, volume_id)


class AOETestCase(DriverTestCase):
    """Test Case for AOEDriver"""
    driver_name = "nova.volume.driver.AOEDriver"

    def setUp(self):
        super(AOETestCase, self).setUp()

    def tearDown(self):
        super(AOETestCase, self).tearDown()

    def _attach_volume(self):
        """Attach volumes to an instance. This function also sets
           a fake log message."""
        volume_id_list = []
        for index in xrange(3):
            vol = {}
            vol['size'] = 0
            volume_id = db.volume_create(self.context,
                                         vol)['id']
            self.volume.create_volume(self.context, volume_id)

            # each volume has a different mountpoint
            mountpoint = "/dev/sd" + chr((ord('b') + index))
            db.volume_attached(self.context, volume_id, self.instance_id,
                               mountpoint)

            (shelf_id, blade_id) = db.volume_get_shelf_and_blade(self.context,
                                                                 volume_id)
            self.output += "%s %s eth0 /dev/nova-volumes/vol-foo auto run\n" \
                      % (shelf_id, blade_id)

            volume_id_list.append(volume_id)

        return volume_id_list

    def test_check_for_export_with_no_volume(self):
        """No log message when no volume is attached to an instance."""
        self.stream.truncate(0)
        self.volume.check_for_export(self.context, self.instance_id)
        self.assertEqual(self.stream.getvalue(), '')

    def test_check_for_export_with_all_vblade_processes(self):
        """No log message when all the vblade processes are running."""
        volume_id_list = self._attach_volume()

        self.stream.truncate(0)
        self.volume.check_for_export(self.context, self.instance_id)
        self.assertEqual(self.stream.getvalue(), '')

        self._detach_volume(volume_id_list)

    def test_check_for_export_with_vblade_process_missing(self):
        """Output a warning message when some vblade processes aren't
           running."""
        volume_id_list = self._attach_volume()

        # the first vblade process isn't running
        self.output = self.output.replace("run", "down", 1)
        (shelf_id, blade_id) = db.volume_get_shelf_and_blade(self.context,
                                                             volume_id_list[0])

        msg_is_match = False
        self.stream.truncate(0)
        try:
            self.volume.check_for_export(self.context, self.instance_id)
        except exception.ProcessExecutionError, e:
            volume_id = volume_id_list[0]
            msg = _("Cannot confirm exported volume id:%(volume_id)s. "
                    "vblade process for e%(shelf_id)s.%(blade_id)s "
                    "isn't running.") % locals()

            msg_is_match = (0 <= e.message.find(msg))

        self.assertTrue(msg_is_match)
        self._detach_volume(volume_id_list)


class ISCSITestCase(DriverTestCase):
    """Test Case for ISCSIDriver"""
    driver_name = "nova.volume.driver.ISCSIDriver"

    def setUp(self):
        super(ISCSITestCase, self).setUp()

    def tearDown(self):
        super(ISCSITestCase, self).tearDown()

    def _attach_volume(self):
        """Attach volumes to an instance. This function also sets
           a fake log message."""
        volume_id_list = []
        for index in xrange(3):
            vol = {}
            vol['size'] = 0
            vol_ref = db.volume_create(self.context, vol)
            self.volume.create_volume(self.context, vol_ref['id'])
            vol_ref = db.volume_get(self.context, vol_ref['id'])

            # each volume has a different mountpoint
            mountpoint = "/dev/sd" + chr((ord('b') + index))
            db.volume_attached(self.context, vol_ref['id'], self.instance_id,
                               mountpoint)
            volume_id_list.append(vol_ref['id'])

        return volume_id_list

    def test_check_for_export_with_no_volume(self):
        """No log message when no volume is attached to an instance."""
        self.stream.truncate(0)
        self.volume.check_for_export(self.context, self.instance_id)
        self.assertEqual(self.stream.getvalue(), '')

    def test_check_for_export_with_all_volume_exported(self):
        """No log message when all the vblade processes are running."""
        volume_id_list = self._attach_volume()

        self.mox.StubOutWithMock(self.volume.driver, '_execute')
        for i in volume_id_list:
            tid = db.volume_get_iscsi_target_num(self.context, i)
            self.volume.driver._execute("ietadm", "--op", "show",
                                        "--tid=%(tid)d" % locals(),
                                        run_as_root=True)

        self.stream.truncate(0)
        self.mox.ReplayAll()
        self.volume.check_for_export(self.context, self.instance_id)
        self.assertEqual(self.stream.getvalue(), '')
        self.mox.UnsetStubs()

        self._detach_volume(volume_id_list)

    def test_check_for_export_with_some_volume_missing(self):
        """Output a warning message when some volumes are not recognied
           by ietd."""
        volume_id_list = self._attach_volume()

        # the first vblade process isn't running
        tid = db.volume_get_iscsi_target_num(self.context, volume_id_list[0])
        self.mox.StubOutWithMock(self.volume.driver, '_execute')
        self.volume.driver._execute("ietadm", "--op", "show",
                                    "--tid=%(tid)d" % locals(),
                                    run_as_root=True).AndRaise(
                                            exception.ProcessExecutionError())

        self.mox.ReplayAll()
        self.assertRaises(exception.ProcessExecutionError,
                          self.volume.check_for_export,
                          self.context,
                          self.instance_id)
        msg = _("Cannot confirm exported volume id:%s.") % volume_id_list[0]
        self.assertTrue(0 <= self.stream.getvalue().find(msg))
        self.mox.UnsetStubs()

        self._detach_volume(volume_id_list)
