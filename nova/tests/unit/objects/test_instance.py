#    Copyright 2013 IBM Corp.
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

import datetime

import mock
from mox3 import mox
import netaddr
from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova.cells import rpcapi as cells_rpcapi
from nova.compute import flavors
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import notifications
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.objects import instance
from nova.objects import instance_info_cache
from nova.objects import pci_device
from nova.objects import security_group
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests.unit.objects import test_instance_numa_topology
from nova.tests.unit.objects import test_instance_pci_requests
from nova.tests.unit.objects import test_migration_context as test_mig_ctxt
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_security_group
from nova.tests.unit.objects import test_vcpu_model
from nova.tests import uuidsentinel as uuids
from nova import utils


class _TestInstanceObject(object):
    @property
    def fake_instance(self):
        db_inst = fake_instance.fake_db_instance(id=2,
                                                 access_ip_v4='1.2.3.4',
                                                 access_ip_v6='::1')
        db_inst['uuid'] = uuids.db_instance
        db_inst['cell_name'] = 'api!child'
        db_inst['terminated_at'] = None
        db_inst['deleted_at'] = None
        db_inst['created_at'] = None
        db_inst['updated_at'] = None
        db_inst['launched_at'] = datetime.datetime(1955, 11, 12,
                                                   22, 4, 0)
        db_inst['deleted'] = False
        db_inst['security_groups'] = []
        db_inst['pci_devices'] = []
        db_inst['user_id'] = self.context.user_id
        db_inst['project_id'] = self.context.project_id
        db_inst['tags'] = []

        db_inst['info_cache'] = dict(test_instance_info_cache.fake_info_cache,
                                     instance_uuid=db_inst['uuid'])

        db_inst['system_metadata'] = {
            'image_name': 'os2-warp',
            'image_min_ram': 100,
            'image_hw_disk_bus': 'ide',
            'image_hw_vif_model': 'ne2k_pci',
        }
        return db_inst

    def test_datetime_deserialization(self):
        red_letter_date = timeutils.parse_isotime(
            utils.isotime(datetime.datetime(1955, 11, 5)))
        inst = objects.Instance(uuid=uuids.instance,
                                launched_at=red_letter_date)
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': inst.VERSION,
                    'nova_object.data':
                        {'uuid': uuids.instance,
                         'launched_at': '1955-11-05T00:00:00Z'},
                    'nova_object.changes': ['launched_at', 'uuid']}
        self.assertJsonEqual(primitive, expected)
        inst2 = objects.Instance.obj_from_primitive(primitive)
        self.assertIsInstance(inst2.launched_at, datetime.datetime)
        self.assertEqual(red_letter_date, inst2.launched_at)

    def test_ip_deserialization(self):
        inst = objects.Instance(uuid=uuids.instance, access_ip_v4='1.2.3.4',
                                access_ip_v6='::1')
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': inst.VERSION,
                    'nova_object.data':
                        {'uuid': uuids.instance,
                         'access_ip_v4': '1.2.3.4',
                         'access_ip_v6': '::1'},
                    'nova_object.changes': ['uuid', 'access_ip_v6',
                                            'access_ip_v4']}
        self.assertJsonEqual(primitive, expected)
        inst2 = objects.Instance.obj_from_primitive(primitive)
        self.assertIsInstance(inst2.access_ip_v4, netaddr.IPAddress)
        self.assertIsInstance(inst2.access_ip_v6, netaddr.IPAddress)
        self.assertEqual(netaddr.IPAddress('1.2.3.4'), inst2.access_ip_v4)
        self.assertEqual(netaddr.IPAddress('::1'), inst2.access_ip_v6)

    def test_get_without_expected(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, 'uuid',
                                columns_to_join=[]
                                ).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, 'uuid',
                                             expected_attrs=[])
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertFalse(inst.obj_attr_is_set(attr))

    def test_get_with_expected(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        self.mox.StubOutWithMock(
                db, 'instance_extra_get_by_instance_uuid')

        exp_cols = instance.INSTANCE_OPTIONAL_ATTRS[:]
        exp_cols.remove('fault')
        exp_cols.remove('numa_topology')
        exp_cols.remove('pci_requests')
        exp_cols.remove('vcpu_model')
        exp_cols.remove('ec2_ids')
        exp_cols.remove('migration_context')
        exp_cols = list(filter(lambda x: 'flavor' not in x, exp_cols))
        exp_cols.extend(['extra', 'extra.numa_topology', 'extra.pci_requests',
                         'extra.flavor', 'extra.vcpu_model',
                         'extra.migration_context'])

        fake_topology = (test_instance_numa_topology.
                         fake_db_topology['numa_topology'])
        fake_requests = jsonutils.dumps(test_instance_pci_requests.
                                        fake_pci_requests)
        fake_flavor = jsonutils.dumps(
            {'cur': objects.Flavor().obj_to_primitive(),
             'old': None, 'new': None})
        fake_vcpu_model = jsonutils.dumps(
            test_vcpu_model.fake_vcpumodel.obj_to_primitive())
        fake_mig_context = jsonutils.dumps(
            test_mig_ctxt.fake_migration_context_obj.obj_to_primitive())
        fake_service = {'created_at': None, 'updated_at': None,
                        'deleted_at': None, 'deleted': False, 'id': 123,
                        'host': 'fake-host', 'binary': 'nova-fake',
                        'topic': 'fake-service-topic', 'report_count': 1,
                        'forced_down': False, 'disabled': False,
                        'disabled_reason': None, 'last_seen_up': None,
                        'version': 1,
                    }
        fake_instance = dict(self.fake_instance,
                             services=[fake_service],
                             extra={
                                 'numa_topology': fake_topology,
                                 'pci_requests': fake_requests,
                                 'flavor': fake_flavor,
                                 'vcpu_model': fake_vcpu_model,
                                 'migration_context': fake_mig_context,
                                 })
        db.instance_get_by_uuid(
            self.context, 'uuid',
            columns_to_join=exp_cols).AndReturn(fake_instance)
        fake_faults = test_instance_fault.fake_faults
        db.instance_fault_get_by_instance_uuids(
                self.context, [fake_instance['uuid']]
                ).AndReturn(fake_faults)

        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(
            self.context, 'uuid',
            expected_attrs=instance.INSTANCE_OPTIONAL_ATTRS)
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertTrue(inst.obj_attr_is_set(attr))
        self.assertEqual(123, inst.services[0].id)

    def test_lazy_load_services_on_deleted_instance(self):
        # We should avoid trying to hit the database to reload the instance
        # and just set the services attribute to an empty list.
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    deleted=True)
        self.assertEqual(0, len(instance.services))

    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'instance_get')
        db.instance_get(self.context, 'instid',
                        columns_to_join=['info_cache',
                                         'security_groups']
                        ).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_id(self.context, 'instid')
        self.assertEqual(self.fake_instance['uuid'], inst.uuid)

    def test_load(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(self.fake_instance)
        fake_inst2 = dict(self.fake_instance,
                          metadata=[{'key': 'foo', 'value': 'bar'}])
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['metadata']
                                ).AndReturn(fake_inst2)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertFalse(hasattr(inst, '_obj_metadata'))
        meta = inst.metadata
        self.assertEqual({'foo': 'bar'}, meta)
        self.assertTrue(hasattr(inst, '_obj_metadata'))
        # Make sure we don't run load again
        meta2 = inst.metadata
        self.assertEqual({'foo': 'bar'}, meta2)

    def test_load_invalid(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        self.assertRaises(exception.ObjectActionError,
                          inst.obj_load_attr, 'foo')

    def test_get_remote(self):
        # isotime doesn't have microseconds and is always UTC
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_instance = self.fake_instance
        db.instance_get_by_uuid(self.context, uuids.instance,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_instance)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, uuids.instance)
        self.assertEqual(fake_instance['id'], inst.id)
        self.assertEqual(fake_instance['launched_at'],
                         inst.launched_at.replace(tzinfo=None))
        self.assertEqual(fake_instance['access_ip_v4'],
                         str(inst.access_ip_v4))
        self.assertEqual(fake_instance['access_ip_v6'],
                         str(inst.access_ip_v6))

    def test_refresh(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(dict(self.fake_instance,
                                                 host='orig-host'))
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(dict(self.fake_instance,
                                                 host='new-host'))
        self.mox.StubOutWithMock(instance_info_cache.InstanceInfoCache,
                                 'refresh')
        instance_info_cache.InstanceInfoCache.refresh()
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual('orig-host', inst.host)
        inst.refresh()
        self.assertEqual('new-host', inst.host)
        self.assertEqual(set([]), inst.obj_what_changed())

    def test_refresh_does_not_recurse(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance,
                                metadata={})
        inst_copy = objects.Instance()
        inst_copy.uuid = inst.uuid
        self.mox.StubOutWithMock(objects.Instance, 'get_by_uuid')
        objects.Instance.get_by_uuid(self.context, uuid=inst.uuid,
                                     expected_attrs=['metadata'],
                                     use_slave=False
                                     ).AndReturn(inst_copy)
        self.mox.ReplayAll()
        self.assertRaises(exception.OrphanedObjectError, inst.refresh)

    def _save_test_helper(self, cell_type, save_kwargs):
        """Common code for testing save() for cells/non-cells."""
        if cell_type:
            self.flags(enable=True, cell_type=cell_type, group='cells')
        else:
            self.flags(enable=False, group='cells')

        old_ref = dict(self.fake_instance, host='oldhost', user_data='old',
                       vm_state='old', task_state='old')
        fake_uuid = old_ref['uuid']

        expected_updates = dict(vm_state='meow', task_state='wuff',
                                user_data='new')

        new_ref = dict(old_ref, host='newhost', **expected_updates)
        exp_vm_state = save_kwargs.get('expected_vm_state')
        exp_task_state = save_kwargs.get('expected_task_state')
        admin_reset = save_kwargs.get('admin_state_reset', False)
        if exp_vm_state:
            expected_updates['expected_vm_state'] = exp_vm_state
        if exp_task_state:
            if (exp_task_state == 'image_snapshot' and
                    'instance_version' in save_kwargs and
                    save_kwargs['instance_version'] == '1.9'):
                expected_updates['expected_task_state'] = [
                    'image_snapshot', 'image_snapshot_pending']
            else:
                expected_updates['expected_task_state'] = exp_task_state
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        cells_api_mock = self.mox.CreateMock(cells_rpcapi.CellsAPI)
        self.mox.StubOutWithMock(cells_api_mock,
                                 'instance_update_at_top')
        self.mox.StubOutWithMock(cells_api_mock,
                                 'instance_update_from_api')
        self.mox.StubOutWithMock(cells_rpcapi, 'CellsAPI',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(notifications, 'send_update')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(old_ref)
        db.instance_update_and_get_original(
                self.context, fake_uuid, expected_updates,
                columns_to_join=['info_cache', 'security_groups',
                                 'system_metadata', 'extra', 'extra.flavor']
                ).AndReturn((old_ref, new_ref))
        if cell_type == 'api':
            cells_rpcapi.CellsAPI().AndReturn(cells_api_mock)
            cells_api_mock.instance_update_from_api(
                    self.context, mox.IsA(objects.Instance),
                    exp_vm_state, exp_task_state, admin_reset)
        elif cell_type == 'compute':
            cells_rpcapi.CellsAPI().AndReturn(cells_api_mock)
            cells_api_mock.instance_update_at_top(self.context,
                                                  mox.IsA(objects.Instance))
        notifications.send_update(self.context, mox.IgnoreArg(),
                                  mox.IgnoreArg())

        self.mox.ReplayAll()

        inst = objects.Instance.get_by_uuid(self.context, old_ref['uuid'])
        if 'instance_version' in save_kwargs:
            inst.VERSION = save_kwargs.pop('instance_version')
        self.assertEqual('old', inst.task_state)
        self.assertEqual('old', inst.vm_state)
        self.assertEqual('old', inst.user_data)
        inst.vm_state = 'meow'
        inst.task_state = 'wuff'
        inst.user_data = 'new'
        save_kwargs.pop('context', None)
        inst.save(**save_kwargs)
        self.assertEqual('newhost', inst.host)
        self.assertEqual('meow', inst.vm_state)
        self.assertEqual('wuff', inst.task_state)
        self.assertEqual('new', inst.user_data)
        # NOTE(danms): Ignore flavor migrations for the moment
        self.assertEqual(set([]), inst.obj_what_changed() - set(['flavor']))

    def test_save(self):
        self._save_test_helper(None, {})

    def test_save_in_api_cell(self):
        self._save_test_helper('api', {})

    def test_save_in_compute_cell(self):
        self._save_test_helper('compute', {})

    def test_save_exp_vm_state(self):
        self._save_test_helper(None, {'expected_vm_state': ['meow']})

    def test_save_exp_task_state(self):
        self._save_test_helper(None, {'expected_task_state': ['meow']})

    def test_save_exp_vm_state_api_cell(self):
        self._save_test_helper('api', {'expected_vm_state': ['meow']})

    def test_save_exp_task_state_api_cell(self):
        self._save_test_helper('api', {'expected_task_state': ['meow']})

    def test_save_exp_task_state_api_cell_admin_reset(self):
        self._save_test_helper('api', {'admin_state_reset': True})

    def test_save_rename_sends_notification(self):
        # Tests that simply changing the 'display_name' on the instance
        # will send a notification.
        self.flags(enable=False, group='cells')
        old_ref = dict(self.fake_instance, display_name='hello')
        fake_uuid = old_ref['uuid']
        expected_updates = dict(display_name='goodbye')
        new_ref = dict(old_ref, **expected_updates)
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(notifications, 'send_update')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(old_ref)
        db.instance_update_and_get_original(
                self.context, fake_uuid, expected_updates,
                columns_to_join=['info_cache', 'security_groups',
                                 'system_metadata', 'extra', 'extra.flavor']
                ).AndReturn((old_ref, new_ref))
        notifications.send_update(self.context, mox.IgnoreArg(),
                                  mox.IgnoreArg())

        self.mox.ReplayAll()

        inst = objects.Instance.get_by_uuid(self.context, old_ref['uuid'],
                                            use_slave=False)
        self.assertEqual('hello', inst.display_name)
        inst.display_name = 'goodbye'
        inst.save()
        self.assertEqual('goodbye', inst.display_name)
        # NOTE(danms): Ignore flavor migrations for the moment
        self.assertEqual(set([]), inst.obj_what_changed() - set(['flavor']))

    def test_save_related_object_if_none(self):
        with mock.patch.object(objects.Instance, '_save_pci_requests'
                ) as save_mock:
            inst = objects.Instance()
            inst = objects.Instance._from_db_object(self.context, inst,
                    self.fake_instance)
            inst.pci_requests = None
            inst.save()
            self.assertTrue(save_mock.called)

    @mock.patch('nova.db.instance_update_and_get_original')
    @mock.patch.object(instance.Instance, '_from_db_object')
    def test_save_does_not_refresh_pci_devices(self, mock_fdo, mock_update):
        # NOTE(danms): This tests that we don't update the pci_devices
        # field from the contents of the database. This is not because we
        # don't necessarily want to, but because the way pci_devices is
        # currently implemented it causes versioning issues. When that is
        # resolved, this test should go away.
        mock_update.return_value = None, None
        inst = objects.Instance(context=self.context, id=123)
        inst.uuid = uuids.test_instance_not_refresh
        inst.pci_devices = pci_device.PciDeviceList()
        inst.save()
        self.assertNotIn('pci_devices',
                         mock_fdo.call_args_list[0][1]['expected_attrs'])

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    @mock.patch('nova.db.instance_update_and_get_original')
    @mock.patch.object(instance.Instance, '_from_db_object')
    def test_save_updates_numa_topology(self, mock_fdo, mock_update,
            mock_extra_update):
        fake_obj_numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0]), memory=128),
            objects.InstanceNUMACell(id=1, cpuset=set([1]), memory=128)])
        fake_obj_numa_topology.instance_uuid = uuids.instance
        jsonified = fake_obj_numa_topology._to_json()

        mock_update.return_value = None, None
        inst = objects.Instance(
            context=self.context, id=123, uuid=uuids.instance)
        inst.numa_topology = fake_obj_numa_topology
        inst.save()

        # NOTE(sdague): the json representation of nova object for
        # NUMA isn't stable from a string comparison
        # perspective. There are sets which get converted to lists,
        # and based on platform differences may show up in different
        # orders. So we can't have mock do the comparison. Instead
        # manually compare the final parameter using our json equality
        # operator which does the right thing here.
        mock_extra_update.assert_called_once_with(
            self.context, inst.uuid, mock.ANY)
        called_arg = mock_extra_update.call_args_list[0][0][2]['numa_topology']
        self.assertJsonEqual(called_arg, jsonified)

        mock_extra_update.reset_mock()
        inst.numa_topology = None
        inst.save()
        mock_extra_update.assert_called_once_with(
                self.context, inst.uuid, {'numa_topology': None})

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    def test_save_vcpu_model(self, mock_update):
        inst = fake_instance.fake_instance_obj(self.context)
        inst.vcpu_model = test_vcpu_model.fake_vcpumodel
        inst.save()
        self.assertTrue(mock_update.called)
        self.assertEqual(1, mock_update.call_count)
        actual_args = mock_update.call_args
        self.assertEqual(self.context, actual_args[0][0])
        self.assertEqual(inst.uuid, actual_args[0][1])
        self.assertEqual(['vcpu_model'], list(actual_args[0][2].keys()))
        self.assertJsonEqual(jsonutils.dumps(
                test_vcpu_model.fake_vcpumodel.obj_to_primitive()),
                             actual_args[0][2]['vcpu_model'])
        mock_update.reset_mock()
        inst.vcpu_model = None
        inst.save()
        mock_update.assert_called_once_with(
            self.context, inst.uuid, {'vcpu_model': None})

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    def test_save_migration_context_model(self, mock_update):
        inst = fake_instance.fake_instance_obj(self.context)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        inst.save()
        self.assertTrue(mock_update.called)
        self.assertEqual(1, mock_update.call_count)
        actual_args = mock_update.call_args
        self.assertEqual(self.context, actual_args[0][0])
        self.assertEqual(inst.uuid, actual_args[0][1])
        self.assertEqual(['migration_context'], list(actual_args[0][2].keys()))
        self.assertIsInstance(
            objects.MigrationContext.obj_from_db_obj(
                actual_args[0][2]['migration_context']),
            objects.MigrationContext)
        mock_update.reset_mock()
        inst.migration_context = None
        inst.save()
        mock_update.assert_called_once_with(
            self.context, inst.uuid, {'migration_context': None})

    def test_save_flavor_skips_unchanged_flavors(self):
        inst = objects.Instance(context=self.context,
                                flavor=objects.Flavor())
        inst.obj_reset_changes()
        with mock.patch('nova.db.instance_extra_update_by_uuid') as mock_upd:
            inst.save()
            self.assertFalse(mock_upd.called)

    @mock.patch.object(notifications, 'send_update')
    @mock.patch.object(cells_rpcapi.CellsAPI, 'instance_update_from_api')
    @mock.patch.object(cells_rpcapi.CellsAPI, 'instance_update_at_top')
    @mock.patch.object(db, 'instance_update_and_get_original')
    def _test_skip_cells_sync_helper(self, mock_db_update, mock_update_at_top,
            mock_update_from_api, mock_notif_update, cell_type):
        self.flags(enable=True, cell_type=cell_type, group='cells')
        inst = fake_instance.fake_instance_obj(self.context, cell_name='fake')
        inst.vm_state = 'foo'
        inst.task_state = 'bar'
        inst.cell_name = 'foo!bar@baz'

        old_ref = dict(base.obj_to_primitive(inst), vm_state='old',
                task_state='old')
        new_ref = dict(old_ref, vm_state='foo', task_state='bar')
        newer_ref = dict(new_ref, vm_state='bar', task_state='foo')
        mock_db_update.side_effect = [(old_ref, new_ref), (new_ref, newer_ref)]

        with inst.skip_cells_sync():
            inst.save()

        mock_update_at_top.assert_has_calls([])
        mock_update_from_api.assert_has_calls([])
        self.assertFalse(mock_notif_update.called)

        inst.vm_state = 'bar'
        inst.task_state = 'foo'

        def fake_update_from_api(context, instance, expected_vm_state,
                expected_task_state, admin_state_reset):
            self.assertEqual('foo!bar@baz', instance.cell_name)

        # This is re-mocked so that cell_name can be checked above.  Since
        # instance objects have no equality testing assert_called_once_with
        # doesn't work.
        with mock.patch.object(cells_rpcapi.CellsAPI,
                'instance_update_from_api',
                side_effect=fake_update_from_api) as fake_update_from_api:
            inst.save()

        self.assertEqual('foo!bar@baz', inst.cell_name)
        self.assertTrue(mock_notif_update.called)
        if cell_type == 'compute':
            mock_update_at_top.assert_called_once_with(self.context, mock.ANY)
            # Compare primitives since we can't check instance object equality
            expected_inst_p = base.obj_to_primitive(inst)
            actual_inst = mock_update_at_top.call_args[0][1]
            actual_inst_p = base.obj_to_primitive(actual_inst)
            self.assertEqual(expected_inst_p, actual_inst_p)
            self.assertFalse(fake_update_from_api.called)
        elif cell_type == 'api':
            self.assertFalse(mock_update_at_top.called)
            fake_update_from_api.assert_called_once_with(self.context,
                    mock.ANY, None, None, False)

        expected_calls = [
                mock.call(self.context, inst.uuid,
                    {'vm_state': 'foo', 'task_state': 'bar',
                     'cell_name': 'foo!bar@baz'},
                    columns_to_join=['system_metadata', 'extra',
                        'extra.flavor']),
                mock.call(self.context, inst.uuid,
                    {'vm_state': 'bar', 'task_state': 'foo'},
                    columns_to_join=['system_metadata'])]
        mock_db_update.assert_has_calls(expected_calls)

    def test_skip_cells_api(self):
        self._test_skip_cells_sync_helper(cell_type='api')

    def test_skip_cells_compute(self):
        self._test_skip_cells_sync_helper(cell_type='compute')

    def test_get_deleted(self):
        fake_inst = dict(self.fake_instance, id=123, deleted=123)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(danms): Make sure it's actually a bool
        self.assertTrue(inst.deleted)

    def test_get_not_cleaned(self):
        fake_inst = dict(self.fake_instance, id=123, cleaned=None)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertFalse(inst.cleaned)

    def test_get_cleaned(self):
        fake_inst = dict(self.fake_instance, id=123, cleaned=1)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertTrue(inst.cleaned)

    def test_with_info_cache(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        nwinfo1 = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        nwinfo2 = network_model.NetworkInfo.hydrate([{'address': 'bar'}])
        nwinfo1_json = nwinfo1.json()
        nwinfo2_json = nwinfo2.json()
        fake_info_cache = test_instance_info_cache.fake_info_cache
        fake_inst['info_cache'] = dict(
            fake_info_cache,
            network_info=nwinfo1_json,
            instance_uuid=fake_uuid)
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        db.instance_info_cache_update(self.context, fake_uuid,
                {'network_info': nwinfo2_json}).AndReturn(fake_info_cache)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(nwinfo1, inst.info_cache.network_info)
        self.assertEqual(fake_uuid, inst.info_cache.instance_uuid)
        inst.info_cache.network_info = nwinfo2
        inst.save()

    def test_with_info_cache_none(self):
        fake_inst = dict(self.fake_instance, info_cache=None)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
                                             ['info_cache'])
        self.assertIsNone(inst.info_cache)

    def test_with_security_groups(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_inst['security_groups'] = [
            {'id': 1, 'name': 'secgroup1', 'description': 'fake-desc',
             'user_id': 'fake-user', 'project_id': 'fake_project',
             'created_at': None, 'updated_at': None, 'deleted_at': None,
             'deleted': False},
            {'id': 2, 'name': 'secgroup2', 'description': 'fake-desc',
             'user_id': 'fake-user', 'project_id': 'fake_project',
             'created_at': None, 'updated_at': None, 'deleted_at': None,
             'deleted': False},
            ]
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'security_group_update')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        db.security_group_update(self.context, 1, {'description': 'changed'}
                                 ).AndReturn(fake_inst['security_groups'][0])
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(2, len(inst.security_groups))
        for index, group in enumerate(fake_inst['security_groups']):
            for key in group:
                self.assertEqual(group[key],
                                 inst.security_groups[index][key])
                self.assertIsInstance(inst.security_groups[index],
                                      security_group.SecurityGroup)
        self.assertEqual(set(), inst.security_groups.obj_what_changed())
        inst.security_groups[0].description = 'changed'
        inst.save()
        self.assertEqual(set(), inst.security_groups.obj_what_changed())

    def test_with_empty_security_groups(self):
        fake_inst = dict(self.fake_instance, security_groups=[])
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(0, len(inst.security_groups))

    def test_with_empty_pci_devices(self):
        fake_inst = dict(self.fake_instance, pci_devices=[])
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['pci_devices']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(0, len(inst.pci_devices))

    def test_with_pci_devices(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_inst['pci_devices'] = [
            {'created_at': None,
             'updated_at': None,
             'deleted_at': None,
             'deleted': None,
             'id': 2,
             'compute_node_id': 1,
             'address': 'a1',
             'vendor_id': 'v1',
             'numa_node': 0,
             'product_id': 'p1',
             'dev_type': fields.PciDeviceType.STANDARD,
             'status': fields.PciDeviceStatus.ALLOCATED,
             'dev_id': 'i',
             'label': 'l',
             'instance_uuid': fake_uuid,
             'request_id': None,
             'parent_addr': None,
             'extra_info': '{}'},
            {
             'created_at': None,
             'updated_at': None,
             'deleted_at': None,
             'deleted': None,
             'id': 1,
             'compute_node_id': 1,
             'address': 'a',
             'vendor_id': 'v',
             'numa_node': 1,
             'product_id': 'p',
             'dev_type': fields.PciDeviceType.STANDARD,
             'status': fields.PciDeviceStatus.ALLOCATED,
             'dev_id': 'i',
             'label': 'l',
             'instance_uuid': fake_uuid,
             'request_id': None,
             'parent_addr': 'a1',
             'extra_info': '{}'},
            ]
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['pci_devices']
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(2, len(inst.pci_devices))
        self.assertEqual(fake_uuid, inst.pci_devices[0].instance_uuid)
        self.assertEqual(fake_uuid, inst.pci_devices[1].instance_uuid)

    def test_with_fault(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_faults = [dict(x, instance_uuid=fake_uuid)
                       for x in test_instance_fault.fake_faults['fake-uuid']]
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=[]
                                ).AndReturn(self.fake_instance)
        db.instance_fault_get_by_instance_uuids(
            self.context, [fake_uuid]).AndReturn({fake_uuid: fake_faults})
        self.mox.ReplayAll()
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
                                            expected_attrs=['fault'])
        self.assertEqual(fake_faults[0], dict(inst.fault.items()))

    @mock.patch('nova.objects.EC2Ids.get_by_instance')
    @mock.patch('nova.db.instance_get_by_uuid')
    def test_with_ec2_ids(self, mock_get, mock_ec2):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst
        fake_ec2_ids = objects.EC2Ids(instance_id='fake-inst',
                                      ami_id='fake-ami')
        mock_ec2.return_value = fake_ec2_ids
        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
                                            expected_attrs=['ec2_ids'])
        mock_ec2.assert_called_once_with(self.context, mock.ANY)

        self.assertEqual(fake_ec2_ids.instance_id, inst.ec2_ids.instance_id)

    @mock.patch('nova.db.instance_get_by_uuid')
    def test_with_image_meta(self, mock_get):
        fake_inst = dict(self.fake_instance)
        mock_get.return_value = fake_inst

        inst = instance.Instance.get_by_uuid(self.context,
                                             fake_inst['uuid'],
                                             expected_attrs=['image_meta'])

        image_meta = inst.image_meta
        self.assertIsInstance(image_meta, objects.ImageMeta)
        self.assertEqual(100, image_meta.min_ram)
        self.assertEqual('ide', image_meta.properties.hw_disk_bus)
        self.assertEqual('ne2k_pci', image_meta.properties.hw_vif_model)

    def test_iteritems_with_extra_attrs(self):
        self.stubs.Set(objects.Instance, 'name', 'foo')
        inst = objects.Instance(uuid=uuids.instance)
        self.assertEqual(sorted({'uuid': uuids.instance,
                                 'name': 'foo',
                                }.items()), sorted(inst.items()))

    def _test_metadata_change_tracking(self, which):
        inst = objects.Instance(uuid=uuids.instance)
        setattr(inst, which, {})
        inst.obj_reset_changes()
        getattr(inst, which)['foo'] = 'bar'
        self.assertEqual(set([which]), inst.obj_what_changed())
        inst.obj_reset_changes()
        self.assertEqual(set(), inst.obj_what_changed())

    def test_create_skip_scheduled_at(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        vals = {'host': 'foo-host',
                'memory_mb': 128,
                'system_metadata': {'foo': 'bar'},
                'extra': {
                    'vcpu_model': None,
                    'numa_topology': None,
                    'pci_requests': None,
                }}
        fake_inst = fake_instance.fake_db_instance(**vals)
        db.instance_create(self.context, vals).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance(context=self.context,
                                host='foo-host', memory_mb=128,
                                scheduled_at=None,
                                system_metadata={'foo': 'bar'})
        inst.create()
        self.assertEqual('foo-host', inst.host)

    def test_metadata_change_tracking(self):
        self._test_metadata_change_tracking('metadata')

    def test_system_metadata_change_tracking(self):
        self._test_metadata_change_tracking('system_metadata')

    def test_create_stubbed(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        vals = {'host': 'foo-host',
                'memory_mb': 128,
                'system_metadata': {'foo': 'bar'},
                'extra': {
                    'vcpu_model': None,
                    'numa_topology': None,
                    'pci_requests': None,
                }}
        fake_inst = fake_instance.fake_db_instance(**vals)
        db.instance_create(self.context, vals).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance(context=self.context,
                                host='foo-host', memory_mb=128,
                                system_metadata={'foo': 'bar'})
        inst.create()

    def test_create(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        extras = {'vcpu_model': None,
                  'numa_topology': None,
                  'pci_requests': None}
        db.instance_create(self.context, {'extra': extras}).AndReturn(
            self.fake_instance)
        self.mox.ReplayAll()
        inst = objects.Instance(context=self.context)
        inst.create()
        self.assertEqual(self.fake_instance['id'], inst.id)
        self.assertIsNotNone(inst.ec2_ids)

    def test_create_with_values(self):
        inst1 = objects.Instance(context=self.context,
                                 user_id=self.context.user_id,
                                 project_id=self.context.project_id,
                                 host='foo-host')
        inst1.create()
        self.assertEqual('foo-host', inst1.host)
        inst2 = objects.Instance.get_by_uuid(self.context, inst1.uuid)
        self.assertEqual('foo-host', inst2.host)

    def test_create_with_extras(self):
        inst = objects.Instance(context=self.context,
            uuid=self.fake_instance['uuid'],
            numa_topology=test_instance_numa_topology.fake_obj_numa_topology,
            pci_requests=objects.InstancePCIRequests(
                requests=[
                    objects.InstancePCIRequest(count=123,
                                               spec=[])]),
            vcpu_model=test_vcpu_model.fake_vcpumodel,
            )
        inst.create()
        self.assertIsNotNone(inst.numa_topology)
        self.assertIsNotNone(inst.pci_requests)
        self.assertEqual(1, len(inst.pci_requests.requests))
        self.assertIsNotNone(inst.vcpu_model)
        got_numa_topo = objects.InstanceNUMATopology.get_by_instance_uuid(
            self.context, inst.uuid)
        self.assertEqual(inst.numa_topology.instance_uuid,
                         got_numa_topo.instance_uuid)
        got_pci_requests = objects.InstancePCIRequests.get_by_instance_uuid(
            self.context, inst.uuid)
        self.assertEqual(123, got_pci_requests.requests[0].count)
        vcpu_model = objects.VirtCPUModel.get_by_instance_uuid(
            self.context, inst.uuid)
        self.assertEqual('fake-model', vcpu_model.model)

    def test_recreate_fails(self):
        inst = objects.Instance(context=self.context,
                                user_id=self.context.user_id,
                                project_id=self.context.project_id,
                                host='foo-host')
        inst.create()
        self.assertRaises(exception.ObjectActionError, inst.create)

    def test_create_with_special_things(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        fake_inst = fake_instance.fake_db_instance()
        db.instance_create(self.context,
                           {'host': 'foo-host',
                            'security_groups': ['foo', 'bar'],
                            'info_cache': {'network_info': '[]'},
                            'extra': {
                                'vcpu_model': None,
                                'numa_topology': None,
                                'pci_requests': None,
                            },
                            }
                           ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        secgroups = security_group.SecurityGroupList()
        secgroups.objects = []
        for name in ('foo', 'bar'):
            secgroup = security_group.SecurityGroup()
            secgroup.name = name
            secgroups.objects.append(secgroup)
        info_cache = instance_info_cache.InstanceInfoCache()
        info_cache.network_info = network_model.NetworkInfo()
        inst = objects.Instance(context=self.context,
                                host='foo-host', security_groups=secgroups,
                                info_cache=info_cache)
        inst.create()

    def test_destroy_stubbed(self):
        self.mox.StubOutWithMock(db, 'instance_destroy')
        deleted_at = datetime.datetime(1955, 11, 6)
        fake_inst = fake_instance.fake_db_instance(deleted_at=deleted_at,
                                                   deleted=True)
        db.instance_destroy(self.context, uuids.instance,
                            constraint=None).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = objects.Instance(context=self.context, id=1,
                                uuid=uuids.instance, host='foo')
        inst.destroy()
        self.assertEqual(timeutils.normalize_time(deleted_at),
                         timeutils.normalize_time(inst.deleted_at))
        self.assertTrue(inst.deleted)

    def test_destroy(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id}
        db_inst = db.instance_create(self.context, values)
        inst = objects.Instance(context=self.context, id=db_inst['id'],
                                 uuid=db_inst['uuid'])
        inst.destroy()
        self.assertRaises(exception.InstanceNotFound,
                          db.instance_get_by_uuid, self.context,
                          db_inst['uuid'])

    def test_destroy_host_constraint(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id,
                  'host': 'foo'}
        db_inst = db.instance_create(self.context, values)
        inst = objects.Instance.get_by_uuid(self.context, db_inst['uuid'])
        inst.host = None
        self.assertRaises(exception.ObjectActionError,
                          inst.destroy)

    @mock.patch.object(cells_rpcapi.CellsAPI, 'instance_destroy_at_top')
    @mock.patch.object(db, 'instance_destroy')
    def test_destroy_cell_sync_to_top(self, mock_destroy, mock_destroy_at_top):
        self.flags(enable=True, cell_type='compute', group='cells')
        fake_inst = fake_instance.fake_db_instance(deleted=True)
        mock_destroy.return_value = fake_inst
        inst = objects.Instance(context=self.context, id=1,
                                uuid=uuids.instance)
        inst.destroy()
        mock_destroy_at_top.assert_called_once_with(self.context, mock.ANY)
        actual_inst = mock_destroy_at_top.call_args[0][1]
        self.assertIsInstance(actual_inst, instance.Instance)

    @mock.patch.object(cells_rpcapi.CellsAPI, 'instance_destroy_at_top')
    @mock.patch.object(db, 'instance_destroy')
    def test_destroy_no_cell_sync_to_top(self, mock_destroy,
                                         mock_destroy_at_top):
        fake_inst = fake_instance.fake_db_instance(deleted=True)
        mock_destroy.return_value = fake_inst
        inst = objects.Instance(context=self.context, id=1,
                                uuid=uuids.instance)
        inst.destroy()
        self.assertFalse(mock_destroy_at_top.called)

    def test_name_does_not_trigger_lazy_loads(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id,
                  'host': 'foo'}
        db_inst = db.instance_create(self.context, values)
        inst = objects.Instance.get_by_uuid(self.context, db_inst['uuid'])
        self.assertFalse(inst.obj_attr_is_set('fault'))
        self.flags(instance_name_template='foo-%(uuid)s')
        self.assertEqual('foo-%s' % db_inst['uuid'], inst.name)
        self.assertFalse(inst.obj_attr_is_set('fault'))

    def test_from_db_object_not_overwrite_info_cache(self):
        info_cache = instance_info_cache.InstanceInfoCache()
        inst = objects.Instance(context=self.context,
                                info_cache=info_cache)
        db_inst = fake_instance.fake_db_instance()
        db_inst['info_cache'] = dict(
            test_instance_info_cache.fake_info_cache)
        inst._from_db_object(self.context, inst, db_inst,
                             expected_attrs=['info_cache'])
        self.assertIs(info_cache, inst.info_cache)

    def test_from_db_object_info_cache_not_set(self):
        inst = instance.Instance(context=self.context,
                                 info_cache=None)
        db_inst = fake_instance.fake_db_instance()
        db_inst.pop('info_cache')
        inst._from_db_object(self.context, inst, db_inst,
                             expected_attrs=['info_cache'])
        self.assertIsNone(inst.info_cache)

    def test_from_db_object_security_groups_net_set(self):
        inst = instance.Instance(context=self.context,
                                 info_cache=None)
        db_inst = fake_instance.fake_db_instance()
        db_inst.pop('security_groups')
        inst._from_db_object(self.context, inst, db_inst,
                             expected_attrs=['security_groups'])
        self.assertEqual([], inst.security_groups.objects)

    @mock.patch('nova.objects.InstancePCIRequests.get_by_instance_uuid')
    def test_get_with_pci_requests(self, mock_get):
        mock_get.return_value = objects.InstancePCIRequests()
        db_instance = db.instance_create(self.context, {
            'user_id': self.context.user_id,
            'project_id': self.context.project_id})
        instance = objects.Instance.get_by_uuid(
            self.context, db_instance['uuid'],
            expected_attrs=['pci_requests'])
        self.assertTrue(instance.obj_attr_is_set('pci_requests'))
        self.assertIsNotNone(instance.pci_requests)

    def test_get_flavor(self):
        db_flavor = flavors.get_default_flavor()
        inst = objects.Instance(flavor=db_flavor)
        self.assertEqual(db_flavor['flavorid'],
                         inst.get_flavor().flavorid)

    def test_get_flavor_namespace(self):
        db_flavor = flavors.get_default_flavor()
        inst = objects.Instance(old_flavor=db_flavor)
        self.assertEqual(db_flavor['flavorid'],
                         inst.get_flavor('old').flavorid)

    @mock.patch.object(db, 'instance_metadata_delete')
    def test_delete_metadata_key(self, db_delete):
        inst = objects.Instance(context=self.context,
                                id=1, uuid=uuids.instance)
        inst.metadata = {'foo': '1', 'bar': '2'}
        inst.obj_reset_changes()
        inst.delete_metadata_key('foo')
        self.assertEqual({'bar': '2'}, inst.metadata)
        self.assertEqual({}, inst.obj_get_changes())
        db_delete.assert_called_once_with(self.context, inst.uuid, 'foo')

    def test_reset_changes(self):
        inst = objects.Instance()
        inst.metadata = {'1985': 'present'}
        inst.system_metadata = {'1955': 'past'}
        self.assertEqual({}, inst._orig_metadata)
        inst.obj_reset_changes(['metadata'])
        self.assertEqual({'1985': 'present'}, inst._orig_metadata)
        self.assertEqual({}, inst._orig_system_metadata)

    def test_load_generic_calls_handler(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(inst, '_load_generic') as mock_load:
            def fake_load(name):
                inst.system_metadata = {}

            mock_load.side_effect = fake_load
            inst.system_metadata
            mock_load.assert_called_once_with('system_metadata')

    def test_load_fault_calls_handler(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(inst, '_load_fault') as mock_load:
            def fake_load():
                inst.fault = None

            mock_load.side_effect = fake_load
            inst.fault
            mock_load.assert_called_once_with()

    def test_load_ec2_ids_calls_handler(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(inst, '_load_ec2_ids') as mock_load:
            def fake_load():
                inst.ec2_ids = objects.EC2Ids(instance_id='fake-inst',
                                              ami_id='fake-ami')

            mock_load.side_effect = fake_load
            inst.ec2_ids
            mock_load.assert_called_once_with()

    def test_load_migration_context(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(
                objects.MigrationContext, 'get_by_instance_uuid',
                return_value=test_mig_ctxt.fake_migration_context_obj
        ) as mock_get:
            inst.migration_context
            mock_get.assert_called_once_with(self.context, inst.uuid)

    def test_load_migration_context_no_context(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(
                objects.MigrationContext, 'get_by_instance_uuid',
            side_effect=exception.MigrationContextNotFound(
                instance_uuid=inst.uuid)
        ) as mock_get:
            mig_ctxt = inst.migration_context
            mock_get.assert_called_once_with(self.context, inst.uuid)
            self.assertIsNone(mig_ctxt)

    def test_load_migration_context_no_data(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        with mock.patch.object(
                objects.MigrationContext, 'get_by_instance_uuid') as mock_get:
            loaded_ctxt = inst._load_migration_context(db_context=None)
            self.assertFalse(mock_get.called)
            self.assertIsNone(loaded_ctxt)

    def test_apply_revert_migration_context(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance,
                                 numa_topology=None)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        inst.apply_migration_context()
        self.assertIsInstance(inst.numa_topology, objects.InstanceNUMATopology)
        inst.revert_migration_context()
        self.assertIsNone(inst.numa_topology)

    def test_drop_migration_context(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        inst.migration_context.instance_uuid = inst.uuid
        inst.migration_context.id = 7
        with mock.patch(
                'nova.db.instance_extra_update_by_uuid') as update_extra:
            inst.drop_migration_context()
            self.assertIsNone(inst.migration_context)
            update_extra.assert_called_once_with(self.context, inst.uuid,
                                                 {"migration_context": None})

    def test_mutated_migration_context(self):
        numa_topology = (test_instance_numa_topology.
                            fake_obj_numa_topology.obj_clone())
        numa_topology.cells[0].memory = 1024
        numa_topology.cells[1].memory = 1024

        inst = instance.Instance(context=self.context, uuid=uuids.instance,
                                 numa_topology=numa_topology)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        with inst.mutated_migration_context():
            self.assertIs(inst.numa_topology,
                          inst.migration_context.new_numa_topology)
        self.assertIs(numa_topology, inst.numa_topology)

    def test_clear_numa_topology(self):
        numa_topology = (test_instance_numa_topology.
                            fake_obj_numa_topology.obj_clone())
        numa_topology.cells[0].id = 42
        numa_topology.cells[1].id = 43

        inst = instance.Instance(context=self.context, uuid=uuids.instance,
                                 numa_topology=numa_topology)
        inst.obj_reset_changes()
        inst.clear_numa_topology()
        self.assertIn('numa_topology', inst.obj_what_changed())
        self.assertEqual(-1, numa_topology.cells[0].id)
        self.assertEqual(-1, numa_topology.cells[1].id)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_load_generic(self, mock_get):
        inst2 = instance.Instance(metadata={'foo': 'bar'})
        mock_get.return_value = inst2
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        inst.metadata

    @mock.patch('nova.db.instance_fault_get_by_instance_uuids')
    def test_load_fault(self, mock_get):
        fake_fault = test_instance_fault.fake_faults['fake-uuid'][0]
        mock_get.return_value = {uuids.load_fault_instance: [fake_fault]}
        inst = objects.Instance(context=self.context,
                                uuid=uuids.load_fault_instance)
        fault = inst.fault
        mock_get.assert_called_once_with(self.context,
                                         [uuids.load_fault_instance])
        self.assertEqual(fake_fault['id'], fault.id)
        self.assertNotIn('metadata', inst.obj_what_changed())

    @mock.patch('nova.objects.EC2Ids.get_by_instance')
    def test_load_ec2_ids(self, mock_get):
        fake_ec2_ids = objects.EC2Ids(instance_id='fake-inst',
                                      ami_id='fake-ami')
        mock_get.return_value = fake_ec2_ids
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        ec2_ids = inst.ec2_ids
        mock_get.assert_called_once_with(self.context, inst)
        self.assertEqual(fake_ec2_ids, ec2_ids)

    @mock.patch('nova.objects.SecurityGroupList.get_by_instance')
    def test_load_security_groups(self, mock_get):
        secgroups = []
        for name in ('foo', 'bar'):
            secgroup = security_group.SecurityGroup()
            secgroup.name = name
            secgroups.append(secgroup)
        fake_secgroups = security_group.SecurityGroupList(objects=secgroups)
        mock_get.return_value = fake_secgroups
        inst = objects.Instance(context=self.context, uuid='fake')
        secgroups = inst.security_groups
        mock_get.assert_called_once_with(self.context, inst)
        self.assertEqual(fake_secgroups, secgroups)

    @mock.patch('nova.objects.PciDeviceList.get_by_instance_uuid')
    def test_load_pci_devices(self, mock_get):
        fake_pci_devices = pci_device.PciDeviceList()
        mock_get.return_value = fake_pci_devices
        inst = objects.Instance(context=self.context, uuid=uuids.pci_devices)
        pci_devices = inst.pci_devices
        mock_get.assert_called_once_with(self.context, uuids.pci_devices)
        self.assertEqual(fake_pci_devices, pci_devices)

    def test_get_with_extras(self):
        pci_requests = objects.InstancePCIRequests(requests=[
            objects.InstancePCIRequest(count=123, spec=[])])
        inst = objects.Instance(context=self.context,
                                user_id=self.context.user_id,
                                project_id=self.context.project_id,
                                pci_requests=pci_requests)
        inst.create()
        uuid = inst.uuid
        inst = objects.Instance.get_by_uuid(self.context, uuid)
        self.assertFalse(inst.obj_attr_is_set('pci_requests'))
        inst = objects.Instance.get_by_uuid(
            self.context, uuid, expected_attrs=['pci_requests'])
        self.assertTrue(inst.obj_attr_is_set('pci_requests'))


class TestInstanceObject(test_objects._LocalTest,
                         _TestInstanceObject):
    def _test_save_objectfield_fk_constraint_fails(self, foreign_key,
                                                   expected_exception):
        # NOTE(danms): Do this here and not in the remote test because
        # we're mocking out obj_attr_is_set() without the thing actually
        # being set, which confuses the heck out of the serialization
        # stuff.
        error = db_exc.DBReferenceError('table', 'constraint', foreign_key,
                                        'key_table')
        # Prevent lazy-loading any fields, results in InstanceNotFound
        attrs = objects.instance.INSTANCE_OPTIONAL_ATTRS
        instance = fake_instance.fake_instance_obj(self.context,
                                                   expected_attrs=attrs)
        fields_with_save_methods = [field for field in instance.fields
                                    if hasattr(instance, '_save_%s' % field)]
        for field in fields_with_save_methods:
            @mock.patch.object(instance, '_save_%s' % field)
            @mock.patch.object(instance, 'obj_attr_is_set')
            def _test(mock_is_set, mock_save_field):
                mock_is_set.return_value = True
                mock_save_field.side_effect = error
                instance.obj_reset_changes(fields=[field])
                instance._changed_fields.add(field)
                self.assertRaises(expected_exception, instance.save)
                instance.obj_reset_changes(fields=[field])
            _test()

    def test_save_objectfield_missing_instance_row(self):
        self._test_save_objectfield_fk_constraint_fails(
                'instance_uuid', exception.InstanceNotFound)

    def test_save_objectfield_reraises_if_not_instance_related(self):
        self._test_save_objectfield_fk_constraint_fails(
                'other_foreign_key', db_exc.DBReferenceError)


class TestRemoteInstanceObject(test_objects._RemoteTest,
                               _TestInstanceObject):
    pass


class _TestInstanceListObject(object):
    def fake_instance(self, id, updates=None):
        db_inst = fake_instance.fake_db_instance(id=2,
                                                 access_ip_v4='1.2.3.4',
                                                 access_ip_v6='::1')
        db_inst['terminated_at'] = None
        db_inst['deleted_at'] = None
        db_inst['created_at'] = None
        db_inst['updated_at'] = None
        db_inst['launched_at'] = datetime.datetime(1955, 11, 12,
                                                   22, 4, 0)
        db_inst['security_groups'] = []
        db_inst['deleted'] = 0

        db_inst['info_cache'] = dict(test_instance_info_cache.fake_info_cache,
                                     instance_uuid=db_inst['uuid'])

        if updates:
            db_inst.update(updates)
        return db_inst

    def test_get_all_by_filters(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, {'foo': 'bar'}, 'uuid',
                                       'asc', limit=None, marker=None,
                                       columns_to_join=['metadata']
                                       ).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    def test_get_all_by_filters_sorted(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters_sort')
        db.instance_get_all_by_filters_sort(self.context, {'foo': 'bar'},
                                            limit=None, marker=None,
                                            columns_to_join=['metadata'],
                                            sort_keys=['uuid'],
                                            sort_dirs=['asc']).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, expected_attrs=['metadata'],
            use_slave=False, sort_keys=['uuid'], sort_dirs=['asc'])

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    @mock.patch.object(db, 'instance_get_all_by_filters_sort')
    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters_calls_non_sort(self,
                                               mock_get_by_filters,
                                               mock_get_by_filters_sort):
        '''Verifies InstanceList.get_by_filters calls correct DB function.'''
        # Single sort key/direction is set, call non-sorted DB function
        objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, sort_key='key', sort_dir='dir',
            limit=100, marker='uuid', use_slave=True)
        mock_get_by_filters.assert_called_once_with(
            self.context, {'foo': 'bar'}, 'key', 'dir', limit=100,
            marker='uuid', columns_to_join=None)
        self.assertEqual(0, mock_get_by_filters_sort.call_count)

    @mock.patch.object(db, 'instance_get_all_by_filters_sort')
    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters_calls_sort(self,
                                           mock_get_by_filters,
                                           mock_get_by_filters_sort):
        '''Verifies InstanceList.get_by_filters calls correct DB function.'''
        # Multiple sort keys/directions are set, call sorted DB function
        objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, limit=100, marker='uuid',
            use_slave=True, sort_keys=['key1', 'key2'],
            sort_dirs=['dir1', 'dir2'])
        mock_get_by_filters_sort.assert_called_once_with(
            self.context, {'foo': 'bar'}, limit=100,
            marker='uuid', columns_to_join=None,
            sort_keys=['key1', 'key2'], sort_dirs=['dir1', 'dir2'])
        self.assertEqual(0, mock_get_by_filters.call_count)

    def test_get_all_by_filters_works_for_cleaned(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2, updates={'deleted': 2,
                                                'cleaned': None})]
        self.context.read_deleted = 'yes'
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context,
                                       {'deleted': True, 'cleaned': False},
                                       'uuid', 'asc', limit=None, marker=None,
                                       columns_to_join=['metadata']).AndReturn(
                                           [fakes[1]])
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'deleted': True, 'cleaned': False}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        self.assertEqual(1, len(inst_list))
        self.assertIsInstance(inst_list.objects[0], instance.Instance)
        self.assertEqual(fakes[1]['uuid'], inst_list.objects[0].uuid)

    def test_get_by_host(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        db.instance_get_all_by_host(self.context, 'foo',
                                    columns_to_join=None).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_host(self.context, 'foo')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)
            self.assertEqual(self.context, inst_list.objects[i]._context)
        self.assertEqual(set(), inst_list.obj_what_changed())

    def test_get_by_host_and_node(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_node')
        db.instance_get_all_by_host_and_node(self.context, 'foo', 'bar',
                                             columns_to_join=None).AndReturn(
                                                 fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_host_and_node(self.context,
                                                              'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    def test_get_by_host_and_not_type(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_not_type')
        db.instance_get_all_by_host_and_not_type(self.context, 'foo',
                                                 type_id='bar').AndReturn(
                                                     fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_by_host_and_not_type(
            self.context, 'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    @mock.patch('nova.objects.instance._expected_cols')
    @mock.patch('nova.db.instance_get_all')
    def test_get_all(self, mock_get_all, mock_exp):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        mock_get_all.return_value = fakes
        mock_exp.return_value = mock.sentinel.exp_att
        inst_list = objects.InstanceList.get_all(
                self.context, expected_attrs='fake')
        mock_get_all.assert_called_once_with(
                self.context, columns_to_join=mock.sentinel.exp_att)
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    def test_get_hung_in_rebooting(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        dt = utils.isotime()
        self.mox.StubOutWithMock(db, 'instance_get_all_hung_in_rebooting')
        db.instance_get_all_hung_in_rebooting(self.context, dt).AndReturn(
            fakes)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList.get_hung_in_rebooting(self.context,
                                                               dt)
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

    def test_get_active_by_window_joined(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        # NOTE(mriedem): Send in a timezone-naive datetime since the
        # InstanceList.get_active_by_window_joined method should convert it
        # to tz-aware for the DB API call, which we'll assert with our stub.
        dt = timeutils.utcnow()

        def fake_instance_get_active_by_window_joined(context, begin, end,
                                                      project_id, host,
                                                      columns_to_join):
            # make sure begin is tz-aware
            self.assertIsNotNone(begin.utcoffset())
            self.assertIsNone(end)
            self.assertEqual(['metadata'], columns_to_join)
            return fakes

        with mock.patch.object(db, 'instance_get_active_by_window_joined',
                               fake_instance_get_active_by_window_joined):
            inst_list = objects.InstanceList.get_active_by_window_joined(
                            self.context, dt, expected_attrs=['metadata'])

        for fake, obj in zip(fakes, inst_list.objects):
            self.assertIsInstance(obj, instance.Instance)
            self.assertEqual(fake['uuid'], obj.uuid)

    def test_with_fault(self):
        fake_insts = [
            fake_instance.fake_db_instance(uuid=uuids.faults_instance,
                                           host='host'),
            fake_instance.fake_db_instance(uuid=uuids.faults_instance_nonexist,
                                           host='host'),
            ]
        fake_faults = test_instance_fault.fake_faults
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_get_all_by_host(self.context, 'host',
                                    columns_to_join=[]).AndReturn(fake_insts)
        db.instance_fault_get_by_instance_uuids(
            self.context, [x['uuid'] for x in fake_insts]
            ).AndReturn(fake_faults)
        self.mox.ReplayAll()
        instances = objects.InstanceList.get_by_host(self.context, 'host',
                                                     expected_attrs=['fault'],
                                                     use_slave=False)
        self.assertEqual(2, len(instances))
        self.assertEqual(fake_faults['fake-uuid'][0],
                         dict(instances[0].fault))
        self.assertIsNone(instances[1].fault)

    def test_fill_faults(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')

        inst1 = objects.Instance(uuid=uuids.db_fault_1)
        inst2 = objects.Instance(uuid=uuids.db_fault_2)
        insts = [inst1, inst2]
        for inst in insts:
            inst.obj_reset_changes()
        db_faults = {
            'uuid1': [{'id': 123,
                       'instance_uuid': uuids.db_fault_1,
                       'code': 456,
                       'message': 'Fake message',
                       'details': 'No details',
                       'host': 'foo',
                       'deleted': False,
                       'deleted_at': None,
                       'updated_at': None,
                       'created_at': None,
                       }
                      ]}

        db.instance_fault_get_by_instance_uuids(self.context,
                                                [x.uuid for x in insts],
                                                ).AndReturn(db_faults)
        self.mox.ReplayAll()
        inst_list = objects.InstanceList()
        inst_list._context = self.context
        inst_list.objects = insts
        faulty = inst_list.fill_faults()
        self.assertEqual([uuids.db_fault_1], list(faulty))
        self.assertEqual(db_faults['uuid1'][0]['message'],
                         inst_list[0].fault.message)
        self.assertIsNone(inst_list[1].fault)
        for inst in inst_list:
            self.assertEqual(set(), inst.obj_what_changed())

    @mock.patch('nova.objects.instance.Instance.obj_make_compatible')
    def test_get_by_security_group(self, mock_compat):
        fake_secgroup = dict(test_security_group.fake_secgroup)
        fake_secgroup['instances'] = [
            fake_instance.fake_db_instance(id=1,
                                           system_metadata={'foo': 'bar'}),
            fake_instance.fake_db_instance(id=2),
            ]

        with mock.patch.object(db, 'security_group_get') as sgg:
            sgg.return_value = fake_secgroup
            secgroup = security_group.SecurityGroup()
            secgroup.id = fake_secgroup['id']
            instances = instance.InstanceList.get_by_security_group(
                self.context, secgroup)

        self.assertEqual(2, len(instances))
        self.assertEqual([1, 2], [x.id for x in instances])
        self.assertTrue(instances[0].obj_attr_is_set('system_metadata'))
        self.assertEqual({'foo': 'bar'}, instances[0].system_metadata)

    def test_get_by_grantee_security_group_ids(self):
        fake_instances = [
            fake_instance.fake_db_instance(id=1),
            fake_instance.fake_db_instance(id=2)
            ]

        with mock.patch.object(
            db, 'instance_get_all_by_grantee_security_groups') as igabgsg:
            igabgsg.return_value = fake_instances
            secgroup_ids = [1]
            instances = objects.InstanceList.get_by_grantee_security_group_ids(
                self.context, secgroup_ids)
            igabgsg.assert_called_once_with(self.context, secgroup_ids)

        self.assertEqual(2, len(instances))
        self.assertEqual([1, 2], [x.id for x in instances])


class TestInstanceListObject(test_objects._LocalTest,
                             _TestInstanceListObject):
    pass


class TestRemoteInstanceListObject(test_objects._RemoteTest,
                                   _TestInstanceListObject):
    pass


class TestInstanceObjectMisc(test.TestCase):
    def test_expected_cols(self):
        self.stubs.Set(instance, '_INSTANCE_OPTIONAL_JOINED_FIELDS', ['bar'])
        self.assertEqual(['bar'], instance._expected_cols(['foo', 'bar']))
        self.assertIsNone(instance._expected_cols(None))

    def test_expected_cols_extra(self):
        self.assertEqual(['metadata', 'extra', 'extra.numa_topology'],
                         instance._expected_cols(['metadata',
                                                  'numa_topology']))
