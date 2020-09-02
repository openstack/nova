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
from oslo_db import exception as db_exc
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_versionedobjects import exception as ovo_exc
import six

from nova.accelerator import cyborg
from nova import block_device
from nova.compute import flavors
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
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
from nova.image import glance as image_api
from nova import objects
from nova.objects import base as obj_base
from nova.objects import block_device as block_device_obj
from nova.objects import fields
from nova.objects import request_spec
from nova.scheduler.client import query
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
from nova import utils
from nova.volume import cinder


CONF = conf.CONF


fake_alloc1 = {
    "allocations": {
        uuids.host1: {
             "resources": {"VCPU": 1,
                           "MEMORY_MB": 1024,
                           "DISK_GB": 100}
        }
    },
    "mappings": {
        uuids.port1: [uuids.host1]
    }
}
fake_alloc2 = {
    "allocations": {
        uuids.host2: {
             "resources": {"VCPU": 1,
                           "MEMORY_MB": 1024,
                           "DISK_GB": 100}
        }
    },
    "mappings": {
        uuids.port1: [uuids.host2]
    }
}
fake_alloc3 = {
    "allocations": {
        uuids.host3: {
             "resources": {"VCPU": 1,
                           "MEMORY_MB": 1024,
                           "DISK_GB": 100}
        }
    },
    "mappings": {
        uuids.port1: [uuids.host3]
    }
}
fake_alloc_json1 = jsonutils.dumps(fake_alloc1)
fake_alloc_json2 = jsonutils.dumps(fake_alloc2)
fake_alloc_json3 = jsonutils.dumps(fake_alloc3)
fake_alloc_version = "1.28"
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

        self.stub_out('nova.rpc.RequestContextSerializer.deserialize_context',
                      lambda *args, **kwargs: self.context)

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
        self.request_spec = objects.RequestSpec()

        self.stub_out('nova.rpc.RequestContextSerializer.deserialize_context',
                      lambda *args, **kwargs: self.context)

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
        compute_rebuild_args['accel_uuids'] = []

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
        flavor = objects.Flavor.get_by_name(self.context, 'm1.small')
        flavor.extra_specs = {'extra_specs': 'fake'}
        inst_obj.flavor = flavor

        fake_spec = fake_request_spec.fake_spec_obj()
        spec_from_components.return_value = fake_spec

        scheduler_hint = {'filter_properties': {}}

        if isinstance(self.conductor, conductor_api.ComputeTaskAPI):
            # The API method is actually 'resize_instance'.  It gets
            # converted into 'migrate_server' when doing RPC.
            self.conductor.resize_instance(
                self.context, inst_obj, scheduler_hint, flavor, [],
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

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_and_bind_arqs')
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
                             mock_build, mock_create_bind_arqs):
        """Tests creating two instances and the scheduler returns a unique
        host/node combo for each instance.
        """
        fake_spec = objects.RequestSpec()
        mock_fp.return_value = fake_spec
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.small')
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
        mock_create_bind_arqs.return_value = mock.sentinel

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
                      node='node1', limits=None, host_list=sched_return[0],
                      accel_uuids=mock.sentinel),
            mock.call(self.context, instance=mock.ANY, host='host2',
                      image={'fake_data': 'should_pass_silently'},
                      request_spec=fake_spec,
                      filter_properties=filter_properties3,
                      admin_password='admin_password',
                      injected_files='injected_files',
                      requested_networks=None,
                      security_groups='security_groups',
                      block_device_mapping=mock.ANY,
                      node='node2', limits=None, host_list=sched_return[1],
                      accel_uuids=mock.sentinel)])
        mock_create_bind_arqs.assert_has_calls([
            mock.call(self.context, instances[0].uuid,
                      instances[0].flavor.extra_specs, 'node1', mock.ANY),
            mock.call(self.context, instances[1].uuid,
                      instances[1].flavor.extra_specs, 'node2', mock.ANY),
            ])

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_when_reschedule_fails')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_and_bind_arqs')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'build_and_run_instance')
    @mock.patch.object(db, 'block_device_mapping_get_all_by_instance',
                       return_value=[])
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances')
    @mock.patch('nova.objects.BuildRequest.get_by_instance_uuid')
    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch('nova.objects.Instance.save')
    @mock.patch.object(objects.RequestSpec, 'from_primitives')
    def test_build_instances_arq_failure(self, mock_fp, mock_save, mock_getaz,
                             mock_buildreq, mock_schedule, mock_bdm,
                             mock_build, mock_create_bind_arqs, mock_cleanup):
        """If _create_and_bind_arqs throws an exception,
           _destroy_build_request must be called for each instance.
        """
        fake_spec = objects.RequestSpec()
        mock_fp.return_value = fake_spec
        instance_type = objects.Flavor.get_by_name(self.context, 'm1.small')
        # NOTE(danms): Avoid datetime timezone issues with converted flavors
        instance_type.created_at = None
        instances = [objects.Instance(context=self.context,
                                      id=i,
                                      uuid=uuids.fake,
                                      flavor=instance_type) for i in range(2)]
        instance_properties = obj_base.obj_to_primitive(instances[0])
        instance_properties['system_metadata'] = flavors.save_flavor_info(
            {}, instance_type)

        sched_return = copy.deepcopy(fake_host_lists2)
        mock_schedule.return_value = sched_return

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        mock_getaz.return_value = 'myaz'
        mock_create_bind_arqs.side_effect = (
            exc.AcceleratorRequestBindingFailed(arqs=[], msg=''))

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
        mock_create_bind_arqs.assert_has_calls([
            mock.call(self.context, instances[0].uuid,
                      instances[0].flavor.extra_specs, 'node1', mock.ANY),
            mock.call(self.context, instances[1].uuid,
                      instances[1].flavor.extra_specs, 'node2', mock.ANY),
            ])
        # Comparing instances fails because the instance objects have changed
        # in the above flow. So, we compare the fields instead.
        mock_cleanup.assert_has_calls([
            mock.call(self.context, test.MatchType(objects.Instance),
                      test.MatchType(exc.AcceleratorRequestBindingFailed),
                      test.MatchType(dict), None),
            mock.call(self.context, test.MatchType(objects.Instance),
                      test.MatchType(exc.AcceleratorRequestBindingFailed),
                      test.MatchType(dict), None),
        ])
        call_list = mock_cleanup.call_args_list
        for idx, instance in enumerate(instances):
            actual_inst = call_list[idx][0][1]
            self.assertEqual(actual_inst['uuid'], instance['uuid'])
            self.assertEqual(actual_inst['flavor']['extra_specs'], {})

    @mock.patch.object(scheduler_utils, 'build_request_spec')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch.object(objects.Instance, 'save')
    def test_build_instances_exhaust_host_list(self, _mock_save, mock_notify):
        # A list of three alternate hosts for one instance
        host_lists = copy.deepcopy(fake_host_lists_alt)
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        self.conductor.build_instances(
            context=self.context,
            instances=[instance], image=image,
            filter_properties={},
            admin_password='admin_password',
            injected_files='injected_files',
            requested_networks=None,
            security_groups='security_groups',
            block_device_mapping=None,
            legacy_bdm=None,
            host_lists=host_lists
        )

        # Since claim_resources() is mocked to always return False, we will run
        # out of alternate hosts, and complain about MaxRetriesExceeded.
        mock_notify.assert_called_once_with(
            self.context, 'build_instances',
            instance.uuid, test.MatchType(dict), 'error',
            test.MatchType(exc.MaxRetriesExceeded))

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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
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
                host_list=expected_build_run_host_list,
                accel_uuids=[])
            mock_pop_inst_map.assert_not_called()
            mock_destroy_build_req.assert_not_called()

        do_test()

    @mock.patch.object(objects.Instance, 'save', new=mock.MagicMock())
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_reschedule_recalculates_provider_mapping(self,
            mock_select_dests):

        rg1 = objects.RequestGroup(resources={"CUSTOM_FOO": 1})
        request_spec = objects.RequestSpec(requested_resources=[rg1])

        mock_select_dests.return_value = [[fake_selection1]]
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        @mock.patch('nova.scheduler.utils.'
                    'fill_provider_mapping')
        @mock.patch('nova.scheduler.utils.claim_resources')
        @mock.patch('nova.objects.request_spec.RequestSpec.from_primitives',
                    return_value=request_spec)
        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'build_and_run_instance')
        @mock.patch.object(self.conductor_manager,
                           '_populate_instance_mapping')
        @mock.patch.object(self.conductor_manager, '_destroy_build_request')
        def do_test(mock_destroy_build_req, mock_pop_inst_map,
                    mock_build_and_run, mock_request_spec_from_primitives,
                    mock_claim, mock_rp_mapping):
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
                legacy_bdm=False,
                host_lists=copy.deepcopy(fake_host_lists1),
                request_spec=request_spec)

            expected_build_run_host_list = copy.copy(fake_host_lists1[0])
            if expected_build_run_host_list:
                expected_build_run_host_list.pop(0)
            mock_build_and_run.assert_called_once_with(
                self.context,
                instance=mock.ANY,
                host='host1',
                image=image,
                request_spec=request_spec,
                filter_properties={'retry': {'num_attempts': 2,
                                             'hosts': [['host1', 'node1']]},
                                   'limits': {}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=test.MatchType(
                    objects.BlockDeviceMappingList),
                node='node1',
                limits=None,
                host_list=expected_build_run_host_list,
                accel_uuids=[])

            mock_rp_mapping.assert_called_once_with(
                test.MatchType(objects.RequestSpec),
                test.MatchType(objects.Selection))
            actual_request_spec = mock_rp_mapping.mock_calls[0][1][0]
            self.assertEqual(
                rg1.resources,
                actual_request_spec.requested_resources[0].resources)

        do_test()

    @mock.patch.object(objects.Instance, 'save', new=mock.MagicMock())
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify', new=mock.MagicMock())
    def test_build_instances_reschedule_not_recalc_mapping_if_claim_fails(
            self, mock_select_dests):

        rg1 = objects.RequestGroup(resources={"CUSTOM_FOO": 1})
        request_spec = objects.RequestSpec(requested_resources=[rg1])

        mock_select_dests.return_value = [[fake_selection1]]
        instance = fake_instance.fake_instance_obj(self.context)
        image = {'fake-data': 'should_pass_silently'}

        # build_instances() is a cast, we need to wait for it to complete
        self.useFixture(cast_as_call.CastAsCall(self))

        @mock.patch('nova.scheduler.utils.'
                    'fill_provider_mapping')
        @mock.patch('nova.scheduler.utils.claim_resources',
                    # simulate that the first claim fails during re-schedule
                    side_effect=[False, True])
        @mock.patch('nova.objects.request_spec.RequestSpec.from_primitives',
                    return_value=request_spec)
        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'build_and_run_instance')
        @mock.patch.object(self.conductor_manager,
                           '_populate_instance_mapping')
        @mock.patch.object(self.conductor_manager, '_destroy_build_request')
        def do_test(mock_destroy_build_req, mock_pop_inst_map,
                    mock_build_and_run, mock_request_spec_from_primitives,
                    mock_claim, mock_rp_mapping):
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
                legacy_bdm=False,
                host_lists=copy.deepcopy(fake_host_lists_alt),
                request_spec=request_spec)

            expected_build_run_host_list = copy.copy(fake_host_lists_alt[0])
            if expected_build_run_host_list:
                # first is consumed but the claim fails so the conductor takes
                # the next host
                expected_build_run_host_list.pop(0)
                # second is consumed and claim succeeds
                expected_build_run_host_list.pop(0)
            mock_build_and_run.assert_called_with(
                self.context,
                instance=mock.ANY,
                host='host2',
                image=image,
                request_spec=request_spec,
                filter_properties={'retry': {'num_attempts': 2,
                                             'hosts': [['host2', 'node2']]},
                                   'limits': {}},
                admin_password='admin_password',
                injected_files='injected_files',
                requested_networks=None,
                security_groups='security_groups',
                block_device_mapping=test.MatchType(
                    objects.BlockDeviceMappingList),
                node='node2',
                limits=None,
                host_list=expected_build_run_host_list,
                accel_uuids=[])

            # called only once when the claim succeeded
            mock_rp_mapping.assert_called_once_with(
                test.MatchType(objects.RequestSpec),
                test.MatchType(objects.Selection))
            actual_request_spec = mock_rp_mapping.mock_calls[0][1][0]
            self.assertEqual(
                rg1.resources,
                actual_request_spec.requested_resources[0].resources)

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
        self.conductor_manager.unshelve_instance(
            self.context, instance, self.request_spec)

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
                self.context, mock.ANY, host['host'],
                test.MatchType(objects.RequestSpec), image=mock.ANY,
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
            self.context, instance, self.request_spec)
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
            self.conductor_manager.unshelve_instance(
                self.context, instance, self.request_spec)
            self.assertEqual(1, unshelve_mock.call_count)

    @mock.patch.object(compute_rpcapi.ComputeAPI, 'unshelve_instance')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances',
                       return_value=[[objects.Selection(
                           service_host='fake_host', nodename='fake_node',
                           limits=None)]])
    @mock.patch.object(image_api.API, 'get', return_value='fake_image')
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_unshelve_instance_schedule_and_rebuild(
            self, mock_im, mock_get, mock_schedule, mock_unshelve):
        fake_spec = objects.RequestSpec()
        # Set requested_destination to test setting cell_mapping in
        # existing object.
        fake_spec.requested_destination = objects.Destination(
            host="dummy", cell=None)
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
        self.conductor_manager.unshelve_instance(
            self.context, instance, fake_spec)
        self.assertEqual(cell_mapping, fake_spec.requested_destination.cell)
        mock_get.assert_called_once_with(
            self.context, 'fake_image_id', show_deleted=False)
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, [instance.uuid], return_alternates=False)
        mock_unshelve.assert_called_once_with(
            self.context, instance, 'fake_host', fake_spec, image='fake_image',
            filter_properties=dict(
                # populate_filter_properties adds limits={}
                fake_spec.to_legacy_filter_properties_dict(), limits={}),
            node='fake_node')

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
            self.conductor_manager.unshelve_instance(
                self.context, instance, self.request_spec)
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
                          self.context, instance, self.request_spec)
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
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    def test_unshelve_instance_schedule_and_rebuild_volume_backed(
            self, mock_im, mock_schedule, mock_unshelve):
        fake_spec = objects.RequestSpec()
        mock_im.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()
        system_metadata = instance.system_metadata

        system_metadata['shelved_at'] = timeutils.utcnow()
        system_metadata['shelved_host'] = 'fake-mini'
        self.conductor_manager.unshelve_instance(
            self.context, instance, fake_spec)
        mock_schedule.assert_called_once_with(
            self.context, fake_spec, [instance.uuid], return_alternates=False)
        mock_unshelve.assert_called_once_with(
            self.context, instance, 'fake_host', fake_spec, image=None,
            filter_properties={'limits': {}}, node='fake_node')

    @mock.patch('nova.scheduler.utils.fill_provider_mapping')
    @mock.patch('nova.network.neutron.API.get_requested_resource_for_instance')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_schedule_instances', )
    def test_unshelve_instance_resource_request(
            self, mock_schedule, mock_get_res_req, mock_fill_provider_mapping):
        instance = self._create_fake_instance_obj()
        instance.vm_state = vm_states.SHELVED_OFFLOADED
        instance.save()

        request_spec = objects.RequestSpec()

        selection = objects.Selection(
            service_host='fake_host',
            nodename='fake_node',
            limits=None)
        mock_schedule.return_value = [[selection]]

        res_req = [objects.RequestGroup()]
        mock_get_res_req.return_value = res_req

        self.conductor_manager.unshelve_instance(
            self.context, instance, request_spec)

        self.assertEqual(res_req, request_spec.requested_resources)

        mock_get_res_req.assert_called_once_with(self.context, instance.uuid)
        mock_schedule.assert_called_once_with(
            self.context, request_spec, [instance.uuid],
            return_alternates=False)
        mock_fill_provider_mapping.assert_called_once_with(
            request_spec, selection)

    def test_rebuild_instance(self):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': inst_obj.host})

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(self.conductor_manager.query_client,
                              'select_destinations'),
            mock.patch('nova.scheduler.utils.fill_provider_mapping',
                       new_callable=mock.NonCallableMock),
            mock.patch('nova.network.neutron.API.'
                       'get_requested_resource_for_instance',
                       new_callable=mock.NonCallableMock)
        ) as (rebuild_mock, select_dest_mock, fill_provider_mock,
              get_resources_mock):
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
        fake_spec = objects.RequestSpec()
        rebuild_args['request_spec'] = fake_spec
        inst_uuids = [inst_obj.uuid]
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(self.conductor_manager.query_client,
                              'select_destinations',
                              return_value=[[fake_selection]])
        ) as (rebuild_mock, sig_mock, select_dest_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
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
        fake_spec = objects.RequestSpec()
        rebuild_args['request_spec'] = fake_spec

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(self.conductor_manager.query_client,
                              'select_destinations',
                              side_effect=exc.NoValidHost(reason='')),
            mock.patch.object(scheduler_utils, 'set_vm_state_and_notify')
        ) as (rebuild_mock, sig_mock,
              select_dest_mock, set_vm_state_and_notify_mock):
            self.assertRaises(exc.NoValidHost,
                              self.conductor_manager.rebuild_instance,
                              context=self.context, instance=inst_obj,
                              **rebuild_args)
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
    @mock.patch.object(conductor_manager.query.SchedulerQueryClient,
                       'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    def test_rebuild_instance_with_scheduler_group_failure(self,
                                                           state_mock,
                                                           select_dest_mock,
                                                           sig_mock,
                                                           rebuild_mock):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, _ = self._prepare_rebuild_args({'host': None})
        rebuild_args['request_spec'] = self.request_spec

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

    def test_rebuild_instance_fill_provider_mapping_raises(self):
        inst_obj = self._create_fake_instance_obj()
        rebuild_args, _ = self._prepare_rebuild_args(
            {'host': None, 'recreate': True})
        fake_spec = objects.RequestSpec()
        fake_spec.flavor = inst_obj.flavor
        rebuild_args['request_spec'] = fake_spec

        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(self.conductor_manager.query_client,
                              'select_destinations'),
            mock.patch.object(scheduler_utils, 'set_vm_state_and_notify'),
            mock.patch.object(scheduler_utils, 'fill_provider_mapping',
                              side_effect=ValueError(
                                  'No valid group - RP mapping is found'))
        ) as (rebuild_mock, sig_mock,
              select_dest_mock, set_vm_state_and_notify_mock,
              fill_mapping_mock):

            self.assertRaises(ValueError,
                              self.conductor_manager.rebuild_instance,
                              context=self.context, instance=inst_obj,
                              **rebuild_args)
            select_dest_mock.assert_called_once_with(self.context, fake_spec,
                    [inst_obj.uuid], return_objects=True,
                    return_alternates=False)
            set_vm_state_and_notify_mock.assert_called_once_with(
                self.context, inst_obj.uuid, 'compute_task', 'rebuild_server',
                {'vm_state': vm_states.ERROR, 'task_state': None},
                test.MatchType(ValueError), fake_spec)
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
            mock.patch.object(self.conductor_manager.query_client,
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
    def test_evacuate_instance_with_request_spec(self, mock_notify):
        inst_obj = self._create_fake_instance_obj()
        inst_obj.host = 'noselect'
        expected_host = 'thebesthost'
        expected_node = 'thebestnode'
        expected_limits = None
        fake_selection = objects.Selection(service_host=expected_host,
                nodename=expected_node, limits=None)
        fake_spec = objects.RequestSpec(ignore_hosts=[uuids.ignored_host])
        fake_spec.flavor = inst_obj.flavor
        rebuild_args, compute_args = self._prepare_rebuild_args(
            {'host': None, 'node': expected_node, 'limits': expected_limits,
             'request_spec': fake_spec, 'recreate': True})
        with test.nested(
            mock.patch.object(self.conductor_manager.compute_rpcapi,
                              'rebuild_instance'),
            mock.patch.object(scheduler_utils, 'setup_instance_group',
                              return_value=False),
            mock.patch.object(self.conductor_manager.query_client,
                              'select_destinations',
                              return_value=[[fake_selection]]),
            mock.patch.object(fake_spec, 'reset_forced_destinations'),
            mock.patch('nova.scheduler.utils.fill_provider_mapping'),
            mock.patch('nova.network.neutron.API.'
                       'get_requested_resource_for_instance',
                       return_value=[])
        ) as (rebuild_mock, sig_mock, select_dest_mock, reset_fd,
              fill_rp_mapping_mock, get_req_res_mock):
            self.conductor_manager.rebuild_instance(context=self.context,
                                            instance=inst_obj,
                                            **rebuild_args)
            reset_fd.assert_called_once_with()
            # The RequestSpec.ignore_hosts field should be overwritten.
            self.assertEqual([inst_obj.host], fake_spec.ignore_hosts)
            # The RequestSpec.requested_destination.cell field should be set.
            self.assertIn('requested_destination', fake_spec)
            self.assertIn('cell', fake_spec.requested_destination)
            self.assertIsNotNone(fake_spec.requested_destination.cell)
            select_dest_mock.assert_called_once_with(self.context,
                    fake_spec, [inst_obj.uuid], return_objects=True,
                    return_alternates=False)
            compute_args['host'] = expected_host
            compute_args['request_spec'] = fake_spec
            rebuild_mock.assert_called_once_with(self.context,
                                            instance=inst_obj,
                                            **compute_args)
            get_req_res_mock.assert_called_once_with(
                self.context, inst_obj.uuid)
            fill_rp_mapping_mock.assert_called_once_with(
                fake_spec, fake_selection)

        self.assertEqual('compute.instance.rebuild.scheduled',
                         fake_notifier.NOTIFICATIONS[0].event_type)
        mock_notify.assert_called_once_with(
            self.context, inst_obj, 'thebesthost', action='rebuild_scheduled',
            source='nova-conductor')

    @mock.patch(
        'nova.conductor.tasks.cross_cell_migrate.ConfirmResizeTask.execute')
    def test_confirm_snapshot_based_resize(self, mock_execute):
        instance = self._create_fake_instance_obj(ctxt=self.context)
        migration = objects.Migration(
            context=self.context, source_compute=instance.host,
            source_node=instance.node, instance_uuid=instance.uuid,
            status='confirming', migration_type='resize')
        self.conductor_manager.confirm_snapshot_based_resize(
            self.context, instance=instance, migration=migration)
        mock_execute.assert_called_once_with()

    @mock.patch('nova.compute.utils.EventReporter')
    @mock.patch(
        'nova.conductor.tasks.cross_cell_migrate.RevertResizeTask.execute')
    def test_revert_snapshot_based_resize(self, mock_execute, mock_er):
        instance = self._create_fake_instance_obj(ctxt=self.context)
        migration = objects.Migration(
            context=self.context, source_compute=instance.host,
            source_node=instance.node, instance_uuid=instance.uuid,
            status='reverting', migration_type='migration')
        self.conductor_manager.revert_snapshot_based_resize(
            self.context, instance=instance, migration=migration)
        mock_execute.assert_called_once_with()
        mock_er.assert_called_once_with(
            self.context, 'conductor_revert_snapshot_based_resize',
            self.conductor_manager.host, instance.uuid, graceful_exit=True)


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
        self.flavor = objects.Flavor.get_by_name(self.ctxt, 'm1.tiny')

    @mock.patch('nova.accelerator.cyborg.get_client')
    def test_create_bind_arqs_no_device_profile(self, mock_get_client):
        # If no device profile name, it is a no op.
        hostname = 'myhost'
        instance = fake_instance.fake_instance_obj(self.context)

        instance.flavor.extra_specs = {}
        self.conductor._create_and_bind_arqs(self.context,
            instance.uuid, instance.flavor.extra_specs,
            hostname, resource_provider_mapping=mock.ANY)
        mock_get_client.assert_not_called()

    @mock.patch('nova.accelerator.cyborg._CyborgClient.bind_arqs')
    @mock.patch('nova.accelerator.cyborg._CyborgClient.'
                'create_arqs_and_match_resource_providers')
    def test_create_bind_arqs(self, mock_create, mock_bind):
        # Happy path
        hostname = 'myhost'
        instance = fake_instance.fake_instance_obj(self.context)
        dp_name = 'mydp'
        instance.flavor.extra_specs = {'accel:device_profile': dp_name}

        in_arq_list, _ = fixtures.get_arqs(dp_name)
        mock_create.return_value = in_arq_list

        self.conductor._create_and_bind_arqs(self.context,
            instance.uuid, instance.flavor.extra_specs,
            hostname, resource_provider_mapping=mock.ANY)

        mock_create.assert_called_once_with(dp_name, mock.ANY)

        expected_bindings = {
            'b59d34d3-787b-4fb0-a6b9-019cd81172f8':
                {'hostname': hostname,
                 'device_rp_uuid': mock.ANY,
                 'instance_uuid': instance.uuid}
        }
        mock_bind.assert_called_once_with(bindings=expected_bindings)

    @mock.patch('nova.availability_zones.get_host_availability_zone')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def _do_schedule_and_build_instances_test(
            self, params, select_destinations, build_and_run_instance,
            get_az, host_list=None):
        if not host_list:
            host_list = copy.deepcopy(fake_host_lists1)
        select_destinations.return_value = host_list
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
        self.start_service('compute', host='host1', cell_name='cell1')
        self.start_service('compute', host='host2', cell_name='cell2')

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

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_scheduler_failure(self, select_destinations,
                                                  mock_notify):
        select_destinations.side_effect = Exception
        self.start_service('compute', host='fake-host')
        self.conductor.schedule_and_build_instances(**self.params)
        with conductor_manager.try_target_cell(self.ctxt,
                                               self.cell_mappings['cell0']):
            instance = objects.Instance.get_by_uuid(
                self.ctxt, self.params['build_requests'][0].instance_uuid)
        self.assertEqual('error', instance.vm_state)
        self.assertIsNone(instance.task_state)

        mock_notify.assert_called_once_with(
            test.MatchType(context.RequestContext), 'build_instances',
            instance.uuid, test.MatchType(dict), 'error',
            test.MatchType(Exception))
        request_spec_dict = mock_notify.call_args_list[0][0][3]
        for key in ('instance_type', 'num_instances', 'instance_properties',
                    'image'):
            self.assertIn(key, request_spec_dict)

    @mock.patch('nova.objects.TagList.destroy')
    @mock.patch('nova.objects.TagList.create')
    @mock.patch('nova.compute.utils.notify_about_instance_action')
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
                                                         legacy_notify,
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
            legacy_notify, notify,
            self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True, expected_source='nova-conductor',
            expected_host='host1')

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch('nova.objects.Instance.destroy')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling_host_changed(
            self, bury, br_destroy, select_destinations,
            build_and_run, legacy_notify, instance_destroy, notify):

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
            legacy_notify, notify,
            self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True, expected_source='nova-conductor',
            expected_host='host1')

    @mock.patch('nova.compute.utils.notify_about_instance_action')
    @mock.patch('nova.objects.Instance.destroy')
    @mock.patch('nova.compute.utils.notify_about_instance_usage')
    @mock.patch('nova.compute.rpcapi.ComputeAPI.build_and_run_instance')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    @mock.patch('nova.objects.BuildRequest.destroy')
    @mock.patch('nova.conductor.manager.ComputeTaskManager._bury_in_cell0')
    def test_schedule_and_build_delete_during_scheduling_instance_not_found(
            self, bury, br_destroy, select_destinations,
            build_and_run, legacy_notify, instance_destroy, notify):

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
            legacy_notify, notify,
            self.params['build_requests'][0].instance_uuid,
            self.conductor.notifier, test.MatchType(context.RequestContext),
            expect_targeted_context=True, expected_source='nova-conductor',
            expected_host='host1')

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
        # Make sure the instance mapping is gone.
        self.assertRaises(exc.InstanceMappingNotFound,
                          objects.InstanceMapping.get_by_instance_uuid,
                          self.context, inst_uuid)

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

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch('nova.objects.quotas.Quotas.check_deltas')
    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_schedule_and_build_over_quota_during_recheck(self, mock_select,
                                                          mock_check,
                                                          mock_notify):
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

        mock_notify.assert_called_once_with(
            test.MatchType(context.RequestContext), 'build_instances',
            instance.uuid, test.MatchType(dict), 'error',
            test.MatchType(exc.TooManyInstances))
        request_spec_dict = mock_notify.call_args_list[0][0][3]
        for key in ('instance_type', 'num_instances', 'instance_properties',
                    'image'):
            self.assertIn(key, request_spec_dict)

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

    def test_schedule_and_build_instances_fill_request_spec(self):
        # makes sure there is some request group in the spec to be mapped
        self.params['request_specs'][0].requested_resources = [
            objects.RequestGroup(requester_id=uuids.port1)]

        self._do_schedule_and_build_instances_test(self.params)

    @mock.patch('nova.conductor.manager.ComputeTaskManager.'
                '_cleanup_build_artifacts')
    @mock.patch('nova.scheduler.utils.'
                'fill_provider_mapping', side_effect=test.TestingException)
    def test_schedule_and_build_instances_fill_request_spec_error(
            self, mock_fill, mock_cleanup):
        self.assertRaises(
            test.TestingException,
            self._do_schedule_and_build_instances_test, self.params)

        mock_fill.assert_called_once()
        mock_cleanup.assert_called_once()

    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_provider_traits', new_callable=mock.NonCallableMock)
    @mock.patch('nova.scheduler.client.report.SchedulerReportClient.'
                'get_allocs_for_consumer',
                new_callable=mock.NonCallableMock)
    @mock.patch('nova.objects.request_spec.RequestSpec.'
                'map_requested_resources_to_providers',
                new_callable=mock.NonCallableMock)
    def test_schedule_and_build_instances_fill_request_spec_noop(
            self, mock_map, mock_get_allocs, mock_traits):
        """Tests to make sure _fill_provider_mapping exits early if there are
        no requested_resources on the RequestSpec.
        """
        self.params['request_specs'][0].requested_resources = []
        self._do_schedule_and_build_instances_test(self.params)

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_and_bind_arqs')
    def test_schedule_and_build_instances_with_arqs_bind_ok(
            self, mock_create_bind_arqs):
        extra_specs = {'accel:device_profile': 'mydp'}
        instance = self.params['build_requests'][0].instance
        instance.flavor.extra_specs = extra_specs

        self._do_schedule_and_build_instances_test(self.params)

        # NOTE(Sundar): At this point, the instance has not been
        # associated with a host yet. The default host.nodename is
        # 'node1'.
        mock_create_bind_arqs.assert_called_once_with(
            self.params['context'], instance.uuid, extra_specs,
            'node1', mock.ANY)

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_build_artifacts')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_and_bind_arqs')
    def test_schedule_and_build_instances_with_arqs_bind_exception(
            self, mock_create_bind_arqs, mock_cleanup):
        # Exceptions in _create_and_bind_arqs result in cleanup
        mock_create_bind_arqs.side_effect = (
            exc.AcceleratorRequestBindingFailed(arqs=[], msg=''))

        try:
            self._do_schedule_and_build_instances_test(self.params)
        except exc.AcceleratorRequestBindingFailed:
            pass

        mock_cleanup.assert_called_once_with(
            self.params['context'], mock.ANY, mock.ANY,
            self.params['build_requests'], self.params['request_specs'],
            self.params['block_device_mapping'], self.params['tags'],
            mock.ANY)

    @mock.patch.object(request_spec.RequestSpec, "get_request_group_mapping")
    @mock.patch.object(cyborg, "get_client")
    @mock.patch.object(
        conductor_manager.ComputeTaskManager, '_create_and_bind_arqs')
    def test__create_and_bind_arq_for_instance(
            self, mock_create_bind_arqs, mock_client, mock_request_mappings):
        # Exceptions in _create_and_bind_arqs result in cleanup
        arqs = ["fake-arq-uuid"]
        mock_create_bind_arqs.side_effect = (
            exc.AcceleratorRequestBindingFailed(arqs=arqs, msg=''))
        mock_client.return_value = mock.Mock()
        instance = mock.Mock()
        instance.uuid = "fake-uuid"
        ex = self.assertRaises(exc.AcceleratorRequestBindingFailed,
            self.conductor._create_and_bind_arq_for_instance,
            None, instance, mock.Mock(), request_spec.RequestSpec())

        self.assertIn('Failed to bind accelerator requests', ex.message)
        mock_client.return_value.delete_arqs_by_uuid.assert_called_with(arqs)

    def test_map_instance_to_cell_already_mapped(self):
        """Tests a scenario where an instance is already mapped to a cell
        during scheduling.
        """
        build_request = self.params['build_requests'][0]
        instance = build_request.get_new_instance(self.ctxt)
        # Simulate MQ split brain craziness by updating the instance mapping
        # to point at cell0.
        inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.ctxt, instance.uuid)
        inst_mapping.cell_mapping = self.cell_mappings['cell0']
        inst_mapping.save()
        cell1 = self.cell_mappings['cell1']
        inst_mapping = self.conductor._map_instance_to_cell(
            self.ctxt, instance, cell1)
        # Assert that the instance mapping was updated to point at cell1 but
        # also that an error was logged.
        self.assertEqual(cell1.uuid, inst_mapping.cell_mapping.uuid)
        self.assertIn('During scheduling instance is already mapped to '
                      'another cell', self.stdlog.logger.output)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_cleanup_build_artifacts(self, inst_map_get):
        """Simple test to ensure the order of operations in the cleanup method
        is enforced.
        """
        req_spec = fake_request_spec.fake_spec_obj()
        build_req = fake_build_request.fake_req_obj(self.context)
        instance = build_req.instance
        bdms = objects.BlockDeviceMappingList(objects=[
            objects.BlockDeviceMapping(instance_uuid=instance.uuid)])
        tags = objects.TagList(objects=[objects.Tag(tag='test')])
        cell1 = self.cell_mappings['cell1']
        cell_mapping_cache = {instance.uuid: cell1}
        err = exc.TooManyInstances('test')

        # We need to assert that BDMs and tags are created in the cell DB
        # before the instance mapping is updated.
        def fake_create_block_device_mapping(*args, **kwargs):
            inst_map_get.return_value.save.assert_not_called()

        def fake_create_tags(*args, **kwargs):
            inst_map_get.return_value.save.assert_not_called()

        with test.nested(
            mock.patch.object(self.conductor_manager,
                              '_set_vm_state_and_notify'),
            mock.patch.object(self.conductor_manager,
                              '_create_block_device_mapping',
                              side_effect=fake_create_block_device_mapping),
            mock.patch.object(self.conductor_manager, '_create_tags',
                              side_effect=fake_create_tags),
            mock.patch.object(build_req, 'destroy'),
            mock.patch.object(req_spec, 'destroy'),
        ) as (
            _set_vm_state_and_notify, _create_block_device_mapping,
            _create_tags, build_req_destroy, req_spec_destroy,
        ):
            self.conductor_manager._cleanup_build_artifacts(
                self.context, err, [instance], [build_req], [req_spec], bdms,
                tags, cell_mapping_cache)
        # Assert the various mock calls.
        _set_vm_state_and_notify.assert_called_once_with(
            test.MatchType(context.RequestContext), instance.uuid,
            'build_instances',
            {'vm_state': vm_states.ERROR, 'task_state': None}, err, req_spec)
        _create_block_device_mapping.assert_called_once_with(
            cell1, instance.flavor, instance.uuid, bdms)
        _create_tags.assert_called_once_with(
            test.MatchType(context.RequestContext), instance.uuid, tags)
        inst_map_get.return_value.save.assert_called_once_with()
        self.assertEqual(cell1, inst_map_get.return_value.cell_mapping)
        build_req_destroy.assert_called_once_with()
        req_spec_destroy.assert_called_once_with()

    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    def test_bury_in_cell0_no_cell0(self, mock_cm_get):
        mock_cm_get.side_effect = exc.CellMappingNotFound(uuid='0')
        # Without an iterable build_requests in the database, this
        # wouldn't work if it continued past the cell0 lookup.
        self.conductor._bury_in_cell0(self.ctxt, None, None,
                                      build_requests=1)
        self.assertTrue(mock_cm_get.called)

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    def test_bury_in_cell0(self, mock_notify):
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

        # Verify instance mappings.
        inst_mappings = objects.InstanceMappingList.get_by_cell_id(
            self.ctxt, self.cell_mappings['cell0'].id)
        # bare_br is the only instance that has a mapping from setUp.
        self.assertEqual(1, len(inst_mappings))
        # Since we did not setup instance mappings for the other fake build
        # requests used in this test, we should see a message logged about
        # there being no instance mappings.
        self.assertIn('While burying instance in cell0, no instance mapping '
                      'was found', self.stdlog.logger.output)

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

        self.assertEqual(4, mock_notify.call_count)
        mock_notify.assert_has_calls([
            mock.call(
                test.MatchType(context.RequestContext), 'build_instances',
                bare_br.instance_uuid, test.MatchType(dict), 'error',
                test.MatchType(Exception)),
            mock.call(
                test.MatchType(context.RequestContext), 'build_instances',
                inst_br.instance_uuid, test.MatchType(dict), 'error',
                test.MatchType(Exception)),
            mock.call(
                test.MatchType(context.RequestContext), 'build_instances',
                deleted_br.instance_uuid, test.MatchType(dict), 'error',
                test.MatchType(Exception)),
            mock.call(
                test.MatchType(context.RequestContext), 'build_instances',
                fast_deleted_br.instance_uuid, test.MatchType(dict), 'error',
                test.MatchType(Exception))],
            any_order=True)

        for i in range(0, 3):
            # traceback.format_exc() returns 'NoneType'
            # because an exception is not raised in this test.
            # So the argument for traceback is not checked.
            request_spec_dict = mock_notify.call_args_list[i][0][3]
            for key in ('instance_type', 'num_instances',
                        'instance_properties', 'image'):
                self.assertIn(key, request_spec_dict)

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_block_device_mapping')
    def test_bury_in_cell0_with_block_device_mapping(self, mock_create_bdm,
            mock_get_cell, mock_notify):
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
        mock_notify.assert_called_once_with(
            test.MatchType(context.RequestContext), 'build_instances',
            inst.uuid, test.MatchType(dict), 'error',
            test.MatchType(Exception))
        # traceback.format_exc() returns 'NoneType'
        # because an exception is not raised in this test.
        # So the argument for traceback is not checked.
        request_spec_dict = mock_notify.call_args_list[0][0][3]
        for key in ('instance_type', 'num_instances', 'instance_properties',
                    'image'):
            self.assertIn(key, request_spec_dict)

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch.object(objects.CellMapping, 'get_by_uuid')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_create_tags')
    def test_bury_in_cell0_with_tags(self, mock_create_tags, mock_get_cell,
                                     mock_notify):
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

    @mock.patch('nova.objects.Instance.create')
    def test_bury_in_cell0_already_mapped(self, mock_inst_create):
        """Tests a scenario where the instance mapping is already mapped to a
        cell when we attempt to bury the instance in cell0.
        """
        build_request = self.params['build_requests'][0]
        # Simulate MQ split brain craziness by updating the instance mapping
        # to point at cell1.
        inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.ctxt, build_request.instance_uuid)
        inst_mapping.cell_mapping = self.cell_mappings['cell1']
        inst_mapping.save()
        # Now attempt to bury the instance in cell0.
        with mock.patch.object(inst_mapping, 'save') as mock_inst_map_save:
            self.conductor._bury_in_cell0(
                self.ctxt, self.params['request_specs'][0],
                exc.NoValidHost(reason='idk'), build_requests=[build_request])
        # We should have exited without creating the instance in cell0 nor
        # should the instance mapping have been updated to point at cell0.
        mock_inst_create.assert_not_called()
        mock_inst_map_save.assert_not_called()
        # And we should have logged an error.
        self.assertIn('When attempting to bury instance in cell0, the '
                      'instance is already mapped to cell',
                      self.stdlog.logger.output)

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
        instance = fake_instance.fake_instance_obj(self.context,
                                                   vm_state=vm_states.ACTIVE,
                                                   flavor=self.flavor)
        self.assertRaises(NotImplementedError, self.conductor.migrate_server,
            self.context, instance, None, True, False, self.flavor, None, None)

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
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(migrate.MigrationTask, '_preallocate_migration')
    def test_cold_migrate_no_valid_host_back_in_active_state(
            self, _preallocate_migration, rollback_mock, notify_mock,
            select_dest_mock, metadata_mock, sig_mock, spec_fc_mock, im_mock):
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            instance_type_id=self.flavor.id,
            vm_state=vm_states.ACTIVE,
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=self.flavor,
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
                          self.flavor, {},
                          True, None, None)
        metadata_mock.assert_called_with({})
        sig_mock.assert_called_once_with(self.context, fake_spec)
        self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                              'migrate_server', updates,
                                              exc_info, fake_spec)
        rollback_mock.assert_called_once_with(exc_info)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(migrate.MigrationTask, '_preallocate_migration')
    def test_cold_migrate_no_valid_host_back_in_stopped_state(
            self, _preallocate_migration, rollback_mock, notify_mock,
            select_dest_mock, metadata_mock, spec_fc_mock, sig_mock, im_mock):
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=self.flavor,
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
                           self.flavor, {},
                           True, None, None)
        metadata_mock.assert_called_with({})
        sig_mock.assert_called_once_with(self.context, fake_spec)
        self.assertEqual(inst_obj.project_id, fake_spec.project_id)
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, fake_spec)
        rollback_mock.assert_called_once_with(exc_info)

    def test_cold_migrate_no_valid_host_error_msg(self):
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
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
                                    inst_obj, self.flavor, {},
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
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
            system_metadata={},
            uuid=uuids.instance,
            project_id=fakes.FAKE_PROJECT_ID,
            user_id=fakes.FAKE_USER_ID,
            flavor=self.flavor,
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
                          inst_obj, self.flavor, {}, True, None, None)

        updates = {'vm_state': vm_states.STOPPED, 'task_state': None}
        set_vm_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exception, fake_spec)
        spec_fc_mock.assert_called_once_with(
            self.context, inst_obj.uuid, image, self.flavor,
            inst_obj.numa_topology, inst_obj.pci_requests, {}, None,
            inst_obj.availability_zone, project_id=inst_obj.project_id,
            user_id=inst_obj.user_id)

    @mock.patch.object(migrate.MigrationTask,
                       '_is_selected_host_in_source_cell',
                       return_value=True)
    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid')
    @mock.patch.object(scheduler_utils, 'setup_instance_group')
    @mock.patch.object(objects.RequestSpec, 'from_components')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    @mock.patch.object(query.SchedulerQueryClient, 'select_destinations')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(migrate.MigrationTask, 'rollback')
    @mock.patch.object(compute_rpcapi.ComputeAPI, 'prep_resize')
    @mock.patch.object(migrate.MigrationTask, '_preallocate_migration')
    def test_cold_migrate_exception_host_in_error_state_and_raise(
            self, _preallocate_migration, prep_resize_mock, rollback_mock,
            notify_mock, select_dest_mock, metadata_mock, spec_fc_mock,
            sig_mock, im_mock, check_cell_mock):
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=self.flavor,
            availability_zone=None,
            pci_requests=None,
            numa_topology=None,
            project_id=self.context.project_id)
        image = 'fake-image'
        fake_spec = objects.RequestSpec(image=objects.ImageMeta())
        spec_fc_mock.return_value = fake_spec

        im_mock.return_value = objects.InstanceMapping(
            cell_mapping=objects.CellMapping.get_by_uuid(self.context,
                                                         uuids.cell1))

        hosts = [dict(host='host1', nodename='node1', limits={})]
        metadata_mock.return_value = image
        exc_info = test.TestingException('something happened')
        select_dest_mock.return_value = [[fake_selection1]]

        updates = {'vm_state': inst_obj.vm_state,
                   'task_state': None}
        prep_resize_mock.side_effect = exc_info
        with mock.patch.object(inst_obj, 'refresh') as mock_refresh:
            self.assertRaises(test.TestingException,
                              self.conductor._cold_migrate,
                              self.context, inst_obj, self.flavor,
                              {}, True, None, None)
            mock_refresh.assert_called_once_with()

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
            self.context, inst_obj, fake_spec.image,
            self.flavor, hosts[0]['host'], _preallocate_migration.return_value,
            request_spec=fake_spec,
            filter_properties=legacy_filter_props,
            node=hosts[0]['nodename'], clean_shutdown=True, host_list=[])
        notify_mock.assert_called_once_with(self.context, inst_obj.uuid,
                                            'migrate_server', updates,
                                            exc_info, fake_spec)
        rollback_mock.assert_called_once_with(exc_info)

    @mock.patch('nova.conductor.tasks.migrate.MigrationTask.execute',
                side_effect=test.TestingException('execute fails'))
    @mock.patch('nova.objects.Instance.refresh',
                side_effect=exc.InstanceNotFound(instance_id=uuids.instance))
    def test_cold_migrate_exception_instance_refresh_not_found(
            self, mock_refresh, mock_execute):
        """Tests the scenario where MigrationTask.execute raises some error
        and then the instance.refresh() in the exception block raises
        InstanceNotFound because the instance was deleted during the operation.
        """
        params = {'uuid': uuids.instance}
        instance = self._create_fake_instance_obj(params=params)
        filter_properties = {}
        clean_shutdown = True
        request_spec = fake_request_spec.fake_spec_obj()
        request_spec.flavor = instance.flavor
        host_list = None
        self.assertRaises(test.TestingException,
                          self.conductor._cold_migrate,
                          self.context, instance, instance.flavor,
                          filter_properties, clean_shutdown,
                          request_spec, host_list)
        self.assertIn('During cold migrate the instance was deleted.',
                      self.stdlog.logger.output)
        mock_execute.assert_called_once_with()
        mock_refresh.assert_called_once_with()

    @mock.patch.object(objects.RequestSpec, 'save')
    @mock.patch.object(migrate.MigrationTask, 'execute')
    @mock.patch.object(utils, 'get_image_from_system_metadata')
    def test_cold_migrate_updates_flavor_if_existing_reqspec(self,
                                                             image_mock,
                                                             task_exec_mock,
                                                             spec_save_mock):
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
            system_metadata={},
            uuid=uuids.instance,
            user_id=fakes.FAKE_USER_ID,
            flavor=self.flavor,
            availability_zone=None,
            pci_requests=None,
            numa_topology=None)
        image = 'fake-image'
        fake_spec = fake_request_spec.fake_spec_obj()

        image_mock.return_value = image
        # Just make sure we have an original flavor which is different from
        # the new one
        self.assertNotEqual(self.flavor, fake_spec.flavor)
        self.conductor._cold_migrate(self.context, inst_obj, self.flavor, {},
                                     True, fake_spec, None)

        # Now the RequestSpec should be updated...
        self.assertEqual(self.flavor, fake_spec.flavor)
        # ...and persisted
        spec_save_mock.assert_called_once_with()

    @mock.patch('nova.objects.RequestSpec.from_primitives')
    @mock.patch.object(objects.RequestSpec, 'save')
    def test_cold_migrate_reschedule_legacy_request_spec(
            self, spec_save_mock, from_primitives_mock):
        """Tests the scenario that compute RPC API is pinned to less than 5.1
        so conductor passes a legacy dict request spec to compute and compute
        sends it back to conductor on a reschedule during prep_resize so
        conductor has to convert the legacy request spec dict to an object.
        """
        instance = objects.Instance(system_metadata={})
        fake_spec = fake_request_spec.fake_spec_obj()
        from_primitives_mock.return_value = fake_spec
        legacy_spec = fake_spec.to_legacy_request_spec_dict()
        filter_props = {}
        clean_shutdown = True
        host_list = mock.sentinel.host_list

        with mock.patch.object(
                self.conductor, '_build_cold_migrate_task') as build_task_mock:
            self.conductor._cold_migrate(
                self.context, instance, self.flavor, filter_props,
                clean_shutdown, legacy_spec, host_list)
        # Make sure the legacy request spec was converted.
        from_primitives_mock.assert_called_once_with(
            self.context, legacy_spec, filter_props)
        build_task_mock.assert_called_once_with(
            self.context, instance, self.flavor,
            fake_spec, clean_shutdown, host_list)
        spec_save_mock.assert_called_once_with()

    def test_resize_no_valid_host_error_msg(self):
        flavor_new = objects.Flavor.get_by_name(self.ctxt, 'm1.small')
        inst_obj = objects.Instance(
            image_ref='fake-image_ref',
            vm_state=vm_states.STOPPED,
            instance_type_id=self.flavor.id,
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
            node='node2', limits=None, host_list=[], accel_uuids=[])

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
                mock.patch.object(self.conductor_manager.query_client,
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
                    node='node2', limits=None, host_list=[], accel_uuids=[])

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch('nova.objects.Instance.save')
    def test_build_instances_max_retries_exceeded(self, mock_save,
                                                  mock_notify):
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

        mock_notify.assert_called_once_with(
            self.context, 'build_instances',
            instance.uuid, test.MatchType(dict), 'error',
            test.MatchType(exc.MaxRetriesExceeded))
        request_spec_dict = mock_notify.call_args_list[0][0][3]
        for key in ('instance_type', 'num_instances', 'instance_properties',
                    'image'):
            self.assertIn(key, request_spec_dict)

    @mock.patch('nova.compute.utils.notify_about_compute_task_error')
    @mock.patch('nova.objects.Instance.save')
    def test_build_instances_reschedule_no_valid_host(self, mock_save,
                                                      mock_notify):
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
                    self.conductor.query_client, 'select_destinations',
                    side_effect=exc.NoValidHost(reason='oops')):
                self.conductor.build_instances(
                    self.context, [instance], image, filter_props,
                    mock.sentinel.admin_pass, mock.sentinel.files,
                    requested_networks, mock.sentinel.secgroups)
                mock_save.assert_called_once_with()

        mock_notify.assert_called_once_with(
            self.context, 'build_instances',
            instance.uuid, test.MatchType(dict), 'error',
            test.MatchType(exc.NoValidHost))
        request_spec_dict = mock_notify.call_args_list[0][0][3]
        for key in ('instance_type', 'num_instances', 'instance_properties',
                    'image'):
            self.assertIn(key, request_spec_dict)

    @mock.patch('nova.scheduler.utils.claim_resources', return_value=True)
    @mock.patch('nova.scheduler.utils.fill_provider_mapping')
    @mock.patch('nova.availability_zones.get_host_availability_zone',
                side_effect=db_exc.CantStartEngineError)
    @mock.patch('nova.conductor.manager.ComputeTaskManager.'
                '_cleanup_when_reschedule_fails')
    @mock.patch('nova.objects.Instance.save')
    def test_build_reschedule_get_az_error(self, mock_save, mock_cleanup,
                                           mock_get_az, mock_fill, mock_claim):
        """Tests a scenario where rescheduling during a build fails trying to
        get the AZ for the selected host will put the instance into a terminal
        (ERROR) state.
        """
        instance = fake_instance.fake_instance_obj(self.context)
        image = objects.ImageMeta()
        requested_networks = objects.NetworkRequestList()
        request_spec = fake_request_spec.fake_spec_obj()
        host_lists = copy.deepcopy(fake_host_lists_alt)
        filter_props = {}
        # Pre-populate the filter properties with the initial host we tried to
        # build on which failed and triggered a reschedule.
        host1 = host_lists[0].pop(0)
        scheduler_utils.populate_filter_properties(filter_props, host1)
        # We have to save off the first alternate we try since build_instances
        # modifies the host_lists list.
        host2 = host_lists[0][0]

        self.conductor.build_instances(
            self.context, [instance], image, filter_props,
            mock.sentinel.admin_password, mock.sentinel.injected_files,
            requested_networks, mock.sentinel.security_groups,
            request_spec=request_spec, host_lists=host_lists)

        mock_claim.assert_called_once()
        mock_fill.assert_called_once()
        mock_get_az.assert_called_once_with(self.context, host2.service_host)
        mock_cleanup.assert_called_once_with(
            self.context, instance,
            test.MatchType(db_exc.CantStartEngineError), test.MatchType(dict),
            requested_networks)
        # Assert that we did not continue processing the instance once we
        # handled the error.
        mock_save.assert_not_called()

    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_cleanup_allocated_networks')
    @mock.patch.object(conductor_manager.ComputeTaskManager,
                       '_set_vm_state_and_notify')
    @mock.patch.object(compute_utils, 'delete_arqs_if_needed')
    def test_cleanup_arqs_on_reschedule(self, mock_del_arqs,
            mock_set_vm, mock_clean_net):
        instance = fake_instance.fake_instance_obj(self.context)
        self.conductor_manager._cleanup_when_reschedule_fails(
            self.context, instance, exception=None,
            legacy_request_spec=None, requested_networks=None)
        mock_del_arqs.assert_called_once_with(self.context, instance)

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
            self.ctxt, self.conductor.report_client, instance,
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

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       side_effect=db_exc.CantStartEngineError)
    def test_targets_cell_no_api_db_conn_noop(self, mock_im):
        """Tests that targets_cell noops on CantStartEngineError if the API
        DB is not configured because we assume we're in the cell conductor.
        """
        self.flags(connection=None, group='api_database')

        @conductor_manager.targets_cell
        def _test(self, context, instance):
            return mock.sentinel.iransofaraway

        ctxt = mock.MagicMock()
        inst = mock.MagicMock()
        self.assertEqual(mock.sentinel.iransofaraway,
                         _test(None, ctxt, inst))
        mock_im.assert_called_once_with(ctxt, inst.uuid)

    @mock.patch.object(objects.InstanceMapping, 'get_by_instance_uuid',
                       side_effect=db_exc.CantStartEngineError)
    def test_targets_cell_no_api_db_conn_reraise(self, mock_im):
        """Tests that targets_cell reraises CantStartEngineError if the
        API DB is configured.
        """
        self.flags(connection='mysql://dbhost?nova_api', group='api_database')

        @conductor_manager.targets_cell
        def _test(self, context, instance):
            return mock.sentinel.iransofaraway

        ctxt = mock.MagicMock()
        inst = mock.MagicMock()
        self.assertRaises(db_exc.CantStartEngineError, _test, None, ctxt, inst)
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

    def test_cache_images(self):
        with mock.patch.object(self.conductor, 'client') as client:
            self.conductor.cache_images(self.context, mock.sentinel.aggregate,
                                        [mock.sentinel.image])
            client.prepare.return_value.cast.assert_called_once_with(
                self.context, 'cache_images',
                aggregate=mock.sentinel.aggregate,
                image_ids=[mock.sentinel.image])
            client.prepare.assert_called_once_with(version='1.21')

        with mock.patch.object(self.conductor.client, 'can_send_version') as v:
            v.return_value = False
            self.assertRaises(exc.NovaException,
                              self.conductor.cache_images,
                              self.context, mock.sentinel.aggregate,
                              [mock.sentinel.image])

    def test_migrate_server(self):
        self.flags(rpc_response_timeout=10, long_rpc_timeout=120)
        instance = objects.Instance()
        scheduler_hint = {}
        live = rebuild = False
        flavor = objects.Flavor()
        block_migration = disk_over_commit = None

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           return_value=True)
        @mock.patch.object(self.conductor.client, 'prepare')
        def _test(prepare_mock, can_send_mock):
            self.conductor.migrate_server(
                self.context, instance, scheduler_hint, live, rebuild,
                flavor, block_migration, disk_over_commit)
            kw = {'instance': instance, 'scheduler_hint': scheduler_hint,
                  'live': live, 'rebuild': rebuild, 'flavor': flavor,
                  'block_migration': block_migration,
                  'disk_over_commit': disk_over_commit,
                  'reservations': None, 'clean_shutdown': True,
                  'request_spec': None, 'host_list': None}
            prepare_mock.assert_called_once_with(
                version=test.MatchType(str),  # version
                call_monitor_timeout=10,
                timeout=120)
            prepare_mock.return_value.call.assert_called_once_with(
                self.context, 'migrate_server', **kw)

        _test()

    def test_migrate_server_cast(self):
        """Tests that if calling migrate_server() with do_cast=True an RPC
        cast is performed rather than a call.
        """
        instance = objects.Instance()
        scheduler_hint = {}
        live = rebuild = False
        flavor = objects.Flavor()
        block_migration = disk_over_commit = None

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           return_value=True)
        @mock.patch.object(self.conductor.client, 'prepare')
        def _test(prepare_mock, can_send_mock):
            self.conductor.migrate_server(
                self.context, instance, scheduler_hint, live, rebuild,
                flavor, block_migration, disk_over_commit, do_cast=True)
            kw = {'instance': instance, 'scheduler_hint': scheduler_hint,
                  'live': live, 'rebuild': rebuild, 'flavor': flavor,
                  'block_migration': block_migration,
                  'disk_over_commit': disk_over_commit,
                  'reservations': None, 'clean_shutdown': True,
                  'request_spec': None, 'host_list': None}
            prepare_mock.assert_called_once_with(
                version=test.MatchType(str),  # version
                call_monitor_timeout=CONF.rpc_response_timeout,
                timeout=CONF.long_rpc_timeout)
            prepare_mock.return_value.cast.assert_called_once_with(
                self.context, 'migrate_server', **kw)

        _test()

    def _test_confirm_snapshot_based_resize(self, do_cast):
        """Tests how confirm_snapshot_based_resize is called when do_cast is
        True or False.
        """
        instance = objects.Instance()
        migration = objects.Migration()

        @mock.patch.object(self.conductor.client, 'can_send_version',
                           return_value=True)
        @mock.patch.object(self.conductor.client, 'prepare')
        def _test(prepare_mock, can_send_mock):
            self.conductor.confirm_snapshot_based_resize(
                self.context, instance, migration, do_cast=do_cast)
            kw = {'instance': instance, 'migration': migration}
            if do_cast:
                prepare_mock.return_value.cast.assert_called_once_with(
                    self.context, 'confirm_snapshot_based_resize', **kw)
            else:
                prepare_mock.return_value.call.assert_called_once_with(
                    self.context, 'confirm_snapshot_based_resize', **kw)
        _test()

    def test_confirm_snapshot_based_resize_cast(self):
        self._test_confirm_snapshot_based_resize(do_cast=True)

    def test_confirm_snapshot_based_resize_call(self):
        self._test_confirm_snapshot_based_resize(do_cast=False)

    def test_confirm_snapshot_based_resize_old_service(self):
        """Tests confirm_snapshot_based_resize when the service is too old."""
        with mock.patch.object(
                self.conductor.client, 'can_send_version', return_value=False):
            self.assertRaises(exc.ServiceTooOld,
                              self.conductor.confirm_snapshot_based_resize,
                              self.context, mock.sentinel.instance,
                              mock.sentinel.migration)

    def test_revert_snapshot_based_resize_old_service(self):
        """Tests revert_snapshot_based_resize when the service is too old."""
        with mock.patch.object(
                self.conductor.client, 'can_send_version',
                return_value=False) as can_send_version:
            self.assertRaises(exc.ServiceTooOld,
                              self.conductor.revert_snapshot_based_resize,
                              self.context, mock.sentinel.instance,
                              mock.sentinel.migration)
        can_send_version.assert_called_once_with('1.23')


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

    def test_cache_images(self):
        @mock.patch.object(self.conductor.conductor_compute_rpcapi,
                           'cache_images')
        @mock.patch.object(self.conductor.image_api, 'get')
        def _test(mock_image, mock_cache):
            self.conductor.cache_images(self.context,
                                        mock.sentinel.aggregate,
                                        [mock.sentinel.image1,
                                         mock.sentinel.image2])
            mock_image.assert_has_calls([mock.call(self.context,
                                                mock.sentinel.image1),
                                         mock.call(self.context,
                                                   mock.sentinel.image2)])
            mock_cache.assert_called_once_with(
                self.context, mock.sentinel.aggregate,
                [mock.sentinel.image1, mock.sentinel.image2])

        _test()

    def test_cache_images_fail(self):
        @mock.patch.object(self.conductor.conductor_compute_rpcapi,
                           'cache_images')
        @mock.patch.object(self.conductor.image_api, 'get')
        def _test(mock_image, mock_cache):
            mock_image.side_effect = test.TestingException()
            # We should expect to see non-NovaException errors
            # raised directly so the API can 500 for them.
            self.assertRaises(test.TestingException,
                              self.conductor.cache_images,
                              self.context,
                              mock.sentinel.aggregate,
                              [mock.sentinel.image1,
                               mock.sentinel.image2])
            mock_cache.assert_not_called()

        _test()

    def test_cache_images_missing(self):
        @mock.patch.object(self.conductor.conductor_compute_rpcapi,
                           'cache_images')
        @mock.patch.object(self.conductor.image_api, 'get')
        def _test(mock_image, mock_cache):
            mock_image.side_effect = exc.ImageNotFound('foo')
            self.assertRaises(exc.ImageNotFound,
                              self.conductor.cache_images,
                              self.context,
                              mock.sentinel.aggregate,
                              [mock.sentinel.image1,
                               mock.sentinel.image2])
            mock_cache.assert_not_called()

        _test()

    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.context.target_cell')
    @mock.patch('nova.objects.Service.get_by_compute_host')
    def test_cache_images_failed_compute(self, mock_service, mock_target,
                                         mock_gbh):
        """Test the edge cases for cache_images(), specifically the
        error, skip, and down situations.
        """

        fake_service = objects.Service(disabled=False, forced_down=False,
                                       last_seen_up=timeutils.utcnow())
        fake_down_service = objects.Service(disabled=False, forced_down=True,
                                            last_seen_up=None)
        mock_service.side_effect = [fake_service, fake_service,
                                    fake_down_service]
        mock_target.__return_value.__enter__.return_value = self.context
        fake_cell = objects.CellMapping(uuid=uuids.cell,
                                        database_connection='',
                                        transport_url='')
        fake_mapping = objects.HostMapping(cell_mapping=fake_cell)
        mock_gbh.return_value = fake_mapping
        fake_agg = objects.Aggregate(name='agg', uuid=uuids.agg, id=1,
                                     hosts=['host1', 'host2', 'host3'])

        @mock.patch.object(self.conductor_manager.compute_rpcapi,
                           'cache_images')
        def _test(mock_cache):
            mock_cache.side_effect = [
                {'image1': 'unsupported'},
                {'image1': 'error'},
            ]
            self.conductor_manager.cache_images(self.context,
                                                fake_agg,
                                                ['image1'])

        _test()

        logtext = self.stdlog.logger.output
        self.assertIn(
            '0 cached, 0 existing, 1 errors, 1 unsupported, 1 skipped',
            logtext)
        self.assertIn('host3\' because it is not up', logtext)
        self.assertIn('image1 failed 1 times', logtext)
