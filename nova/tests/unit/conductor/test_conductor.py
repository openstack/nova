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
from mox3 import mox
import oslo_messaging as messaging
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
from nova import db
from nova import exception as exc
from nova.image import api as image_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova import rpc
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
from nova.tests import uuidsentinel as uuids
from nova import utils

CONF = conf.CONF


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

        self.stubs.Set(rpc.RequestContextSerializer, 'deserialize_context',
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

        def fake_ping(context, message, timeout):
            timeouts.append(timeout)
            calls['count'] += 1
            if calls['count'] < 15:
                raise messaging.MessagingTimeout("fake")

        self.stubs.Set(self.conductor.base_rpcapi, 'ping', fake_ping)

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

        self.stubs.Set(rpc.RequestContextSerializer, 'deserialize_context',
                       fake_deserialize_context)

        self.useFixture(fixtures.SpawnIsSynchronousFixture())

    def _prepare_rebuild_args(self, update_args=None):
        # Args that don't get passed in to the method but do get passed to RPC
        migration = update_args and update_args.pop('migration', None)
        node = update_args and update_args.pop('node', None)
        limits = update_args and update_args.pop('limits', None)

        rebuild_args = {'new_pass': 'admin_password',
                        'injected_files': 'files_to_inject',
                        'image_ref': 'image_ref',
                        'orig_image_ref': 'orig_image_ref',
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

        # Args that are passed in to the method but don't get passed to RPC
        compute_rebuild_args.pop('request_spec')

        return rebuild_args, compute_rebuild_args

    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    def _test_cold_migrate(self, spec_from_components, get_image_from_metadata,
                           migration_task_execute, spec_save,
                           clean_shutdown=True):
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
                clean_shutdown)
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

    @mock.patch('nova.objects.Instance.refresh')
    def test_build_instances(self, mock_refresh):
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

        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(db,
                                 'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                                 'build_and_run_instance')

        spec = {'image': {'fake_data': 'should_pass_silently'},
                'instance_properties': instance_properties,
                'instance_type': instance_type_p,
                'num_instances': 2}
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        self.conductor_manager._schedule_instances(self.context,
                spec, filter_properties).AndReturn(
                        [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                         {'host': 'host2', 'nodename': 'node2', 'limits': []}])
        db.block_device_mapping_get_all_by_instance(self.context,
                instances[0].uuid).AndReturn([])
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context,
                instance=mox.IgnoreArg(),
                host='host1',
                image={'fake_data': 'should_pass_silently'},
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': instance_properties,
                    'instance_type': instance_type_p,
                    'num_instances': 2},
                filter_properties={'retry': {'num_attempts': 1,
                                             'hosts': [['host1', 'node1']]},
                                   'limits': []},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IgnoreArg(),
                node='node1', limits=[])
        db.block_device_mapping_get_all_by_instance(self.context,
                instances[1].uuid).AndReturn([])
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context,
                instance=mox.IgnoreArg(),
                host='host2',
                image={'fake_data': 'should_pass_silently'},
                request_spec={
                    'image': {'fake_data': 'should_pass_silently'},
                    'instance_properties': instance_properties,
                    'instance_type': instance_type_p,
                    'num_instances': 2},
                filter_properties={'limits': [],
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['host2', 'node2']]}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IgnoreArg(),
                node='node2', limits=[])
        self.mox.ReplayAll()

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.conductor.build_instances(self.context,
                instances=instances,
                image={'fake_data': 'should_pass_silently'},
                filter_properties={},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping='block_device_mapping',
                legacy_bdm=False)

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
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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
            self.useFixture(cast_as_call.CastAsCall(self.stubs))

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
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
            side_effect=exc.InstanceMappingNotFound(uuid='fake'))
    @mock.patch.object(objects.HostMapping, 'get_by_host')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_no_instance_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_refresh):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]

        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.HostMapping, 'get_by_host',
            side_effect=exc.HostMappingNotFound(name='fake'))
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_no_host_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_refresh):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]

        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        inst_mapping_mocks = [mock.Mock() for i in range(num_instances)]
        mock_get_inst_map_by_uuid.side_effect = inst_mapping_mocks
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(objects.HostMapping, 'get_by_host')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_build_instances_update_instance_mapping(self, _mock_set_state,
            mock_select_dests, mock_get_by_host, mock_get_inst_map_by_uuid,
            _mock_refresh):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]
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
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

    @mock.patch.object(objects.Instance, 'refresh', new=mock.MagicMock())
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_destroy_build_request(self, mock_select_dests,
            mock_build_req_get):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]

        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        build_req_mocks = [mock.Mock() for i in range(num_instances)]
        mock_build_req_get.side_effect = build_req_mocks
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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
                              legacy_bdm=False)

        do_test()

        for build_req in build_req_mocks:
            build_req.destroy.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'refresh', new=mock.MagicMock())
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid',
            side_effect=exc.BuildRequestNotFound(uuid='fake'))
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_build_request_not_found_older_api(self,
            mock_select_dests, mock_build_req_get):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]

        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance')
        @mock.patch.object(self.conductor_manager,
            '_populate_instance_mapping', new=mock.MagicMock())
        def do_test(mock_build_and_run):
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
            self.assertTrue(mock_build_and_run.called)

        do_test()

    @mock.patch.object(objects.Service, 'get_minimum_version', return_value=12)
    @mock.patch.object(objects.Instance, 'refresh', new=mock.MagicMock())
    @mock.patch.object(objects.BuildRequest, 'get_by_instance_uuid',
            side_effect=exc.BuildRequestNotFound(uuid='fake'))
    @mock.patch.object(scheduler_client.SchedulerClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_build_request_not_found_because_delete(self,
            mock_select_dests, mock_build_req_get, mock_service_version):

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]

        num_instances = 2
        instances = [fake_instance.fake_instance_obj(self.context)
                     for i in range(num_instances)]
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        inst_map_mock = mock.MagicMock()

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance')
        @mock.patch.object(self.conductor_manager,
            '_populate_instance_mapping', return_value=inst_map_mock)
        def do_test(mock_pop_inst_map, mock_build_and_run):
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
            self.assertFalse(mock_build_and_run.called)
            self.assertTrue(inst_map_mock.destroy.called)

        do_test()
        mock_service_version.assert_called_once_with(self.context,
                                                     'nova-osapi_compute')

    @mock.patch.object(objects.Instance, 'refresh', new=mock.MagicMock())
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

        mock_select_dests.return_value = [
                {'host': 'host1', 'nodename': 'node1', 'limits': []}]

        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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
                legacy_bdm=False)

            mock_build_and_run.assert_called_once_with(
                self.context,
                instance=mock.ANY,
                host='host1',
                image=image,
                request_spec=mock.ANY,
                filter_properties={'retry': {'num_attempts': 2,
                                             'hosts': [['host1', 'node1']]},
                                   'limits': []},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=test.MatchType(
                    objects.BlockDeviceMappingList),
                node='node1', limits=[])
            mock_pop_inst_map.assert_not_called()
            mock_destroy_build_req.assert_not_called()

        do_test()

    def test_unshelve_instance_on_host(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'start_instance')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager.compute_rpcapi.start_instance(self.context,
                instance)
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

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
        request_spec = fake_spec.to_legacy_request_spec_dict()

        host = {'host': 'host1', 'nodename': 'node1', 'limits': []}

        # unshelve_instance() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'unshelve_instance')
        @mock.patch.object(scheduler_utils, 'populate_filter_properties')
        @mock.patch.object(scheduler_utils, 'populate_retry')
        @mock.patch.object(self.conductor_manager, '_schedule_instances')
        @mock.patch.object(objects.RequestSpec, 'to_legacy_request_spec_dict')
        @mock.patch.object(objects.RequestSpec,
                           'to_legacy_filter_properties_dict')
        @mock.patch.object(objects.RequestSpec, 'reset_forced_destinations')
        def do_test(reset_forced_destinations,
                    to_filtprops, to_reqspec, sched_instances,
                    populate_retry, populate_filter_properties,
                    unshelve_instance):
            to_filtprops.return_value = filter_properties
            to_reqspec.return_value = request_spec
            sched_instances.return_value = [host]
            self.conductor.unshelve_instance(self.context, instance, fake_spec)
            reset_forced_destinations.assert_called_once_with()
            sched_instances.assert_called_once_with(self.context, request_spec,
                                                    filter_properties)
            # NOTE(sbauza): Since the instance is dehydrated when passing
            # through the RPC API, we can only assert mock.ANY for it
            unshelve_instance.assert_called_once_with(
                self.context, mock.ANY, host['host'], image=mock.ANY,
                filter_properties=filter_properties, node=host['nodename']
            )

        do_test()

    def test_unshelve_offloaded_instance_glance_image_not_found(self):
        shelved_image_id = "image_not_found"

        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.task_state = task_states.UNSHELVING
        instance.save()
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.image_api, 'get')

        e = exc.ImageNotFound(image_id=shelved_image_id)
        self.conductor_manager.image_api.get(
            self.context, shelved_image_id, show_deleted=False).AndRaise(e)
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        system_metadata['shelved_image_id'] = shelved_image_id

        self.assertRaises(
            exc.UnshelveException,
            self.conductor_manager.unshelve_instance,
            self.context, instance)
        self.assertEqual(instance.vm_state, vm_states.ERROR)

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
        ) as (schedule_mock, unshelve_mock):
            schedule_mock.return_value = [{'host': 'fake_host',
                                           'nodename': 'fake_node',
                                           'limits': {}}]
            self.conductor_manager.unshelve_instance(self.context, instance)
            self.assertEqual(1, unshelve_mock.call_count)

    def test_unshelve_instance_schedule_and_rebuild(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {'retry': {'num_attempts': 1,
                                       'hosts': []}}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(self.conductor_manager.image_api, 'get')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        self.conductor_manager.image_api.get(self.context,
                'fake_image_id', show_deleted=False).AndReturn('fake_image')
        scheduler_utils.build_request_spec(self.context, 'fake_image',
                mox.IgnoreArg()).AndReturn('req_spec')
        self.conductor_manager._schedule_instances(self.context,
                'req_spec', filter_properties).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image='fake_image',
                filter_properties={'limits': {},
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['fake_host',
                                                        'fake_node']]}},
                                    node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_image_id'] = 'fake_image_id'
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

    def test_unshelve_instance_schedule_and_rebuild_novalid_host(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        def fake_schedule_instances(context, image, filter_properties,
                                    *instances):
            raise exc.NoValidHost(reason='')

        with test.nested(
            mock.patch.object(self.conductor_manager.image_api, 'get',
                              return_value='fake_image'),
            mock.patch.object(self.conductor_manager, '_schedule_instances',
                              fake_schedule_instances)
        ) as (_get_image, _schedule_instances):
            system_metadata['shelved_at'] = timeutils.utcnow()
            system_metadata['shelved_image_id'] = 'fake_image_id'
            system_metadata['shelved_host'] = 'fake-mini'
            self.conductor_manager.unshelve_instance(self.context, instance)
            _get_image.assert_has_calls([mock.call(self.context,
                                      system_metadata['shelved_image_id'],
                                      show_deleted=False)])
            self.assertEqual(vm_states.SHELVED_OFFLOADED, instance.vm_state)

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances',
                       side_effect=messaging.MessagingTimeout())
    @mock.patch.object(image_api.API, 'get', return_value='fake_image')
    def test_unshelve_instance_schedule_and_rebuild_messaging_exception(
            self, mock_get_image, mock_schedule_instances):
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

    def test_unshelve_instance_schedule_and_rebuild_volume_backed(self):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        filter_properties = {'retry': {'num_attempts': 1,
                                       'hosts': []}}
        system_metadata = instance.system_metadata

        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'unshelve_instance')

        scheduler_utils.build_request_spec(self.context, None,
                mox.IgnoreArg()).AndReturn('req_spec')
        self.conductor_manager._schedule_instances(self.context,
                'req_spec', filter_properties).AndReturn(
                        [{'host': 'fake_host',
                          'nodename': 'fake_node',
                          'limits': {}}])
        self.conductor_manager.compute_rpcapi.unshelve_instance(self.context,
                instance, 'fake_host', image=None,
                filter_properties={'limits': {},
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['fake_host',
                                                        'fake_node']]}},
                node='fake_node')
        self.mox.ReplayAll()

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(self.context, instance)

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

    def test_rebuild_instance_with_scheduler(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = 'fake-limits'
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits})
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
                              return_value=[{'host': expected_host,
                                             'nodename': expected_node,
                                             'limits': expected_limits}]),
            mock.patch('nova.scheduler.utils.build_request_spec',
                       return_value=request_spec)
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, bs_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context, fake_spec)
            compute_args['host'] = expected_host
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)

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
                       return_value=request_spec)
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, bs_mock):
            self.assertRaises(exc.NoValidHost,
                              self.conductor_manager.rebuild_instance,
                              context=self.context, instance=inst_obj,
                              **rebuild_args)
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context, fake_spec)
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
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor.rebuild_instance,
                          self.context,
                          inst_obj,
                          **rebuild_args)
        updates = {'vm_state': vm_states.ACTIVE, 'task_state': None}
        state_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                           'rebuild_server', updates,
                                           exception, request_spec)
        self.assertFalse(select_dest_mock.called)
        self.assertFalse(rebuild_mock.called)

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

    def test_rebuild_instance_with_request_spec(self):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = 'fake-limits'
        request_spec = {}
        filter_properties = {'ignore_hosts': [(inst_obj.host)]}
        fake_spec = objects.RequestSpec(ignore_hosts=[])
        augmented_spec = objects.RequestSpec(ignore_hosts=[inst_obj.host])
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits,
             'request_spec': fake_spec})
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(objects.RequestSpec, 'from_primitives',
                              return_value=augmented_spec),
            mock.patch.object(self.conductor_manager.scheduler_client,
                              'select_destinations',
                              return_value=[{'host': expected_host,
                                             'nodename': expected_node,
                                             'limits': expected_limits}]),
            mock.patch.object(fake_spec, 'reset_forced_destinations'),
            mock.patch.object(fake_spec, 'to_legacy_request_spec_dict',
                       return_value=request_spec),
            mock.patch.object(fake_spec, 'to_legacy_filter_properties_dict',
                       return_value=filter_properties),
        ) as (rebuild_mock, sig_mock, fp_mock, select_dest_mock, reset_fd,
              to_reqspec, to_filtprops):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            reset_fd.assert_called_once_with()
            to_reqspec.assert_called_once_with()
            to_filtprops.assert_called_once_with()
            fp_mock.assert_called_once_with(self.context, request_spec,
                                            filter_properties)
            select_dest_mock.assert_called_once_with(self.context,
                                                     augmented_spec)
            compute_args['host'] = expected_host
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)


