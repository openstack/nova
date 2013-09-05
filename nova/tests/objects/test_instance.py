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
import mox
import netaddr

from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova.network import model as network_model
from nova import notifications
from nova.objects import instance
from nova.objects import instance_info_cache
from nova.objects import security_group
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.objects import test_instance_fault
from nova.tests.objects import test_instance_info_cache
from nova.tests.objects import test_objects
from nova.tests.objects import test_security_group


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
        return fake_instance

    def test_datetime_deserialization(self):
        red_letter_date = timeutils.parse_isotime(
            timeutils.isotime(datetime.datetime(1955, 11, 5)))
        inst = instance.Instance(uuid='fake-uuid', launched_at=red_letter_date)
        primitive = inst.obj_to_primitive()
        expected = {'nova_object.name': 'Instance',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.10',
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
                    'nova_object.version': '1.10',
                    'nova_object.data':
                        {'uuid': 'fake-uuid',
                         'access_ip_v4': '1.2.3.4',
                         'access_ip_v6': '::1'},
                    'nova_object.changes': ['access_ip_v4', 'uuid',
                                            'access_ip_v6']}
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

        exp_cols = instance.INSTANCE_OPTIONAL_ATTRS[:]
        exp_cols.remove('fault')

        db.instance_get_by_uuid(
            self.context, 'uuid',
            columns_to_join=exp_cols,
            use_slave=False
            ).AndReturn(self.fake_instance)
        fake_faults = test_instance_fault.fake_faults
        db.instance_fault_get_by_instance_uuids(
                self.context, [self.fake_instance['uuid']]
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
                'system_metadata': {'foo': 'bar'}}
        fake_inst = fake_instance.fake_db_instance(**vals)
        db.instance_create(self.context, vals).AndReturn(fake_inst)
        self.mox.ReplayAll()
        inst = instance.Instance(host='foo-host', memory_mb=128,
                                 system_metadata={'foo': 'bar'})
        inst.create(self.context)

    def test_create(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        db.instance_create(self.context, {}).AndReturn(self.fake_instance)
        self.mox.ReplayAll()
        inst = instance.Instance()
        inst.create(self.context)
        self.assertEqual(self.fake_instance['id'], inst.id)

    def test_create_with_values(self):
        inst1 = instance.Instance(user_id=self.context.user_id,
                                  project_id=self.context.project_id,
                                  host='foo-host')
        inst1.create(self.context)
        self.assertEqual(inst1.host, 'foo-host')
        inst2 = instance.Instance.get_by_uuid(self.context, inst1.uuid)
        self.assertEqual(inst2.host, 'foo-host')

    def test_recreate_fails(self):
        inst = instance.Instance(user_id=self.context.user_id,
                                 project_id=self.context.project_id,
                                 host='foo-host')
        inst.create(self.context)
        self.assertRaises(exception.ObjectActionError, inst.create,
                          self.context)

    def test_create_with_special_things(self):
        self.mox.StubOutWithMock(db, 'instance_create')
        fake_inst = fake_instance.fake_db_instance()
        db.instance_create(self.context,
                           {'host': 'foo-host',
                            'security_groups': ['foo', 'bar'],
                            'info_cache': {'network_info': '[]'},
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
        inst = instance.Instance(host='foo-host', security_groups=secgroups,
                                 info_cache=info_cache)
        inst.create(self.context)

    def test_destroy_stubbed(self):
        self.mox.StubOutWithMock(db, 'instance_destroy')
        db.instance_destroy(self.context, 'fake-uuid', constraint=None)
        self.mox.ReplayAll()
        inst = instance.Instance(id=1, uuid='fake-uuid', host='foo')
        inst.destroy(self.context)

    def test_destroy(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id}
        db_inst = db.instance_create(self.context, values)
        inst = instance.Instance(id=db_inst['id'], uuid=db_inst['uuid'])
        inst.destroy(self.context)
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
                                       columns_to_join=['metadata']).AndReturn(
                                           fakes)
        self.mox.ReplayAll()
        inst_list = instance.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, 'uuid', 'asc',
            expected_attrs=['metadata'])

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(inst_list.objects[i].uuid, fakes[i]['uuid'])
        self.assertRemotes()

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
        inst_list = instance.InstanceList.get_by_filters(
            self.context, {'deleted': True, 'cleaned': False}, 'uuid', 'asc',
            expected_attrs=['metadata'])

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
        db.instance_get_all_by_host_and_node(self.context, 'foo', 'bar'
                                             ).AndReturn(fakes)
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
