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

import collections
import datetime
import six

import mock
import netaddr
from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import base as ovo_base

from nova.compute import task_states
from nova.compute import vm_states
from nova.db import api as db
from nova.db.sqlalchemy import api as sql_api
from nova.db.sqlalchemy import models as sql_models
from nova import exception
from nova.network import model as network_model
from nova import notifications
from nova import objects
from nova.objects import fields
from nova.objects import instance
from nova.objects import instance_info_cache
from nova.objects import pci_device
from nova.objects import security_group
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_instance_device_metadata
from nova.tests.unit.objects import test_instance_fault
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests.unit.objects import test_instance_numa
from nova.tests.unit.objects import test_instance_pci_requests
from nova.tests.unit.objects import test_migration_context as test_mig_ctxt
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_security_group
from nova.tests.unit.objects import test_vcpu_model
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
        db_inst['trusted_certs'] = []

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

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_without_expected(self, mock_get):
        mock_get.return_value = self.fake_instance

        inst = objects.Instance.get_by_uuid(self.context, 'uuid',
                                            expected_attrs=[])
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertFalse(inst.obj_attr_is_set(attr))

        mock_get.assert_called_once_with(self.context, 'uuid',
                                         columns_to_join=[])

    @mock.patch.object(db, 'instance_extra_get_by_instance_uuid')
    @mock.patch.object(db, 'instance_fault_get_by_instance_uuids')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_with_expected(self, mock_get, mock_fault_get, mock_extra_get):
        exp_cols = instance.INSTANCE_OPTIONAL_ATTRS[:]
        exp_cols.remove('numa_topology')
        exp_cols.remove('pci_requests')
        exp_cols.remove('vcpu_model')
        exp_cols.remove('ec2_ids')
        exp_cols.remove('migration_context')
        exp_cols.remove('keypairs')
        exp_cols.remove('device_metadata')
        exp_cols.remove('trusted_certs')
        exp_cols.remove('resources')
        exp_cols = [exp_col for exp_col in exp_cols if 'flavor' not in exp_col]
        exp_cols.extend(['extra', 'extra.numa_topology', 'extra.pci_requests',
                         'extra.flavor', 'extra.vcpu_model',
                         'extra.migration_context', 'extra.keypairs',
                         'extra.device_metadata', 'extra.trusted_certs',
                         'extra.resources'])

        fake_topology = test_instance_numa.fake_db_topology['numa_topology']
        fake_requests = jsonutils.dumps(test_instance_pci_requests.
                                        fake_pci_requests)
        fake_devices_metadata = \
                            test_instance_device_metadata.fake_devices_metadata
        fake_flavor = jsonutils.dumps(
            {'cur': objects.Flavor().obj_to_primitive(),
             'old': None, 'new': None})
        fake_vcpu_model = jsonutils.dumps(
            test_vcpu_model.fake_vcpumodel.obj_to_primitive())
        fake_mig_context = jsonutils.dumps(
            test_mig_ctxt.fake_migration_context_obj.obj_to_primitive())
        fake_keypairlist = objects.KeyPairList(objects=[
            objects.KeyPair(name='foo')])
        fake_keypairs = jsonutils.dumps(
            fake_keypairlist.obj_to_primitive())
        fake_trusted_certs = jsonutils.dumps(
            objects.TrustedCerts(ids=['123foo']).obj_to_primitive())
        fake_resource = objects.Resource(
            provider_uuid=uuids.rp, resource_class='CUSTOM_FOO',
            identifier='foo')
        fake_resources = jsonutils.dumps(objects.ResourceList(
            objects=[fake_resource]).obj_to_primitive())
        fake_service = {'created_at': None, 'updated_at': None,
                        'deleted_at': None, 'deleted': False, 'id': 123,
                        'host': 'fake-host', 'binary': 'nova-compute',
                        'topic': 'fake-service-topic', 'report_count': 1,
                        'forced_down': False, 'disabled': False,
                        'disabled_reason': None, 'last_seen_up': None,
                        'version': 1, 'uuid': uuids.service,
                    }
        fake_instance = dict(self.fake_instance,
                             services=[fake_service],
                             extra={
                                 'numa_topology': fake_topology,
                                 'pci_requests': fake_requests,
                                 'device_metadata': fake_devices_metadata,
                                 'flavor': fake_flavor,
                                 'vcpu_model': fake_vcpu_model,
                                 'migration_context': fake_mig_context,
                                 'keypairs': fake_keypairs,
                                 'trusted_certs': fake_trusted_certs,
                                 'resources': fake_resources,
                                 })

        mock_get.return_value = fake_instance

        fake_faults = test_instance_fault.fake_faults
        mock_fault_get.return_value = fake_faults

        inst = objects.Instance.get_by_uuid(
            self.context, 'uuid',
            expected_attrs=instance.INSTANCE_OPTIONAL_ATTRS)
        for attr in instance.INSTANCE_OPTIONAL_ATTRS:
            self.assertTrue(inst.obj_attr_is_set(attr))
        self.assertEqual(123, inst.services[0].id)
        self.assertEqual('foo', inst.keypairs[0].name)
        self.assertEqual(['123foo'], inst.trusted_certs.ids)
        self.assertEqual(fake_resource.identifier,
                         inst.resources[0].identifier)

        mock_get.assert_called_once_with(self.context, 'uuid',
            columns_to_join=exp_cols)
        mock_fault_get.assert_called_once_with(self.context,
            [fake_instance['uuid']])
        self.assertFalse(mock_extra_get.called)

    def test_lazy_load_services_on_deleted_instance(self):
        # We should avoid trying to hit the database to reload the instance
        # and just set the services attribute to an empty list.
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    deleted=True)
        self.assertEqual(0, len(instance.services))

    def test_lazy_load_tags_on_deleted_instance(self):
        # We should avoid trying to hit the database to reload the instance
        # and just set the tags attribute to an empty list.
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    deleted=True)
        self.assertEqual(0, len(instance.tags))

    def test_lazy_load_generic_on_deleted_instance(self):
        # For generic fields, we try to load the deleted record from the
        # database.
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        instance.create()
        instance.destroy()
        # Re-create our local object to make sure it doesn't have sysmeta
        # filled in by create()
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        self.assertNotIn('system_metadata', instance)
        self.assertEqual(0, len(instance.system_metadata))

    def test_lazy_load_flavor_on_deleted_instance(self):
        # For something like a flavor, we should be reading from the DB
        # with read_deleted='yes'
        flavor = objects.Flavor(name='testflavor')
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    flavor=flavor,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        instance.create()
        instance.destroy()
        # Re-create our local object to make sure it doesn't have sysmeta
        # filled in by create()
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        self.assertNotIn('flavor', instance)
        self.assertEqual('testflavor', instance.flavor.name)

    def test_lazy_load_tags(self):
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        instance.create()
        tag = objects.Tag(self.context, resource_id=instance.uuid, tag='foo')
        tag.create()
        self.assertNotIn('tags', instance)
        self.assertEqual(1, len(instance.tags))
        self.assertEqual('foo', instance.tags[0].tag)

    @mock.patch('nova.objects.instance.LOG.exception')
    def test_save_does_not_log_exception_after_tags_loaded(self, mock_log):
        instance = objects.Instance(self.context, uuid=uuids.instance,
                                    user_id=self.context.user_id,
                                    project_id=self.context.project_id)
        instance.create()
        tag = objects.Tag(self.context, resource_id=instance.uuid, tag='foo')
        tag.create()

        # this will lazy load tags so instance.tags will be set
        self.assertEqual(1, len(instance.tags))

        # instance.save will try to find a way to save tags but is should not
        # spam the log with errors
        instance.display_name = 'foobar'
        instance.save()

        self.assertFalse(mock_log.called)

    @mock.patch.object(db, 'instance_get')
    def test_get_by_id(self, mock_get):
        mock_get.return_value = self.fake_instance

        inst = objects.Instance.get_by_id(self.context, 'instid')
        self.assertEqual(self.fake_instance['uuid'], inst.uuid)
        mock_get.assert_called_once_with(self.context, 'instid',
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_load(self, mock_get):
        fake_uuid = self.fake_instance['uuid']
        fake_inst2 = dict(self.fake_instance,
                          metadata=[{'key': 'foo', 'value': 'bar'}])
        mock_get.side_effect = [self.fake_instance, fake_inst2]

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertFalse(hasattr(inst, '_obj_metadata'))
        meta = inst.metadata
        self.assertEqual({'foo': 'bar'}, meta)
        self.assertTrue(hasattr(inst, '_obj_metadata'))
        # Make sure we don't run load again
        meta2 = inst.metadata
        self.assertEqual({'foo': 'bar'}, meta2)

        call_list = [mock.call(self.context, fake_uuid,
                               columns_to_join=['info_cache',
                                                'security_groups']),
                     mock.call(self.context, fake_uuid,
                               columns_to_join=['metadata']),
                     ]
        mock_get.assert_has_calls(call_list, any_order=False)

    def test_load_invalid(self):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        self.assertRaises(exception.ObjectActionError,
                          inst.obj_load_attr, 'foo')

    def test_create_and_load_keypairs_from_extra(self):
        inst = objects.Instance(context=self.context,
                                user_id=self.context.user_id,
                                project_id=self.context.project_id)
        inst.keypairs = objects.KeyPairList(objects=[
            objects.KeyPair(name='foo')])
        inst.create()

        inst = objects.Instance.get_by_uuid(self.context, inst.uuid,
                                            expected_attrs=['keypairs'])
        self.assertEqual('foo', inst.keypairs[0].name)

    def test_lazy_load_keypairs_from_extra(self):
        inst = objects.Instance(context=self.context,
                                user_id=self.context.user_id,
                                project_id=self.context.project_id)
        inst.keypairs = objects.KeyPairList(objects=[
            objects.KeyPair(name='foo')])
        inst.create()

        inst = objects.Instance.get_by_uuid(self.context, inst.uuid)
        self.assertNotIn('keypairs', inst)
        self.assertEqual('foo', inst.keypairs[0].name)
        self.assertNotIn('keypairs', inst.obj_what_changed())

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_lazy_load_flavor_from_extra(self, mock_get):
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
        # These disabled values are only here for logic testing purposes to
        # make sure we default the "new" flavor's disabled value to False on
        # load from the database.
        fake_flavor = jsonutils.dumps(
            {'cur': objects.Flavor(disabled=False,
                                   is_public=True).obj_to_primitive(),
             'old': objects.Flavor(disabled=True,
                                   is_public=False).obj_to_primitive(),
             'new': objects.Flavor().obj_to_primitive()})
        fake_inst = dict(self.fake_instance, extra={'flavor': fake_flavor})
        mock_get.return_value = fake_inst
        # Assert the disabled values on the flavors.
        self.assertFalse(inst.flavor.disabled)
        self.assertTrue(inst.old_flavor.disabled)
        self.assertFalse(inst.new_flavor.disabled)
        # Assert the is_public values on the flavors
        self.assertTrue(inst.flavor.is_public)
        self.assertFalse(inst.old_flavor.is_public)
        self.assertTrue(inst.new_flavor.is_public)

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_remote(self, mock_get):
        # isotime doesn't have microseconds and is always UTC
        fake_instance = self.fake_instance
        mock_get.return_value = fake_instance

        inst = objects.Instance.get_by_uuid(self.context, uuids.instance)
        self.assertEqual(fake_instance['id'], inst.id)
        self.assertEqual(fake_instance['launched_at'],
                         inst.launched_at.replace(tzinfo=None))
        self.assertEqual(fake_instance['access_ip_v4'],
                         str(inst.access_ip_v4))
        self.assertEqual(fake_instance['access_ip_v6'],
                         str(inst.access_ip_v6))

        mock_get.assert_called_once_with(self.context, uuids.instance,
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(instance_info_cache.InstanceInfoCache, 'refresh')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_refresh(self, mock_get, mock_refresh):
        fake_uuid = self.fake_instance['uuid']
        fake_inst = dict(self.fake_instance, host='orig-host')
        fake_inst2 = dict(self.fake_instance, host='new-host')
        mock_get.side_effect = [fake_inst, fake_inst2]

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual('orig-host', inst.host)
        inst.refresh()
        self.assertEqual('new-host', inst.host)
        self.assertEqual(set([]), inst.obj_what_changed())

        get_call_list = [mock.call(self.context, fake_uuid,
                                   columns_to_join=['info_cache',
                                                    'security_groups']),
                         mock.call(self.context, fake_uuid,
                                   columns_to_join=['info_cache',
                                                    'security_groups']),
                         ]
        mock_get.assert_has_calls(get_call_list, any_order=False)
        mock_refresh.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_refresh_does_not_recurse(self, mock_get):
        inst = objects.Instance(context=self.context, uuid=uuids.instance,
                                metadata={})
        inst_copy = objects.Instance()
        inst_copy.uuid = inst.uuid

        mock_get.return_value = inst_copy

        inst.refresh()
        mock_get.assert_called_once_with(self.context, uuid=inst.uuid,
            expected_attrs=['metadata'], use_slave=False)

    @mock.patch.object(notifications, 'send_update')
    @mock.patch.object(db, 'instance_info_cache_update')
    @mock.patch.object(db, 'instance_update_and_get_original')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def _save_test_helper(self, save_kwargs,
                          mock_db_instance_get_by_uuid,
                          mock_db_instance_update_and_get_original,
                          mock_db_instance_info_cache_update,
                          mock_notifications_send_update):
        """Common code for testing save() for cells/non-cells."""
        old_ref = dict(self.fake_instance, host='oldhost', user_data='old',
                       vm_state='old', task_state='old')
        fake_uuid = old_ref['uuid']

        expected_updates = dict(vm_state='meow', task_state='wuff',
                                user_data='new')

        new_ref = dict(old_ref, host='newhost', **expected_updates)
        exp_vm_state = save_kwargs.get('expected_vm_state')
        exp_task_state = save_kwargs.get('expected_task_state')
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
        mock_db_instance_get_by_uuid.return_value = old_ref
        mock_db_instance_update_and_get_original\
            .return_value = (old_ref, new_ref)

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
        mock_db_instance_get_by_uuid.assert_called_once_with(
            self.context, fake_uuid, columns_to_join=['info_cache',
                                                      'security_groups'])
        mock_db_instance_update_and_get_original.assert_called_once_with(
            self.context, fake_uuid, expected_updates,
            columns_to_join=['info_cache', 'security_groups',
                             'system_metadata']
        )
        mock_notifications_send_update.assert_called_with(self.context,
                                                          mock.ANY,
                                                          mock.ANY)

    def test_save(self):
        self._save_test_helper({})

    def test_save_exp_vm_state(self):
        self._save_test_helper({'expected_vm_state': ['meow']})

    def test_save_exp_task_state(self):
        self._save_test_helper({'expected_task_state': ['meow']})

    @mock.patch.object(db, 'instance_update_and_get_original')
    @mock.patch.object(db, 'instance_get_by_uuid')
    @mock.patch.object(notifications, 'send_update')
    def test_save_rename_sends_notification(self, mock_send, mock_get,
                                            mock_update_and_get):
        old_ref = dict(self.fake_instance, display_name='hello')
        fake_uuid = old_ref['uuid']
        expected_updates = dict(display_name='goodbye')
        new_ref = dict(old_ref, **expected_updates)

        mock_get.return_value = old_ref
        mock_update_and_get.return_value = (old_ref, new_ref)

        inst = objects.Instance.get_by_uuid(self.context, old_ref['uuid'],
                                            use_slave=False)
        self.assertEqual('hello', inst.display_name)
        inst.display_name = 'goodbye'
        inst.save()
        self.assertEqual('goodbye', inst.display_name)
        # NOTE(danms): Ignore flavor migrations for the moment
        self.assertEqual(set([]), inst.obj_what_changed() - set(['flavor']))

        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])
        mock_update_and_get.assert_called_once_with(self.context, fake_uuid,
            expected_updates, columns_to_join=['info_cache', 'security_groups',
            'system_metadata'])
        mock_send.assert_called_once_with(self.context, mock.ANY, mock.ANY)

    @mock.patch('nova.db.api.instance_extra_update_by_uuid')
    def test_save_object_pci_requests(self, mock_instance_extra_update):
        expected_json = ('[{"count": 1, "alias_name": null, "is_new": false,'
                         '"request_id": null, "requester_id": null,'
                         '"spec": [{"vendor_id": "8086", '
                         '"product_id": "1502"}], "numa_policy": null}]')

        inst = objects.Instance()
        inst = objects.Instance._from_db_object(self.context, inst,
                self.fake_instance)
        inst.obj_reset_changes()
        pci_req_obj = objects.InstancePCIRequest(
            count=1, spec=[{'vendor_id': '8086', 'product_id': '1502'}])
        inst.pci_requests = (
            objects.InstancePCIRequests(requests=[pci_req_obj]))
        inst.pci_requests.instance_uuid = inst.uuid
        inst.save()
        mock_instance_extra_update.assert_called_once_with(
            self.context, inst.uuid, mock.ANY)
        actual_args = (
            mock_instance_extra_update.call_args[0][2]['pci_requests'])
        mock_instance_extra_update.reset_mock()
        self.assertJsonEqual(expected_json, actual_args)
        inst.pci_requests = None
        inst.save()
        mock_instance_extra_update.assert_called_once_with(
            self.context, inst.uuid, {'pci_requests': None})
        mock_instance_extra_update.reset_mock()
        inst.obj_reset_changes()
        inst.save()
        self.assertFalse(mock_instance_extra_update.called)

    @mock.patch('nova.db.api.instance_update_and_get_original')
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

    @mock.patch('nova.db.api.instance_extra_update_by_uuid')
    @mock.patch('nova.db.api.instance_update_and_get_original')
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

    @mock.patch('nova.db.api.instance_extra_update_by_uuid')
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

    @mock.patch('nova.db.api.instance_extra_update_by_uuid')
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
        with mock.patch(
                'nova.db.api.instance_extra_update_by_uuid') as mock_upd:
            inst.save()
            self.assertFalse(mock_upd.called)

    @mock.patch('nova.db.api.instance_extra_update_by_uuid')
    def test_save_multiple_extras_updates_once(self, mock_update):
        inst = fake_instance.fake_instance_obj(self.context)
        inst.numa_topology = None
        inst.migration_context = None
        inst.vcpu_model = test_vcpu_model.fake_vcpumodel
        inst.keypairs = objects.KeyPairList(
            objects=[objects.KeyPair(name='foo')])

        json_vcpu_model = jsonutils.dumps(
            test_vcpu_model.fake_vcpumodel.obj_to_primitive())
        json_keypairs = jsonutils.dumps(inst.keypairs.obj_to_primitive())

        # Check changed fields in the instance object
        self.assertIn('keypairs', inst.obj_what_changed())
        self.assertEqual({'objects'}, inst.keypairs.obj_what_changed())

        inst.save()

        expected_vals = {
            'numa_topology': None,
            'migration_context': None,
            'vcpu_model': json_vcpu_model,
            'keypairs': json_keypairs,
        }
        mock_update.assert_called_once_with(self.context, inst.uuid,
                                            expected_vals)

        # Verify that the record of changed fields has been cleared
        self.assertNotIn('keypairs', inst.obj_what_changed())
        self.assertEqual(set(), inst.keypairs.obj_what_changed())

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_deleted(self, mock_get):
        fake_inst = dict(self.fake_instance, id=123, deleted=123)
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(danms): Make sure it's actually a bool
        self.assertTrue(inst.deleted)
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_not_cleaned(self, mock_get):
        fake_inst = dict(self.fake_instance, id=123, cleaned=None)
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertFalse(inst.cleaned)
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_cleaned(self, mock_get):
        fake_inst = dict(self.fake_instance, id=123, cleaned=1)
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        # NOTE(mikal): Make sure it's actually a bool
        self.assertTrue(inst.cleaned)
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(db, 'instance_update_and_get_original')
    @mock.patch.object(db, 'instance_info_cache_update')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_info_cache(self, mock_get, mock_upd_cache, mock_upd_and_get):
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

        mock_get.return_value = fake_inst
        mock_upd_cache.return_value = fake_info_cache

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(nwinfo1, inst.info_cache.network_info)
        self.assertEqual(fake_uuid, inst.info_cache.instance_uuid)
        inst.info_cache.network_info = nwinfo2
        inst.save()

        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])
        mock_upd_cache.assert_called_once_with(self.context, fake_uuid,
            {'network_info': nwinfo2_json})
        self.assertFalse(mock_upd_and_get.called)

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_info_cache_none(self, mock_get):
        fake_inst = dict(self.fake_instance, info_cache=None)
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
                                             ['info_cache'])
        self.assertIsNone(inst.info_cache)
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache'])

    def test_get_network_info_with_cache(self):
        info_cache = instance_info_cache.InstanceInfoCache()
        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        info_cache.network_info = nwinfo
        inst = objects.Instance(context=self.context,
                                info_cache=info_cache)

        self.assertEqual(nwinfo, inst.get_network_info())

    def test_get_network_info_without_cache(self):
        inst = objects.Instance(context=self.context, info_cache=None)

        self.assertEqual(network_model.NetworkInfo.hydrate([]),
                         inst.get_network_info())

    @mock.patch.object(db, 'security_group_update')
    @mock.patch.object(db, 'instance_update_and_get_original')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_security_groups(self, mock_get, mock_upd_and_get,
                                  mock_upd_secgrp):
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

        mock_get.return_value = fake_inst
        mock_upd_secgrp.return_value = fake_inst['security_groups'][0]

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(2, len(inst.security_groups))
        for index, group in enumerate(fake_inst['security_groups']):
            for key in group:
                self.assertEqual(group[key],
                                 getattr(inst.security_groups[index], key))
                self.assertIsInstance(inst.security_groups[index],
                                      security_group.SecurityGroup)
        self.assertEqual(set(), inst.security_groups.obj_what_changed())
        inst.security_groups[0].description = 'changed'
        inst.save()
        self.assertEqual(set(), inst.security_groups.obj_what_changed())

        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])
        mock_upd_secgrp.assert_called_once_with(self.context, 1,
            {'description': 'changed'})
        self.assertFalse(mock_upd_and_get.called)

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_empty_security_groups(self, mock_get):
        fake_inst = dict(self.fake_instance, security_groups=[])
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid)
        self.assertEqual(0, len(inst.security_groups))
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['info_cache', 'security_groups'])

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_empty_pci_devices(self, mock_get):
        fake_inst = dict(self.fake_instance, pci_devices=[])
        fake_uuid = fake_inst['uuid']
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(0, len(inst.pci_devices))
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['pci_devices'])

    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_pci_devices(self, mock_get):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_inst['pci_devices'] = [
            {'created_at': None,
             'updated_at': None,
             'deleted_at': None,
             'deleted': None,
             'id': 2,
             'uuid': uuids.pci_device2,
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
             'uuid': uuids.pci_device1,
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
        mock_get.return_value = fake_inst

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
            ['pci_devices'])
        self.assertEqual(2, len(inst.pci_devices))
        self.assertEqual(fake_uuid, inst.pci_devices[0].instance_uuid)
        self.assertEqual(fake_uuid, inst.pci_devices[1].instance_uuid)
        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['pci_devices'])

    @mock.patch.object(db, 'instance_fault_get_by_instance_uuids')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_with_fault(self, mock_get, mock_fault_get):
        fake_inst = dict(self.fake_instance)
        fake_uuid = fake_inst['uuid']
        fake_faults = [dict(x, instance_uuid=fake_uuid)
                       for x in test_instance_fault.fake_faults['fake-uuid']]

        mock_get.return_value = self.fake_instance
        mock_fault_get.return_value = {fake_uuid: fake_faults}

        inst = objects.Instance.get_by_uuid(self.context, fake_uuid,
                                            expected_attrs=['fault'])
        self.assertEqual(fake_faults[0], dict(inst.fault.items()))

        mock_get.assert_called_once_with(self.context, fake_uuid,
            columns_to_join=['fault'])
        mock_fault_get.assert_called_once_with(self.context, [fake_uuid])

    @mock.patch('nova.objects.EC2Ids.get_by_instance')
    @mock.patch('nova.db.api.instance_get_by_uuid')
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

    @mock.patch('nova.db.api.instance_get_by_uuid')
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
        self.stub_out('nova.objects.Instance.name', 'foo')
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

    @mock.patch.object(db, 'instance_create')
    def test_create_skip_scheduled_at(self, mock_create):
        vals = {'host': 'foo-host',
                'deleted': 0,
                'memory_mb': 128,
                'system_metadata': {'foo': 'bar'},
                'extra': {
                    'vcpu_model': None,
                    'numa_topology': None,
                    'pci_requests': None,
                    'device_metadata': None,
                    'trusted_certs': None,
                    'resources': None,
                }}
        fake_inst = fake_instance.fake_db_instance(**vals)
        mock_create.return_value = fake_inst

        inst = objects.Instance(context=self.context,
                                host='foo-host', memory_mb=128,
                                scheduled_at=None,
                                system_metadata={'foo': 'bar'})
        inst.create()
        self.assertEqual('foo-host', inst.host)
        mock_create.assert_called_once_with(self.context, vals)

    def test_metadata_change_tracking(self):
        self._test_metadata_change_tracking('metadata')

    def test_system_metadata_change_tracking(self):
        self._test_metadata_change_tracking('system_metadata')

    @mock.patch.object(db, 'instance_create')
    def test_create_stubbed(self, mock_create):
        vals = {'host': 'foo-host',
                'deleted': 0,
                'memory_mb': 128,
                'system_metadata': {'foo': 'bar'},
                'extra': {
                    'vcpu_model': None,
                    'numa_topology': None,
                    'pci_requests': None,
                    'device_metadata': None,
                    'trusted_certs': None,
                    'resources': None,
                }}
        fake_inst = fake_instance.fake_db_instance(**vals)
        mock_create.return_value = fake_inst

        inst = objects.Instance(context=self.context,
                                host='foo-host', memory_mb=128,
                                system_metadata={'foo': 'bar'})
        inst.create()
        mock_create.assert_called_once_with(self.context, vals)

    @mock.patch.object(db, 'instance_create')
    def test_create(self, mock_create):
        extras = {'vcpu_model': None,
                  'numa_topology': None,
                  'pci_requests': None,
                  'device_metadata': None,
                  'trusted_certs': None,
                  'resources': None,
                  }
        mock_create.return_value = self.fake_instance
        inst = objects.Instance(context=self.context)
        inst.create()

        self.assertEqual(self.fake_instance['id'], inst.id)
        self.assertIsNotNone(inst.ec2_ids)
        mock_create.assert_called_once_with(self.context, {'deleted': 0,
                                                           'extra': extras})

    def test_create_with_values(self):
        inst1 = objects.Instance(context=self.context,
                                 user_id=self.context.user_id,
                                 project_id=self.context.project_id,
                                 host='foo-host')
        inst1.create()
        self.assertEqual('foo-host', inst1.host)
        inst2 = objects.Instance.get_by_uuid(self.context, inst1.uuid)
        self.assertEqual('foo-host', inst2.host)

    def test_create_deleted(self):
        inst1 = objects.Instance(context=self.context,
                                 user_id=self.context.user_id,
                                 project_id=self.context.project_id,
                                 deleted=True)
        self.assertRaises(exception.ObjectActionError, inst1.create)

    def test_create_with_extras(self):
        inst = objects.Instance(context=self.context,
            uuid=self.fake_instance['uuid'],
            numa_topology=test_instance_numa.fake_obj_numa_topology,
            pci_requests=objects.InstancePCIRequests(
                requests=[
                    objects.InstancePCIRequest(count=123,
                                               spec=[])]),
            vcpu_model=test_vcpu_model.fake_vcpumodel,
            trusted_certs=objects.TrustedCerts(ids=['123foo']),
            resources=objects.ResourceList(objects=[objects.Resource(
                provider_uuid=uuids.rp, resource_class='CUSTOM_FOO',
                identifier='foo')])
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
        self.assertEqual(['123foo'], inst.trusted_certs.ids)
        self.assertEqual('foo', inst.resources[0].identifier)

    def test_recreate_fails(self):
        inst = objects.Instance(context=self.context,
                                user_id=self.context.user_id,
                                project_id=self.context.project_id,
                                host='foo-host')
        inst.create()
        self.assertRaises(exception.ObjectActionError, inst.create)

    @mock.patch.object(db, 'instance_create')
    def test_create_with_special_things(self, mock_create):
        fake_inst = fake_instance.fake_db_instance()
        mock_create.return_value = fake_inst

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

        mock_create.assert_called_once_with(self.context,
                           {'host': 'foo-host',
                            'deleted': 0,
                            'security_groups': ['foo', 'bar'],
                            'info_cache': {'network_info': '[]'},
                            'extra': {
                                'vcpu_model': None,
                                'numa_topology': None,
                                'pci_requests': None,
                                'device_metadata': None,
                                'trusted_certs': None,
                                'resources': None,
                            },
                            })

    @mock.patch.object(db, 'instance_destroy')
    def test_destroy_stubbed(self, mock_destroy):
        deleted_at = datetime.datetime(1955, 11, 6)
        fake_inst = fake_instance.fake_db_instance(deleted_at=deleted_at,
                                                   deleted=True)
        mock_destroy.return_value = fake_inst

        inst = objects.Instance(context=self.context, id=1,
                                uuid=uuids.instance, host='foo')
        inst.destroy()
        self.assertEqual(timeutils.normalize_time(deleted_at),
                         timeutils.normalize_time(inst.deleted_at))
        self.assertTrue(inst.deleted)
        mock_destroy.assert_called_once_with(self.context, uuids.instance,
                                             constraint=None,
                                             hard_delete=False)

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

    def test_destroy_hard(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id}
        db_inst = db.instance_create(self.context, values)
        inst = objects.Instance(context=self.context, id=db_inst['id'],
                                uuid=db_inst['uuid'])
        inst.destroy(hard_delete=True)
        elevated = self.context.elevated(read_deleted="yes")
        self.assertRaises(exception.InstanceNotFound,
                          objects.Instance.get_by_uuid, elevated,
                          db_inst['uuid'])

    def test_destroy_hard_host_constraint(self):
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id,
                  'host': 'foo'}
        db_inst = db.instance_create(self.context, values)
        inst = objects.Instance.get_by_uuid(self.context, db_inst['uuid'])
        inst.host = None
        ex = self.assertRaises(exception.ObjectActionError,
                               inst.destroy, hard_delete=True)
        self.assertIn('host changed', six.text_type(ex))

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

    def test_name_blank_if_no_id_pre_scheduling(self):
        # inst.id is not set and can't be lazy loaded
        inst = objects.Instance(context=self.context,
                                vm_state=vm_states.BUILDING,
                                task_state=task_states.SCHEDULING)
        self.assertEqual('', inst.name)

    def test_name_uuid_if_no_id_post_scheduling(self):
        # inst.id is not set and can't be lazy loaded

        inst = objects.Instance(context=self.context,
                                uuid=uuids.instance,
                                vm_state=vm_states.ACTIVE,
                                task_state=None)
        self.assertEqual(uuids.instance, inst.name)

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

    @mock.patch('nova.db.api.instance_extra_get_by_instance_uuid',
                return_value=None)
    def test_from_db_object_no_extra_db_calls(self, mock_get):
        db_inst = fake_instance.fake_db_instance()
        instance.Instance._from_db_object(
            self.context, objects.Instance(), db_inst,
            expected_attrs=instance._INSTANCE_EXTRA_FIELDS)
        self.assertEqual(0, mock_get.call_count)

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
        db_flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
        inst = objects.Instance(flavor=db_flavor)
        self.assertEqual(db_flavor['flavorid'],
                         inst.get_flavor().flavorid)

    def test_get_flavor_namespace(self):
        db_flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
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
                                 numa_topology=None, pci_requests=None,
                                 pci_devices=None)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        inst.apply_migration_context()
        attrs_type = {'numa_topology': objects.InstanceNUMATopology,
                      'pci_requests': objects.InstancePCIRequests,
                      'pci_devices': objects.PciDeviceList,
                      'resources': objects.ResourceList}

        for attr_name in instance._MIGRATION_CONTEXT_ATTRS:
            value = getattr(inst, attr_name)
            self.assertIsInstance(value, attrs_type[attr_name])
        inst.revert_migration_context()
        for attr_name in instance._MIGRATION_CONTEXT_ATTRS:
            value = getattr(inst, attr_name)
            self.assertIsNone(value)

    def test_drop_migration_context(self):
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        inst.migration_context.instance_uuid = inst.uuid
        inst.migration_context.id = 7
        with mock.patch(
                'nova.db.api.instance_extra_update_by_uuid') as update_extra:
            inst.drop_migration_context()
            self.assertIsNone(inst.migration_context)
            update_extra.assert_called_once_with(self.context, inst.uuid,
                                                 {"migration_context": None})

    def test_mutated_migration_context(self):
        numa_topology = (test_instance_numa.
                            fake_obj_numa_topology.obj_clone())
        numa_topology.cells[0].memory = 1024
        numa_topology.cells[1].memory = 1024
        pci_requests = objects.InstancePCIRequests(requests=[
            objects.InstancePCIRequest(count=1, spec=[])])
        pci_devices = pci_device.PciDeviceList()
        resources = objects.ResourceList()

        inst = instance.Instance(context=self.context, uuid=uuids.instance,
                                 numa_topology=numa_topology,
                                 pci_requests=pci_requests,
                                 pci_devices=pci_devices,
                                 resources=resources)
        expected_objs = {'numa_topology': numa_topology,
                         'pci_requests': pci_requests,
                         'pci_devices': pci_devices,
                         'resources': resources}
        inst.migration_context = test_mig_ctxt.get_fake_migration_context_obj(
            self.context)
        with inst.mutated_migration_context():
            for attr_name in instance._MIGRATION_CONTEXT_ATTRS:
                inst_value = getattr(inst, attr_name)
                migration_context_value = (
                    getattr(inst.migration_context, 'new_' + attr_name))
                self.assertIs(inst_value, migration_context_value)

        for attr_name in instance._MIGRATION_CONTEXT_ATTRS:
            inst_value = getattr(inst, attr_name)
            self.assertIs(expected_objs[attr_name], inst_value)

    @mock.patch('nova.objects.Instance.obj_load_attr',
                new_callable=mock.NonCallableMock)  # asserts not called
    def test_mutated_migration_context_early_exit(self, obj_load_attr):
        """Tests that we exit early from mutated_migration_context if the
        migration_context attribute is set to None meaning this instance is
        not being migrated.
        """
        inst = instance.Instance(context=self.context, migration_context=None)
        for attr in instance._MIGRATION_CONTEXT_ATTRS:
            self.assertNotIn(attr, inst)
        with inst.mutated_migration_context():
            for attr in instance._MIGRATION_CONTEXT_ATTRS:
                self.assertNotIn(attr, inst)

    def test_clear_numa_topology(self):
        numa_topology = test_instance_numa.fake_obj_numa_topology.obj_clone()
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

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_load_something_unspecial(self, mock_get):
        inst2 = objects.Instance(vm_state=vm_states.ACTIVE,
                                 task_state=task_states.SCHEDULING)
        mock_get.return_value = inst2
        inst = instance.Instance(context=self.context, uuid=uuids.instance)
        self.assertEqual(vm_states.ACTIVE, inst.vm_state)
        self.assertEqual(task_states.SCHEDULING, inst.task_state)
        mock_get.assert_called_once_with(self.context,
                                         uuid=uuids.instance,
                                         expected_attrs=['vm_state'])

    @mock.patch('nova.db.api.instance_fault_get_by_instance_uuids')
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
        inst = objects.Instance(context=self.context, uuid=uuids.instance)
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

    @mock.patch('nova.objects.ResourceList.get_by_instance_uuid')
    def test_load_resources(self, mock_get):
        fake_resources = objects.ResourceList()
        mock_get.return_value = fake_resources
        inst = objects.Instance(context=self.context, uuid=uuids.resources)
        resources = inst.resources
        mock_get.assert_called_once_with(self.context, uuids.resources)
        self.assertEqual(fake_resources, resources)

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

    def test_obj_clone(self):
        # Make sure clone shows no changes when no metadata is set
        inst1 = objects.Instance(uuid=uuids.instance)
        inst1.obj_reset_changes()
        inst1 = inst1.obj_clone()
        self.assertEqual(len(inst1.obj_what_changed()), 0)
        # Make sure clone shows no changes when metadata is set
        inst1 = objects.Instance(uuid=uuids.instance)
        inst1.metadata = dict(key1='val1')
        inst1.system_metadata = dict(key1='val1')
        inst1.obj_reset_changes()
        inst1 = inst1.obj_clone()
        self.assertEqual(len(inst1.obj_what_changed()), 0)

    def test_obj_make_compatible(self):
        inst_obj = objects.Instance(
            # trusted_certs were added in 2.4
            trusted_certs=objects.TrustedCerts(ids=[uuids.cert1]),
            # hidden was added in 2.6
            hidden=True)
        versions = ovo_base.obj_tree_get_versions('Instance')
        data = lambda x: x['nova_object.data']
        primitive = data(inst_obj.obj_to_primitive(
            target_version='2.5', version_manifest=versions))
        self.assertIn('trusted_certs', primitive)
        self.assertNotIn('hidden', primitive)


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

    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters(self, mock_get_all):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

        mock_get_all.assert_called_once_with(self.context, {'foo': 'bar'},
            'uuid', 'asc', limit=None, marker=None,
            columns_to_join=['metadata'])

    @mock.patch.object(db, 'instance_get_all_by_filters_sort')
    def test_get_all_by_filters_sorted(self, mock_get_all):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'foo': 'bar'}, expected_attrs=['metadata'],
            use_slave=False, sort_keys=['uuid'], sort_dirs=['asc'])

        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

        mock_get_all.assert_called_once_with(self.context, {'foo': 'bar'},
                                            limit=None, marker=None,
                                            columns_to_join=['metadata'],
                                            sort_keys=['uuid'],
                                            sort_dirs=['asc'])

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

    @mock.patch.object(db, 'instance_get_all_by_filters')
    def test_get_all_by_filters_works_for_cleaned(self, mock_get_all):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2, updates={'deleted': 2,
                                                'cleaned': None})]
        self.context.read_deleted = 'yes'
        mock_get_all.return_value = [fakes[1]]

        inst_list = objects.InstanceList.get_by_filters(
            self.context, {'deleted': True, 'cleaned': False}, 'uuid', 'asc',
            expected_attrs=['metadata'], use_slave=False)

        self.assertEqual(1, len(inst_list))
        self.assertIsInstance(inst_list.objects[0], instance.Instance)
        self.assertEqual(fakes[1]['uuid'], inst_list.objects[0].uuid)

        mock_get_all.assert_called_once_with(
            self.context,
            {'deleted': True, 'cleaned': False},
            'uuid', 'asc',
            limit=None, marker=None,
            columns_to_join=['metadata'])

    @mock.patch.object(db, 'instance_get_all_by_host')
    def test_get_by_host(self, mock_get_all):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_by_host(self.context, 'foo')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)
            self.assertEqual(self.context, inst_list.objects[i]._context)
        self.assertEqual(set(), inst_list.obj_what_changed())

        mock_get_all.assert_called_once_with(self.context, 'foo',
                                             columns_to_join=None)

    @mock.patch.object(db, 'instance_get_all_by_host_and_node')
    def test_get_by_host_and_node(self, mock_get_all):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_by_host_and_node(self.context,
                                                              'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

        mock_get_all.assert_called_once_with(self.context, 'foo', 'bar',
                                             columns_to_join=None)

    @mock.patch.object(db, 'instance_get_all_by_host_and_not_type')
    def test_get_by_host_and_not_type(self, mock_get_all):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_by_host_and_not_type(
            self.context, 'foo', 'bar')
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

        mock_get_all.assert_called_once_with(self.context, 'foo',
                                             type_id='bar')

    @mock.patch('nova.objects.instance._expected_cols')
    @mock.patch('nova.db.api.instance_get_all')
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

    @mock.patch.object(db, 'instance_get_all_hung_in_rebooting')
    def test_get_hung_in_rebooting(self, mock_get_all):
        fakes = [self.fake_instance(1),
                 self.fake_instance(2)]
        dt = utils.isotime()
        mock_get_all.return_value = fakes

        inst_list = objects.InstanceList.get_hung_in_rebooting(self.context,
                                                               dt)
        for i in range(0, len(fakes)):
            self.assertIsInstance(inst_list.objects[i], instance.Instance)
            self.assertEqual(fakes[i]['uuid'], inst_list.objects[i].uuid)

        mock_get_all.assert_called_once_with(self.context, dt)

    def test_get_active_by_window_joined(self):
        fakes = [self.fake_instance(1), self.fake_instance(2)]
        # NOTE(mriedem): Send in a timezone-naive datetime since the
        # InstanceList.get_active_by_window_joined method should convert it
        # to tz-aware for the DB API call, which we'll assert with our stub.
        dt = timeutils.utcnow()

        def fake_instance_get_active_by_window_joined(context, begin, end,
                                                      project_id, host,
                                                      columns_to_join,
                                                      limit=None, marker=None):
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

    @mock.patch.object(db, 'instance_fault_get_by_instance_uuids')
    @mock.patch.object(db, 'instance_get_all_by_host')
    def test_with_fault(self, mock_get_all, mock_fault_get):
        fake_insts = [
            fake_instance.fake_db_instance(uuid=uuids.faults_instance,
                                           host='host'),
            fake_instance.fake_db_instance(uuid=uuids.faults_instance_nonexist,
                                           host='host'),
            ]
        fake_faults = test_instance_fault.fake_faults

        mock_get_all.return_value = fake_insts
        mock_fault_get.return_value = fake_faults

        instances = objects.InstanceList.get_by_host(self.context, 'host',
                                                     expected_attrs=['fault'],
                                                     use_slave=False)
        self.assertEqual(2, len(instances))
        self.assertEqual(fake_faults['fake-uuid'][0],
                         dict(instances[0].fault))
        self.assertIsNone(instances[1].fault)

        mock_get_all.assert_called_once_with(self.context, 'host',
            columns_to_join=['fault'])
        mock_fault_get.assert_called_once_with(self.context,
            [x['uuid'] for x in fake_insts])

    @mock.patch.object(db, 'instance_fault_get_by_instance_uuids')
    def test_fill_faults(self, mock_fault_get):
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
        mock_fault_get.return_value = db_faults

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

        mock_fault_get.assert_called_once_with(self.context,
                                               [x.uuid for x in insts],
                                               latest=True)

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

    def test_get_by_security_group_after_destroy(self):
        db_sg = db.security_group_create(
            self.context,
            {'name': 'foo',
             'description': 'test group',
             'user_id': self.context.user_id,
             'project_id': self.context.project_id})
        self.assertFalse(db.security_group_in_use(self.context, db_sg.id))
        inst = objects.Instance(
            context=self.context,
            user_id=self.context.user_id,
            project_id=self.context.project_id)
        inst.create()

        db.instance_add_security_group(self.context,
                                       inst.uuid,
                                       db_sg.id)

        self.assertTrue(db.security_group_in_use(self.context, db_sg.id))
        inst.destroy()
        self.assertFalse(db.security_group_in_use(self.context, db_sg.id))

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

    @mock.patch('nova.db.api.instance_get_all_uuids_by_hosts')
    def test_get_uuids_by_host_no_match(self, mock_get_all):
        mock_get_all.return_value = collections.defaultdict(list)
        actual_uuids = objects.InstanceList.get_uuids_by_host(
            self.context, 'b')
        self.assertEqual([], actual_uuids)
        mock_get_all.assert_called_once_with(self.context, ['b'])

    @mock.patch('nova.db.api.instance_get_all_uuids_by_hosts')
    def test_get_uuids_by_host(self, mock_get_all):
        fake_instances = [uuids.inst1, uuids.inst2]
        mock_get_all.return_value = {
            'b': fake_instances
        }
        actual_uuids = objects.InstanceList.get_uuids_by_host(
            self.context, 'b')
        self.assertEqual(fake_instances, actual_uuids)
        mock_get_all.assert_called_once_with(self.context, ['b'])

    @mock.patch('nova.db.api.instance_get_all_uuids_by_hosts')
    def test_get_uuids_by_hosts(self, mock_get_all):
        fake_instances_a = [uuids.inst1, uuids.inst2]
        fake_instances_b = [uuids.inst3, uuids.inst4]
        fake_instances = {
            'a': fake_instances_a,
            'b': fake_instances_b
        }
        mock_get_all.return_value = fake_instances
        actual_uuids = objects.InstanceList.get_uuids_by_hosts(
            self.context, ['a', 'b'])
        self.assertEqual(fake_instances, actual_uuids)
        mock_get_all.assert_called_once_with(self.context, ['a', 'b'])


class TestInstanceListObject(test_objects._LocalTest,
                             _TestInstanceListObject):
    # No point in doing this db-specific test twice for remote
    def test_hidden_filter_query(self):
        """Check that our instance_get_by_filters() honors hidden properly

        As reported in bug #1862205, we need to properly handle instances
        with the hidden field set to NULL and not expect SQLAlchemy to
        translate those values on SELECT.
        """
        values = {'user_id': self.context.user_id,
                  'project_id': self.context.project_id,
                  'host': 'foo'}

        for hidden_value in (True, False):
            db.instance_create(self.context,
                               dict(values, hidden=hidden_value))

        # NOTE(danms): Because the model has default=False, we can not use
        # it to create an instance with a hidden value of NULL. So, do it
        # manually here.
        engine = sql_api.get_engine()
        table = sql_models.Instance.__table__
        with engine.connect() as conn:
            update = table.insert().values(user_id=self.context.user_id,
                                           project_id=self.context.project_id,
                                           uuid=uuids.nullinst,
                                           host='foo',
                                           hidden=None)
            conn.execute(update)

        insts = objects.InstanceList.get_by_filters(self.context,
                                                    {'hidden': True})
        # We created one hidden instance above, so expect only that one
        # to come out of this query.
        self.assertEqual(1, len(insts))

        # We created one unhidden instance above, and one specifically
        # with a NULL value to represent an unmigrated instance, which
        # defaults to hidden=False, so expect both of those here.
        insts = objects.InstanceList.get_by_filters(self.context,
                                                    {'hidden': False})
        self.assertEqual(2, len(insts))

        # Do the same check as above, but make sure hidden=False is the
        # default behavior.
        insts = objects.InstanceList.get_by_filters(self.context,
                                                    {})
        self.assertEqual(2, len(insts))


class TestRemoteInstanceListObject(test_objects._RemoteTest,
                                   _TestInstanceListObject):
    pass


class TestInstanceObjectMisc(test.NoDBTestCase):
    def test_expected_cols(self):
        self.stub_out('nova.objects.instance._INSTANCE_OPTIONAL_JOINED_FIELDS',
                      ['bar'])
        self.assertEqual(['bar'], instance._expected_cols(['foo', 'bar']))
        self.assertIsNone(instance._expected_cols(None))

    def test_expected_cols_extra(self):
        self.assertEqual(['metadata', 'extra', 'extra.numa_topology'],
                         instance._expected_cols(['metadata',
                                                  'numa_topology']))

    def test_expected_cols_no_duplicates(self):
        expected_attr = ['metadata', 'system_metadata', 'info_cache',
                         'security_groups', 'info_cache', 'metadata',
                         'pci_devices', 'tags', 'extra', 'flavor']

        result_list = instance._expected_cols(expected_attr)

        self.assertEqual(len(result_list), len(set(expected_attr)))
        self.assertEqual(['metadata', 'system_metadata', 'info_cache',
                         'security_groups', 'pci_devices', 'tags', 'extra',
                         'extra.flavor'], result_list)
