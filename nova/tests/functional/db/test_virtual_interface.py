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

import datetime
import mock
from oslo_config import cfg
from oslo_utils import timeutils

from nova import context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.objects import virtual_interface
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_network

CONF = cfg.CONF

FAKE_UUID = '00000000-0000-0000-0000-000000000000'


def _delete_vif_list(context, instance_uuid):
    vif_list = objects.VirtualInterfaceList.\
        get_by_instance_uuid(context, instance_uuid)

    # Set old VirtualInterfaces as deleted.
    for vif in vif_list:
        vif.destroy()


def _verify_list_fulfillment(context, instance_uuid):
    try:
        info_cache = objects.InstanceInfoCache.\
            get_by_instance_uuid(context, instance_uuid)
    except exception.InstanceInfoCacheNotFound:
        info_cache = []

    vif_list = objects.VirtualInterfaceList.\
        get_by_instance_uuid(context, instance_uuid)
    vif_list = filter(lambda x: not x.deleted,
                      vif_list)

    cached_vif_ids = [vif['id'] for vif in info_cache.network_info]
    db_vif_ids = [vif.uuid for vif in vif_list]
    return cached_vif_ids == db_vif_ids


class VirtualInterfaceListMigrationTestCase(
        integrated_helpers._IntegratedTestBase):

    ADMIN_API = True
    api_major_version = 'v2.1'

    def setUp(self):
        super(VirtualInterfaceListMigrationTestCase, self).setUp()

        self.context = context.get_admin_context()
        fake_network.set_stub_network_methods(self)
        self.cells = objects.CellMappingList.get_all(self.context)

        self._start_compute('compute2')
        self.instances = []

    def _create_instances(self, pre_newton=2, deleted=0, total=5,
                          target_cell=None):
        if not target_cell:
            target_cell = self.cells[1]

        instances = []
        with context.target_cell(self.context, target_cell) as cctxt:
            flav_dict = objects.Flavor._flavor_get_from_db(cctxt, 1)
            flavor = objects.Flavor(**flav_dict)
            for i in range(0, total):
                inst = objects.Instance(
                    context=cctxt,
                    project_id=self.api.project_id,
                    user_id=FAKE_UUID,
                    vm_state='active',
                    flavor=flavor,
                    created_at=datetime.datetime(1985, 10, 25, 1, 21, 0),
                    launched_at=datetime.datetime(1985, 10, 25, 1, 22, 0),
                    host=self.computes['compute2'].host,
                    hostname='%s-inst%i' % (target_cell.name, i))
                inst.create()

                info_cache = objects.InstanceInfoCache(context=cctxt)
                info_cache.updated_at = timeutils.utcnow()
                info_cache.network_info = network_model.NetworkInfo()
                info_cache.instance_uuid = inst.uuid
                info_cache.save()

                instances.append(inst)

                im = objects.InstanceMapping(context=cctxt,
                    project_id=inst.project_id,
                    user_id=inst.user_id,
                    instance_uuid=inst.uuid,
                    cell_mapping=target_cell)
                im.create()

        # Attach fake interfaces to instances
        network_id = list(self.neutron._networks.keys())[0]
        for i in range(0, len(instances)):
            for k in range(0, 4):
                self.api.attach_interface(instances[i].uuid,
                    {"interfaceAttachment": {"net_id": network_id}})

        with context.target_cell(self.context, target_cell) as cctxt:
            # Fake the pre-newton behaviour by removing the
            # VirtualInterfacesList objects.
            if pre_newton:
                for i in range(0, pre_newton):
                    _delete_vif_list(cctxt, instances[i].uuid)

        if deleted:
            # Delete from the end of active instances list
            for i in range(total - deleted, total):
                instances[i].destroy()

        self.instances += instances

    def test_migration_nothing_to_migrate(self):
        """This test when there already populated VirtualInterfaceList
           objects for created instances.
        """
        self._create_instances(pre_newton=0, total=5)
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        self.assertEqual(5, match)
        self.assertEqual(0, done)

    def test_migration_verify_max_count(self):
        """This verifies if max_count is respected to avoid migration
           of bigger set of data, than user specified.
        """
        self._create_instances(pre_newton=0, total=3)
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 2)

        self.assertEqual(2, match)
        self.assertEqual(0, done)

    def test_migration_do_not_step_to_next_cell(self):
        """This verifies if script doesn't step into next cell
           when max_count is reached.
        """
        # Create 2 instances in cell0
        self._create_instances(
            pre_newton=0, total=2, target_cell=self.cells[0])

        # Create 2 instances in cell1
        self._create_instances(
            pre_newton=0, total=2, target_cell=self.cells[1])

        with mock.patch('nova.objects.InstanceList.get_by_filters',
                        side_effect=[self.instances[0:2],
                                     self.instances[2:]]) \
            as mock_get:
            match, done = virtual_interface.fill_virtual_interface_list(
                self.context, 2)

        self.assertEqual(2, match)
        self.assertEqual(0, done)
        mock_get.assert_called_once()

    def test_migration_pre_newton_instances(self):
        """This test when there is an instance created in release
           older than Newton. For those instances the VirtualInterfaceList
           needs to be re-created from cache.
        """
        # Lets spawn 3 pre-newton instances and 2 new ones
        self._create_instances(pre_newton=3, total=5)
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        self.assertEqual(5, match)
        self.assertEqual(3, done)

        # Make sure we ran over all the instances - verify if marker works
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 50)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

        for i in range(0, 5):
            _verify_list_fulfillment(self.context, self.instances[i].uuid)

    def test_migration_pre_newton_instance_new_vifs(self):
        """This test when instance was created before Newton
           but in meantime new interfaces where attached and
           VirtualInterfaceList is not populated.
        """
        self._create_instances(pre_newton=0, total=1)

        vif_list = objects.VirtualInterfaceList.get_by_instance_uuid(
            self.context, self.instances[0].uuid)
        # Drop first vif from list to pretend old instance
        vif_list[0].destroy()

        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        # The whole VirtualInterfaceList should be rewritten and base
        # on cache.
        self.assertEqual(1, match)
        self.assertEqual(1, done)

        _verify_list_fulfillment(self.context, self.instances[0].uuid)

    def test_migration_attach_in_progress(self):
        """This test when number of vifs (db) is bigger than
           number taken from network cache. Potential
           port-attach is taking place.
        """
        self._create_instances(pre_newton=0, total=1)
        instance_info_cache = objects.InstanceInfoCache.get_by_instance_uuid(
            self.context, self.instances[0].uuid)

        # Delete last interface to pretend that's still in progress
        instance_info_cache.network_info.pop()
        instance_info_cache.updated_at = datetime.datetime(2015, 1, 1)

        instance_info_cache.save()

        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        # I don't know whats going on so instance VirtualInterfaceList
        # should stay untouched.
        self.assertEqual(1, match)
        self.assertEqual(0, done)

    def test_migration_empty_network_info(self):
        """This test if migration is not executed while
           NetworkInfo is empty, like instance without
           interfaces attached.
        """
        self._create_instances(pre_newton=0, total=1)
        instance_info_cache = objects.InstanceInfoCache.get_by_instance_uuid(
            self.context, self.instances[0].uuid)

        # Clean NetworkInfo. Pretend instance without interfaces.
        instance_info_cache.network_info = None
        instance_info_cache.save()

        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        self.assertEqual(0, match)
        self.assertEqual(0, done)

    def test_migration_inconsistent_data(self):
        """This test when vif (db) are in completely different
           comparing to network cache and we don't know how to
           deal with it. It's the corner-case.
        """
        self._create_instances(pre_newton=0, total=1)
        instance_info_cache = objects.InstanceInfoCache.get_by_instance_uuid(
            self.context, self.instances[0].uuid)

        # Change order of interfaces in NetworkInfo to fake
        # inconsistency between cache and db.
        nwinfo = instance_info_cache.network_info
        interface = nwinfo.pop()
        nwinfo.insert(0, interface)
        instance_info_cache.updated_at = datetime.datetime(2015, 1, 1)
        instance_info_cache.network_info = nwinfo

        # Update the cache
        instance_info_cache.save()

        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 5)

        # Cache is corrupted, so must be rewritten
        self.assertEqual(1, match)
        self.assertEqual(1, done)

    def test_migration_dont_touch_deleted_objects(self):
        """This test if deleted instances are skipped
           during migration.
        """
        self._create_instances(
            pre_newton=1, deleted=1, total=3)

        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(2, match)
        self.assertEqual(1, done)

    def test_migration_multiple_cells(self):
        """This test if marker and max_rows limit works properly while
           running in multi-cell environment.
        """
        # Create 2 instances in cell0
        self._create_instances(
            pre_newton=1, total=2, target_cell=self.cells[0])
        # Create 4 instances in cell1
        self._create_instances(
            pre_newton=3, total=5, target_cell=self.cells[1])

        # Fill vif list limiting to 4 instances - it should
        # touch cell0 and cell1 instances (migrate 3 due 1 is post newton).
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(4, match)
        self.assertEqual(3, done)

        # Verify that the marker instance has project_id/user_id set properly.
        with context.target_cell(self.context, self.cells[1]) as cctxt:
            # The marker record is destroyed right after it's created, since
            # only the presence of the row is needed to satisfy the fkey
            # constraint.
            cctxt = cctxt.elevated(read_deleted='yes')
            marker_instance = objects.Instance.get_by_uuid(cctxt, FAKE_UUID)
        self.assertEqual(FAKE_UUID, marker_instance.project_id)
        self.assertEqual(FAKE_UUID, marker_instance.user_id)

        # Try again - should fill 3 left instances from cell1
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(3, match)
        self.assertEqual(1, done)

        # Try again - should be nothing to migrate
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

    def test_migration_multiple_cells_new_instances_in_meantime(self):
        """This test if marker is created per-cell and we're able to
           verify instanced that were added in meantime.
        """
        # Create 2 instances in cell0
        self._create_instances(
            pre_newton=1, total=2, target_cell=self.cells[0])
        # Create 2 instances in cell1
        self._create_instances(
            pre_newton=1, total=2, target_cell=self.cells[1])

        # Migrate instances in both cells.
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(4, match)
        self.assertEqual(2, done)

        # Add new instances to cell1
        self._create_instances(
            pre_newton=0, total=2, target_cell=self.cells[1])

        # Try again, should find instances in cell1
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(2, match)
        self.assertEqual(0, done)

        # Try again - should be nothing to migrate
        match, done = virtual_interface.fill_virtual_interface_list(
            self.context, 4)
        self.assertEqual(0, match)
        self.assertEqual(0, done)
