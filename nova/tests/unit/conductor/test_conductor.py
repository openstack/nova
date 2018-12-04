#    Copyright 2012 IBM Corp.
#    Copyright 2013 Red Hat, Inc.
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

"""Tests for the conductor service."""

import copy

import mock
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import timeutils
from oslo_versionedobjects import exception as ovo_exc
import six

from nova import block_device
from nova.compute import flavors
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova.conductor.tasks import live_migrate
from nova.conductor.tasks import migrate
from nova import conf
from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception as exc
from nova.image import api as image_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import fields
from nova.scheduler import client as scheduler_client
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests import fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import cast_as_call
from nova.tests.unit.compute import test_compute
from nova.tests.unit import fake_build_request
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_notifier
from nova.tests.unit import fake_request_spec
from nova.tests.unit import fake_server_actions
from nova.tests.unit import utils as test_utils
from nova.tests import uuidsentinel as uuids
from nova import utils
from nova.volume import cinder

CONF = conf.CONF


fake_alloc1 = {"allocations": [
        {"resource_provider": {"uuid": uuids.host1},
         "resources": {"VCPU": 1,
                       "MEMORY_MB": 1024,
                       "DISK_GB": 100}
        }]}
fake_alloc2 = {"allocations": [
        {"resource_provider": {"uuid": uuids.host2},
         "resources": {"VCPU": 1,
                       "MEMORY_MB": 1024,
                       "DISK_GB": 100}
        }]}
fake_alloc3 = {"allocations": [
        {"resource_provider": {"uuid": uuids.host3},
         "resources": {"VCPU": 1,
                       "MEMORY_MB": 1024,
                       "DISK_GB": 100}
        }]}
fake_alloc_json1 = jsonutils.dumps(fake_alloc1)
fake_alloc_json2 = jsonutils.dumps(fake_alloc2)
fake_alloc_json3 = jsonutils.dumps(fake_alloc3)
fake_alloc_version = "1.23"
fake_selection1 = objects.Selection(service_host="host1", nodename="node1",
        cell_uuid=uuids.cell, limits=None, allocation_request=fake_alloc_json1,
        allocation_request_version=fake_alloc_version)
fake_selection2 = objects.Selection(service_host="host2", nodename="node2",
        cell_uuid=uuids.cell, limits=None, allocation_request=fake_alloc_json2,
        allocation_request_version=fake_alloc_version)
fake_selection3 = objects.Selection(service_host="host3", nodename="node3",
        cell_uuid=uuids.cell, limits=None, allocation_request=fake_alloc_json3,
        allocation_request_version=fake_alloc_version)
fake_host_lists1 = [[fake_selection1]]
fake_host_lists2 = [[fake_selection1], [fake_selection2]]
fake_host_lists_alt = [[fake_selection1, fake_selection2, fake_selection3]]


class FakeContext(context.RequestContext):
    def elevated(self):
        """Return a consistent elevated context so we can detect it."""
        if not hasattr(self, '_elevated'):
            self._elevated = super(FakeContext, self).elevated()
        return self._elevated


class _BaseTestCase(object):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.user_id = fakes.FAKE_USER_ID
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = FakeContext(self.user_id, self.project_id)

        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

        def fake_deserialize_context(serializer, ctxt_dict):
            self.assertEqual(self.context.user_id, ctxt_dict['user_id'])
            self.assertEqual(self.context.project_id, ctxt_dict['project_id'])
            return self.context

        self.stub_out('nova.rpc.RequestContextSerializer.deserialize_context',
                      fake_deserialize_context)

        self.useFixture(fixtures.SpawnIsSynchronousFixture())


class ConductorTestCase(_BaseTestCase, test.TestCase):
    """Conductor Manager Tests."""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.conductor_manager = self.conductor

    def _test_object_action(self, is_classmethod, raise_exception):
        class TestObject(obj_base.NovaObject):
            def foo(self, raise_exception=False):
                if raise_exception:
                    raise Exception('test')
                else:
                    return 'test'

            @classmethod
            def bar(cls, context, raise_exception=False):
                if raise_exception:
                    raise Exception('test')
                else:
                    return 'test'

        obj_base.NovaObjectRegistry.register(TestObject)

        obj = TestObject()
        # NOTE(danms): After a trip over RPC, any tuple will be a list,
        # so use a list here to make sure we can handle it
        fake_args = []
        if is_classmethod:
            versions = {'TestObject': '1.0'}
            result = self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'bar', versions,
                fake_args, {'raise_exception': raise_exception})
        else:
            updates, result = self.conductor.object_action(
                self.context, obj, 'foo', fake_args,
                {'raise_exception': raise_exception})
        self.assertEqual('test', result)

    def test_object_action(self):
        self._test_object_action(False, False)

    def test_object_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, False, True)

    def test_object_class_action(self):
        self._test_object_action(True, False)

    def test_object_class_action_on_raise(self):
        self.assertRaises(messaging.ExpectedException,
                          self._test_object_action, True, True)

    def test_object_action_copies_object(self):
        class TestObject(obj_base.NovaObject):
            fields = {'dict': fields.DictOfStringsField()}

            def touch_dict(self):
                self.dict['foo'] = 'bar'
                self.obj_reset_changes()

        obj_base.NovaObjectRegistry.register(TestObject)

        obj = TestObject()
        obj.dict = {}
        obj.obj_reset_changes()
        updates, result = self.conductor.object_action(
            self.context, obj, 'touch_dict', tuple(), {})
        # NOTE(danms): If conductor did not properly copy the object, then
        # the new and reference copies of the nested dict object will be
        # the same, and thus 'dict' will not be reported as changed
        self.assertIn('dict', updates)
        self.assertEqual({'foo': 'bar'}, updates['dict'])

    def test_object_class_action_versions(self):
        @obj_base.NovaObjectRegistry.register
        class TestObject(obj_base.NovaObject):
            VERSION = '1.10'

            @classmethod
            def foo(cls, context):
                return cls()

        versions = {
            'TestObject': '1.2',
            'OtherObj': '1.0',
        }
        with mock.patch.object(self.conductor_manager,
                               '_object_dispatch') as m:
            m.return_value = TestObject()
            m.return_value.obj_to_primitive = mock.MagicMock()
            self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'foo', versions,
                tuple(), {})
            m.return_value.obj_to_primitive.assert_called_once_with(
                target_version='1.2', version_manifest=versions)

    def test_object_class_action_versions_old_object(self):
        # Make sure we return older than requested objects unmodified,
        # see bug #1596119.
        @obj_base.NovaObjectRegistry.register
        class TestObject(obj_base.NovaObject):
            VERSION = '1.10'

            @classmethod
            def foo(cls, context):
                return cls()

        versions = {
            'TestObject': '1.10',
            'OtherObj': '1.0',
        }
        with mock.patch.object(self.conductor_manager,
                               '_object_dispatch') as m:
            m.return_value = TestObject()
            m.return_value.VERSION = '1.9'
            m.return_value.obj_to_primitive = mock.MagicMock()
            obj = self.conductor.object_class_action_versions(
                self.context, TestObject.obj_name(), 'foo', versions,
                tuple(), {})
            self.assertFalse(m.return_value.obj_to_primitive.called)
            self.assertEqual('1.9', obj.VERSION)

    def test_object_class_action_versions_major_version_diff(self):
        @obj_base.NovaObjectRegistry.register
        class TestObject(obj_base.NovaObject):
            VERSION = '2.10'

            @classmethod
            def foo(cls, context):
                return cls()

        versions = {
            'TestObject': '2.10',
            'OtherObj': '1.0',
        }
        with mock.patch.object(self.conductor_manager,
                               '_object_dispatch') as m:
            m.return_value = TestObject()
            m.return_value.VERSION = '1.9'
            self.assertRaises(
                ovo_exc.InvalidTargetVersion,
                self.conductor.object_class_action_versions,
                self.context, TestObject.obj_name(), 'foo', versions,
                tuple(), {})

    def test_reset(self):
        with mock.patch.object(objects.Service, 'clear_min_version_cache'
                               ) as mock_clear_cache:
            self.conductor.reset()
            mock_clear_cache.assert_called_once_with()

    def test_provider_fw_rule_get_all(self):
        result = self.conductor.provider_fw_rule_get_all(self.context)
        self.assertEqual([], result)

    def test_conductor_host(self):
        self.assertTrue(hasattr(self.conductor_manager, 'host'))
        self.assertEqual(CONF.host, self.conductor_manager.host)


class ConductorRPCAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor RPC API Tests."""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor_manager = self.conductor_service.manager
        self.conductor = conductor_rpcapi.ConductorAPI()


class ConductorAPITestCase(_BaseTestCase, test.TestCase):
    """Conductor API Tests."""
    def setUp(self):
        super(ConductorAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.API()
        self.conductor_manager = self.conductor_service.manager

    def test_wait_until_ready(self):
        timeouts = []
        calls = dict(count=0)

        def fake_ping(self, context, message, timeout):
            timeouts.append(timeout)
            calls['count'] += 1
            if calls['count'] < 15:
                raise messaging.MessagingTimeout("fake")

        self.stub_out('nova.baserpc.BaseAPI.ping', fake_ping)

        self.conductor.wait_until_ready(self.context)

        self.assertEqual(timeouts.count(10), 10)
        self.assertIn(None, timeouts)


class _BaseTaskTestCase(object):
    def setUp(self):
        super(_BaseTaskTestCase, self).setUp()
        self.user_id = fakes.FAKE_USER_ID
        self.project_id = fakes.FAKE_PROJECT_ID
        self.context = FakeContext(self.user_id, self.project_id)
        fake_server_actions.stub_out_action_events(self)

        def fake_deserialize_context(serializer, ctxt_dict):
            self.assertEqual(self.context.user_id, ctxt_dict['user_id'])
            self.assertEqual(self.context.project_id, ctxt_dict['project_id'])
            return self.context

        self.stub_out('nova.rpc.RequestContextSerializer.deserialize_context',
                      fake_deserialize_context)

        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        _p = mock.patch('nova.compute.utils.heal_reqspec_is_bfv')
        self.heal_reqspec_is_bfv_mock = _p.start()
        self.addCleanup(_p.stop)

        _p = mock.patch('nova.objects.RequestSpec.ensure_network_metadata')
        self.ensure_network_metadata_mock = _p.start()
        self.addCleanup(_p.stop)

    def _prepare_rebuild_args(self, update_args=None):
        # Args that don't get passed in to the method but do get passed to RPC
        migration = update_args and update_args.pop('migration', None)
        node = update_args and update_args.pop('node', None)
        limits = update_args and update_args.pop('limits', None)

        rebuild_args = {'new_pass': 'admin_password',
                        'injected_files': 'files_to_inject',
                        'image_ref': uuids.image_ref,
                        'orig_image_ref': uuids.orig_image_ref,
                        'orig_sys_metadata': 'orig_sys_meta',
                        'bdms': {},
                        'recreate': False,
                        'on_shared_storage': False,
                        'preserve_ephemeral': False,
                        'host': 'compute-host',
                        'request_spec': None}
        if update_args:
            rebuild_args.update(update_args)
        compute_rebuild_args = copy.deepcopy(rebuild_args)
        compute_rebuild_args['migration'] = migration
        compute_rebuild_args['node'] = node
        compute_rebuild_args['limits'] = limits

        return rebuild_args, compute_rebuild_args

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    def _test_cold_migrate(self, spec_from_components, get_image_from_metadata,
                           migration_task_execute, spec_save, get_im,
                           clean_shutdown=True):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])
        get_image_from_metadata.return_value = 'image'
        inst = fake_instance.fake_db_instance(image_ref='image_ref')
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), inst, [])
        inst_obj.system_metadata = {'image_hw_disk_bus': 'scsi'}
        flavor = flavors.get_default_flavor()
        flavor.extra_specs = {'extra_specs': 'fake'}
        inst_obj.flavor = flavor

        fake_spec = fake_request_spec.fake_spec_obj()
        spec_from_components.return_value = fake_spec

        scheduler_hint = {'filter_properties': {}}

        if isinstance(self.conductor, conductor_api.ComputeTaskAPI):
            # The API method is actually 'resize_instance'.  It gets
            # converted into 'migrate_server' when doing RPC.
            self.conductor.resize_instance(
                self.context, inst_obj, {}, scheduler_hint, flavor, [],
                clean_shutdown, host_list=None)
        else:
            self.conductor.migrate_server(
                self.context, inst_obj, scheduler_hint,
                False, False, flavor, None, None, [],
                clean_shutdown)

        get_image_from_metadata.assert_called_once_with(
            inst_obj.system_metadata)
        migration_task_execute.assert_called_once_with()
        spec_save.assert_called_once_with()

    def test_cold_migrate(self):
        self._test_cold_migrate()

    def test_cold_migrate_forced_shutdown(self):
        self._test_cold_migrate(clean_shutdown=False)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'build_and_run_instance')
    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance',
                       return_value=[])
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances')
    @mock.patch('nova.objects.BuildRequest.get_by_instance_uuid')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_build_instances(self, mock_fp, mock_save, mock_getaz,
                             mock_buildreq, mock_schedule, mock_bdm,
                             mock_build):
        """Tests creating two instances and the scheduler returns a unique
        host/node combo for each instance.
        """
        fake_spec = objects.RequestSpec()
        mock_fp.return_value = fake_spec
        instance_type = flavors.get_default_flavor()
        # NOTE(danms): Avoid datetime timezone issues with converted flavors
        instance_type.created_at = None
        instances = [objects.Instance(context=self.context,
                                      id=i,
                                      uuid=uuids.fake,
                                      flavor=instance_type) for i in range(2)]
        instance_type_p = obj_base.obj_to_primitive(instance_type)
        instance_properties = obj_base.obj_to_primitive(instances[0])
        instance_properties['system_metadata'] = flavors.save_flavor_info(
            {}, instance_type)

        spec = {'image': {'fake_data': 'should_pass_silently'},
                'instance_properties': instance_properties,
                'instance_type': instance_type_p,
                'num_instances': 2}
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        sched_return = copy.deepcopy(fake_host_lists2)
        mock_schedule.return_value = sched_return
        filter_properties2 = {'retry': {'num_attempts': 1,
                                        'hosts': [['host1', 'node1']]},
                              'limits': {}}
        filter_properties3 = {'limits': {},
                              'retry': {'num_attempts': 1,
                                        'hosts': [['host2', 'node2']]}}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        mock_getaz.return_value = 'myaz'

        self.conductor.build_instances(self.context,
                instances=instances,
                image={'fake_data': 'should_pass_silently'},
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False, host_lists=None)
        mock_getaz.assert_has_calls([
            mock.call(self.context, 'host1'),
            mock.call(self.context, 'host2')])
        # A RequestSpec is built from primitives once before calling the
        # scheduler to get hosts and then once per instance we're building.
        mock_fp.assert_has_calls([
            mock.call(self.context, spec, filter_properties),
            mock.call(self.context, spec, filter_properties2),
            mock.call(self.context, spec, filter_properties3)])
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, [uuids.fake, uuids.fake],
            return_alternates=True)
        mock_bdm.assert_has_calls([mock.call(self.context, instances[0].uuid),
                                   mock.call(self.context, instances[1].uuid)])
        mock_build.assert_has_calls([
            mock.call(self.context, instance=mock.ANY, host='host1',
                      image={'fake_data': 'should_pass_silently'},
                      request_spec=fake_spec,
                      filter_properties=filter_properties2,
                      admin_password='admin_password',
                      injected_files='injected_files',
                      requested_networks=None,
                      security_groups='security_groups',
                      block_device_mapping=mock.ANY,
                      node='node1', limits=None, host_list=sched_return[0]),
            mock.call(self.context, instance=mock.ANY, host='host2',
                      image={'fake_data': 'should_pass_silently'},
                      request_spec=fake_spec,
                      filter_properties=filter_properties3,
                      admin_password='admin_password',
                      injected_files='injected_files',
                      requested_networks=None,
                      security_groups='security_groups',
                      block_device_mapping=mock.ANY,
                      node='node2', limits=None, host_list=sched_return[1])])

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_allocated_networks')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_destroy_build_request')
    def test_build_instances_scheduler_failure(
            self, dest_build_req_mock, cleanup_mock, sd_mock, state_mock,
            sig_mock, bs_mock):
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        exception = exc.NoValidHost(reason='fake-reason')

        dest_build_req_mock.side_effect = (
            exc.BuildRequestNotFound(uuid='fake'),
            None)
        bs_mock.return_value = spec
        sd_mock.side_effect = exception
        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        self.conductor.build_instances(
            self.context,
            instances=instances,
            image=image,
            filter_properties={},
            admin_password='admin_password',
            injected_files='injected_files',
            requested_networks=None,
            security_groups='security_groups',
            block_device_mapping='block_device_mapping',
            legacy_bdm=False)

        set_state_calls = []
        cleanup_network_calls = []
        dest_build_req_calls = []
        for instance in instances:
            set_state_calls.append(mock.call(
                self.context, instance.uuid, 'compute_task', 'build_instances',
                updates, exception, spec))
            cleanup_network_calls.append(mock.call(
                self.context, mock.ANY, None))
            dest_build_req_calls.append(
                mock.call(self.context, test.MatchType(type(instance))))
        state_mock.assert_has_calls(set_state_calls)
        cleanup_mock.assert_has_calls(cleanup_network_calls)
        dest_build_req_mock.assert_has_calls(dest_build_req_calls)

    def test_build_instances_retry_exceeded(self):
        instances = [fake_instance.fake_instance_obj(self.context)]
        image = {'fake-data': 'should_pass_silently'}
        filter_properties = {'retry': {'num_attempts': 10, 'hosts': []}}
        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        @mock.patch.object(conductor_manager.ComputeTaskManager,
                           '_cleanup_allocated_networks')
        @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
        @mock.patch.object(scheduler_utils, 'build_request_spec')
        @mock.patch.object(scheduler_utils, 'populate_retry')
        def _test(populate_retry, build_spec,
                  set_vm_state_and_notify, cleanup_mock):
            # build_instances() is a cast, we need to wait for it to
            # complete
            self.useFixture(cast_as_call.CastAsCall(self))

            populate_retry.side_effect = exc.MaxRetriesExceeded(
                reason="Too many try")

            self.conductor.build_instances(
                self.context,
                instances=instances,
                image=image,
                filter_properties=filter_properties,
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

            populate_retry.assert_called_once_with(
                filter_properties, instances[0].uuid)
            set_vm_state_and_notify.assert_called_once_with(
                self.context, instances[0].uuid, 'compute_task',
                'build_instances', updates, mock.ANY, build_spec.return_value)
            cleanup_mock.assert_called_once_with(self.context, mock.ANY, None)

        _test()

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_allocated_networks')
    def test_build_instances_scheduler_group_failure(
            self, cleanup_mock, state_mock, sig_mock, bs_mock):
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}

        bs_mock.return_value = spec
        exception = exc.UnsupportedPolicyException(reason='fake-reason')
        sig_mock.side_effect = exception

        updates = {'vm_state': vm_states.ERROR, 'task_state': None}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        self.conductor.build_instances(
                          context=self.context,
                          instances=instances,
                          image=image,
                          filter_properties={},
                          admin_password='admin_password',
                          injected_files='injected_files',
                          requested_networks=None,
                          security_groups='security_groups',
                          block_device_mapping='block_device_mapping',
                          legacy_bdm=False)
        set_state_calls = []
        cleanup_network_calls = []
        for instance in instances:
            set_state_calls.append(mock.call(
                self.context, instance.uuid, 'build_instances', updates,
                exception, spec))
            cleanup_network_calls.append(mock.call(
                self.context, mock.ANY, None))
        state_mock.assert_has_calls(set_state_calls)
        cleanup_mock.assert_has_calls(cleanup_network_calls)

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
            side_effect=exc.InstanceMappingNotFound(uuid='fake'))
    @mock.patch.object(objects.HostMapping, 'get_by_host')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_no_instance_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_save, _mock_buildreq):

        mock_select_dests.return_value = [[fake_selection1], [fake_selection2]]

        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        with mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance'):
            self.conductor.build_instances(
                              context=self.context,
                              instances=instances,
                              image=image,
                              filter_properties={},
                              admin_password='admin_password',
                              injected_files='injected_files',
                              requested_networks=None,
                              security_groups='security_groups',
                              block_device_mapping='block_device_mapping',
                              legacy_bdm=False)
        mock_get_inst_map_by_uuid.assert_has_calls([
            mock.call(self.context, instances[0].uuid),
            mock.call(self.context, instances[1].uuid)])
        self.assertFalse(mock_get_by_host.called)

    @mock.patch("nova.scheduler.utils.claim_resources", return_value=False)
    @mock.patch.object(objects.Instance, 'save')
    def test_build_instances_exhaust_host_list(self, _mock_save, mock_claim):
        # A list of three alternate hosts for one instance
        host_lists = copy.deepcopy(fake_host_lists_alt)
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}
        expected_claim_count = len(host_lists[0])

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))
        # Since claim_resources() is mocked to always return False, we will run
        # out of alternate hosts, and MaxRetriesExceeded should be raised.
        self.assertRaises(exc.MaxRetriesExceeded,
                self.conductor.build_instances, context=self.context,
                instances=[instance], image=image, filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files', requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=None, legacy_bdm=None,
                host_lists=host_lists)
        self.assertEqual(expected_claim_count, mock_claim.call_count)

    @mock.patch.object(conductor_manager.ComputeTaskManager,
            '_destroy_build_request')
    @mock.patch.object(conductor_manager.LOG, 'debug')
    @mock.patch("nova.scheduler.utils.claim_resources", return_value=True)
    @mock.patch.object(objects.Instance, 'save')
    def test_build_instances_logs_selected_and_alts(self, _mock_save,
            mock_claim, mock_debug, mock_destroy):
        # A list of three alternate hosts for one instance
        host_lists = copy.deepcopy(fake_host_lists_alt)
        expected_host = host_lists[0][0]
        expected_alts = host_lists[0][1:]
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))
        with mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance'):
            self.conductor.build_instances(context=self.context,
                    instances=[instance], image=image, filter_properties={},
                    admin_password='admin_password',
                    injected_files='injected_files', requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping=None, legacy_bdm=None,
                    host_lists=host_lists)
        # The last LOG.debug call should record the selected host name and the
        # list of alternates.
        last_call = mock_debug.call_args_list[-1][0]
        self.assertIn(expected_host.service_host, last_call)
        expected_alt_hosts = [(alt.service_host, alt.nodename)
                for alt in expected_alts]
        self.assertIn(expected_alt_hosts, last_call)

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.HostMapping, 'get_by_host',
            side_effect=exc.HostMappingNotFound(name='fake'))
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_no_host_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_save, mock_buildreq):

        mock_select_dests.return_value = [[fake_selection1], [fake_selection2]]
        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        inst_mapping_mocks = [mock.Mock() for i in range(num_instances)]
        mock_get_inst_map_by_uuid.side_effect = inst_mapping_mocks
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        with mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance'):
            self.conductor.build_instances(
                              context=self.context,
                              instances=instances,
                              image=image,
                              filter_properties={},
                              admin_password='admin_password',
                              injected_files='injected_files',
                              requested_networks=None,
                              security_groups='security_groups',
                              block_device_mapping='block_device_mapping',
                              legacy_bdm=False)
        for instance in instances:
            mock_get_inst_map_by_uuid.assert_any_call(self.context,
                    instance.uuid)

        for inst_mapping in inst_mapping_mocks:
            inst_mapping.destroy.assert_called_once_with()

        mock_get_by_host.assert_has_calls([mock.call(self.context, 'host1'),
                                           mock.call(self.context, 'host2')])

    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.HostMapping, 'get_by_host')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_update_instance_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_save, _mock_buildreq):

        mock_select_dests.return_value = [[fake_selection1], [fake_selection2]]
        mock_get_by_host.side_effect = [
                objects.HostMapping(cell_mapping=objects.CellMapping(id=1)),
                objects.HostMapping(cell_mapping=objects.CellMapping(id=2))]

        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        inst_mapping_mocks = [mock.Mock() for i in range(num_instances)]
        mock_get_inst_map_by_uuid.side_effect = inst_mapping_mocks
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        with mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance'):
            self.conductor.build_instances(
                              context=self.context,
                              instances=instances,
                              image=image,
                              filter_properties={},
                              admin_password='admin_password',
                              injected_files='injected_files',
                              requested_networks=None,
                              security_groups='security_groups',
                              block_device_mapping='block_device_mapping',
                              legacy_bdm=False)
        for instance in instances:
            mock_get_inst_map_by_uuid.assert_any_call(self.context,
                    instance.uuid)

        for inst_mapping in inst_mapping_mocks:
            inst_mapping.save.assert_called_once_with()

        self.assertEqual(1, inst_mapping_mocks[0].cell_mapping.id)
        self.assertEqual(2, inst_mapping_mocks[1].cell_mapping.id)
        mock_get_by_host.assert_has_calls([mock.call(self.context, 'host1'),
                                           mock.call(self.context, 'host2')])

    @mock.patch.object(objects.Instance, 'save', new=mock.MagicMock())
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_destroy_build_request(self, mock_select_dests,
            mock_build_req_get):

        mock_select_dests.return_value = [[fake_selection1], [fake_selection2]]
        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        build_req_mocks = [mock.Mock() for i in range(num_instances)]
        mock_build_req_get.side_effect = build_req_mocks
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance', new=mock.MagicMock())
        @mock.patch.object(self.conductor_manager,
            '_populate_instance_mapping', new=mock.MagicMock())
        def do_test():
            self.conductor.build_instances(
                              context=self.context,
                              instances=instances,
                              image=image,
                              filter_properties={},
                              admin_password='admin_password',
                              injected_files='injected_files',
                              requested_networks=None,
                              security_groups='security_groups',
                              block_device_mapping='block_device_mapping',
                              legacy_bdm=False,
                              host_lists=None)

        do_test()

        for build_req in build_req_mocks:
            build_req.destroy.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'save', new=mock.MagicMock())
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_reschedule_ignores_build_request(self,
            mock_select_dests):
        # This test calls build_instances as if it was a reschedule. This means
        # that the exc.BuildRequestNotFound() exception raised by
        # conductor_manager._destroy_build_request() should not cause the
        # build to stop.

        mock_select_dests.return_value = [[fake_selection1]]
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'build_and_run_instance')
        @mock.patch.object(self.conductor_manager,
                           '_populate_instance_mapping')
        @mock.patch.object(self.conductor_manager,
                           '_destroy_build_request',
                           side_effect=exc.BuildRequestNotFound(uuid='fake'))
        def do_test(mock_destroy_build_req, mock_pop_inst_map,
                    mock_build_and_run):
            self.conductor.build_instances(
                context=self.context,
                instances=[instance],
                image=image,
                filter_properties={'retry': {'num_attempts': 1, 'hosts': []}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False, host_lists=None)

            expected_build_run_host_list = copy.copy(fake_host_lists1[0])
            if expected_build_run_host_list:
                expected_build_run_host_list.pop(0)
            mock_build_and_run.assert_called_once_with(
                self.context,
                instance=mock.ANY,
                host='host1',
                image=image,
                request_spec=mock.ANY,
                filter_properties={'retry': {'num_attempts': 2,
                                             'hosts': [['host1', 'node1']]},
                                   'limits': {}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=test.MatchType(
                    objects.BlockDeviceMappingList),
                node='node1', limits=None,
                host_list=expected_build_run_host_list)
            mock_pop_inst_map.assert_not_called()
            mock_destroy_build_req.assert_not_called()

        do_test()

    @mock.patch.object(cinder.API, 'attachment_get')
    @mock.patch.object(cinder.API, 'attachment_create')
    @mock.patch.object(block_device_obj.BlockDeviceMapping, 'save')
    def test_validate_existing_attachment_ids_with_missing_attachments(self,
            mock_bdm_save, mock_attachment_create, mock_attachment_get):
        instance = self._create_fake_instance_obj()
        bdms = [
            block_device.BlockDeviceDict({
                'boot_index': 0,
                'guest_format': None,
                'connection_info': None,
                'device_type': u'disk',
                'source_type': 'image',
                'destination_type': 'volume',
                'volume_size': 1,
                'image_id': 1,
                'device_name': '/dev/vdb',
                'attachment_id': uuids.attachment,
                'volume_id': uuids.volume
            })]
        bdms = block_device_obj.block_device_make_list_from_dicts(
            self.context, bdms)
        mock_attachment_get.side_effect = exc.VolumeAttachmentNotFound(
            attachment_id=uuids.attachment)
        mock_attachment_create.return_value = {'id': uuids.new_attachment}

        self.assertEqual(uuids.attachment, bdms[0].attachment_id)
        self.conductor_manager._validate_existing_attachment_ids(self.context,
                                                                 instance,
                                                                 bdms)
        mock_attachment_get.assert_called_once_with(self.context,
                                                    uuids.attachment)
        mock_attachment_create.assert_called_once_with(self.context,
                                                       uuids.volume,
                                                       instance.uuid)
        mock_bdm_save.assert_called_once()
        self.assertEqual(uuids.new_attachment, bdms[0].attachment_id)

    @mock.patch.object(cinder.API, 'attachment_get')
    @mock.patch.object(cinder.API, 'attachment_create')
    @mock.patch.object(block_device_obj.BlockDeviceMapping, 'save')
    def test_validate_existing_attachment_ids_with_attachments_present(self,
            mock_bdm_save, mock_attachment_create, mock_attachment_get):
        instance = self._create_fake_instance_obj()
        bdms = [
            block_device.BlockDeviceDict({
                'boot_index': 0,
                'guest_format': None,
                'connection_info': None,
                'device_type': u'disk',
                'source_type': 'image',
                'destination_type': 'volume',
                'volume_size': 1,
                'image_id': 1,
                'device_name': '/dev/vdb',
                'attachment_id': uuids.attachment,
                'volume_id': uuids.volume
            })]
        bdms = block_device_obj.block_device_make_list_from_dicts(
            self.context, bdms)
        mock_attachment_get.return_value = {
        "attachment": {
            "status": "attaching",
            "detached_at": "2015-09-16T09:28:52.000000",
            "connection_info": {},
            "attached_at": "2015-09-16T09:28:52.000000",
            "attach_mode": "ro",
            "instance": instance.uuid,
            "volume_id": uuids.volume,
            "id": uuids.attachment
        }}

        self.assertEqual(uuids.attachment, bdms[0].attachment_id)
        self.conductor_manager._validate_existing_attachment_ids(self.context,
                                                                 instance,
                                                                 bdms)
        mock_attachment_get.assert_called_once_with(self.context,
                                                    uuids.attachment)
        mock_attachment_create.assert_not_called()
        mock_bdm_save.assert_not_called()
        self.assertEqual(uuids.attachment, bdms[0].attachment_id)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'unshelve_instance')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'start_instance')
    def test_unshelve_instance_on_host(self, mock_start, mock_unshelve):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

        mock_start.assert_called_once_with(self.context, instance)
        mock_unshelve.assert_not_called()

    def test_unshelve_offload_instance_on_host_with_request_spec(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'

        fake_spec = fake_request_spec.fake_spec_obj()
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty SchedulerRetries object or nullify the field
        fake_spec.retry = None
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty SchedulerLimits object or nullify the field
        fake_spec.limits = None
        # FIXME(sbauza): Modify the fake RequestSpec object to either add a
        # non-empty InstanceGroup object or nullify the field
        fake_spec.instance_group = None

        filter_properties = fake_spec.to_legacy_filter_properties_dict()

        host = {'host': 'host1', 'nodename': 'node1', 'limits': {}}

        # unshelve_instance() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'unshelve_instance')
        @mock.patch.object(scheduler_utils, 'populate_filter_properties')
        @mock.patch.object(self.conductor_manager, '_schedule_instances')
        @mock.patch.object(objects.RequestSpec,
                           'to_legacy_filter_properties_dict')
        @mock.patch.object(objects.RequestSpec, 'reset_forced_destinations')
        def do_test(reset_forced_destinations,
                    to_filtprops, sched_instances, populate_filter_properties,
                    unshelve_instance, get_by_instance_uuid):
            cell_mapping = objects.CellMapping.get_by_uuid(self.context,
                                                           uuids.cell1)
            get_by_instance_uuid.return_value = objects.InstanceMapping(
                cell_mapping=cell_mapping)
            to_filtprops.return_value = filter_properties
            sched_instances.return_value = [[fake_selection1]]
            self.conductor.unshelve_instance(self.context, instance, fake_spec)
            # The fake_spec already has a project_id set which doesn't match
            # the instance.project_id so the spec's project_id won't be
            # overridden using the instance.project_id.
            self.assertNotEqual(fake_spec.project_id, instance.project_id)
            reset_forced_destinations.assert_called_once_with()
            # The fake_spec is only going to modified by reference for
            # ComputeTaskManager.
            if isinstance(self.conductor,
                          conductor_manager.ComputeTaskManager):
                self.ensure_network_metadata_mock.assert_called_once_with(
                    test.MatchType(objects.Instance))
                self.heal_reqspec_is_bfv_mock.assert_called_once_with(
                    self.context, fake_spec, instance)
                sched_instances.assert_called_once_with(
                    self.context, fake_spec, [instance.uuid],
                    return_alternates=False)
                self.assertEqual(cell_mapping,
                                 fake_spec.requested_destination.cell)
            else:
                # RPC API tests won't have the same request spec or instance
                # since they go over the wire.
                self.ensure_network_metadata_mock.assert_called_once_with(
                    test.MatchType(objects.Instance))
                self.heal_reqspec_is_bfv_mock.assert_called_once_with(
                    self.context, test.MatchType(objects.RequestSpec),
                    test.MatchType(objects.Instance))
                sched_instances.assert_called_once_with(
                    self.context, test.MatchType(objects.RequestSpec),
                    [instance.uuid], return_alternates=False)
            # NOTE(sbauza): Since the instance is dehydrated when passing
            # through the RPC API, we can only assert mock.ANY for it
            unshelve_instance.assert_called_once_with(
                self.context, mock.ANY, host['host'], image=mock.ANY,
                filter_properties=filter_properties, node=host['nodename']
            )

        do_test()

    @mock.patch('nova.compute.utils.add_instance_fault_from_exc')
    @mock.patch.object(image_api.API, 'get',
                       side_effect=exc.ImageNotFound(image_id=uuids.image))
    def test_unshelve_offloaded_instance_glance_image_not_found(
            self, mock_get, add_instance_fault_from_exc):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        system_metadata['shelved_image_id'] = uuids.image

        reason = ('Unshelve attempted but the image %s '
                  'cannot be found.') % uuids.image

        self.assertRaises(
            exc.UnshelveException,
            self.conductor_manager.unshelve_instance,
            self.context, instance)
        add_instance_fault_from_exc.assert_called_once_with(
            self.context, instance, mock_get.side_effect, mock.ANY,
            fault_message=reason)
        self.assertEqual(instance.vm_state, vm_states.ERROR)
        mock_get.assert_called_once_with(self.context, uuids.image,
                                         show_deleted=False)

    def test_unshelve_offloaded_instance_image_id_is_none(self):

        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        # 'shelved_image_id' is None for volumebacked instance
        instance.system_metadata['shelved_image_id'] = None

        with test.nested(
            mock.patch.object(self.conductor_manager,
                              '_schedule_instances'),
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'unshelve_instance'),
            mock.patch.object(objects.InstanceMapping,
                              'get_by_instance_uuid'),
        ) as (schedule_mock, unshelve_mock, get_by_instance_uuid):
            schedule_mock.return_value = [[fake_selection1]]
            get_by_instance_uuid.return_value = objects.InstanceMapping(
                cell_mapping=objects.CellMapping.get_by_uuid(
                    self.context, uuids.cell1))
            self.conductor_manager.unshelve_instance(self.context, instance)
            self.assertEqual(1, unshelve_mock.call_count)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'unshelve_instance')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances',
                       return_value=[[objects.Selection(
                           service_host='fake_host', nodename='fake_node',
                           limits=None)]])
    @mock.patch.object(scheduler_utils, 'build_request_spec',
                       return_value='req_spec')
    @mock.patch.object(image_api.API, 'get', return_value='fake_image')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_unshelve_instance_schedule_and_rebuild(
            self, fp, mock_im, mock_get, mock_build, mock_schedule,
            mock_unshelve):
        fake_spec = objects.RequestSpec()
        # Set requested_destination to test setting cell_mapping in
        # existing object.
        fake_spec.requested_destination = objects.Destination(
            host="dummy", cell=None)
        fp.return_value = fake_spec
        cell_mapping = objects.CellMapping.get_by_uuid(self.context,
                                                       uuids.cell1)
        mock_im.return_value = objects.InstanceMapping(
            cell_mapping=cell_mapping)
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)
        fp.assert_called_once_with(self.context, 'req_spec', mock.ANY)
        self.assertEqual(cell_mapping, fake_spec.requested_destination.cell)
        mock_get.assert_called_once_with(
            self.context, 'fake_image_id', show_deleted=False)
        mock_build.assert_called_once_with('fake_image', mock.ANY)
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, [instance.uuid], return_alternates=False)
        mock_unshelve.assert_called_once_with(
            self.context, instance, 'fake_host', image='fake_image',
            filter_properties={'limits': {}}, node='fake_node')

    def test_unshelve_instance_schedule_and_rebuild_novalid_host(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        def fake_schedule_instances(context, request_spec, *instances,
                **kwargs):
            raise exc.NoValidHost(reason='')

        with test.nested(
            mock.patch.object(self.conductor_manager.image_api, 'get',
                              return_value='fake_image'),
            mock.patch.object(self.conductor_manager, '_schedule_instances',
                              fake_schedule_instances),
            mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid'),
            mock.patch.object(objects.Instance, 'save')
        ) as (_get_image, _schedule_instances, get_by_instance_uuid, save):
            get_by_instance_uuid.return_value = objects.InstanceMapping(
                cell_mapping=objects.CellMapping.get_by_uuid(
                    self.context, uuids.cell1))
            system_metadata['shelved_at'] = timeutils.utcnow()
            system_metadata['shelved_image_id'] = 'fake_image_id'
            system_metadata['shelved_host'] = 'fake-mini'
            self.conductor_manager.unshelve_instance(self.context, instance)
            _get_image.assert_has_calls([mock.call(self.context,
                                      system_metadata['shelved_image_id'],
                                      show_deleted=False)])
            self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances',
                       side_effect=messaging.MessagingTimeout())
    @mock.patch.object(image_api.API, 'get', return_value='fake_image')
    @mock.patch.object(objects.Instance, 'save')
    def test_unshelve_instance_schedule_and_rebuild_messaging_exception(
            self, mock_save, mock_get_image, mock_schedule_instances, mock_im):
        mock_im.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.assertRaises(messaging.MessagingTimeout,
                          self.conductor_manager.unshelve_instance,
                          self.context, instance)
        mock_get_image.assert_has_calls([mock.call(self.context,
                                        system_metadata['shelved_image_id'],
                                        show_deleted=False)])
        self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)
        self.assertIsNone(instance.task_state)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'unshelve_instance')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances', return_value=[[
                           objects.Selection(service_host='fake_host',
                                             nodename='fake_node',
                                             limits=None)]])
    @mock.patch.object(scheduler_utils, 'build_request_spec',
                       return_value='req_spec')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_unshelve_instance_schedule_and_rebuild_volume_backed(
            self, fp, mock_im, mock_build, mock_schedule, mock_unshelve):
        fake_spec = objects.RequestSpec()
        fp.return_value = fake_spec
        mock_im.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)
        fp.assert_called_once_with(self.context, 'req_spec', mock.ANY)
        mock_build.assert_called_once_with(None, mock.ANY)
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, [instance.uuid], return_alternates=False)
        mock_unshelve.assert_called_once_with(
            self.context, instance, 'fake_host', image=None,
            filter_properties={'limits': {}}, node='fake_node')

    def test_rebuild_instance(self):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': inst_obj.host})

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations')
        ) as (rebuild_mock, select_dest_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            self.assertFalse(select_dest_mock.called)
            rebuild_mock.assert_called_once_with(self.context,
                               instance=inst_obj,
                               **compute_args)

    @mock.patch('nova.compute.utils.notify_about_instance_rebuild')
    def test_rebuild_instance_with_scheduler(self, mock_notify):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = None
        fake_selection = objects.Selection(service_host=expected_host,
                nodename=expected_node, limits=None)
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits})
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec()
        inst_uuids = [inst_obj.uuid]
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=fake_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              return_value=[[fake_selection]]),
            mock.patch('nova.scheduler.utils.build_request_spec',
                       return_value=request_spec)
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, bs_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            bs_mock.assert_called_once_with(
                obj_base.obj_to_primitive(inst_obj.image_meta), [inst_obj])
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            self.ensure_network_metadata_mock.assert_called_once_with(
                inst_obj)
            self.heal_reqspec_is_bfv_mock.assert_called_once_with(
                self.context, fake_spec, inst_obj)
            select_dest_mock.assert_called_once_with(self.context, fake_spec,
                    inst_uuids, return_objects=True, return_alternates=False)
            compute_args['host'] = expected_host
            compute_args['request_spec'] = fake_spec
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
            self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)
        mock_notify.assert_called_once_with(
            self.context, inst_obj, 'thebesthost', action='rebuild_scheduled',
            source='nova-conductor')

    def test_rebuild_instance_with_scheduler_no_host(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        rebuild_args, _ = self._prepare_rebuild_args({'host': None})
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec()

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=fake_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              side_effect=exc.NoValidHost(reason='')),
            mock.patch('nova.scheduler.utils.build_request_spec',
                       return_value=request_spec),
            mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
        ) as (rebuild_mock, sig_mock, fp_mock,
              select_dest_mock, bs_mock, set_vm_state_and_notify_mock):
            self.assertRaises(exc.NoValidHost,
                              self.conductor_manager.rebuild_instance,
                              context=self.context, instance=inst_obj,
                              **rebuild_args)
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context, fake_spec,
                    [inst_obj.uuid], return_objects=True,
                    return_alternates=False)
            self.assertEqual(
                set_vm_state_and_notify_mock.call_args[0][4]['vm_state'],
                vm_states.ERROR)
            self.assertFalse(rebuild_mock.called)

    @mock.patch.object(conductor_manager.compute_rpcapi.ComputeAPI,
                       'rebuild_instance')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(conductor_manager.scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch('nova.scheduler.utils.build_request_spec')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_rebuild_instance_with_scheduler_group_failure(self,
                                                           state_mock,
                                                           bs_mock,
                                                           select_dest_mock,
                                                           sig_mock,
                                                           rebuild_mock):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, _ = self._prepare_rebuild_args({'host': None})
        request_spec = {}
        bs_mock.return_value = request_spec

        exception = exc.UnsupportedPolicyException(reason='')
        sig_mock.side_effect = exception

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        # Create the migration record (normally created by the compute API).
        migration = objects.Migration(self.context,
                                      source_compute=inst_obj.host,
                                      source_node=inst_obj.node,
                                      instance_uuid=inst_obj.uuid,
                                      status='accepted',
                                      migration_type='evacuation')
        migration.create()

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor.rebuild_instance,
                          self.context,
                          inst_obj,
                          **rebuild_args)
        updates = {'vm_state': vm_states.ERROR, 'task_state': None}
        state_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                           'rebuild_server', updates,
                                           exception, mock.ANY)
        self.assertFalse(select_dest_mock.called)
        self.assertFalse(rebuild_mock.called)

        # Assert the migration status was updated.
        migration = objects.Migration.get_by_id(self.context, migration.id)
        self.assertEqual('error', migration.status)

    def test_rebuild_instance_evacuate_migration_record(self):
        inst_obj = self._create_fake_instance_obj()
        migration = objects.Migration(context=self.context,
                                      source_compute=inst_obj.host,
                                      source_node=inst_obj.node,
                                      instance_uuid=inst_obj.uuid,
                                      status='accepted',
                                      migration_type='evacuation')
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': inst_obj.host, 'migration': migration})

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations'),
            mock.patch.object(objects.Migration, 'get_by_instance_and_status',
                              return_value=migration)
        ) as (rebuild_mock, select_dest_mock, get_migration_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            self.assertFalse(select_dest_mock.called)
            rebuild_mock.assert_called_once_with(self.context,
                               instance=inst_obj,
                               **compute_args)

    @mock.patch('nova.compute.utils.notify_about_instance_rebuild')
    def test_rebuild_instance_with_request_spec(self, mock_notify):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = None
        fake_selection = objects.Selection(service_host=expected_host,
                nodename=expected_node, limits=None)
        fake_spec = objects.RequestSpec(ignore_hosts=[])
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits,
             'request_spec': fake_spec})
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              return_value=[[fake_selection]]),
            mock.patch.object(fake_spec, 'reset_forced_destinations'),
        ) as (rebuild_mock, sig_mock, select_dest_mock, reset_fd):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            if rebuild_args['recreate']:
                reset_fd.assert_called_once_with()
            else:
                reset_fd.assert_not_called()
            select_dest_mock.assert_called_once_with(self.context,
                    fake_spec, [inst_obj.uuid], return_objects=True,
                    return_alternates=False)
            compute_args['host'] = expected_host
            compute_args['request_spec'] = fake_spec
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)
        mock_notify.assert_called_once_with(
            self.context, inst_obj, 'thebesthost', action='rebuild_scheduled',
            source='nova-conductor')


class ConductorTaskTestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
    """ComputeTaskManager Tests."""

    NUMBER_OF_CELLS = 2

    def setUp(self):
        super(ConductorTaskTestCase, self).setUp()
        self.conductor = conductor_manager.ComputeTaskManager()
        self.conductor_manager = self.conductor

        params = {}
        self.ctxt = params['context'] = context.RequestContext(
            'fake-user', 'fake-project').elevated()
        build_request = fake_build_request.fake_req_obj(self.ctxt)
        del build_request.instance.id
        build_request.create()
        params['build_requests'] = objects.BuildRequestList(
            objects=[build_request])
        im = objects.InstanceMapping(
            self.ctxt, instance_uuid=build_request.instance.uuid,
            cell_mapping=None, project_id=self.ctxt.project_id)
        im.create()
        rs = fake_request_spec.fake_spec_obj(remove_id=True)
        rs._context = self.ctxt
        rs.instance_uuid = build_request.instance_uuid
        rs.instance_group = None
        rs.retry = None
        rs.limits = None
        rs.create()
        params['request_specs'] = [rs]
        params['image'] = {'fake_data': 'should_pass_silently'}
        params['admin_password'] = 'admin_password',
        params['injected_files'] = 'injected_files'
        params['requested_networks'] = None
        bdm = objects.BlockDeviceMapping(self.ctxt, **dict(
            source_type='blank', destination_type='local',
            guest_format='foo', device_type='disk', disk_bus='',
            boot_index=1, device_name='xvda', delete_on_termination=False,
            snapshot_id=None, volume_id=None, volume_size=1,
            image_id='bar', no_device=False, connection_info=None,
            tag=''))
        params['block_device_mapping'] = objects.BlockDeviceMappingList(
            objects=[bdm])
        tag = objects.Tag(self.ctxt, tag='tag1')
        params['tags'] = objects.TagList(objects=[tag])
        self.params = params

    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def _do_schedule_and_build_instances_test(self, params,
                                               select_destinations,
                                               build_and_run_instance,
                                               get_az):
        select_destinations.return_value = [[fake_selection1]]
        get_az.return_value = 'myaz'
        details = {}

        def _build_and_run_instance(ctxt, *args, **kwargs):
            details['instance'] = kwargs['instance']
            self.assertTrue(kwargs['instance'].id)
            self.assertTrue(kwargs['filter_properties'].get('retry'))
            self.assertEqual(1, len(kwargs['block_device_mapping']))
            # FIXME(danms): How to validate the db connection here?

        self.start_service('compute', host='host1')
        build_and_run_instance.side_effect = _build_and_run_instance
        self.conductor.schedule_and_build_instances(**params)
        self.assertTrue(build_and_run_instance.called)
        get_az.assert_called_once_with(mock.ANY, 'host1')

        instance_uuid = details['instance'].uuid
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.ctxt, instance_uuid)
        ephemeral = list(filter(block_device.new_format_is_ephemeral, bdms))
        self.assertEqual(1, len(ephemeral))
        swap = list(filter(block_device.new_format_is_swap, bdms))
        self.assertEqual(0, len(swap))

        self.assertEqual(1, ephemeral[0].volume_size)
        return instance_uuid

    @mock.patch('nova.notifications.send_update_with_states')
    def test_schedule_and_build_instances(self, mock_notify):
        # NOTE(melwitt): This won't work with call_args because the call
        # arguments are recorded as references and not as copies of objects.
        # So even though the notify method was called with Instance._context
        # targeted, by the time we assert with call_args, the target_cell
        # context manager has already exited and the referenced Instance
        # object's _context.db_connection has been restored to None.
        def fake_notify(ctxt, instance, *args, **kwargs):
            # Assert the instance object is targeted when going through the
            # notification code.
            self.assertIsNotNone(ctxt.db_connection)
            self.assertIsNotNone(instance._context.db_connection)

        mock_notify.side_effect = fake_notify

        instance_uuid = self._do_schedule_and_build_instances_test(
            self.params)
        cells = objects.CellMappingList.get_all(self.ctxt)

        # NOTE(danms): Assert that we created the InstanceAction in the
        # correct cell
        # NOTE(Kevin Zheng): Also assert tags in the correct cell
        for cell in cells:
            with context.target_cell(self.ctxt, cell) as cctxt:
                actions = objects.InstanceActionList.get_by_instance_uuid(
                    cctxt, instance_uuid)
                if cell.name == 'cell1':
                    self.assertEqual(1, len(actions))
                    tags = objects.TagList.get_by_resource_id(
                        cctxt, instance_uuid)
                    self.assertEqual(1, len(tags))
                else:
                    self.assertEqual(0, len(actions))

    def test_schedule_and_build_instances_no_tags_provided(self):
        params = copy.deepcopy(self.params)
        del params['tags']
        instance_uuid = self._do_schedule_and_build_instances_test(params)
        cells = objects.CellMappingList.get_all(self.ctxt)

        # NOTE(danms): Assert that we created the InstanceAction in the
        # correct cell
        # NOTE(Kevin Zheng): Also assert tags in the correct cell
        for cell in cells:
            with context.target_cell(self.ctxt, cell) as cctxt:
                actions = objects.InstanceActionList.get_by_instance_uuid(
                    cctxt, instance_uuid)
                if cell.name == 'cell1':
                    self.assertEqual(1, len(actions))
                    tags = objects.TagList.get_by_resource_id(
                        cctxt, instance_uuid)
                    self.assertEqual(0, len(tags))
                else:
                    self.assertEqual(0, len(actions))

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.availability_zones.get_host_availability_zone',
                return_value='nova')
    def test_schedule_and_build_multiple_instances(self, mock_get_az,
                                                   get_hostmapping,
                                                   select_destinations,
                                                   build_and_run_instance):
        # This list needs to match the number of build_requests and the number
        # of request_specs in params.
        select_destinations.return_value = [[fake_selection1],
                [fake_selection2], [fake_selection1], [fake_selection2]]
        params = self.params

        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')

        # Because of the cache, this should only be called twice,
        # once for the first and once for the third request.
        get_hostmapping.side_effect = self.host_mappings.values()

        # create three additional build requests for a total of four
        for x in range(3):
            build_request = fake_build_request.fake_req_obj(self.ctxt)
            del build_request.instance.id
            build_request.create()
            params['build_requests'].objects.append(build_request)
            im2 = objects.InstanceMapping(
                self.ctxt, instance_uuid=build_request.instance.uuid,
                cell_mapping=None, project_id=self.ctxt.project_id)
            im2.create()
            params['request_specs'].append(objects.RequestSpec(
                instance_uuid=build_request.instance_uuid,
                instance_group=None))

        # Now let's have some fun and delete the third build request before
        # passing the object on to schedule_and_build_instances so that the
        # instance will be created for that build request but when it calls
        # BuildRequest.destroy(), it will raise BuildRequestNotFound and we'll
        # cleanup the instance instead of passing it to build_and_run_instance
        # and we make sure that the fourth build request still gets processed.
        deleted_build_request = params['build_requests'][2]
        deleted_build_request.destroy()

        def _build_and_run_instance(ctxt, *args, **kwargs):
            # Make sure the instance wasn't the one that was deleted.
            instance = kwargs['instance']
            self.assertNotEqual(deleted_build_request.instance_uuid,
                                instance.uuid)
            # This just makes sure that the instance was created in the DB.
            self.assertTrue(kwargs['instance'].id)
            self.assertEqual(1, len(kwargs['block_device_mapping']))
            # FIXME(danms): How to validate the db connection here?

        build_and_run_instance.side_effect = _build_and_run_instance
        self.conductor.schedule_and_build_instances(**params)
        self.assertEqual(3, build_and_run_instance.call_count)
        # We're processing 4 instances over 2 hosts, so we should only lookup
        # the AZ per host once.
        mock_get_az.assert_has_calls([
            mock.call(self.ctxt, 'host1'), mock.call(self.ctxt, 'host2')],
            any_order=True)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    def test_schedule_and_build_multiple_cells(
            self, get_hostmapping, select_destinations,
            build_and_run_instance):
        """Test that creates two instances in separate cells."""
        # This list needs to match the number of build_requests and the number
        # of request_specs in params.
        select_destinations.return_value = [[fake_selection1],
                [fake_selection2]]

        params = self.params

        # The cells are created in the base TestCase setup.
        self.start_service('compute', host='host1', cell='cell1')
        self.start_service('compute', host='host2', cell='cell2')

        get_hostmapping.side_effect = self.host_mappings.values()

        # create an additional build request and request spec
        build_request = fake_build_request.fake_req_obj(self.ctxt)
        del build_request.instance.id
        build_request.create()
        params['build_requests'].objects.append(build_request)
        im2 = objects.InstanceMapping(
            self.ctxt, instance_uuid=build_request.instance.uuid,
            cell_mapping=None, project_id=self.ctxt.project_id)
        im2.create()
        params['request_specs'].append(objects.RequestSpec(
            instance_uuid=build_request.instance_uuid,
            instance_group=None))

        instance_cells = set()

        def _build_and_run_instance(ctxt, *args, **kwargs):
            instance = kwargs['instance']
            # Keep track of the cells that the instances were created in.
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                ctxt, instance.uuid)
            instance_cells.add(inst_mapping.cell_mapping.uuid)

        build_and_run_instance.side_effect = _build_and_run_instance
        self.conductor.schedule_and_build_instances(**params)
        self.assertEqual(2, build_and_run_instance.call_count)
        self.assertEqual(2, len(instance_cells))

    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_scheduler_failure(self, select_destinations):
        select_destinations.side_effect = Exception
        self.start_service('compute', host='fake-host')
        self.conductor.schedule_and_build_instances(**self.params)
        with conductor_manager.try_target_cell(self.ctxt,
                                               self.cell_mappings['cell0']):
            instance = objects.Instance.get_by_uuid(
                self.ctxt, self.params['build_requests'][0].instance_uuid)
        self.assertEqual('error', instance.vm_state)
        self.assertIsNone(instance.task_state)

    @mock.patch('nova.objects.TagList.destroy')
    @mock.patch('nova.objects.TagList.create')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling(self,
                                                         bury,
                                                         br_destroy,
                                                         select_destinations,
                                                         build_and_run,
                                                         notify,
                                                         taglist_create,
                                                         taglist_destroy):

        br_destroy.side_effect = exc.BuildRequestNotFound(uuid='foo')
        self.start_service('compute', host='host1')
        select_destinations.return_value = [[fake_selection1]]
        taglist_create.return_value = self.params['tags']
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertFalse(build_and_run.called)
        self.assertFalse(bury.called)
        self.assertTrue(br_destroy.called)
        taglist_destroy.assert_called_once_with(
            test.MatchType(context.RequestContext),
            self.params['build_requests'][0].instance_uuid)
        # Make sure TagList.destroy was called with the targeted context.
        self.assertIsNotNone(taglist_destroy.call_args[0][0].db_connection)

        test_utils.assert_instance_delete_notification_by_uuid(
            notify, self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True)

    @mock.patch('nova.objects.Instance.destroy')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling_host_changed(
            self, bury, br_destroy, select_destinations,
            build_and_run, notify, instance_destroy):

        br_destroy.side_effect = exc.BuildRequestNotFound(uuid='foo')
        instance_destroy.side_effect = [
            exc.ObjectActionError(action='destroy',
                                  reason='host changed'),
            None,
        ]

        self.start_service('compute', host='host1')
        select_destinations.return_value = [[fake_selection1]]
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertFalse(build_and_run.called)
        self.assertFalse(bury.called)
        self.assertTrue(br_destroy.called)
        self.assertEqual(2, instance_destroy.call_count)
        test_utils.assert_instance_delete_notification_by_uuid(
            notify, self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True)

    @mock.patch('nova.objects.Instance.destroy')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling_instance_not_found(
            self, bury, br_destroy, select_destinations,
            build_and_run, notify, instance_destroy):

        br_destroy.side_effect = exc.BuildRequestNotFound(uuid='foo')
        instance_destroy.side_effect = [
            exc.InstanceNotFound(instance_id='fake'),
            None,
        ]

        self.start_service('compute', host='host1')
        select_destinations.return_value = [[fake_selection1]]
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertFalse(build_and_run.called)
        self.assertFalse(bury.called)
        self.assertTrue(br_destroy.called)
        self.assertEqual(1, instance_destroy.call_count)
        test_utils.assert_instance_delete_notification_by_uuid(
            notify, self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.get_by_instance_uuid')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    @mock.patch('nova.objects.Instance.create')
    def test_schedule_and_build_delete_before_scheduling(self, inst_create,
                                                         bury, br_destroy,
                                                         br_get_by_inst,
                                                         select_destinations,
                                                         build_and_run):
        """Tests the case that the build request is deleted before the instance
        is created, so we do not create the instance.
        """
        inst_uuid = self.params['build_requests'][0].instance.uuid
        br_get_by_inst.side_effect = exc.BuildRequestNotFound(uuid=inst_uuid)
        self.start_service('compute', host='host1')
        select_destinations.return_value = [[fake_selection1]]
        self.conductor.schedule_and_build_instances(**self.params)
        # we don't create the instance since the build request is gone
        self.assertFalse(inst_create.called)
        # we don't build the instance since we didn't create it
        self.assertFalse(build_and_run.called)
        # we don't bury the instance in cell0 since it's already deleted
        self.assertFalse(bury.called)
        # we don't don't destroy the build request since it's already gone
        self.assertFalse(br_destroy.called)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_unmapped_host_ends_up_in_cell0(self,
                                                               bury,
                                                               br_destroy,
                                                               select_dest,
                                                               build_and_run):
        def _fake_bury(ctxt, request_spec, exc,
                       build_requests=None, instances=None,
                       block_device_mapping=None,
                       tags=None):
            self.assertIn('not mapped to any cell', str(exc))
            self.assertEqual(1, len(build_requests))
            self.assertEqual(1, len(instances))
            self.assertEqual(build_requests[0].instance_uuid,
                             instances[0].uuid)
            self.assertEqual(self.params['block_device_mapping'],
                             block_device_mapping)
            self.assertEqual(self.params['tags'],
                             tags)

        bury.side_effect = _fake_bury
        select_dest.return_value = [[fake_selection1]]
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertTrue(bury.called)
        self.assertFalse(build_and_run.called)

    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_over_quota_during_recheck(self, mock_select,
                                                          mock_check):
        mock_select.return_value = [[fake_selection1]]
        # Simulate a race where the first check passes and the recheck fails.
        # First check occurs in compute/api.
        fake_quotas = {'instances': 5, 'cores': 10, 'ram': 4096}
        fake_headroom = {'instances': 5, 'cores': 10, 'ram': 4096}
        fake_usages = {'instances': 5, 'cores': 10, 'ram': 4096}
        e = exc.OverQuota(overs=['instances'], quotas=fake_quotas,
                          headroom=fake_headroom, usages=fake_usages)
        mock_check.side_effect = e

        original_save = objects.Instance.save

        def fake_save(inst, *args, **kwargs):
            # Make sure the context is targeted to the cell that the instance
            # was created in.
            self.assertIsNotNone(
                inst._context.db_connection, 'Context is not targeted')
            original_save(inst, *args, **kwargs)

        self.stub_out('nova.objects.Instance.save', fake_save)

        # This is needed to register the compute node in a cell.
        self.start_service('compute', host='host1')
        self.assertRaises(
            exc.TooManyInstances,
            self.conductor.schedule_and_build_instances, **self.params)

        project_id = self.params['context'].project_id
        mock_check.assert_called_once_with(
            self.params['context'], {'instances': 0, 'cores': 0, 'ram': 0},
            project_id, user_id=None, check_project_id=project_id,
            check_user_id=None)

        # Verify we set the instance to ERROR state and set the fault message.
        instances = objects.InstanceList.get_all(self.ctxt)
        self.assertEqual(1, len(instances))
        instance = instances[0]
        self.assertEqual(vm_states.ERROR, instance.vm_state)
        self.assertIsNone(instance.task_state)
        self.assertIn('Quota exceeded', instance.fault.message)
        # Verify we removed the build objects.
        build_requests = objects.BuildRequestList.get_all(self.ctxt)
        # Verify that the instance is mapped to a cell
        inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                self.ctxt, instance.uuid)
        self.assertIsNotNone(inst_mapping.cell_mapping)

        self.assertEqual(0, len(build_requests))

        @db_api.api_context_manager.reader
        def request_spec_get_all(context):
            return context.session.query(api_models.RequestSpec).all()

        request_specs = request_spec_get_all(self.ctxt)
        self.assertEqual(0, len(request_specs))

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_no_quota_recheck(self, mock_select,
                                                 mock_check, mock_build):
        mock_select.return_value = [[fake_selection1]]
        # Disable recheck_quota.
        self.flags(recheck_quota=False, group='quota')
        # This is needed to register the compute node in a cell.
        self.start_service('compute', host='host1')
        self.conductor.schedule_and_build_instances(**self.params)

        # check_deltas should not have been called a second time. The first
        # check occurs in compute/api.
        mock_check.assert_not_called()

        self.assertTrue(mock_build.called)

    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    def test_bury_in_cell0_no_cell0(self, mock_cm_get):
        mock_cm_get.side_effect = exc.CellMappingNotFound(uuid='0')
        # Without an iterable build_requests in the database, this
        # wouldn't work if it continued past the cell0 lookup.
        self.conductor._bury_in_cell0(self.ctxt, None, None,
                                      build_requests=1)
        self.assertTrue(mock_cm_get.called)

    def test_bury_in_cell0(self):
        bare_br = self.params['build_requests'][0]

        inst_br = fake_build_request.fake_req_obj(self.ctxt)
        del inst_br.instance.id
        inst_br.create()
        inst = inst_br.get_new_instance(self.ctxt)

        deleted_br = fake_build_request.fake_req_obj(self.ctxt)
        del deleted_br.instance.id
        deleted_br.create()
        deleted_inst = inst_br.get_new_instance(self.ctxt)
        deleted_br.destroy()

        fast_deleted_br = fake_build_request.fake_req_obj(self.ctxt)
        del fast_deleted_br.instance.id
        fast_deleted_br.create()
        fast_deleted_br.destroy()

        self.conductor._bury_in_cell0(self.ctxt,
                                      self.params['request_specs'][0],
                                      Exception('Foo'),
                                      build_requests=[bare_br, inst_br,
                                                      deleted_br,
                                                      fast_deleted_br],
                                      instances=[inst, deleted_inst])

        with conductor_manager.try_target_cell(self.ctxt,
                                               self.cell_mappings['cell0']):
            self.ctxt.read_deleted = 'yes'
            build_requests = objects.BuildRequestList.get_all(self.ctxt)
            instances = objects.InstanceList.get_all(self.ctxt)

        self.assertEqual(0, len(build_requests))
        self.assertEqual(4, len(instances))
        inst_states = {inst.uuid: (inst.deleted, inst.vm_state)
                       for inst in instances}
        expected = {
            bare_br.instance_uuid: (False, vm_states.ERROR),
            inst_br.instance_uuid: (False, vm_states.ERROR),
            deleted_br.instance_uuid: (True, vm_states.ERROR),
            fast_deleted_br.instance_uuid: (True, vm_states.ERROR),
        }

        self.assertEqual(expected, inst_states)

    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_block_device_mapping')
    def test_bury_in_cell0_with_block_device_mapping(self, mock_create_bdm,
            mock_get_cell):
        mock_get_cell.return_value = self.cell_mappings['cell0']

        inst_br = fake_build_request.fake_req_obj(self.ctxt)
        del inst_br.instance.id
        inst_br.create()
        inst = inst_br.get_new_instance(self.ctxt)

        self.conductor._bury_in_cell0(
            self.ctxt, self.params['request_specs'][0], Exception('Foo'),
            build_requests=[inst_br], instances=[inst],
            block_device_mapping=self.params['block_device_mapping'])

        mock_create_bdm.assert_called_once_with(
            self.cell_mappings['cell0'], inst.flavor, inst.uuid,
            self.params['block_device_mapping'])

    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_tags')
    def test_bury_in_cell0_with_tags(self, mock_create_tags, mock_get_cell):
        mock_get_cell.return_value = self.cell_mappings['cell0']

        inst_br = fake_build_request.fake_req_obj(self.ctxt)
        del inst_br.instance.id
        inst_br.create()
        inst = inst_br.get_new_instance(self.ctxt)

        self.conductor._bury_in_cell0(
            self.ctxt, self.params['request_specs'][0], Exception('Foo'),
            build_requests=[inst_br], instances=[inst],
            tags=self.params['tags'])

        mock_create_tags.assert_called_once_with(
            test.MatchType(context.RequestContext), inst.uuid,
            self.params['tags'])

    def test_reset(self):
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            old_rpcapi = self.conductor_manager.compute_rpcapi
            self.conductor_manager.reset()
            mock_rpc.assert_called_once_with()
            self.assertNotEqual(old_rpcapi,
                                self.conductor_manager.compute_rpcapi)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_migrate_server_fails_with_rebuild(self, get_im):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])

        instance = fake_instance.fake_instance_obj(self.context,
                                                   vm_state=vm_states.ACTIVE)
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, instance, None, True, True, None, None, None)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_migrate_server_fails_with_flavor(self, get_im):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])
        flavor = flavors.get_flavor_by_name('m1.tiny')
        instance = fake_instance.fake_instance_obj(self.context,
                                                   vm_state=vm_states.ACTIVE,
                                                   flavor=flavor)
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, instance, None, True, False, flavor, None, None)

    def _build_request_spec(self, instance):
        return {
            'instance_properties': {
                'uuid': instance['uuid'], },
        }

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def _test_migrate_server_deals_with_expected_exceptions(self, ex,
            mock_execute, mock_set, get_im):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])
        instance = fake_instance.fake_db_instance(uuid=uuids.instance,
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        mock_execute.side_effect = ex
        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(type(ex),
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

        mock_set.assert_called_once_with(self.context,
                inst_obj.uuid,
                'compute_task', 'migrate_server',
                {'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'expected_task_state': task_states.MIGRATING},
                ex, self._build_request_spec(inst_obj))

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_migrate_server_deals_with_invalidcpuinfo_exception(
            self, get_im, mock_execute, mock_set):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])
        instance = fake_instance.fake_db_instance(uuid=uuids.instance,
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        ex = exc.InvalidCPUInfo(reason="invalid cpu info.")
        mock_execute.side_effect = ex

        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(exc.InvalidCPUInfo,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')
        mock_execute.assert_called_once_with()
        mock_set.assert_called_once_with(
            self.context, inst_obj.uuid, 'compute_task', 'migrate_server',
            {'vm_state': vm_states.ACTIVE,
             'task_state': None,
             'expected_task_state': task_states.MIGRATING},
            ex, self._build_request_spec(inst_obj))

    def test_migrate_server_deals_with_expected_exception(self):
        exs = [exc.InstanceInvalidState(instance_uuid="fake", attr='',
                                        state='', method=''),
               exc.DestinationHypervisorTooOld(),
               exc.HypervisorUnavailable(host='dummy'),
               exc.MigrationPreCheckError(reason='dummy'),
               exc.InvalidSharedStorage(path='dummy', reason='dummy'),
               exc.NoValidHost(reason='dummy'),
               exc.ComputeServiceUnavailable(host='dummy'),
               exc.InvalidHypervisorType(),
               exc.InvalidCPUInfo(reason='dummy'),
               exc.UnableToMigrateToSelf(instance_id='dummy', host='dummy'),
               exc.InvalidLocalStorage(path='dummy', reason='dummy'),
               exc.MigrationSchedulerRPCError(reason='dummy'),
               exc.ComputeHostNotFound(host='dummy')]
        for ex in exs:
            self._test_migrate_server_deals_with_expected_exceptions(ex)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def test_migrate_server_deals_with_unexpected_exceptions(self,
            mock_live_migrate, mock_set_state, get_im):
        get_im.return_value.cell_mapping = (
            objects.CellMappingList.get_all(self.context)[0])
        expected_ex = IOError('fake error')
        mock_live_migrate.side_effect = expected_ex
        instance = fake_instance.fake_db_instance()
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        ex = self.assertRaises(exc.MigrationError,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')
        request_spec = {'instance_properties': {
                'uuid': instance['uuid'], },
        }
        mock_set_state.assert_called_once_with(self.context,
                        instance['uuid'],
                        'compute_task', 'migrate_server',
                        dict(vm_state=vm_states.ERROR,
                             task_state=None,
                             expected_task_state=task_states.MIGRATING,),
                        expected_ex, request_spec)
        self.assertEqual(ex.kwargs['reason'], six.text_type(expected_ex))

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    def test_set_vm_state_and_notify(self, mock_set):
        self.conductor._set_vm_state_and_notify(
                self.context, 1, 'method', 'updates', 'ex', 'request_spec')
        mock_set.assert_called_once_with(
            self.context, 1, 'compute_task', 'method', 'updates', 'ex',
            'request_spec')

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_active_state(
            self, rollback_mock, notify_mock, select_dest_mock,
            metadata_mock, sig_mock, spec_fc_mock, im_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            instance_type_id=flavor['id'],
            vm_state=vm_states.ACTIVE,
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            availability_zone=None,
            pci_requests=None,
            numa_topology=None,
            project_id=self.context.project_id)
        image = 'fake-image'
        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        spec_fc_mock.return_value = fake_spec
        metadata_mock.return_value = image
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.ACTIVE,
                   'task_state': None}

        im_mock.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))

        self.assertRaises(exc.NoValidHost,
                          self.conductor._cold_migrate,
                          self.context, inst_obj,
                          flavor, {},
                          True, None, None)
        metadata_mock.assert_called_with({})
        sig_mock.assert_called_once_with(self.context, fake_spec)
        self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                              'migrate_server', updates,
                                              exc_info, fake_spec)
        rollback_mock.assert_called_once_with()

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_stopped_state(
            self, rollback_mock, notify_mock, select_dest_mock,
            metadata_mock, spec_fc_mock, sig_mock, im_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            numa_topology=None,
            pci_requests=None,
            availability_zone=None,
            project_id=self.context.project_id)
        image = 'fake-image'

        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        spec_fc_mock.return_value = fake_spec

        im_mock.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))

        metadata_mock.return_value = image
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        self.assertRaises(exc.NoValidHost,
                           self.conductor._cold_migrate,
                           self.context, inst_obj,
                           flavor, {},
                           True, None, None)
        metadata_mock.assert_called_with({})
        sig_mock.assert_called_once_with(self.context, fake_spec)
        self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, fake_spec)
        rollback_mock.assert_called_once_with()

    def test_cold_migrate_no_valid_host_error_msg(self):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID)
        fake_spec = fake_request_spec.fake_spec_obj()
        image = 'fake-image'

        with test.nested(
            mock.patch.object(utils, 'get_image_from_system_metadata',
                              return_value=image),
            mock.patch.object(self.conductor, '_set_vm_state_and_notify'),
            mock.patch.object(migrate.MigrationTask,
                              'execute',
                              side_effect=exc.NoValidHost(reason="")),
            mock.patch.object(migrate.MigrationTask, 'rollback')
        ) as (image_mock, set_vm_mock, task_execute_mock,
              task_rollback_mock):
            nvh = self.assertRaises(exc.NoValidHost,
                                    self.conductor._cold_migrate, self.context,
                                    inst_obj, flavor, {},
                                    True, fake_spec, None)
            self.assertIn('cold migrate', nvh.message)

    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    def test_cold_migrate_no_valid_host_in_group(self,
                                                 spec_fc_mock,
                                                 set_vm_mock,
                                                 task_rollback_mock,
                                                 task_exec_mock,
                                                 image_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            project_id=fakes.FAKE_PROJECT_ID,
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            numa_topology=None,
            pci_requests=None,
            availability_zone=None)
        image = 'fake-image'
        exception = exc.UnsupportedPolicyException(reason='')
        fake_spec = fake_request_spec.fake_spec_obj()
        spec_fc_mock.return_value = fake_spec

        image_mock.return_value = image
        task_exec_mock.side_effect = exception

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor._cold_migrate, self.context,
                          inst_obj, flavor, {}, True, None, None)

        updates = {'vm_state': vm_states.STOPPED, 'task_state': None}
        set_vm_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exception, fake_spec)
        spec_fc_mock.assert_called_once_with(
            self.context, inst_obj.uuid, image, flavor, inst_obj.numa_topology,
            inst_obj.pci_requests, {}, None, inst_obj.availability_zone,
            project_id=inst_obj.project_id, user_id=inst_obj.user_id)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_cold_migrate_exception_host_in_error_state_and_raise(
            self, prep_resize_mock, rollback_mock, notify_mock,
            select_dest_mock, metadata_mock, spec_fc_mock,
            sig_mock, im_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            availability_zone=None,
            pci_requests=None,
            numa_topology=None,
            project_id=self.context.project_id)
        image = 'fake-image'
        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        legacy_request_spec = fake_spec.to_legacy_request_spec_dict()
        spec_fc_mock.return_value = fake_spec

        im_mock.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))

        hosts = [dict(host='host1', nodename='node1', limits={})]
        metadata_mock.return_value = image
        exc_info = test.TestingException('something happened')
        select_dest_mock.return_value = [[fake_selection1]]

        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        prep_resize_mock.side_effect = exc_info
        self.assertRaises(test.TestingException,
                          self.conductor._cold_migrate,
                          self.context, inst_obj, flavor,
                          {}, True, None, None)

        # Filter properties are populated during code execution
        legacy_filter_props = {'retry': {'num_attempts': 1,
                                         'hosts': [['host1', 'node1']]},
                               'limits': {}}

        metadata_mock.assert_called_with({})
        sig_mock.assert_called_once_with(self.context, fake_spec)
        self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        select_dest_mock.assert_called_once_with(self.context, fake_spec,
                [inst_obj.uuid], return_objects=True, return_alternates=True)
        prep_resize_mock.assert_called_once_with(
            self.context, inst_obj, legacy_request_spec['image'],
            flavor, hosts[0]['host'], None,
            request_spec=legacy_request_spec,
            filter_properties=legacy_filter_props,
            node=hosts[0]['nodename'], clean_shutdown=True, host_list=[])
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, fake_spec)
        rollback_mock.assert_called_once_with()

    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    def test_cold_migrate_updates_flavor_if_existing_reqspec(self,
                                                             image_mock,
                                                             task_exec_mock,
                                                             spec_save_mock):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            availability_zone=None,
            pci_requests=None,
            numa_topology=None)
        image = 'fake-image'
        fake_spec = fake_request_spec.fake_spec_obj()

        image_mock.return_value = image
        # Just make sure we have an original flavor which is different from
        # the new one
        self.assertNotEqual(flavor, fake_spec.flavor)
        self.conductor._cold_migrate(self.context, inst_obj, flavor, {},
                                     True, fake_spec, None)

        # Now the RequestSpec should be updated...
        self.assertEqual(flavor, fake_spec.flavor)
        # ...and persisted
        spec_save_mock.assert_called_once_with()

    def test_resize_no_valid_host_error_msg(self):
        flavor = flavors.get_flavor_by_name('m1.tiny')
        flavor_new = flavors.get_flavor_by_name('m1.small')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=flavor['id'],
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID)

        fake_spec = fake_request_spec.fake_spec_obj()
        image = 'fake-image'

        with test.nested(
            mock.patch.object(utils, 'get_image_from_system_metadata',
                              return_value=image),
            mock.patch.object(scheduler_utils, 'build_request_spec',
                              return_value=fake_spec),
            mock.patch.object(self.conductor, '_set_vm_state_and_notify'),
            mock.patch.object(migrate.MigrationTask,
                              'execute',
                              side_effect=exc.NoValidHost(reason="")),
            mock.patch.object(migrate.MigrationTask, 'rollback')
        ) as (image_mock, brs_mock, vm_st_mock, task_execute_mock,
              task_rb_mock):
            nvh = self.assertRaises(exc.NoValidHost,
                                    self.conductor._cold_migrate, self.context,
                                    inst_obj, flavor_new, {},
                                    True, fake_spec, None)
            self.assertIn('resize', nvh.message)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'build_and_run_instance')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances')
    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch('nova.objects.BuildRequest.get_by_instance_uuid')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_build_instances_instance_not_found(
            self, fp, _mock_buildreq, mock_save, mock_build_rspec,
            mock_schedule, mock_build_run):
        fake_spec = objects.RequestSpec()
        fp.return_value = fake_spec
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}

        mock_build_rspec.return_value = spec
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        inst_uuids = [inst.uuid for inst in instances]

        sched_return = copy.deepcopy(fake_host_lists2)
        mock_schedule.return_value = sched_return
        mock_save.side_effect = [
            exc.InstanceNotFound(instance_id=instances[0].uuid), None]
        filter_properties2 = {'limits': {},
                              'retry': {'num_attempts': 1,
                                        'hosts': [['host2', 'node2']]}}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        self.conductor.build_instances(self.context,
                instances=instances,
                image=image,
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False, host_lists=None)
        # RequestSpec.from_primitives is called once before we call the
        # scheduler to select_destinations and then once per instance that
        # gets build in the compute.
        fp.assert_has_calls([
            mock.call(self.context, spec, filter_properties),
            mock.call(self.context, spec, filter_properties2)])
        mock_build_rspec.assert_called_once_with(image, mock.ANY)
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, inst_uuids, return_alternates=True)
        mock_save.assert_has_calls([mock.call(), mock.call()])
        mock_build_run.assert_called_once_with(
            self.context, instance=instances[1], host='host2',
            image={'fake-data': 'should_pass_silently'},
            request_spec=fake_spec,
            filter_properties=filter_properties2,
            admin_password='admin_password',
            injected_files='injected_files',
            requested_networks=None,
            security_groups='security_groups',
            block_device_mapping=test.MatchType(
                objects.BlockDeviceMappingList),
            node='node2', limits=None, host_list=[])

    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'build_request_spec')
    def test_build_instances_info_cache_not_found(self, build_request_spec,
                                                  setup_instance_group):
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        destinations = [[fake_selection1], [fake_selection2]]
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        build_request_spec.return_value = spec
        fake_spec = objects.RequestSpec()
        with test.nested(
                mock.patch.object(instances[0], 'save',
                    side_effect=exc.InstanceInfoCacheNotFound(
                        instance_uuid=instances[0].uuid)),
                mock.patch.object(instances[1], 'save'),
                mock.patch.object(objects.RequestSpec, 'from_primitives',
                                  return_value=fake_spec),
                mock.patch.object(self.conductor_manager.scheduler_client,
                    'select_destinations', return_value=destinations),
                mock.patch.object(self.conductor_manager.compute_rpcapi,
                    'build_and_run_instance'),
                mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
                ) as (inst1_save, inst2_save, from_primitives,
                        select_destinations,
                        build_and_run_instance, get_buildreq):

            # build_instances() is a cast, we need to wait for it to complete
            self.useFixture(cast_as_call.CastAsCall(self))

            self.conductor.build_instances(self.context,
                    instances=instances,
                    image=image,
                    filter_properties={},
                    admin_password='admin_password',
                    injected_files='injected_files',
                    requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping='block_device_mapping',
                    legacy_bdm=False)

            setup_instance_group.assert_called_once_with(
                self.context, fake_spec)
            get_buildreq.return_value.destroy.assert_called_once_with()
            build_and_run_instance.assert_called_once_with(self.context,
                    instance=instances[1], host='host2', image={'fake-data':
                        'should_pass_silently'},
                    request_spec=from_primitives.return_value,
                    filter_properties={'limits': {},
                                       'retry': {'num_attempts': 1,
                                                 'hosts': [['host2',
                                                            'node2']]}},
                    admin_password='admin_password',
                    injected_files='injected_files',
                    requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping=mock.ANY,
                    node='node2', limits=None, host_list=[])

    @mock.patch('nova.objects.Instance.save')
    def test_build_instances_max_retries_exceeded(self, mock_save):
        """Tests that when populate_retry raises MaxRetriesExceeded in
        build_instances, we don't attempt to cleanup the build request.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'id': uuids.image_id}
        filter_props = {
            'retry': {
                'num_attempts': CONF.scheduler.max_attempts
            }
        }
        requested_networks = objects.NetworkRequestList()
        with mock.patch.object(self.conductor, '_destroy_build_request',
                               new_callable=mock.NonCallableMock):
            self.conductor.build_instances(
                self.context, [instance], image, filter_props,
                mock.sentinel.admin_pass, mock.sentinel.files,
                requested_networks, mock.sentinel.secgroups)
            mock_save.assert_called_once_with()

    @mock.patch('nova.objects.Instance.save')
    def test_build_instances_reschedule_no_valid_host(self, mock_save):
        """Tests that when select_destinations raises NoValidHost in
        build_instances, we don't attempt to cleanup the build request if
        we're rescheduling (num_attempts>1).
        """
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'id': uuids.image_id}
        filter_props = {
            'retry': {
                'num_attempts': 1   # populate_retry will increment this
            }
        }
        requested_networks = objects.NetworkRequestList()
        with mock.patch.object(self.conductor, '_destroy_build_request',
                               new_callable=mock.NonCallableMock):
            with mock.patch.object(
                    self.conductor.scheduler_client, 'select_destinations',
                    side_effect=exc.NoValidHost(reason='oops')):
                self.conductor.build_instances(
                    self.context, [instance], image, filter_props,
                    mock.sentinel.admin_pass, mock.sentinel.files,
                    requested_networks, mock.sentinel.secgroups)
                mock_save.assert_called_once_with()

    def test_cleanup_allocated_networks_none_requested(self):
        # Tests that we don't deallocate networks if 'none' were specifically
        # requested.
        fake_inst = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='none')])
        with mock.patch.object(self.conductor.network_api,
                               'deallocate_for_instance') as deallocate:
            with mock.patch.object(fake_inst, 'save') as mock_save:
                self.conductor._cleanup_allocated_networks(
                    self.context, fake_inst, requested_networks)
        self.assertFalse(deallocate.called)
        self.assertEqual('False',
                         fake_inst.system_metadata['network_allocated'],
                         fake_inst.system_metadata)
        mock_save.assert_called_once_with()

    def test_cleanup_allocated_networks_auto_or_none_provided(self):
        # Tests that we deallocate networks if auto-allocating networks or
        # requested_networks=None.
        fake_inst = fake_instance.fake_instance_obj(
            self.context, expected_attrs=['system_metadata'])
        requested_networks = objects.NetworkRequestList(
            objects=[objects.NetworkRequest(network_id='auto')])
        for req_net in (requested_networks, None):
            with mock.patch.object(self.conductor.network_api,
                                   'deallocate_for_instance') as deallocate:
                with mock.patch.object(fake_inst, 'save') as mock_save:
                    self.conductor._cleanup_allocated_networks(
                        self.context, fake_inst, req_net)
        deallocate.assert_called_once_with(
            self.context, fake_inst, requested_networks=req_net)
        self.assertEqual('False',
                         fake_inst.system_metadata['network_allocated'],
                         fake_inst.system_metadata)
        mock_save.assert_called_once_with()

    @mock.patch.object(objects.ComputeNode, 'get_by_host_and_nodename',
                       side_effect=exc.ComputeHostNotFound('source-host'))
    def test_allocate_for_evacuate_dest_host_source_node_not_found_no_reqspec(
            self, get_compute_node):
        """Tests that the source node for the instance isn't found. In this
        case there is no request spec provided.
        """
        instance = self.params['build_requests'][0].instance
        instance.host = 'source-host'
        with mock.patch.object(self.conductor,
                               '_set_vm_state_and_notify') as notify:
            ex = self.assertRaises(
                exc.ComputeHostNotFound,
                self.conductor._allocate_for_evacuate_dest_host,
                self.ctxt, instance, 'dest-host')
        get_compute_node.assert_called_once_with(
            self.ctxt, instance.host, instance.node)
        notify.assert_called_once_with(
            self.ctxt, instance.uuid, 'rebuild_server',
            {'vm_state': instance.vm_state, 'task_state': None}, ex, None)

    @mock.patch.object(objects.ComputeNode, 'get_by_host_and_nodename',
                       return_value=objects.ComputeNode(host='source-host'))
    @mock.patch.object(objects.ComputeNode,
                       'get_first_node_by_host_for_old_compat',
                       side_effect=exc.ComputeHostNotFound(host='dest-host'))
    def test_allocate_for_evacuate_dest_host_dest_node_not_found_reqspec(
            self, get_dest_node, get_source_node):
        """Tests that the destination node for the request isn't found. In this
        case there is a request spec provided.
        """
        instance = self.params['build_requests'][0].instance
        instance.host = 'source-host'
        reqspec = self.params['request_specs'][0]
        with mock.patch.object(self.conductor,
                               '_set_vm_state_and_notify') as notify:
            ex = self.assertRaises(
                exc.ComputeHostNotFound,
                self.conductor._allocate_for_evacuate_dest_host,
                self.ctxt, instance, 'dest-host', reqspec)
        get_source_node.assert_called_once_with(
            self.ctxt, instance.host, instance.node)
        get_dest_node.assert_called_once_with(
            self.ctxt, 'dest-host', use_slave=True)
        notify.assert_called_once_with(
            self.ctxt, instance.uuid, 'rebuild_server',
            {'vm_state': instance.vm_state, 'task_state': None}, ex, reqspec)

    @mock.patch.object(objects.ComputeNode, 'get_by_host_and_nodename',
                       return_value=objects.ComputeNode(host='source-host'))
    @mock.patch.object(objects.ComputeNode,
                       'get_first_node_by_host_for_old_compat',
                       return_value=objects.ComputeNode(host='dest-host'))
    def test_allocate_for_evacuate_dest_host_claim_fails(
            self, get_dest_node, get_source_node):
        """Tests that the allocation claim fails."""
        instance = self.params['build_requests'][0].instance
        instance.host = 'source-host'
        reqspec = self.params['request_specs'][0]
        with test.nested(
            mock.patch.object(self.conductor,
                              '_set_vm_state_and_notify'),
            mock.patch.object(scheduler_utils,
                              'claim_resources_on_destination',
                              side_effect=exc.NoValidHost(reason='I am full'))
        ) as (
            notify, claim
        ):
            ex = self.assertRaises(
                exc.NoValidHost,
                self.conductor._allocate_for_evacuate_dest_host,
                self.ctxt, instance, 'dest-host', reqspec)
        get_source_node.assert_called_once_with(
            self.ctxt, instance.host, instance.node)
        get_dest_node.assert_called_once_with(
            self.ctxt, 'dest-host', use_slave=True)
        claim.assert_called_once_with(
            self.ctxt, self.conductor.scheduler_client.reportclient, instance,
            get_source_node.return_value, get_dest_node.return_value)
        notify.assert_called_once_with(
            self.ctxt, instance.uuid, 'rebuild_server',
            {'vm_state': instance.vm_state, 'task_state': None}, ex, reqspec)

    @mock.patch('nova.conductor.tasks.live_migrate.LiveMigrationTask.execute')
    def test_live_migrate_instance(self, mock_execute):
        """Tests that asynchronous live migration targets the cell that the
        instance lives in.
        """
        instance = self.params['build_requests'][0].instance
        scheduler_hint = {'host': None}
        reqspec = self.params['request_specs'][0]

        # setUp created the instance mapping but didn't target it to a cell,
        # to mock out the API doing that, but let's just update it to point
        # at cell1.
        im = objects.InstanceMapping.get_by_instance_uuid(
            self.ctxt, instance.uuid)
        im.cell_mapping = self.cell_mappings[test.CELL1_NAME]
        im.save()

        # Make sure the InstanceActionEvent is created in the cell.
        original_event_start = objects.InstanceActionEvent.event_start

        def fake_event_start(_cls, ctxt, *args, **kwargs):
            # Make sure the context is targeted to the cell that the instance
            # was created in.
            self.assertIsNotNone(ctxt.db_connection, 'Context is not targeted')
            original_event_start(ctxt, *args, **kwargs)

        self.stub_out(
            'nova.objects.InstanceActionEvent.event_start', fake_event_start)

        self.conductor.live_migrate_instance(
            self.ctxt, instance, scheduler_hint, block_migration=None,
            disk_over_commit=None, request_spec=reqspec)
        mock_execute.assert_called_once_with()


