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

import iso8601
import mock
from mox3 import mox
import netaddr
from oslo.serialization import jsonutils
from oslo.utils import timeutils

from nova.cells import rpcapi as cells_rpcapi
from nova.compute import flavors
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import notifications
from nova import objects
from nova.objects import instance
from nova.objects import instance_info_cache
from nova.objects import pci_device
from nova.objects import security_group
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests.unit.objects import test_instance_numa_topology
from nova.tests.unit.objects import test_instance_pci_requests
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_security_group
from nova import utils


class _TestInstanceObject(object):
    @property
    def fake_instance(self):
        fake_instance = fakes.stub_instance(id=2,
                                            access_ipv4='1.2.3.4',
                                            access_ipv6='::1')
        fake_instance['cell_name'] = 'api!child'
        fake_instance['scheduled_at'] = None
        fake_instance['terminated_at'] = None
        fake_instance['deleted_at'] = None
        fake_instance['created_at'] = None
        fake_instance['updated_at'] = None
        fake_instance['launched_at'] = (
            fake_instance['launched_at'].replace(
                tzinfo=iso8601.iso8601.Utc(), microsecond=0))
        fake_instance['deleted'] = False
        fake_instance['info_cache']['instance_uuid'] = fake_instance['uuid']
        fake_instance['security_groups'] = []
        fake_instance['pci_devices'] = []
        fake_instance['user_id'] = self.context.user_id
        fake_instance['project_id'] = self.context.project_id
        fake_instance['tags'] = []
        return fake_instance

    def test_datetime_deserialization(self):
        red_letter_date = timeutils.parse_isotime(
            timeutils.isotime(datetime.datetime(1955, 11, 5)))
        inst = instance.Instance(uuid='fake-uuid', launched_at=red_letter_date)
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.17',
                    'nova_object.data':
                        {'uuid': 'fake-uuid',
                         'launched_at': '1955-11-05T00:00:00Z'},
                    'nova_object.changes': ['launched_at', 'uuid']}
        self.assertEqual(primitive, expected)
        inst2 = instance.Instance.obj_from_primitive(primitive)
        self.assertIsInstance(inst2.launched_at, datetime.datetime)
        self.assertEqual(inst2.launched_at, red_letter_date)

    def test_ip_deserialization(self):
        inst = instance.Instance(uuid='fake-uuid', access_ip_v4='1.2.3.4',
                                 access_ip_v6='::1')
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.17',
                    'nova_object.data':
                        {'uuid': 'fake-uuid',
                         'access_ip_v4': '1.2.3.4',
                         'access_ip_v6': '::1'},
                    'nova_object.changes': ['uuid', 'access_ip_v6',
                                            'access_ip_v4']}
        self.assertEqual(primitive, expected)
        inst2 = instance.Instance.obj_from_primitive(primitive)
        self.assertIsInstance(inst2.access_ip_v4, netaddr.IPAddress)
        self.assertIsInstance(inst2.access_ip_v6, netaddr.IPAddress)
        self.assertEqual(inst2.access_ip_v4, netaddr.IPAddress('1.2.3.4'))
        self.assertEqual(inst2.access_ip_v6, netaddr.IPAddress('::1'))

    def test_get_without_expected(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, 'uuid',
                                columns_to_join=[],
                                use_slave=False
                                ).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, 'uuid',
                                             expected_attrs=[])
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertFalse(inst.obj_attr_is_set(attr))
        self.assertRemotes()

    def test_get_with_expected(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        self.mox.StubOutWithMock(
                db, 'instance_extra_get_by_instance_uuid')

        exp_cols = instance.INSTANCE_OPTIONAL_ATTRS[:]
        exp_cols.remove('fault')
        exp_cols.remove('numa_topology')
        exp_cols.remove('pci_requests')
        exp_cols.extend(['extra', 'extra.numa_topology', 'extra.pci_requests'])

        fake_topology = (test_instance_numa_topology.
                         fake_db_topology['numa_topology'])
        fake_requests = jsonutils.dumps(test_instance_pci_requests.
                                        fake_pci_requests)
        fake_instance = dict(self.fake_instance,
                             extra={
                                 'numa_topology': fake_topology,
                                 'pci_requests': fake_requests,
                                 })
        db.instance_get_by_uuid(
            self.context, 'uuid',
            columns_to_join=exp_cols,
            use_slave=False
            ).AndReturn(fake_instance)
        fake_faults = test_instance_fault.fake_faults
        db.instance_fault_get_by_instance_uuids(
                self.context, [fake_instance['uuid']]
                ).AndReturn(fake_faults)

        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(
            self.context, 'uuid',
            expected_attrs=instance.INSTANCE_OPTIONAL_ATTRS)
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertTrue(inst.obj_attr_is_set(attr))
        self.assertRemotes()

    def test_get_by_id(self):
        self.mox.StubOutWithMock(db, 'instance_get')
        db.instance_get(self.context, 'instid',
                        columns_to_join=['info_cache',
                                         'security_groups']
                        ).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_id(self.context, 'instid')
        self.assertEqual(inst.uuid, self.fake_instance['uuid'])
        self.assertRemotes()

    def test_load(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(self.fake_instance)
        fake_inst2 = dict(self.fake_instance,
                          system_metadata=[{'key': 'foo', 'value': 'bar'}])
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['system_metadata'],
                                use_slave=False
                                ).AndReturn(fake_inst2)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertFalse(hasattr(inst, '_system_metadata'))
        sys_meta = inst.system_metadata
        self.assertEqual(sys_meta, {'foo': 'bar'})
        self.assertTrue(hasattr(inst, '_system_metadata'))
        # Make sure we don't run load again
        sys_meta2 = inst.system_metadata
        self.assertEqual(sys_meta2, {'foo': 'bar'})
        self.assertRemotes()

    def test_load_invalid(self):
        inst = instance.Instance(context=self.context, uuid='fake-uuid')
        self.assertRaises(exception.ObjectActionError,
                          inst.obj_load_attr, 'foo')

    def test_get_remote(self):
        # isotime doesn't have microseconds and is always UTC
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_instance = self.fake_instance
        db.instance_get_by_uuid(self.context, 'fake-uuid',
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, 'fake-uuid')
        self.assertEqual(inst.id, fake_instance['id'])
        self.assertEqual(inst.launched_at, fake_instance['launched_at'])
        self.assertEqual(str(inst.access_ip_v4),
                         fake_instance['access_ip_v4'])
        self.assertEqual(str(inst.access_ip_v6),
                         fake_instance['access_ip_v6'])
        self.assertRemotes()

    def test_refresh(self):
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        fake_uuid = self.fake_instance['uuid']
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(dict(self.fake_instance,
                                                 host='orig-host'))
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(dict(self.fake_instance,
                                                 host='new-host'))
        self.mox.StubOutWithMock(instance_info_cache.InstanceInfoCache,
                                 'refresh')
        instance_info_cache.InstanceInfoCache.refresh()
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(inst.host, 'orig-host')
        inst.refresh()
        self.assertEqual(inst.host, 'new-host')
        self.assertRemotes()
        self.assertEqual(set([]), inst.obj_what_changed())

    def test_refresh_does_not_recurse(self):
        inst = instance.Instance(context=self.context, uuid='fake-uuid',
                                 metadata={})
        inst_copy = instance.Instance()
        inst_copy.uuid = inst.uuid
        self.mox.StubOutWithMock(instance.Instance, 'get_by_uuid')
        instance.Instance.get_by_uuid(self.context, uuid=inst.uuid,
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
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(old_ref)
        db.instance_update_and_get_original(
                self.context, fake_uuid, expected_updates,
                update_cells=False,
                columns_to_join=['info_cache', 'security_groups',
                    'system_metadata']
                ).AndReturn((old_ref, new_ref))
        if cell_type == 'api':
            cells_rpcapi.CellsAPI().AndReturn(cells_api_mock)
            cells_api_mock.instance_update_from_api(
                    self.context, mox.IsA(instance.Instance),
                    exp_vm_state, exp_task_state, admin_reset)
        elif cell_type == 'compute':
            cells_rpcapi.CellsAPI().AndReturn(cells_api_mock)
            cells_api_mock.instance_update_at_top(self.context, new_ref)
        notifications.send_update(self.context, mox.IgnoreArg(),
                                  mox.IgnoreArg())

        self.mox.ReplayAll()

        inst = instance.Instance.get_by_uuid(self.context, old_ref['uuid'])
        if 'instance_version' in save_kwargs:
            inst.VERSION = save_kwargs.pop('instance_version')
        self.assertEqual('old', inst.task_state)
        self.assertEqual('old', inst.vm_state)
        self.assertEqual('old', inst.user_data)
        inst.vm_state = 'meow'
        inst.task_state = 'wuff'
        inst.user_data = 'new'
        inst.save(**save_kwargs)
        self.assertEqual('newhost', inst.host)
        self.assertEqual('meow', inst.vm_state)
        self.assertEqual('wuff', inst.task_state)
        self.assertEqual('new', inst.user_data)
        self.assertEqual(set([]), inst.obj_what_changed())

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

    def test_save_exp_task_state_havana(self):
        self._save_test_helper(None, {
                'expected_task_state': 'image_snapshot',
                'instance_version': '1.9'})

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
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(old_ref)
        db.instance_update_and_get_original(
                self.context, fake_uuid, expected_updates, update_cells=False,
                columns_to_join=['info_cache', 'security_groups',
                    'system_metadata']
                ).AndReturn((old_ref, new_ref))
        notifications.send_update(self.context, mox.IgnoreArg(),
                                  mox.IgnoreArg())

        self.mox.ReplayAll()

        inst = instance.Instance.get_by_uuid(self.context, old_ref['uuid'],
                                             use_slave=False)
        self.assertEqual('hello', inst.display_name)
        inst.display_name = 'goodbye'
        inst.save()
        self.assertEqual('goodbye', inst.display_name)
        self.assertEqual(set([]), inst.obj_what_changed())

    def test_save_related_object_if_none(self):
        with mock.patch.object(instance.Instance, '_save_pci_requests'
                ) as save_mock:
            inst = instance.Instance()
            inst = instance.Instance._from_db_object(self.context, inst,
                    self.fake_instance)
            inst.pci_requests = None
            inst.save()
            self.assertTrue(save_mock.called)

    @mock.patch('nova.db.instance_update_and_get_original')
    @mock.patch('nova.objects.Instance._from_db_object')
    def test_save_does_not_refresh_pci_devices(self, mock_fdo, mock_update):
        # NOTE(danms): This tests that we don't update the pci_devices
        # field from the contents of the database. This is not because we
        # don't necessarily want to, but because the way pci_devices is
        # currently implemented it causes versioning issues. When that is
        # resolved, this test should go away.
        mock_update.return_value = None, None
        inst = instance.Instance(context=self.context, id=123)
        inst.uuid = 'foo'
        inst.pci_devices = pci_device.PciDeviceList()
        inst.save()
        self.assertNotIn('pci_devices',
                         mock_fdo.call_args_list[0][1]['expected_attrs'])

    @mock.patch('nova.db.instance_extra_update_by_uuid')
    @mock.patch('nova.db.instance_update_and_get_original')
    @mock.patch('nova.objects.Instance._from_db_object')
    def test_save_updates_numa_topology(self, mock_fdo, mock_update,
            mock_extra_update):
        fake_obj_numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(id=0, cpuset=set([0]), memory=128),
            objects.InstanceNUMACell(id=1, cpuset=set([1]), memory=128)])
        fake_obj_numa_topology.instance_uuid = 'fake-uuid'
        jsonified = fake_obj_numa_topology._to_json()

        mock_update.return_value = None, None
        inst = instance.Instance(
            context=self.context, id=123, uuid='fake-uuid')
        inst.numa_topology = fake_obj_numa_topology
        inst.save()
        mock_extra_update.assert_called_once_with(
            self.context, inst.uuid, {'numa_topology': jsonified})
        mock_extra_update.reset_mock()
        inst.numa_topology = None
        inst.save()
        mock_extra_update.assert_called_once_with(
                self.context, inst.uuid, {'numa_topology': None})

    def test_get_deleted(self):
        fake_inst = dict(self.fake_instance, id=123, deleted=123)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(danms): Make sure it's actually a bool
        self.assertEqual(inst.deleted, True)

    def test_get_not_cleaned(self):
        fake_inst = dict(self.fake_instance, id=123, cleaned=None)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertEqual(inst.cleaned, False)

    def test_get_cleaned(self):
        fake_inst = dict(self.fake_instance, id=123, cleaned=1)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertEqual(inst.cleaned, True)

    def test_with_info_cache(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        nwinfo1 = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        nwinfo2 = network_model.NetworkInfo.hydrate([{'address': 'bar'}])
        nwinfo1_json = nwinfo1.json()
        nwinfo2_json = nwinfo2.json()
        fake_inst['info_cache'] = dict(
            test_instance_info_cache.fake_info_cache,
            network_info=nwinfo1_json,
            instance_uuid=fake_uuid)
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_update_and_get_original')
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        db.instance_info_cache_update(self.context, fake_uuid,
                                      {'network_info': nwinfo2_json})
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(inst.info_cache.network_info, nwinfo1)
        self.assertEqual(inst.info_cache.instance_uuid, fake_uuid)
        inst.info_cache.network_info = nwinfo2
        inst.save()

    def test_with_info_cache_none(self):
        fake_inst = dict(self.fake_instance, info_cache=None)
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid,
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
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        db.security_group_update(self.context, 1, {'description': 'changed'}
                                 ).AndReturn(fake_inst['security_groups'][0])
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(len(inst.security_groups), 2)
        for index, group in enumerate(fake_inst['security_groups']):
            for key in group:
                self.assertEqual(group[key],
                                 inst.security_groups[index][key])
                self.assertIsInstance(inst.security_groups[index],
                                      security_group.SecurityGroup)
        self.assertEqual(inst.security_groups.obj_what_changed(), set())
        inst.security_groups[0].description = 'changed'
        inst.save()
        self.assertEqual(inst.security_groups.obj_what_changed(), set())

    def test_with_empty_security_groups(self):
        fake_inst = dict(self.fake_instance, security_groups=[])
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['info_cache',
                                                 'security_groups'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(0, len(inst.security_groups))

    def test_with_empty_pci_devices(self):
        fake_inst = dict(self.fake_instance, pci_devices=[])
        fake_uuid = fake_inst['uuid']
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['pci_devices'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(len(inst.pci_devices), 0)

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
             'product_id': 'p1',
             'dev_type': 't',
             'status': 'allocated',
             'dev_id': 'i',
             'label': 'l',
             'instance_uuid': fake_uuid,
             'request_id': None,
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
             'product_id': 'p',
             'dev_type': 't',
             'status': 'allocated',
             'dev_id': 'i',
             'label': 'l',
             'instance_uuid': fake_uuid,
             'request_id': None,
             'extra_info': '{}'},
            ]
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=['pci_devices'],
                                use_slave=False
                                ).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(len(inst.pci_devices), 2)
        self.assertEqual(inst.pci_devices[0].instance_uuid, fake_uuid)
        self.assertEqual(inst.pci_devices[1].instance_uuid, fake_uuid)

    def test_with_fault(self):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_faults = [dict(x, instance_uuid=fake_uuid)
                       for x in test_instance_fault.fake_faults['fake-uuid']]
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_get_by_uuid(self.context, fake_uuid,
                                columns_to_join=[],
                                use_slave=False
                                ).AndReturn(self.fake_instance)
        db.instance_fault_get_by_instance_uuids(
            self.context, [fake_uuid]).AndReturn({fake_uuid: fake_faults})
        self.mox.ReplayAll()
        inst = instance.Instance.get_by_uuid(self.context, fake_uuid,
                                             expected_attrs=['fault'])
        self.assertEqual(fake_faults[0], dict(inst.fault.items()))
        self.assertRemotes()

    def test_iteritems_with_extra_attrs(self):
        self.stubs.Set(instance.Instance, 'name', 'foo')
        inst = instance.Instance(uuid='fake-uuid')
        self.assertEqual(inst.items(),
                         {'uuid': 'fake-uuid',
                          'name': 'foo',
                          }.items())

    def _test_metadata_change_tracking(self, which):
        inst = instance.Instance(uuid='fake-uuid')
        setattr(inst, which, {})
        inst.obj_reset_changes()
        getattr(inst, which)['foo'] = 'bar'
        self.assertEqual(set([which]), inst.obj_what_changed())
        inst.obj_reset_changes()
        self.assertEqual(set(), inst.obj_what_changed())

    def test_metadata_change_tracking(self):
        self._test_metadata_change_tracking('metadata')

    def test_system_metadata_change_tracking(self):
        self._test_metadata_change_tracking('system_metadata')

    def test_create_stubbed(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        vals = {'host': 'foo-host',
                'memory_mb': 128,
                'system_metadata': {'foo': 'bar'},
                'extra': {}}
        fake_inst = fake_instance.fake_db_instance(**vals)
        db.instance_create(self.context, vals).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance(context=self.context,
                                 host='foo-host', memory_mb=128,
                                 system_metadata={'foo': 'bar'})
        inst.create()

    def test_create(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        db.instance_create(self.context, {'extra': {}}).AndReturn(
            self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance(context=self.context)
        inst.create()
        self.assertEqual(self.fake_instance['id'], inst.id)

    def test_create_with_values(self):
        inst1 = instance.Instance(context=self.context,
                                  user_id=self.context.user_id,
                                  project_id=self.context.project_id,
                                  host='foo-host')
        inst1.create()
        self.assertEqual(inst1.host, 'foo-host')
        inst2 = instance.Instance.get_by_uuid(self.context, inst1.uuid)
        self.assertEqual(inst2.host, 'foo-host')

    def test_create_with_extras(self):
        inst = instance.Instance(context=self.context,
            uuid=self.fake_instance['uuid'],
            numa_topology=test_instance_numa_topology.fake_obj_numa_topology,
            pci_requests=objects.InstancePCIRequests(
                requests=[
                    objects.InstancePCIRequest(count=123,
                                               spec=[])]))
        inst.create()
        self.assertIsNotNone(inst.numa_topology)
        self.assertIsNotNone(inst.pci_requests)
        got_numa_topo = objects.InstanceNUMATopology.get_by_instance_uuid(
            self.context, inst.uuid)
        self.assertEqual(inst.numa_topology.instance_uuid,
                         got_numa_topo.instance_uuid)
        got_pci_requests = objects.InstancePCIRequests.get_by_instance_uuid(
            self.context, inst.uuid)
        self.assertEqual(123, got_pci_requests.requests[0].count)

    def test_recreate_fails(self):
        inst = instance.Instance(context=self.context,
                                 user_id=self.context.user_id,
                                 project_id=self.context.project_id,
                                 host='foo-host')
        inst.create()
        self.assertRaises(exception.ObjectActionError, inst.create,
                          self.context)

    def test_create_with_special_things(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        fake_inst = fake_instance.fake_db_instance()
        db.instance_create(self.context,
                           {'host': 'foo-host',
                            'security_groups': ['foo', 'bar'],
                            'info_cache': {'network_info': '[]'},
                            'extra': {},
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
        inst = instance.Instance(context=self.context,
                                 host='foo-host', security_groups=secgroups,
                                 info_cache=info_cache)
        inst.create()

    def test_destroy_stubbed(self):
        self.mox.StubOutWithMock(db, 'instance_destroy')
        deleted_at = datetime.datetime(1955, 11, 6)
        fake_inst = fake_instance.fake_db_instance(deleted_at=deleted_at,
                                                   deleted=True)
        db.instance_destroy(self.context, 'fake-uuid',
                            constraint=None).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance(context=self.context, id=1, uuid='fake-uuid',
                                 host='foo')
        inst.destroy()
        self.assertEqual(timeutils.normalize_time(inst.deleted_at),
                         timeutils.normalize_time(deleted_at))
        self.assertTrue(inst.deleted)

    def test_destroy(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id}
        db_inst = db.instance_create(self.context, values)
        inst = instance.Instance(context=self.context, id=db_inst['id'],
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
        inst = instance.Instance.get_by_uuid(self.context, db_inst['uuid'])
        inst.host = None
        self.assertRaises(exception.ObjectActionError,
                          inst.destroy)

    def test_name_does_not_trigger_lazy_loads(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id,
                  'host': 'foo'}
        db_inst = db.instance_create(self.context, values)
        inst = instance.Instance.get_by_uuid(self.context, db_inst['uuid'])
        self.assertFalse(inst.obj_attr_is_set('fault'))
        self.flags(instance_name_template='foo-%(uuid)s')
        self.assertEqual('foo-%s' % db_inst['uuid'], inst.name)
        self.assertFalse(inst.obj_attr_is_set('fault'))

    def test_from_db_object_not_overwrite_info_cache(self):
        info_cache = instance_info_cache.InstanceInfoCache()
        inst = instance.Instance(context=self.context,
                                 info_cache=info_cache)
        db_inst = fake_instance.fake_db_instance()
        db_inst['info_cache'] = dict(
            test_instance_info_cache.fake_info_cache)
        inst._from_db_object(self.context, inst, db_inst,
                             expected_attrs=['info_cache'])
        self.assertIs(info_cache, inst.info_cache)

    def test_compat_strings(self):
        unicode_attributes = ['user_id', 'project_id', 'image_ref',
                              'kernel_id', 'ramdisk_id', 'hostname',
                              'key_name', 'key_data', 'host', 'node',
                              'user_data', 'availability_zone',
                              'display_name', 'display_description',
                              'launched_on', 'locked_by', 'os_type',
                              'architecture', 'vm_mode', 'root_device_name',
                              'default_ephemeral_device',
                              'default_swap_device', 'config_drive',
                              'cell_name']
        inst = instance.Instance()
        expected = {}
        for key in unicode_attributes:
            inst[key] = u'\u2603'
            expected[key] = '?'
        primitive = inst.obj_to_primitive(target_version='1.6')
        self.assertEqual(expected, primitive['nova_object.data'])
        self.assertEqual('1.6', primitive['nova_object.version'])

    def test_compat_pci_devices(self):
        inst = instance.Instance()
        inst.pci_devices = pci_device.PciDeviceList()
        primitive = inst.obj_to_primitive(target_version='1.5')
        self.assertNotIn('pci_devices', primitive)

    def test_compat_info_cache(self):
        inst = instance.Instance()
        inst.info_cache = instance_info_cache.InstanceInfoCache()
        primitive = inst.obj_to_primitive(target_version='1.9')
        self.assertEqual(
            '1.4',
            primitive['nova_object.data']['info_cache']['nova_object.version'])

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

    def _test_get_flavor(self, namespace):
        prefix = '%s_' % namespace if namespace is not None else ''
        db_inst = db.instance_create(self.context, {
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            'system_metadata': flavors.save_flavor_info(
                {}, flavors.get_default_flavor(), prefix)})
        db_flavor = flavors.extract_flavor(db_inst, prefix)
        inst = instance.Instance.get_by_uuid(self.context, db_inst['uuid'])
        flavor = inst.get_flavor(namespace)
        self.assertEqual(db_flavor['flavorid'], flavor.flavorid)

    def test_get_flavor(self):
        self._test_get_flavor(None)
        self._test_get_flavor('foo')

    def _test_set_flavor(self, namespace):
        prefix = '%s_' % namespace if namespace is not None else ''
        db_inst = db.instance_create(self.context, {
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            })
        inst = instance.Instance.get_by_uuid(self.context, db_inst['uuid'])
        db_flavor = flavors.get_default_flavor()
        inst.set_flavor(db_flavor, namespace)
        db_inst = db.instance_get(self.context, db_inst['id'])
        self.assertEqual(
            db_flavor['flavorid'], flavors.extract_flavor(
                db_inst, prefix)['flavorid'])

    def test_set_flavor(self):
        self._test_set_flavor(None)
        self._test_set_flavor('foo')

    def test_delete_flavor(self):
        namespace = 'foo'
        prefix = '%s_' % namespace
        db_inst = db.instance_create(self.context, {
            'user_id': self.context.user_id,
            'project_id': self.context.project_id,
            'system_metadata': flavors.save_flavor_info(
                {}, flavors.get_default_flavor(), prefix)})
        inst = instance.Instance.get_by_uuid(self.context, db_inst['uuid'])
        inst.delete_flavor(namespace)
        db_inst = db.instance_get(self.context, db_inst['id'])
        self.assertEqual({}, utils.instance_sys_meta(db_inst))

    def test_delete_flavor_no_namespace_fails(self):
        inst = instance.Instance(system_metadata={})
        self.assertRaises(KeyError, inst.delete_flavor, None)
        self.assertRaises(KeyError, inst.delete_flavor, '')

    @mock.patch.object(db, 'instance_metadata_delete')
    def test_delete_metadata_key(self, db_delete):
        inst = instance.Instance(context=self.context,
                                 id=1, uuid='fake-uuid')
        inst.metadata = {'foo': '1', 'bar': '2'}
        inst.obj_reset_changes()
        inst.delete_metadata_key('foo')
        self.assertEqual({'bar': '2'}, inst.metadata)
        self.assertEqual({}, inst.obj_get_changes())
        db_delete.assert_called_once_with(self.context, inst.uuid, 'foo')

    def test_reset_changes(self):
        inst = instance.Instance()
        inst.metadata = {'1985': 'present'}
        inst.system_metadata = {'1955': 'past'}
        self.assertEqual({}, inst._orig_metadata)
        inst.obj_reset_changes(['metadata'])
        self.assertEqual({'1985': 'present'}, inst._orig_metadata)
        self.assertEqual({}, inst._orig_system_metadata)

    def test_load_generic_calls_handler(self):
        inst = instance.Instance(context=self.context,
                                 uuid='fake-uuid')
        with mock.patch.object(inst, '_load_generic') as mock_load:
            def fake_load(name):
                inst.system_metadata = {}

            mock_load.side_effect = fake_load
            inst.system_metadata
            mock_load.assert_called_once_with('system_metadata')

    def test_load_fault_calls_handler(self):
        inst = instance.Instance(context=self.context,
                                 uuid='fake-uuid')
        with mock.patch.object(inst, '_load_fault') as mock_load:
            def fake_load():
                inst.fault = None

            mock_load.side_effect = fake_load
            inst.fault
            mock_load.assert_called_once_with()

    @mock.patch('nova.objects.Instance.get_by_uuid')
    def test_load_generic(self, mock_get):
        inst2 = instance.Instance(metadata={'foo': 'bar'})
        mock_get.return_value = inst2
        inst = instance.Instance(context=self.context,
                                 uuid='fake-uuid')
        inst.metadata
        self.assertEqual({'foo': 'bar'}, inst.metadata)
        mock_get.assert_called_once_with(self.context,
                                         uuid='fake-uuid',
                                         expected_attrs=['metadata'])
        self.assertNotIn('metadata', inst.obj_what_changed())

    @mock.patch('nova.db.instance_fault_get_by_instance_uuids')
    def test_load_fault(self, mock_get):
        fake_fault = test_instance_fault.fake_faults['fake-uuid'][0]
        mock_get.return_value = {'fake': [fake_fault]}
        inst = instance.Instance(context=self.context, uuid='fake')
        fault = inst.fault
        mock_get.assert_called_once_with(self.context, ['fake'])
        self.assertEqual(fake_fault['id'], fault.id)
        self.assertNotIn('metadata', inst.obj_what_changed())

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
    pass


class TestRemoteInstanceObject(test_objects._RemoteTest,
                               _TestInstanceObject):
    pass


class _TestInstanceListObject(object):
    def fake_instance(self, id, updates=None):
        fake_instance = fakes.stub_instance(id=2,
                                            access_ipv4='1.2.3.4',
                                            access_ipv6='::1')
        fake_instance['scheduled_at'] = None
        fake_instance['terminated_at'] = None
        fake_instance['deleted_at'] = None
        fake_instance['created_at'] = None
        fake_instance['updated_at'] = None
        fake_instance['launched_at'] = (
            fake_instance['launched_at'].replace(
                tzinfo=iso8601.iso8601.Utc(), microsecond=0))
        fake_instance['info_cache'] = {'network_info': '[]',
                                       'instance_uuid': fake_instance['uuid']}
        fake_instance['security_groups'] = []
        fake_instance['deleted'] = 0
        if updates:
            fake_instance.update(updates)
        return fake_instance

    def test_get_all_by_filters(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters')
        db.instance_get_all_by_filters(self.context, {'foo': 'bar'}, 'uuid',
                                       'asc', limit=None, marker=None,
                                       columns_to_join=['metadata'],
                                       use_slave=False).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

    def test_get_all_by_filters_sorted(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_filters_sort')
        db.instance_get_all_by_filters_sort(self.context, {'foo': 'bar'},
                                            limit=None, marker=None,
                                            columns_to_join=['metadata'],
                                            use_slave=False,
                                            sort_keys=['uuid'],
                                            sort_dirs=['asc']).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, expected_attrs=['metadata'],
            use_slave=False, sort_keys=['uuid'], sort_dirs=['asc'])

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

    @mock.patch.object(db, 'instance_get_all_by_filters_sort')
    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters_calls_non_sort(self,
                                               mock_get_by_filters,
                                               mock_get_by_filters_sort):
        '''Verifies InstanceList.get_by_filters calls correct DB function.'''
        # Single sort key/direction is set, call non-sorted DB function
        instance.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, sort_key='key', sort_dir='dir',
            limit=100, marker='uuid', use_slave=True)
        mock_get_by_filters.assert_called_once_with(
            self.context, {'foo': 'bar'}, 'key', 'dir', limit=100,
            marker='uuid', columns_to_join=None, use_slave=True)
        self.assertEqual(0, mock_get_by_filters_sort.call_count)

    @mock.patch.object(db, 'instance_get_all_by_filters_sort')
    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters_calls_sort(self,
                                           mock_get_by_filters,
                                           mock_get_by_filters_sort):
        '''Verifies InstanceList.get_by_filters calls correct DB function.'''
        # Multiple sort keys/directions are set, call sorted DB function
        instance.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, limit=100, marker='uuid',
            use_slave=True, sort_keys=['key1', 'key2'],
            sort_dirs=['dir1', 'dir2'])
        mock_get_by_filters_sort.assert_called_once_with(
            self.context, {'foo': 'bar'}, limit=100,
            marker='uuid', columns_to_join=None, use_slave=True,
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
                                       columns_to_join=['metadata'],
                                       use_slave=False).AndReturn(
                                           [fakes[1]])
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_filters(
            self.context, {'deleted': True, 'cleaned': False}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        self.assertEqual(1, len(inst_list))
        self.assertIsInstance(inst_list.objects[0], instance.Instance)
        self.assertEqual(inst_list.objects[0].uuid, fakes[1]['uuid'])
        self.assertRemotes()

    def test_get_by_host(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        db.instance_get_all_by_host(self.context, 'foo',
                                    columns_to_join=None,
                                    use_slave=False).AndReturn(fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_host(self.context, 'foo')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
            self.assertEqual(inst_list.objects[i]._context, self.context)
        self.assertEqual(inst_list.obj_what_changed(), set())
        self.assertRemotes()

    def test_get_by_host_and_node(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_node')
        db.instance_get_all_by_host_and_node(self.context, 'foo', 'bar',
                                             columns_to_join=None).AndReturn(
                                                 fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_host_and_node(self.context,
                                                               'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

    def test_get_by_host_and_not_type(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host_and_not_type')
        db.instance_get_all_by_host_and_not_type(self.context, 'foo',
                                                 type_id='bar').AndReturn(
                                                     fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_host_and_not_type(
            self.context, 'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

    def test_get_hung_in_rebooting(self):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        dt = timeutils.isotime()
        self.mox.StubOutWithMock(db, 'instance_get_all_hung_in_rebooting')
        db.instance_get_all_hung_in_rebooting(self.context, dt).AndReturn(
            fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_hung_in_rebooting(self.context,
                                                                dt)
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

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
            inst_list = instance.InstanceList.get_active_by_window_joined(
                            self.context, dt, expected_attrs=['metadata'])

        for fake, obj in zip(fakes, inst_list.objects):
            self.assertIsInstance(obj, instance.Instance)
            self.assertEqual(obj.uuid, fake['uuid'])
        self.assertRemotes()

    def test_with_fault(self):
        fake_insts = [
            fake_instance.fake_db_instance(uuid='fake-uuid', host='host'),
            fake_instance.fake_db_instance(uuid='fake-inst2', host='host'),
            ]
        fake_faults = test_instance_fault.fake_faults
        self.mox.StubOutWithMock(db, 'instance_get_all_by_host')
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')
        db.instance_get_all_by_host(self.context, 'host',
                                    columns_to_join=[],
                                    use_slave=False
                                    ).AndReturn(fake_insts)
        db.instance_fault_get_by_instance_uuids(
            self.context, [x['uuid'] for x in fake_insts]
            ).AndReturn(fake_faults)
        self.mox.ReplayAll()
        instances = instance.InstanceList.get_by_host(self.context, 'host',
                                                      expected_attrs=['fault'],
                                                      use_slave=False)
        self.assertEqual(2, len(instances))
        self.assertEqual(fake_faults['fake-uuid'][0],
                         dict(instances[0].fault.iteritems()))
        self.assertIsNone(instances[1].fault)

    def test_fill_faults(self):
        self.mox.StubOutWithMock(db, 'instance_fault_get_by_instance_uuids')

        inst1 = instance.Instance(uuid='uuid1')
        inst2 = instance.Instance(uuid='uuid2')
        insts = [inst1, inst2]
        for inst in insts:
            inst.obj_reset_changes()
        db_faults = {
            'uuid1': [{'id': 123,
                       'instance_uuid': 'uuid1',
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
        inst_list = instance.InstanceList()
        inst_list._context = self.context
        inst_list.objects = insts
        faulty = inst_list.fill_faults()
        self.assertEqual(faulty, ['uuid1'])
        self.assertEqual(inst_list[0].fault.message,
                         db_faults['uuid1'][0]['message'])
        self.assertIsNone(inst_list[1].fault)
        for inst in inst_list:
            self.assertEqual(inst.obj_what_changed(), set())

    def test_get_by_security_group(self):
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


class TestInstanceListObject(test_objects._LocalTest,
                             _TestInstanceListObject):
    pass


class TestRemoteInstanceListObject(test_objects._RemoteTest,
                                   _TestInstanceListObject):
    pass


class TestInstanceObjectMisc(test.NoDBTestCase):
    def test_expected_cols(self):
        self.stubs.Set(instance, '_INSTANCE_OPTIONAL_JOINED_FIELDS', ['bar'])
        self.assertEqual(['bar'], instance._expected_cols(['foo', 'bar']))
        self.assertIsNone(instance._expected_cols(None))

    def test_expected_cols_extra(self):
        self.assertEqual(['metadata', 'extra', 'extra.numa_topology'],
                         instance._expected_cols(['metadata',
                                                  'numa_topology']))