class ConductorTaskTestCase(_BaseTaskTestCase, test_compute.BaseTestCase):
    """ComputeTaskManager Tests."""
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
        params['request_specs'] = [objects.RequestSpec(
            instance_uuid=build_request.instance_uuid)]
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
        self.params = params

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_instances(self, select_destinations,
                                          build_and_run_instance):
        select_destinations.return_value = [{'host': 'fake-host',
                                             'nodename': 'fake-nodename',
                                             'limits': None}]
        params = self.params
        details = {}

        def _build_and_run_instance(ctxt, *args, **kwargs):
            details['instance'] = kwargs['instance']
            self.assertTrue(kwargs['instance'].id)
            self.assertEqual(1, len(kwargs['block_device_mapping']))
            # FIXME(danms): How to validate the db connection here?

        self.start_service('compute', host='fake-host')
        build_and_run_instance.side_effect = _build_and_run_instance
        self.conductor.schedule_and_build_instances(**params)
        self.assertTrue(build_and_run_instance.called)

        instance_uuid = details['instance'].uuid
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            self.context, instance_uuid)
        ephemeral = list(filter(block_device.new_format_is_ephemeral, bdms))
        self.assertEqual(1, len(ephemeral))
        swap = list(filter(block_device.new_format_is_swap, bdms))
        self.assertEqual(0, len(swap))

        self.assertEqual(1, ephemeral[0].volume_size)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    def test_schedule_and_build_multiple_instances(self,
                                                   get_hostmapping,
                                                   select_destinations,
                                                   build_and_run_instance):
        # This list needs to match the number of build_requests and the number
        # of request_specs in params.
        select_destinations.return_value = [{'host': 'fake-host',
                                             'nodename': 'fake-nodename',
                                             'limits': None},
                                            {'host': 'fake-host',
                                             'nodename': 'fake-nodename',
                                             'limits': None},
                                            {'host': 'fake-host2',
                                             'nodename': 'fake-nodename2',
                                             'limits': None},
                                            {'host': 'fake-host2',
                                             'nodename': 'fake-nodename2',
                                             'limits': None}]

        params = self.params

        self.start_service('compute', host='fake-host')
        self.start_service('compute', host='fake-host2')

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
                instance_uuid=build_request.instance_uuid))

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
        self.assertIsNone(None, instance.task_state)

    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling(self, bury,
                                                         br_destroy,
                                                         select_destinations,
                                                         build_and_run):
        br_destroy.side_effect = exc.BuildRequestNotFound(uuid='foo')
        self.start_service('compute', host='fake-host')
        select_destinations.return_value = [{'host': 'fake-host',
                                             'nodename': 'nodesarestupid',
                                             'limits': None}]
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertFalse(build_and_run.called)
        self.assertFalse(bury.called)
        self.assertTrue(br_destroy.called)

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
        self.start_service('compute', host='fake-host')
        select_destinations.return_value = [{'host': 'fake-host',
                                             'nodename': 'nodesarestupid',
                                             'limits': None}]
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
                       build_requests=None, instances=None):
            self.assertIn('not mapped to any cell', str(exc))
            self.assertEqual(1, len(build_requests))
            self.assertEqual(1, len(instances))
            self.assertEqual(build_requests[0].instance_uuid,
                             instances[0].uuid)

        bury.side_effect = _fake_bury
        select_dest.return_value = [{'host': 'missing-host',
                                             'nodename': 'nodesarestupid',
                                             'limits': None}]
        self.conductor.schedule_and_build_instances(**self.params)
        self.assertTrue(bury.called)
        self.assertFalse(build_and_run.called)

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

    def test_reset(self):
        with mock.patch('nova.compute.rpcapi.ComputeAPI') as mock_rpc:
            old_rpcapi = self.conductor_manager.compute_rpcapi
            self.conductor_manager.reset()
            mock_rpc.assert_called_once_with()
            self.assertNotEqual(old_rpcapi,
                                self.conductor_manager.compute_rpcapi)

    def test_migrate_server_fails_with_rebuild(self):
        instance = fake_instance.fake_instance_obj(self.context,
                                                   vm_state=vm_states.ACTIVE)
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, instance, None, True, True, None, None, None)

    def test_migrate_server_fails_with_flavor(self):
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

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def _test_migrate_server_deals_with_expected_exceptions(self, ex,
        mock_execute, mock_set):
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

    def test_migrate_server_deals_with_invalidcpuinfo_exception(self):
        instance = fake_instance.fake_db_instance(uuid=uuids.instance,
                                                  vm_state=vm_states.ACTIVE)
        inst_obj = objects.Instance._from_db_object(
            self.context, objects.Instance(), instance, [])
        self.mox.StubOutWithMock(live_migrate.LiveMigrationTask, 'execute')
        self.mox.StubOutWithMock(scheduler_utils,
                'set_vm_state_and_notify')

        ex = exc.InvalidCPUInfo(reason="invalid cpu info.")

        task = self.conductor._build_live_migrate_task(
            self.context, inst_obj, 'destination', 'block_migration',
            'disk_over_commit', mox.IsA(objects.Migration))
        task.execute().AndRaise(ex)

        scheduler_utils.set_vm_state_and_notify(self.context,
                inst_obj.uuid,
                'compute_task', 'migrate_server',
                {'vm_state': vm_states.ACTIVE,
                 'task_state': None,
                 'expected_task_state': task_states.MIGRATING},
                ex, self._build_request_spec(inst_obj))
        self.mox.ReplayAll()

        self.conductor = utils.ExceptionHelper(self.conductor)

        self.assertRaises(exc.InvalidCPUInfo,
            self.conductor.migrate_server, self.context, inst_obj,
            {'host': 'destination'}, True, False, None, 'block_migration',
            'disk_over_commit')

    def test_migrate_server_deals_with_expected_exception(self):
        exs = [exc.InstanceInvalidState(instance_uuid="fake", attr='',
                                        state='', method=''),
               exc.DestinationHypervisorTooOld(),
               exc.HypervisorUnavailable(host='dummy'),
               exc.LiveMigrationWithOldNovaNotSupported(),
               exc.MigrationPreCheckError(reason='dummy'),
               exc.MigrationPreCheckClientException(reason='dummy'),
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

    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(live_migrate.LiveMigrationTask, 'execute')
    def test_migrate_server_deals_with_unexpected_exceptions(self,
            mock_live_migrate, mock_set_state):
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
                             task_state=inst_obj.task_state,
                             expected_task_state=task_states.MIGRATING,),
                        expected_ex, request_spec)
        self.assertEqual(ex.kwargs['reason'], six.text_type(expected_ex))

    def test_set_vm_state_and_notify(self):
        self.mox.StubOutWithMock(scheduler_utils,
                                 'set_vm_state_and_notify')
        scheduler_utils.set_vm_state_and_notify(
                self.context, 1, 'compute_task', 'method', 'updates',
                'ex', 'request_spec')

        self.mox.ReplayAll()

        self.conductor._set_vm_state_and_notify(
                self.context, 1, 'method', 'updates', 'ex', 'request_spec')

    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_active_state(
            self, rollback_mock, notify_mock, select_dest_mock, quotas_mock,
            metadata_mock, sig_mock, spec_fc_mock):
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
            numa_topology=None)
        resvs = 'fake-resvs'
        image = 'fake-image'
        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        spec_fc_mock.return_value = fake_spec
        legacy_request_spec = fake_spec.to_legacy_request_spec_dict()
        metadata_mock.return_value = image
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.ACTIVE,
                   'task_state': None}

        # Filter properties are populated during code execution
        legacy_filter_props = {'retry': {'num_attempts': 1,
                                         'hosts': []}}

        self.assertRaises(exc.NoValidHost,
                          self.conductor._cold_migrate,
                          self.context, inst_obj,
                          flavor, {}, [resvs],
                          True, None)
        metadata_mock.assert_called_with({})
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, legacy_request_spec,
                                         legacy_filter_props)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                              'migrate_server', updates,
                                              exc_info, legacy_request_spec)
        rollback_mock.assert_called_once_with()

    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    def test_cold_migrate_no_valid_host_back_in_stopped_state(
            self, rollback_mock, notify_mock, select_dest_mock, quotas_mock,
            metadata_mock, spec_fc_mock, sig_mock):
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
            availability_zone=None)
        image = 'fake-image'
        resvs = 'fake-resvs'

        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        spec_fc_mock.return_value = fake_spec
        legacy_request_spec = fake_spec.to_legacy_request_spec_dict()

        # Filter properties are populated during code execution
        legacy_filter_props = {'retry': {'num_attempts': 1,
                                         'hosts': []}}

        metadata_mock.return_value = image
        exc_info = exc.NoValidHost(reason="")
        select_dest_mock.side_effect = exc_info
        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        self.assertRaises(exc.NoValidHost,
                           self.conductor._cold_migrate,
                           self.context, inst_obj,
                           flavor, {}, [resvs],
                           True, None)
        metadata_mock.assert_called_with({})
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, legacy_request_spec,
                                         legacy_filter_props)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, legacy_request_spec)
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
        resvs = 'fake-resvs'
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
                                    inst_obj, flavor, {}, [resvs],
                                    True, fake_spec)
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
            user_id=fakes.FAKE_USER_ID,
            flavor=flavor,
            numa_topology=None,
            pci_requests=None,
            availability_zone=None)
        resvs = 'fake-resvs'
        image = 'fake-image'
        exception = exc.UnsupportedPolicyException(reason='')
        fake_spec = fake_request_spec.fake_spec_obj()
        spec_fc_mock.return_value = fake_spec
        legacy_request_spec = fake_spec.to_legacy_request_spec_dict()

        image_mock.return_value = image
        task_exec_mock.side_effect = exception

        self.assertRaises(exc.UnsupportedPolicyException,
                          self.conductor._cold_migrate, self.context,
                          inst_obj, flavor, {}, [resvs], True, None)

        updates = {'vm_state': vm_states.STOPPED, 'task_state': None}
        set_vm_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exception, legacy_request_spec)

    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(objects.Quotas, 'from_reservations')
    @mock.patch.object(scheduler_client.SchedulerClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    def test_cold_migrate_exception_host_in_error_state_and_raise(
            self, prep_resize_mock, rollback_mock, notify_mock,
            select_dest_mock, quotas_mock, metadata_mock, spec_fc_mock,
            sig_mock):
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
        resvs = 'fake-resvs'
        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        legacy_request_spec = fake_spec.to_legacy_request_spec_dict()
        spec_fc_mock.return_value = fake_spec

        hosts = [dict(host='host1', nodename=None, limits={})]
        metadata_mock.return_value = image
        exc_info = test.TestingException('something happened')
        select_dest_mock.return_value = hosts

        updates = {'vm_state': vm_states.STOPPED,
                   'task_state': None}
        prep_resize_mock.side_effect = exc_info
        self.assertRaises(test.TestingException,
                          self.conductor._cold_migrate,
                          self.context, inst_obj, flavor,
                          {}, [resvs], True, None)

        # Filter properties are populated during code execution
        legacy_filter_props = {'retry': {'num_attempts': 1,
                                         'hosts': [['host1', None]]},
                               'limits': {}}

        metadata_mock.assert_called_with({})
        quotas_mock.assert_called_once_with(self.context, [resvs],
                                            instance=inst_obj)
        sig_mock.assert_called_once_with(self.context, legacy_request_spec,
                                         legacy_filter_props)
        select_dest_mock.assert_called_once_with(
            self.context, fake_spec)
        prep_resize_mock.assert_called_once_with(
            self.context, inst_obj, legacy_request_spec['image'],
            flavor, hosts[0]['host'], [resvs],
            request_spec=legacy_request_spec,
            filter_properties=legacy_filter_props,
            node=hosts[0]['nodename'], clean_shutdown=True)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, legacy_request_spec)
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
        resvs = 'fake-resvs'
        image = 'fake-image'
        fake_spec = fake_request_spec.fake_spec_obj()

        image_mock.return_value = image
        # Just make sure we have an original flavor which is different from
        # the new one
        self.assertNotEqual(flavor, fake_spec.flavor)
        with mock.patch.object(
                fake_spec, 'to_legacy_request_spec_dict') as spec_to_dict_mock:
            self.conductor._cold_migrate(self.context, inst_obj, flavor, {},
                                         [resvs], True, fake_spec)

        spec_to_dict_mock.assert_called_once_with()
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
        resvs = 'fake-resvs'
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
                                    [resvs], True, fake_spec)
            self.assertIn('resize', nvh.message)

    def test_build_instances_instance_not_found(self):
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        self.mox.StubOutWithMock(instances[0], 'refresh')
        self.mox.StubOutWithMock(instances[1], 'refresh')
        image = {'fake-data': 'should_pass_silently'}
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(self.conductor_manager, '_schedule_instances')
        self.mox.StubOutWithMock(self.conductor_manager.compute_rpcapi,
                'build_and_run_instance')

        scheduler_utils.build_request_spec(self.context, image,
                mox.IgnoreArg()).AndReturn(spec)
        filter_properties = {'retry': {'num_attempts': 1, 'hosts': []}}
        self.conductor_manager._schedule_instances(self.context,
                spec, filter_properties).AndReturn(
                        [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                         {'host': 'host2', 'nodename': 'node2', 'limits': []}])
        instances[0].refresh().AndRaise(
                exc.InstanceNotFound(instance_id=instances[0].uuid))
        instances[1].refresh()
        self.conductor_manager.compute_rpcapi.build_and_run_instance(
                self.context, instance=instances[1], host='host2',
                image={'fake-data': 'should_pass_silently'}, request_spec=spec,
                filter_properties={'limits': [],
                                   'retry': {'num_attempts': 1,
                                             'hosts': [['host2',
                                                        'node2']]}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=mox.IsA(objects.BlockDeviceMappingList),
                node='node2', limits=[])
        self.mox.ReplayAll()

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'build_request_spec')
    def test_build_instances_info_cache_not_found(self, build_request_spec,
                                                  setup_instance_group):
        instances = [fake_instance.fake_instance_obj(self.context)
                for i in range(2)]
        image = {'fake-data': 'should_pass_silently'}
        destinations = [{'host': 'host1', 'nodename': 'node1', 'limits': []},
                {'host': 'host2', 'nodename': 'node2', 'limits': []}]
        spec = {'fake': 'specs',
                'instance_properties': instances[0]}
        build_request_spec.return_value = spec
        with test.nested(
                mock.patch.object(instances[0], 'refresh',
                    side_effect=exc.InstanceInfoCacheNotFound(
                        instance_uuid=instances[0].uuid)),
                mock.patch.object(instances[1], 'refresh'),
                mock.patch.object(objects.RequestSpec, 'from_primitives'),
                mock.patch.object(self.conductor_manager.scheduler_client,
                    'select_destinations', return_value=destinations),
                mock.patch.object(self.conductor_manager.compute_rpcapi,
                    'build_and_run_instance')
                ) as (inst1_refresh, inst2_refresh, from_primitives,
                        select_destinations,
                        build_and_run_instance):

            # build_instances() is a cast, we need to wait for it to complete
            self.useFixture(cast_as_call.CastAsCall(self.stubs))

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

            # NOTE(sbauza): Due to populate_retry() later in the code,
            # filter_properties is dynamically modified
            setup_instance_group.assert_called_once_with(
                self.context, spec, {'retry': {'num_attempts': 1,
                                               'hosts': []}})
            build_and_run_instance.assert_called_once_with(self.context,
                    instance=instances[1], host='host2', image={'fake-data':
                        'should_pass_silently'}, request_spec=spec,
                    filter_properties={'limits': [],
                                       'retry': {'num_attempts': 1,
                                                 'hosts': [['host2',
                                                            'node2']]}},
                    admin_password='admin_password',
                    injected_files='injected_files',
                    requested_networks=None,
                    security_groups='security_groups',
                    block_device_mapping=mock.ANY,
                    node='node2', limits=[])

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