class ConductorTaskRPCAPITestCase(_BaseTaskTestCase,
        test_compute.BaseTestCase):
    """Conductor compute_task RPC namespace Tests."""
    def setUp(self):
        super(ConductorTaskRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_rpcapi.ComputeTaskAPI()
        service_manager = self.conductor_service.manager
        self.conductor_manager = service_manager.compute_task_mgr

    def test_live_migrate_instance(self):

        inst = fake_instance.fake_db_instance()
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), inst, [])
        version = '1.15'
        scheduler_hint = {'host': 'destination'}
        cctxt_mock = mock.MagicMock()

        @mock.patch.object(self.conductor.client, 'prepare',
                          return_value=cctxt_mock)
        def _test(prepare_mock):
            self.conductor.live_migrate_instance(
                self.context, inst_obj, scheduler_hint,
                'block_migration', 'disk_over_commit', request_spec=None)
            prepare_mock.assert_called_once_with(version=version)
            kw = {'instance': inst_obj, 'scheduler_hint': scheduler_hint,
                  'block_migration': 'block_migration',
                  'disk_over_commit': 'disk_over_commit',
                  'request_spec': None,
              }
            cctxt_mock.cast.assert_called_once_with(
                self.context, 'live_migrate_instance', **kw)
        _test()

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_targets_cell_no_instance_mapping(self, mock_im):

        @conductor_manager.targets_cell
        def test(self, context, instance):
            return mock.sentinel.iransofaraway

        mock_im.side_effect = exc.InstanceMappingNotFound(uuid='something')
        ctxt = mock.MagicMock()
        inst = mock.MagicMock()
        self.assertEqual(mock.sentinel.iransofaraway,
                         test(None, ctxt, inst))
        mock_im.assert_called_once_with(ctxt, inst.uuid)

    def test_schedule_and_build_instances_with_tags(self):

        build_request = fake_build_request.fake_req_obj(self.context)
        request_spec = objects.RequestSpec(
            instance_uuid=build_request.instance_uuid)
        image = {'fake_data': 'should_pass_silently'}
        admin_password = 'fake_password'
        injected_file = 'fake'
        requested_network = None
        block_device_mapping = None
        tags = ['fake_tag']
        version = '1.17'
        cctxt_mock = mock.MagicMock()

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           return_value=True)
        @mock.patch.object(self.conductor.client, 'prepare',
                          return_value=cctxt_mock)
        def _test(prepare_mock, can_send_mock):
            self.conductor.schedule_and_build_instances(
                self.context, build_request, request_spec, image,
                admin_password, injected_file, requested_network,
                block_device_mapping, tags=tags)
            prepare_mock.assert_called_once_with(version=version)
            kw = {'build_requests': build_request,
                  'request_specs': request_spec,
                  'image': jsonutils.to_primitive(image),
                  'admin_password': admin_password,
                  'injected_files': injected_file,
                  'requested_networks': requested_network,
                  'block_device_mapping': block_device_mapping,
                  'tags': tags}
            cctxt_mock.cast.assert_called_once_with(
                self.context, 'schedule_and_build_instances', **kw)
        _test()

    def test_schedule_and_build_instances_with_tags_cannot_send(self):

        build_request = fake_build_request.fake_req_obj(self.context)
        request_spec = objects.RequestSpec(
            instance_uuid=build_request.instance_uuid)
        image = {'fake_data': 'should_pass_silently'}
        admin_password = 'fake_password'
        injected_file = 'fake'
        requested_network = None
        block_device_mapping = None
        tags = ['fake_tag']
        cctxt_mock = mock.MagicMock()

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           return_value=False)
        @mock.patch.object(self.conductor.client, 'prepare',
                           return_value=cctxt_mock)
        def _test(prepare_mock, can_send_mock):
            self.conductor.schedule_and_build_instances(
                self.context, build_request, request_spec, image,
                admin_password, injected_file, requested_network,
                block_device_mapping, tags=tags)
            prepare_mock.assert_called_once_with(version='1.16')
            kw = {'build_requests': build_request,
                  'request_specs': request_spec,
                  'image': jsonutils.to_primitive(image),
                  'admin_password': admin_password,
                  'injected_files': injected_file,
                  'requested_networks': requested_network,
                  'block_device_mapping': block_device_mapping}
            cctxt_mock.cast.assert_called_once_with(
                self.context, 'schedule_and_build_instances', **kw)
        _test()

    def test_build_instances_with_request_spec_ok(self):
        """Tests passing a request_spec to the build_instances RPC API
        method and having it passed through to the conductor task manager.
        """
        image = {}
        cctxt_mock = mock.MagicMock()

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           side_effect=(False, True, True, True, True))
        @mock.patch.object(self.conductor.client, 'prepare',
                           return_value=cctxt_mock)
        def _test(prepare_mock, can_send_mock):
            self.conductor.build_instances(
                self.context, mock.sentinel.instances, image,
                mock.sentinel.filter_properties, mock.sentinel.admin_password,
                mock.sentinel.injected_files, mock.sentinel.requested_networks,
                mock.sentinel.security_groups,
                mock.sentinel.block_device_mapping,
                request_spec=mock.sentinel.request_spec)
            kw = {'instances': mock.sentinel.instances, 'image': image,
                  'filter_properties': mock.sentinel.filter_properties,
                  'admin_password': mock.sentinel.admin_password,
                  'injected_files': mock.sentinel.injected_files,
                  'requested_networks': mock.sentinel.requested_networks,
                  'security_groups': mock.sentinel.security_groups,
                  'request_spec': mock.sentinel.request_spec}
            cctxt_mock.cast.assert_called_once_with(
                self.context, 'build_instances', **kw)
        _test()

    def test_build_instances_with_request_spec_cannot_send(self):
        """Tests passing a request_spec to the build_instances RPC API
        method but not having it passed through to the conductor task manager
        because the version is too old to handle it.
        """
        image = {}
        cctxt_mock = mock.MagicMock()

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           side_effect=(False, False, True, True, True))
        @mock.patch.object(self.conductor.client, 'prepare',
                           return_value=cctxt_mock)
        def _test(prepare_mock, can_send_mock):
            self.conductor.build_instances(
                self.context, mock.sentinel.instances, image,
                mock.sentinel.filter_properties, mock.sentinel.admin_password,
                mock.sentinel.injected_files, mock.sentinel.requested_networks,
                mock.sentinel.security_groups,
                mock.sentinel.block_device_mapping,
                request_spec=mock.sentinel.request_spec)
            kw = {'instances': mock.sentinel.instances, 'image': image,
                  'filter_properties': mock.sentinel.filter_properties,
                  'admin_password': mock.sentinel.admin_password,
                  'injected_files': mock.sentinel.injected_files,
                  'requested_networks': mock.sentinel.requested_networks,
                  'security_groups': mock.sentinel.security_groups}
            cctxt_mock.cast.assert_called_once_with(
                self.context, 'build_instances', **kw)
        _test()


class ConductorTaskAPITestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
    """Compute task API Tests."""
    def setUp(self):
        super(ConductorTaskAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.ComputeTaskAPI()
        service_manager = self.conductor_service.manager
        self.conductor_manager = service_manager.compute_task_mgr

    def test_live_migrate(self):
        inst = fake_instance.fake_db_instance()
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), inst, [])

        with mock.patch.object(self.conductor.conductor_compute_rpcapi,
                               'migrate_server') as mock_migrate_server:
            self.conductor.live_migrate_instance(self.context, inst_obj,
                'destination', 'block_migration', 'disk_over_commit')
            mock_migrate_server.assert_called_once_with(
                self.context, inst_obj, {'host': 'destination'}, True, False,
                None, 'block_migration', 'disk_over_commit', None,
                request_spec=None)
