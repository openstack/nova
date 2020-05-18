# Copyright 2015 Red Hat, Inc.
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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

"""Tests for the ironic driver."""

import fixtures
from ironicclient import exc as ironic_exception
import mock
from openstack import exceptions as sdk_exc
from oslo_config import cfg
from oslo_service import loopingcall
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils
import six
from testtools import matchers
from tooz import hashring as hash_ring

from nova.api.metadata import base as instance_metadata
from nova.api.openstack import common
from nova import block_device
from nova.compute import power_state as nova_states
from nova.compute import provider_tree
from nova.compute import task_states
from nova.compute import vm_states
from nova.console import type as console_type
from nova import context as nova_context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova import servicegroup
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.tests.unit import matchers as nova_matchers
from nova.tests.unit import utils
from nova.tests.unit.virt.ironic import utils as ironic_utils
from nova import utils as nova_utils
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt import driver
from nova.virt import fake
from nova.virt import hardware
from nova.virt.ironic import client_wrapper as cw
from nova.virt.ironic import driver as ironic_driver
from nova.virt.ironic import ironic_states


CONF = cfg.CONF

FAKE_CLIENT = ironic_utils.FakeClient()

SENTINEL = object()


class FakeClientWrapper(cw.IronicClientWrapper):
    def _get_client(self, retry_on_conflict=True):
        return FAKE_CLIENT


class FakeLoopingCall(object):
    def __init__(self):
        self.wait = mock.MagicMock()
        self.start = mock.MagicMock()
        self.start.return_value = self


def _get_properties():
    return {'cpus': 2,
            'memory_mb': 512,
            'local_gb': 10,
            'cpu_arch': 'x86_64',
            'capabilities': None}


def _get_instance_info():
    return {'vcpus': 1,
            'memory_mb': 1024,
            'local_gb': 10}


def _get_stats():
    return {'cpu_arch': 'x86_64'}


def _get_cached_node(**kw):
    """Return a fake node object representative of objects in the cache."""
    return ironic_utils.get_test_node(**kw)


def _make_compute_service(hostname):
    return objects.Service(host=hostname)


FAKE_CLIENT_WRAPPER = FakeClientWrapper()


@mock.patch.object(cw, 'IronicClientWrapper', lambda *_: FAKE_CLIENT_WRAPPER)
class IronicDriverTestCase(test.NoDBTestCase):

    @mock.patch.object(cw, 'IronicClientWrapper',
                       lambda *_: FAKE_CLIENT_WRAPPER)
    @mock.patch.object(ironic_driver.IronicDriver, '_refresh_hash_ring')
    @mock.patch.object(servicegroup, 'API', autospec=True)
    def setUp(self, mock_sg, mock_hash):
        super(IronicDriverTestCase, self).setUp()

        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()

        self.mock_conn = self.useFixture(
            fixtures.MockPatchObject(self.driver, '_ironic_connection')).mock

        self.ctx = nova_context.get_admin_context()

        # TODO(dustinc): Remove once all id/uuid usages are normalized.
        self.instance_id = uuidutils.generate_uuid()
        self.instance_uuid = self.instance_id

        self.ptree = provider_tree.ProviderTree()
        self.ptree.new_root(mock.sentinel.nodename, mock.sentinel.nodename)

        # mock retries configs to avoid sleeps and make tests run quicker
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

    def test_public_api_signatures(self):
        self.assertPublicAPISignatures(driver.ComputeDriver(None), self.driver)

    def test_validate_driver_loading(self):
        self.assertIsInstance(self.driver, ironic_driver.IronicDriver)

    def test_driver_capabilities(self):
        self.assertFalse(self.driver.capabilities['has_imagecache'],
                         'Driver capabilities for \'has_imagecache\''
                         'is invalid')
        self.assertFalse(self.driver.capabilities['supports_evacuate'],
                         'Driver capabilities for \'supports_evacuate\''
                         'is invalid')
        self.assertFalse(self.driver.capabilities[
                             'supports_migrate_to_same_host'],
                         'Driver capabilities for '
                         '\'supports_migrate_to_same_host\' is invalid')

    def test__get_hypervisor_type(self):
        self.assertEqual('ironic', self.driver._get_hypervisor_type())

    def test__get_hypervisor_version(self):
        self.assertEqual(1, self.driver._get_hypervisor_version())

    def test__get_node(self):
        node_id = uuidutils.generate_uuid()
        node = _get_cached_node(id=node_id)
        self.mock_conn.get_node.return_value = node

        actual = self.driver._get_node(node_id)

        self.assertEqual(node, actual)
        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)

    def test__get_node_not_found(self):
        node_id = uuidutils.generate_uuid()
        self.mock_conn.get_node.side_effect = sdk_exc.ResourceNotFound

        self.assertRaises(sdk_exc.ResourceNotFound,
                          self.driver._get_node, node_id)
        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)

    def test__validate_instance_and_node(self):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(id=node_id, instance_id=self.instance_id)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_id)
        self.mock_conn.nodes.return_value = iter([node])
        result = self.driver._validate_instance_and_node(instance)
        self.assertEqual(result.uuid, node_id)
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    def test__validate_instance_and_node_failed(self):
        self.mock_conn.nodes.return_value = iter([])
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_id)
        self.assertRaises(exception.InstanceNotFound,
                          self.driver._validate_instance_and_node, instance)
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    def test__validate_instance_and_node_unexpected_many_nodes(self):
        self.mock_conn.nodes.return_value = iter(['1', '2', '3'])
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_id)
        self.assertRaises(exception.NovaException,
                          self.driver._validate_instance_and_node, instance)
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_active_pass(self, fake_validate, fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = _get_cached_node(provision_state=ironic_states.DEPLOYING)

        fake_validate.return_value = node
        self.driver._wait_for_active(instance)
        fake_validate.assert_called_once_with(instance)
        fake_refresh.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_active_done(self, fake_validate, fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = _get_cached_node(provision_state=ironic_states.ACTIVE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_active, instance)
        fake_validate.assert_called_once_with(instance)
        fake_refresh.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_active_from_error(self, fake_validate, fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid(),
                vm_state=vm_states.ERROR,
                task_state=task_states.REBUILD_SPAWNING)
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.ACTIVE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_active, instance)
        fake_validate.assert_called_once_with(instance)
        fake_refresh.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_active_fail(self, fake_validate, fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = _get_cached_node(provision_state=ironic_states.DEPLOYFAIL)

        fake_validate.return_value = node
        self.assertRaises(exception.InstanceDeployFailure,
                self.driver._wait_for_active, instance)
        fake_validate.assert_called_once_with(instance)
        fake_refresh.assert_called_once_with()

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def _wait_for_active_abort(self, instance_params, fake_validate,
                              fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid(),
                **instance_params)
        self.assertRaises(exception.InstanceDeployFailure,
                self.driver._wait_for_active, instance)
        # Assert _validate_instance_and_node wasn't called
        self.assertFalse(fake_validate.called)
        fake_refresh.assert_called_once_with()

    def test__wait_for_active_abort_deleting(self):
        self._wait_for_active_abort({'task_state': task_states.DELETING})

    def test__wait_for_active_abort_deleted(self):
        self._wait_for_active_abort({'vm_state': vm_states.DELETED})

    def test__wait_for_active_abort_error(self):
        self._wait_for_active_abort({'task_state': task_states.SPAWNING,
                                     'vm_state': vm_states.ERROR})

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_power_state_pass(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = _get_cached_node(target_power_state=ironic_states.POWER_OFF)

        fake_validate.return_value = node
        self.driver._wait_for_power_state(instance, 'fake message')
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_power_state_ok(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = _get_cached_node(target_power_state=ironic_states.NOSTATE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_power_state, instance, 'fake message')
        self.assertTrue(fake_validate.called)

    def test__node_resource_with_instance_uuid(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = _get_cached_node(
                uuid=node_uuid, instance_uuid=self.instance_uuid,
                properties=props, resource_class='foo')

        result = self.driver._node_resource(node)

        wantkeys = ["uuid", "hypervisor_hostname", "hypervisor_type",
                    "hypervisor_version", "cpu_info",
                    "vcpus", "vcpus_used",
                    "memory_mb", "memory_mb_used",
                    "local_gb", "local_gb_used",
                    "disk_available_least",
                    "supported_instances",
                    "stats",
                    "numa_topology", "resource_class"]
        wantkeys.sort()
        gotkeys = sorted(result.keys())
        self.assertEqual(wantkeys, gotkeys)

        self.assertEqual(0, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(0, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(0, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['uuid'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])
        self.assertEqual('foo', result['resource_class'])
        self.assertIsNone(result['numa_topology'])

    def test__node_resource_canonicalizes_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        props['cpu_arch'] = 'i386'
        node = _get_cached_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual('i686', result['supported_instances'][0][0])
        self.assertEqual('i386', result['stats']['cpu_arch'])

    def test__node_resource_unknown_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        del props['cpu_arch']
        node = _get_cached_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual([], result['supported_instances'])

    def test__node_resource_exposes_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability, test2:value2'
        node = _get_cached_node(properties=props)
        result = self.driver._node_resource(node)
        stats = result['stats']
        self.assertIsNone(stats.get('capabilities'))
        self.assertEqual('capability', stats.get('test'))
        self.assertEqual('value2', stats.get('test2'))

    def test__node_resource_no_capabilities(self):
        props = _get_properties()
        props['capabilities'] = None
        node = _get_cached_node(properties=props)
        result = self.driver._node_resource(node)
        self.assertIsNone(result['stats'].get('capabilities'))

    def test__node_resource_malformed_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability,:no_key,no_val:'
        node = _get_cached_node(properties=props)
        result = self.driver._node_resource(node)
        stats = result['stats']
        self.assertEqual('capability', stats.get('test'))

    def test__node_resource_available(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = _get_cached_node(
            uuid=node_uuid,
            instance_uuid=None,
            power_state=ironic_states.POWER_OFF,
            properties=props,
            provision_state=ironic_states.AVAILABLE)

        result = self.driver._node_resource(node)
        self.assertEqual(0, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(0, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(0, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable')
    def test__node_resource_unavailable_node_res(self, mock_res_unavail):
        mock_res_unavail.return_value = True
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = _get_cached_node(
                uuid=node_uuid, instance_uuid=None, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual(0, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(0, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(0, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used')
    def test__node_resource_used_node_res(self, mock_res_used):
        mock_res_used.return_value = True
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        instance_info = _get_instance_info()
        node = _get_cached_node(
            uuid=node_uuid,
            instance_uuid=uuidutils.generate_uuid(),
            provision_state=ironic_states.ACTIVE,
            properties=props,
            instance_info=instance_info)

        result = self.driver._node_resource(node)
        self.assertEqual(0, result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(0, result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(0, result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_properties(self, mock_warning):
        props = _get_properties()
        node = _get_cached_node(
            uuid=uuidutils.generate_uuid(),
            properties=props)
        # raw_cpu_arch is included because extra_specs filters do not
        # canonicalized the arch
        props['raw_cpu_arch'] = props['cpu_arch']
        parsed = self.driver._parse_node_properties(node)

        self.assertEqual(props, parsed)
        # Assert we didn't log any warning since all properties are
        # correct
        self.assertFalse(mock_warning.called)

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_properties_bad_values(self, mock_warning):
        props = _get_properties()
        props['cpus'] = 'bad-value'
        props['memory_mb'] = 'bad-value'
        props['local_gb'] = 'bad-value'
        props['cpu_arch'] = 'bad-value'
        node = _get_cached_node(
            uuid=uuidutils.generate_uuid(),
            properties=props)
        # raw_cpu_arch is included because extra_specs filters do not
        # canonicalized the arch
        props['raw_cpu_arch'] = props['cpu_arch']
        parsed = self.driver._parse_node_properties(node)

        expected_props = props.copy()
        expected_props['cpus'] = 0
        expected_props['memory_mb'] = 0
        expected_props['local_gb'] = 0
        expected_props['cpu_arch'] = None
        self.assertEqual(expected_props, parsed)
        self.assertEqual(4, mock_warning.call_count)

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_properties_canonicalize_cpu_arch(self, mock_warning):
        props = _get_properties()
        props['cpu_arch'] = 'amd64'
        node = _get_cached_node(
            uuid=uuidutils.generate_uuid(),
            properties=props)
        # raw_cpu_arch is included because extra_specs filters do not
        # canonicalized the arch
        props['raw_cpu_arch'] = props['cpu_arch']
        parsed = self.driver._parse_node_properties(node)

        expected_props = props.copy()
        # Make sure it cpu_arch was canonicalized
        expected_props['cpu_arch'] = 'x86_64'
        self.assertEqual(expected_props, parsed)
        # Assert we didn't log any warning since all properties are
        # correct
        self.assertFalse(mock_warning.called)

    def test_instance_exists(self):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_id)
        node = ironic_utils.get_test_node(fields=ironic_driver._NODE_FIELDS,
                                          id=uuidutils.generate_uuid(),
                                          instance_id=instance.uuid)

        self.mock_conn.nodes.return_value = iter([node])

        self.assertTrue(self.driver.instance_exists(instance))
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    def test_instance_exists_fail(self):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_id)
        self.mock_conn.nodes.return_value = iter([])

        self.assertFalse(self.driver.instance_exists(instance))
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    def test__get_node_list(self):
        test_nodes = [ironic_utils.get_test_node(
            fields=ironic_driver._NODE_FIELDS, id=uuidutils.generate_uuid())
            for _ in range(3)]
        self.mock_conn.nodes.return_value = iter(test_nodes)

        response = self.driver._get_node_list(associated=True)

        self.assertIsInstance(response, list)
        self.assertEqual(test_nodes, response)
        self.mock_conn.nodes.assert_called_once_with(associated=True)

    def test__get_node_list_generator(self):
        test_nodes = [ironic_utils.get_test_node(
            fields=ironic_driver._NODE_FIELDS, id=uuidutils.generate_uuid())
            for _ in range(3)]
        self.mock_conn.nodes.return_value = iter(test_nodes)

        response = self.driver._get_node_list(return_generator=True,
                                              associated=True)

        # NOTE(dustinc): This is simpler than importing a module just to get
        #  this one type...
        self.assertIsInstance(response, type(iter([])))
        self.assertEqual(test_nodes, list(response))
        self.mock_conn.nodes.assert_called_once_with(associated=True)

    def test__get_node_list_fail(self):
        self.mock_conn.nodes.side_effect = sdk_exc.InvalidResourceQuery()
        self.assertRaises(exception.VirtDriverNotReady,
                          self.driver._get_node_list)

        self.mock_conn.nodes.side_effect = Exception()
        self.assertRaises(exception.VirtDriverNotReady,
                          self.driver._get_node_list)

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instances(self, mock_inst_by_uuid):
        nodes = []
        instances = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            instances.append(fake_instance.fake_instance_obj(self.ctx,
                                                             id=i,
                                                             uuid=uuid))
            nodes.append(ironic_utils.get_test_node(instance_id=uuid,
                                                    fields=['instance_id']))
        mock_inst_by_uuid.side_effect = instances
        self.mock_conn.nodes.return_value = iter(nodes)

        response = self.driver.list_instances()

        self.mock_conn.nodes.assert_called_with(associated=True,
                                                fields=['instance_uuid'])
        expected_calls = [mock.call(mock.ANY, instances[0].uuid),
                          mock.call(mock.ANY, instances[1].uuid)]
        mock_inst_by_uuid.assert_has_calls(expected_calls)
        self.assertEqual(['instance-00000000', 'instance-00000001'],
                         sorted(response))

    # NOTE(dustinc) This test ensures we use instance_uuid not instance_id in
    # 'fields' when calling ironic.
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instances_uses_instance_uuid(self, mock_inst_by_uuid):
        self.driver.list_instances()

        self.mock_conn.nodes.assert_called_with(associated=True,
                                                fields=['instance_uuid'])

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instances_fail(self, mock_inst_by_uuid):
        self.mock_conn.nodes.side_effect = exception.NovaException

        self.assertRaises(exception.VirtDriverNotReady,
                          self.driver.list_instances)
        self.mock_conn.nodes.assert_called_with(associated=True,
                                                fields=['instance_uuid'])
        self.assertFalse(mock_inst_by_uuid.called)

    def test_list_instance_uuids(self):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                      instance_id=uuidutils.generate_uuid(),
                                      fields=['instance_id']))
        self.mock_conn.nodes.return_value = iter(nodes)

        uuids = self.driver.list_instance_uuids()

        self.mock_conn.nodes.assert_called_with(associated=True,
                                                fields=['instance_uuid'])
        expected = [n.instance_id for n in nodes]
        self.assertEqual(sorted(expected), sorted(uuids))

    # NOTE(dustinc) This test ensures we use instance_uuid not instance_id in
    # 'fields' when calling ironic.
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instance_uuids_uses_instance_uuid(self, mock_inst_by_uuid):
        self.driver.list_instance_uuids()

        self.mock_conn.nodes.assert_called_with(associated=True,
                                                fields=['instance_uuid'])

    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_node_is_available_empty_cache_empty_list(self, mock_services,
                                                      mock_instances):
        node = _get_cached_node()
        self.mock_conn.get_node.return_value = node
        self.mock_conn.nodes.return_value = iter([])

        self.assertTrue(self.driver.node_is_available(node.id))
        self.mock_conn.get_node.assert_called_with(
            node.id, fields=ironic_driver._NODE_FIELDS)
        self.mock_conn.nodes.assert_called_with(
            fields=ironic_driver._NODE_FIELDS)

        self.mock_conn.get_node.side_effect = sdk_exc.ResourceNotFound
        self.assertFalse(self.driver.node_is_available(node.id))

    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_node_is_available_empty_cache(self, mock_services,
                                           mock_instances):
        node = _get_cached_node()
        self.mock_conn.get_node.return_value = node
        self.mock_conn.nodes.return_value = iter([node])

        self.assertTrue(self.driver.node_is_available(node.uuid))
        self.mock_conn.nodes.assert_called_with(
            fields=ironic_driver._NODE_FIELDS)
        self.assertEqual(0, self.mock_conn.get_node.call_count)

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_node_is_available_with_cache(self, mock_services, mock_instances,
                                          mock_get, mock_list):
        node = _get_cached_node()
        mock_get.return_value = node
        mock_list.return_value = [node]
        # populate the cache
        self.driver.get_available_nodes(refresh=True)
        # prove that zero calls are made after populating cache
        mock_list.reset_mock()
        self.assertTrue(self.driver.node_is_available(node.uuid))
        self.assertEqual(0, mock_list.call_count)
        self.assertEqual(0, mock_get.call_count)

    def test__node_resources_unavailable(self):
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF,
             'provision_state': ironic_states.AVAILABLE},
            # a node in maintenance /w no instance and ERROR power state
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.ERROR,
             'provision_state': ironic_states.AVAILABLE},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.NOSTATE,
             'provision_state': ironic_states.AVAILABLE},
            # a node not in maintenance or bad power state, bad provision state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'provision_state': ironic_states.MANAGEABLE},
            # a node in cleaning
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'provision_state': ironic_states.CLEANING},
            # a node in cleaning, waiting for a clean step to finish
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'provision_state': ironic_states.CLEANWAIT},
            # a node in deleting
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'provision_state': ironic_states.DELETING},
            # a node in deleted
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'provision_state': ironic_states.DELETED},
        ]
        for n in node_dicts:
            node = _get_cached_node(**n)
            self.assertTrue(self.driver._node_resources_unavailable(node))

        for ok_state in (ironic_states.AVAILABLE, ironic_states.NOSTATE):
            # these are both ok and should present as available as they
            # have no instance_uuid
            avail_node = _get_cached_node(
                            power_state=ironic_states.POWER_OFF,
                            provision_state=ok_state)
            unavailable = self.driver._node_resources_unavailable(avail_node)
            self.assertFalse(unavailable)

    def test__node_resources_used(self):
        node_dicts = [
            # a node in maintenance /w instance and active
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': uuidutils.generate_uuid(),
             'provision_state': ironic_states.ACTIVE},
        ]
        for n in node_dicts:
            node = _get_cached_node(**n)
            self.assertTrue(self.driver._node_resources_used(node))

        unused_node = _get_cached_node(
            instance_uuid=None,
            provision_state=ironic_states.AVAILABLE)
        self.assertFalse(self.driver._node_resources_used(unused_node))

    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    def test_get_available_nodes(self, mock_gi, mock_services):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        mock_gi.return_value = [instance.uuid]
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF,
             'expected': True},
            # a node /w instance on this compute daemon and power ON
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': self.instance_uuid,
             'power_state': ironic_states.POWER_ON,
             'expected': True},
            # a node /w instance on another compute daemon and power ON
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.POWER_ON,
             'expected': False},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.ERROR,
             'expected': True},
        ]
        nodes = [_get_cached_node(**n)
                 for n in node_dicts]
        self.mock_conn.nodes.return_value = iter(nodes)
        available_nodes = self.driver.get_available_nodes()
        mock_gi.assert_called_once_with(mock.ANY, CONF.host)
        expected_uuids = [n['uuid'] for n in node_dicts if n['expected']]
        self.assertEqual(sorted(expected_uuids), sorted(available_nodes))

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_no_rc(self, mock_nfc, mock_nr,
                                        mock_res_unavail, mock_res_used):
        """Ensure that when node.resource_class is missing, that we return the
        legacy VCPU, MEMORY_MB and DISK_GB resources for inventory.
        """
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 0,
            'memory_mb': 1024,
            'memory_mb_used': 0,
            'local_gb': 100,
            'local_gb_used': 0,
            'resource_class': None,
        }

        self.assertRaises(exception.NoResourceClass,
                          self.driver.update_provider_tree,
                          self.ptree, mock.sentinel.nodename)

        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        mock_res_unavail.assert_called_once_with(mock_nfc.return_value)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_with_rc(self, mock_nfc, mock_nr,
                                          mock_res_unavail, mock_res_used):
        """Ensure that when node.resource_class is present, that we return the
        legacy VCPU, MEMORY_MB and DISK_GB resources for inventory in addition
        to the custom resource class inventory record.
        """
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 0,
            'memory_mb': 1024,
            'memory_mb_used': 0,
            'local_gb': 100,
            'local_gb_used': 0,
            'resource_class': 'iron-nfv',
        }

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        expected = {
            'CUSTOM_IRON_NFV': {
                'total': 1,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        mock_res_unavail.assert_called_once_with(mock_nfc.return_value)
        result = self.ptree.data(mock.sentinel.nodename).inventory
        self.assertEqual(expected, result)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_only_rc(self, mock_nfc, mock_nr,
                                          mock_res_unavail, mock_res_used):
        """Ensure that when node.resource_class is present, that we return the
        legacy VCPU, MEMORY_MB and DISK_GB resources for inventory in addition
        to the custom resource class inventory record.
        """
        mock_nr.return_value = {
            'vcpus': 0,
            'vcpus_used': 0,
            'memory_mb': 0,
            'memory_mb_used': 0,
            'local_gb': 0,
            'local_gb_used': 0,
            'resource_class': 'iron-nfv',
        }

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        expected = {
            'CUSTOM_IRON_NFV': {
                'total': 1,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        mock_res_unavail.assert_called_once_with(mock_nfc.return_value)
        result = self.ptree.data(mock.sentinel.nodename).inventory
        self.assertEqual(expected, result)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=True)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_with_rc_occupied(self, mock_nfc, mock_nr,
                                                   mock_res_unavail,
                                                   mock_res_used):
        """Ensure that when a node is used, we report the inventory matching
        the consumed resources.
        """
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 24,
            'memory_mb': 1024,
            'memory_mb_used': 1024,
            'local_gb': 100,
            'local_gb_used': 100,
            'resource_class': 'iron-nfv',
        }

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        expected = {
            'CUSTOM_IRON_NFV': {
                'total': 1,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        self.assertFalse(mock_res_unavail.called)
        result = self.ptree.data(mock.sentinel.nodename).inventory
        self.assertEqual(expected, result)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=True)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_disabled_node(self, mock_nfc, mock_nr,
                                                mock_res_unavail,
                                                mock_res_used):
        """Ensure that when a node is disabled, that update_provider_tree()
        sets inventory with reserved amounts equal to the total amounts.
        """
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 0,
            'memory_mb': 1024,
            'memory_mb_used': 0,
            'local_gb': 100,
            'local_gb_used': 0,
            'resource_class': 'iron-nfv',
        }

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        expected = {
            'CUSTOM_IRON_NFV': {
                'total': 1,
                'reserved': 1,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            },
        }
        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_unavail.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        result = self.ptree.data(mock.sentinel.nodename).inventory
        self.assertEqual(expected, result)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=True)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_no_traits(self, mock_nfc, mock_nr,
                                            mock_res_unavail, mock_res_used):
        """Ensure that when the node has no traits, we set no traits."""
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 24,
            'memory_mb': 1024,
            'memory_mb_used': 1024,
            'local_gb': 100,
            'local_gb_used': 100,
            'resource_class': 'iron-nfv',
        }

        mock_nfc.return_value = _get_cached_node(uuid=mock.sentinel.nodename)

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        self.assertFalse(mock_res_unavail.called)
        result = self.ptree.data(mock.sentinel.nodename).traits
        self.assertEqual(set(), result)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_used', return_value=True)
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_node_resources_unavailable', return_value=False)
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_update_provider_tree_with_traits(self, mock_nfc, mock_nr,
                                              mock_res_unavail, mock_res_used):
        """Ensure that when the node has traits, we set the traits."""
        mock_nr.return_value = {
            'vcpus': 24,
            'vcpus_used': 24,
            'memory_mb': 1024,
            'memory_mb_used': 1024,
            'local_gb': 100,
            'local_gb_used': 100,
            'resource_class': 'iron-nfv',
        }

        traits = ['trait1', 'trait2']
        mock_nfc.return_value = _get_cached_node(
            uuid=mock.sentinel.nodename, traits=traits)

        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)

        mock_nfc.assert_called_once_with(mock.sentinel.nodename)
        mock_nr.assert_called_once_with(mock_nfc.return_value)
        mock_res_used.assert_called_once_with(mock_nfc.return_value)
        self.assertFalse(mock_res_unavail.called)
        result = self.ptree.data(mock.sentinel.nodename).traits
        self.assertEqual(set(traits), result)

        # A different set of traits - we should replace (for now).
        traits = ['trait1', 'trait7', 'trait42']
        mock_nfc.return_value = _get_cached_node(
            uuid=mock.sentinel.nodename, traits=traits)
        self.driver.update_provider_tree(self.ptree, mock.sentinel.nodename)
        result = self.ptree.data(mock.sentinel.nodename).traits
        self.assertEqual(set(traits), result)

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource(self, mock_nr, mock_services,
                                    mock_instances, mock_list):
        node = _get_cached_node()
        node_2 = _get_cached_node(id=uuidutils.generate_uuid())
        fake_resource = 'fake-resource'
        self.mock_conn.get_node.return_value = node
        # ensure cache gets populated without the node we want
        mock_list.return_value = [node_2]
        mock_nr.return_value = fake_resource

        result = self.driver.get_available_resource(node.id)
        self.assertEqual(fake_resource, result)
        mock_nr.assert_called_once_with(node)
        self.mock_conn.get_node.assert_called_once_with(
            node.id, fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource_with_cache(self, mock_nr, mock_services,
                                               mock_instances):
        node = _get_cached_node()
        fake_resource = 'fake-resource'
        self.mock_conn.nodes.return_value = iter([node])
        mock_nr.return_value = fake_resource

        # populate the cache
        self.driver.get_available_nodes(refresh=True)
        self.mock_conn.nodes.reset_mock()

        result = self.driver.get_available_resource(node.uuid)
        self.assertEqual(fake_resource, result)
        self.assertEqual(0, self.mock_conn.nodes.call_count)
        self.assertEqual(0, self.mock_conn.get_node.call_count)
        mock_nr.assert_called_once_with(node)

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_get_info(self, mock_svc_by_hv,
                      mock_uuids_by_host, mock_get_node_list):
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = _get_cached_node(
                instance_uuid=self.instance_uuid, properties=properties,
                power_state=power_state)

        self.mock_conn.nodes.return_value = iter([node])
        mock_svc_by_hv.return_value = []
        mock_get_node_list.return_value = []

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=self.instance_uuid)
        mock_uuids_by_host.return_value = [instance.uuid]
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.RUNNING),
                         result)
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info_cached(self, mock_gbiu, mock_svc_by_hv,
                             mock_uuids_by_host, mock_get_node_list):
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = _get_cached_node(
                instance_uuid=self.instance_uuid, properties=properties,
                power_state=power_state)

        mock_gbiu.return_value = node
        mock_svc_by_hv.return_value = []
        mock_get_node_list.return_value = [node]

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=self.instance_uuid)
        mock_uuids_by_host.return_value = [instance.uuid]
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.RUNNING),
                         result)
        mock_gbiu.assert_not_called()

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_get_info_not_found_in_cache(self, mock_svc_by_hv,
                                         mock_uuids_by_host,
                                         mock_get_node_list):
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = _get_cached_node(
                instance_uuid=self.instance_uuid, properties=properties,
                power_state=power_state)
        node2 = _get_cached_node()

        self.mock_conn.nodes.return_value = iter([node])
        mock_svc_by_hv.return_value = []
        mock_get_node_list.return_value = [node2]

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=self.instance_uuid)
        mock_uuids_by_host.return_value = [instance.uuid]
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.RUNNING),
                         result)
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_get_info_skip_cache(self, mock_svc_by_hv,
                                 mock_uuids_by_host, mock_get_node_list):
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = _get_cached_node(
                instance_uuid=self.instance_uuid, properties=properties,
                power_state=power_state)

        self.mock_conn.nodes.return_value = iter([node])
        mock_svc_by_hv.return_value = []
        mock_get_node_list.return_value = [node]

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=self.instance_uuid)
        mock_uuids_by_host.return_value = [instance.uuid]
        result = self.driver.get_info(instance, use_cache=False)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.RUNNING),
                         result)
        # verify we hit the ironic API for fresh data
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def test_get_info_http_not_found(self, mock_svc_by_hv,
                                     mock_uuids_by_host):
        self.mock_conn.get_node.side_effect = sdk_exc.ResourceNotFound
        mock_svc_by_hv.return_value = []
        self.mock_conn.nodes.return_value = iter([])

        instance = fake_instance.fake_instance_obj(
                                  self.ctx, uuid=uuidutils.generate_uuid())
        mock_uuids_by_host.return_value = [instance]
        mock_uuids_by_host.return_value = [instance.uuid]
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.NOSTATE),
                         result)
        self.mock_conn.nodes.assert_has_calls([mock.call(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)])

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_add_instance_info_to_node')
    def _test_spawn(self, mock_aiitn, mock_wait_active,
                    mock_avti, mock_node, mock_looping, mock_save):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        fake_flavor = objects.Flavor(ephemeral_gb=0)
        instance.flavor = fake_flavor

        self.mock_conn.get_node.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        image_meta = ironic_utils.get_test_image_meta()

        self.driver.spawn(self.ctx, instance, image_meta, [], None, {})

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_id)
        mock_aiitn.assert_called_once_with(node, instance,
                                         test.MatchType(objects.ImageMeta),
                                         fake_flavor, block_device_info=None)
        mock_avti.assert_called_once_with(self.ctx, instance, None)
        mock_node.set_provision_state.assert_called_once_with(
            node_id, 'active', configdrive=mock.ANY)

        self.assertIsNone(instance.default_ephemeral_device)
        self.assertFalse(mock_save.called)

        mock_looping.assert_called_once_with(mock_wait_active,
                                             instance)
        fake_looping_call.start.assert_called_once_with(
            interval=CONF.ironic.api_retry_interval)
        fake_looping_call.wait.assert_called_once_with()

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    def test_spawn(self, mock_required_by, mock_configdrive):
        mock_required_by.return_value = False
        self._test_spawn()
        # assert configdrive was not generated
        self.assertFalse(mock_configdrive.called)

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    def test_spawn_with_configdrive(self, mock_required_by, mock_configdrive):
        mock_required_by.return_value = True
        self._test_spawn()
        # assert configdrive was generated
        mock_configdrive.assert_called_once_with(mock.ANY, mock.ANY, mock.ANY,
                                                 mock.ANY, extra_md={},
                                                 files=[])

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_add_instance_info_to_node')
    def test_spawn_destroyed_after_failure(self, mock_aiitn,
                                           mock_wait_active, mock_avti,
                                           mock_destroy, mock_node,
                                           mock_looping, mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', uuid=node_uuid)
        fake_flavor = objects.Flavor(ephemeral_gb=0)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = fake_flavor

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        deploy_exc = exception.InstanceDeployFailure('foo')
        fake_looping_call.wait.side_effect = deploy_exc
        self.assertRaises(
            exception.InstanceDeployFailure,
            self.driver.spawn, self.ctx, instance, None, [], None, {})
        self.assertEqual(0, mock_destroy.call_count)

    def _test_add_instance_info_to_node(self, mock_update=None,
                                        mock_call=None):
        node = _get_cached_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        image_meta = ironic_utils.get_test_image_meta()
        flavor = ironic_utils.get_test_flavor()
        instance.flavor = flavor
        self.driver._add_instance_info_to_node(node, instance, image_meta,
                                               flavor)
        expected_patch = [{'path': '/instance_info/image_source', 'op': 'add',
                           'value': image_meta.id},
                          {'path': '/instance_info/root_gb', 'op': 'add',
                           'value': str(instance.flavor.root_gb)},
                          {'path': '/instance_info/swap_mb', 'op': 'add',
                           'value': str(flavor['swap'])},
                          {'path': '/instance_info/display_name',
                           'value': instance.display_name, 'op': 'add'},
                          {'path': '/instance_info/vcpus', 'op': 'add',
                           'value': str(instance.flavor.vcpus)},
                          {'path': '/instance_info/nova_host_id', 'op': 'add',
                           'value': instance.host},
                          {'path': '/instance_info/memory_mb', 'op': 'add',
                           'value': str(instance.flavor.memory_mb)},
                          {'path': '/instance_info/local_gb', 'op': 'add',
                           'value': str(node.properties.get('local_gb', 0))}]

        if mock_call is not None:
            # assert call() is invoked with retry_on_conflict False to
            # avoid bug #1341420
            mock_call.assert_called_once_with('node.update', node.uuid,
                                              expected_patch,
                                              retry_on_conflict=False)
        if mock_update is not None:
            mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_instance_info_to_node_mock_update(self, mock_update):
        self._test_add_instance_info_to_node(mock_update=mock_update)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test__add_instance_info_to_node_mock_call(self, mock_call):
        self._test_add_instance_info_to_node(mock_call=mock_call)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_instance_info_to_node_fail(self, mock_update):
        mock_update.side_effect = ironic_exception.BadRequest()
        node = _get_cached_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        image_meta = ironic_utils.get_test_image_meta()
        flavor = ironic_utils.get_test_flavor()
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver._add_instance_info_to_node,
                          node, instance, image_meta, flavor)

    def _test_remove_instance_info_from_node(self, mock_update):
        node = _get_cached_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._remove_instance_info_from_node(node, instance)
        expected_patch = [{'path': '/instance_info', 'op': 'remove'},
                          {'path': '/instance_uuid', 'op': 'remove'}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test_remove_instance_info_from_node(self, mock_update):
        self._test_remove_instance_info_from_node(mock_update)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test_remove_instance_info_from_node_fail(self, mock_update):
        mock_update.side_effect = ironic_exception.BadRequest()
        self._test_remove_instance_info_from_node(mock_update)

    def _create_fake_block_device_info(self):
        bdm_dict = block_device.BlockDeviceDict({
            'id': 1, 'instance_uuid': uuids.instance,
            'device_name': '/dev/sda',
            'source_type': 'volume',
            'volume_id': 'fake-volume-id-1',
            'connection_info':
            '{"data":"fake_data",\
              "driver_volume_type":"fake_type"}',
            'boot_index': 0,
            'destination_type': 'volume'
        })
        driver_bdm = driver_block_device.DriverVolumeBlockDevice(
            fake_block_device.fake_bdm_object(self.ctx, bdm_dict))
        return {
            'block_device_mapping': [driver_bdm]
        }

    @mock.patch.object(FAKE_CLIENT.volume_target, 'create')
    def test__add_volume_target_info(self, mock_create):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        block_device_info = self._create_fake_block_device_info()
        self.driver._add_volume_target_info(self.ctx, instance,
                                            block_device_info)

        expected_volume_type = 'fake_type'
        expected_properties = 'fake_data'
        expected_boot_index = 0

        mock_create.assert_called_once_with(node_uuid=instance.node,
                                            volume_type=expected_volume_type,
                                            properties=expected_properties,
                                            boot_index=expected_boot_index,
                                            volume_id='fake-volume-id-1')

    @mock.patch.object(FAKE_CLIENT.volume_target, 'create')
    def test__add_volume_target_info_empty_bdms(self, mock_create):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        self.driver._add_volume_target_info(self.ctx, instance, None)

        self.assertFalse(mock_create.called)

    @mock.patch.object(FAKE_CLIENT.volume_target, 'create')
    def test__add_volume_target_info_failures(self, mock_create):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        block_device_info = self._create_fake_block_device_info()

        exceptions = [
            ironic_exception.BadRequest(),
            ironic_exception.Conflict(),
        ]
        for e in exceptions:
            mock_create.side_effect = e
            self.assertRaises(exception.InstanceDeployFailure,
                              self.driver._add_volume_target_info,
                              self.ctx, instance, block_device_info)

    @mock.patch.object(FAKE_CLIENT.volume_target, 'delete')
    @mock.patch.object(FAKE_CLIENT.node, 'list_volume_targets')
    def test__cleanup_volume_target_info(self, mock_lvt, mock_delete):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_lvt.return_value = [ironic_utils.get_test_volume_target(
            uuid='fake_uuid')]

        self.driver._cleanup_volume_target_info(instance)
        expected_volume_target_id = 'fake_uuid'

        mock_delete.assert_called_once_with(expected_volume_target_id)

    @mock.patch.object(FAKE_CLIENT.volume_target, 'delete')
    @mock.patch.object(FAKE_CLIENT.node, 'list_volume_targets')
    def test__cleanup_volume_target_info_empty_targets(self, mock_lvt,
                                                       mock_delete):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_lvt.return_value = []

        self.driver._cleanup_volume_target_info(instance)

        self.assertFalse(mock_delete.called)

    @mock.patch.object(FAKE_CLIENT.volume_target, 'delete')
    @mock.patch.object(FAKE_CLIENT.node, 'list_volume_targets')
    def test__cleanup_volume_target_info_not_found(self, mock_lvt,
                                                   mock_delete):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_lvt.return_value = [
            ironic_utils.get_test_volume_target(uuid='fake_uuid1'),
            ironic_utils.get_test_volume_target(uuid='fake_uuid2'),
        ]
        mock_delete.side_effect = [ironic_exception.NotFound('not found'),
                                   None]

        self.driver._cleanup_volume_target_info(instance)

        self.assertEqual([mock.call('fake_uuid1'), mock.call('fake_uuid2')],
                         mock_delete.call_args_list)

    @mock.patch.object(FAKE_CLIENT.volume_target, 'delete')
    @mock.patch.object(FAKE_CLIENT.node, 'list_volume_targets')
    def test__cleanup_volume_target_info_bad_request(self, mock_lvt,
                                                     mock_delete):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_lvt.return_value = [
            ironic_utils.get_test_volume_target(uuid='fake_uuid1'),
            ironic_utils.get_test_volume_target(uuid='fake_uuid2'),
        ]
        mock_delete.side_effect = [ironic_exception.BadRequest('error'),
                                   None]

        self.driver._cleanup_volume_target_info(instance)

        self.assertEqual([mock.call('fake_uuid1'), mock.call('fake_uuid2')],
                         mock_delete.call_args_list)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    def test_spawn_node_driver_validation_fail(self, mock_avti, mock_node,
                                               mock_required_by):
        mock_required_by.return_value = False
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        instance.flavor = flavor

        mock_node.validate.return_value = ironic_utils.get_test_validation(
            power={'result': False}, deploy={'result': False},
            storage={'result': False})
        self.mock_conn.get_node.return_value = node
        image_meta = ironic_utils.get_test_image_meta()

        self.assertRaises(exception.ValidationError, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None, {})
        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_avti.assert_called_once_with(self.ctx, instance, None)
        mock_node.validate.assert_called_once_with(node_id)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    def test_spawn_node_configdrive_fail(self,
                                         mock_configdrive,
                                         mock_avti, mock_node, mock_save,
                                         mock_required_by):
        mock_required_by.return_value = True
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        instance.flavor = flavor
        self.mock_conn.get_node.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        image_meta = ironic_utils.get_test_image_meta()

        mock_configdrive.side_effect = test.TestingException()
        with mock.patch.object(self.driver, '_cleanup_deploy',
                               autospec=True) as mock_cleanup_deploy:
            self.assertRaises(test.TestingException, self.driver.spawn,
                              self.ctx, instance, image_meta, [], None, {})

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_id)
        mock_cleanup_deploy.assert_called_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail(self, mock_cleanup_deploy,
                                            mock_avti,
                                            mock_node, mock_required_by):
        mock_required_by.return_value = False
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        self.mock_conn.get_node.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        mock_node.set_provision_state.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None, {})

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_id)
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail2(self, mock_cleanup_deploy,
                                             mock_avti,
                                             mock_node, mock_required_by):
        mock_required_by.return_value = False
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        self.mock_conn.get_node.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.set_provision_state.side_effect = ironic_exception.BadRequest
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.spawn,
                          self.ctx, instance, image_meta, [], None, {})

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_id)
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    def test_spawn_node_trigger_deploy_fail3(self, mock_destroy,
                                             mock_avti,
                                             mock_node, mock_looping,
                                             mock_required_by):
        mock_required_by.return_value = False
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', id=node_id)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        self.mock_conn.get_node.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        fake_looping_call.wait.side_effect = ironic_exception.BadRequest
        fake_net_info = utils.get_test_network_info()
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.spawn, self.ctx, instance,
                          image_meta, [], None, {}, fake_net_info)
        self.assertEqual(0, mock_destroy.call_count)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_volume_target_info')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    def test_spawn_sets_default_ephemeral_device(self,
                                                 mock_wait, mock_avti,
                                                 mock_node, mock_save,
                                                 mock_looping,
                                                 mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor(ephemeral_gb=1)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        image_meta = ironic_utils.get_test_image_meta()

        self.driver.spawn(self.ctx, instance, image_meta, [], None, {})
        self.assertTrue(mock_save.called)
        self.assertEqual('/dev/sda1', instance.default_ephemeral_device)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_remove_instance_info_from_node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def _test_destroy(self, state, mock_cleanup_deploy,
                      mock_remove_instance_info, mock_node):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = _get_cached_node(
                driver='fake', uuid=node_id, provision_state=state)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)

        def fake_set_provision_state(*_):
            node.provision_state = None

        self.mock_conn.nodes.return_value = iter([node])
        mock_node.set_provision_state.side_effect = fake_set_provision_state
        self.driver.destroy(self.ctx, instance, network_info, None)

        self.mock_conn.nodes.assert_called_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)
        mock_cleanup_deploy.assert_called_with(node, instance, network_info,
                                               remove_instance_info=False)

        # For states that makes sense check if set_provision_state has
        # been called
        if state in ironic_driver._UNPROVISION_STATES:
            mock_node.set_provision_state.assert_called_once_with(
                node_id, 'deleted')
            self.assertFalse(mock_remove_instance_info.called)
        else:
            self.assertFalse(mock_node.set_provision_state.called)
            mock_remove_instance_info.assert_called_once_with(node, instance)

    def test_destroy(self):
        for state in ironic_states.PROVISION_STATE_LIST:
            self._test_destroy(state)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_cleanup_deploy')
    def test_destroy_trigger_undeploy_fail(self, mock_clean, fake_validate,
                                           mock_sps):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(
                driver='fake', uuid=node_uuid,
                provision_state=ironic_states.ACTIVE)
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        mock_sps.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_clean.assert_called_once_with(node, instance, None,
                                           remove_instance_info=False)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_cleanup_deploy')
    def test_destroy_trigger_remove_info_fail(self, mock_clean, fake_validate,
                                              mock_update):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(
            driver='fake', uuid=node_uuid,
            provision_state=ironic_states.AVAILABLE)
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        mock_update.side_effect = SystemError('unexpected error')
        self.assertRaises(SystemError, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_clean.assert_called_once_with(node, instance, None,
                                           remove_instance_info=False)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def _test__unprovision_instance(self, mock_validate_inst, mock_set_pstate,
                                    state=None):
        node = _get_cached_node(driver='fake', provision_state=state)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_validate_inst.return_value = node
        with mock.patch.object(self.driver, 'node_cache') as cache_mock:
            self.driver._unprovision(instance, node)
        mock_validate_inst.assert_called_once_with(instance)
        mock_set_pstate.assert_called_once_with(node.uuid, "deleted")
        cache_mock.pop.assert_called_once_with(node.uuid, None)

    def test__unprovision_cleaning(self):
        self._test__unprovision_instance(state=ironic_states.CLEANING)

    def test__unprovision_cleanwait(self):
        self._test__unprovision_instance(state=ironic_states.CLEANWAIT)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__unprovision_fail_max_retries(self, mock_validate_inst,
                                           mock_set_pstate):
        CONF.set_default('api_max_retries', default=2, group='ironic')
        node = _get_cached_node(
            driver='fake', provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        mock_validate_inst.return_value = node
        self.assertRaises(exception.NovaException, self.driver._unprovision,
                          instance, node)
        expected_calls = (mock.call(instance),
                          mock.call(instance))
        mock_validate_inst.assert_has_calls(expected_calls)
        mock_set_pstate.assert_called_once_with(node.uuid, "deleted")

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__unprovision_instance_not_found(self, mock_validate_inst,
                                             mock_set_pstate):
        node = _get_cached_node(
            driver='fake', provision_state=ironic_states.DELETING)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        mock_validate_inst.side_effect = exception.InstanceNotFound(
            instance_id='fake')
        self.driver._unprovision(instance, node)
        mock_validate_inst.assert_called_once_with(instance)
        mock_set_pstate.assert_called_once_with(node.uuid, "deleted")

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_destroy_unassociate_fail(self, mock_node):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(
                driver='fake', id=node_id,
                provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        self.mock_conn.nodes.return_value = iter([node])
        mock_node.set_provision_state.side_effect = exception.NovaException()

        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)

        mock_node.set_provision_state.assert_called_once_with(node_id,
                                                              'deleted')
        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_reboot(self, mock_sp, fake_validate, mock_looping):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.reboot(self.ctx, instance, None, 'HARD')
        mock_sp.assert_called_once_with(node.uuid, 'reboot')

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'inject_nmi')
    def test_trigger_crash_dump(self, mock_nmi, fake_validate):
        node = _get_cached_node()
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.trigger_crash_dump(instance)
        mock_nmi.assert_called_once_with(node.uuid)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'inject_nmi')
    def test_trigger_crash_dump_error(self, mock_nmi, fake_validate):
        node = _get_cached_node()
        fake_validate.return_value = node
        mock_nmi.side_effect = ironic_exception.BadRequest()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.trigger_crash_dump, instance)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_reboot_soft(self, mock_sp, fake_validate, mock_looping):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.reboot(self.ctx, instance, None, 'SOFT')
        mock_sp.assert_called_once_with(node.uuid, 'reboot', soft=True)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_reboot_soft_not_supported(self, mock_sp, fake_validate,
                                       mock_looping):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]
        mock_sp.side_effect = [ironic_exception.BadRequest(), None]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.reboot(self.ctx, instance, None, 'SOFT')
        mock_sp.assert_has_calls([mock.call(node.uuid, 'reboot', soft=True),
                                  mock.call(node.uuid, 'reboot')])

    @mock.patch.object(objects.Instance, 'save')
    def test_power_update_event(self, mock_save):
        instance = fake_instance.fake_instance_obj(
            self.ctx, node=self.instance_uuid,
            power_state=nova_states.RUNNING,
            vm_state=vm_states.ACTIVE,
            task_state=task_states.POWERING_OFF)
        self.driver.power_update_event(instance, common.POWER_OFF)
        self.assertEqual(nova_states.SHUTDOWN, instance.power_state)
        self.assertEqual(vm_states.STOPPED, instance.vm_state)
        self.assertIsNone(instance.task_state)
        mock_save.assert_called_once_with(
            expected_task_state=task_states.POWERING_OFF)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_on(self, mock_sp, fake_validate, mock_looping):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=self.instance_uuid)
        self.driver.power_on(self.ctx, instance,
                             utils.get_test_network_info())
        mock_sp.assert_called_once_with(node.uuid, 'on')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    def _test_power_off(self, mock_looping, timeout=0):
        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=self.instance_uuid)
        self.driver.power_off(instance, timeout)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off(self, mock_sp, fake_validate):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]

        self._test_power_off()
        mock_sp.assert_called_once_with(node.uuid, 'off')

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off_soft(self, mock_sp, fake_validate):
        node = _get_cached_node()
        power_off_node = _get_cached_node(power_state=ironic_states.POWER_OFF)
        fake_validate.side_effect = [node, power_off_node]

        self._test_power_off(timeout=30)
        mock_sp.assert_called_once_with(node.uuid, 'off', soft=True,
                                        timeout=30)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off_soft_exception(self, mock_sp, fake_validate):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]
        mock_sp.side_effect = [ironic_exception.BadRequest(), None]

        self._test_power_off(timeout=30)
        expected_calls = [mock.call(node.uuid, 'off', soft=True, timeout=30),
                          mock.call(node.uuid, 'off')]
        self.assertEqual(len(expected_calls), mock_sp.call_count)
        mock_sp.assert_has_calls(expected_calls)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off_soft_not_stopped(self, mock_sp, fake_validate):
        node = _get_cached_node()
        fake_validate.side_effect = [node, node]

        self._test_power_off(timeout=30)
        expected_calls = [mock.call(node.uuid, 'off', soft=True, timeout=30),
                          mock.call(node.uuid, 'off')]
        self.assertEqual(len(expected_calls), mock_sp.call_count)
        mock_sp.assert_has_calls(expected_calls)

    @mock.patch.object(FAKE_CLIENT.node, 'vif_attach')
    def test_plug_vifs_with_port(self, mock_vatt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()
        vif_id = six.text_type(network_info[0]['id'])

        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_vatt.assert_called_with(node.uuid, vif_id)

    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    def test_plug_vifs(self, mock__plug_vifs):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(id=node_id)

        self.mock_conn.get_node.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_id)
        network_info = utils.get_test_network_info()
        self.driver.plug_vifs(instance, network_info)

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock__plug_vifs.assert_called_once_with(node, instance, network_info)

    @mock.patch.object(FAKE_CLIENT.node, 'vif_attach')
    def test_plug_vifs_multiple_ports(self, mock_vatt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        first_vif_id = 'aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee'
        second_vif_id = 'aaaaaaaa-vv22-cccc-dddd-eeeeeeeeeeee'
        first_vif = ironic_utils.get_test_vif(address='22:FF:FF:FF:FF:FF',
                                              id=first_vif_id)
        second_vif = ironic_utils.get_test_vif(address='11:FF:FF:FF:FF:FF',
                                               id=second_vif_id)
        network_info = [first_vif, second_vif]
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        calls = (mock.call(node.uuid, first_vif_id),
                 mock.call(node.uuid, second_vif_id))
        mock_vatt.assert_has_calls(calls, any_order=True)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_plug_vifs_failure(self, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        first_vif_id = 'aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee'
        second_vif_id = 'aaaaaaaa-vv22-cccc-dddd-eeeeeeeeeeee'
        first_vif = ironic_utils.get_test_vif(address='22:FF:FF:FF:FF:FF',
                                              id=first_vif_id)
        second_vif = ironic_utils.get_test_vif(address='11:FF:FF:FF:FF:FF',
                                               id=second_vif_id)
        mock_node.vif_attach.side_effect = [None,
                                            ironic_exception.BadRequest()]
        network_info = [first_vif, second_vif]
        self.assertRaises(exception.VirtualInterfacePlugException,
                          self.driver._plug_vifs, node, instance,
                          network_info)

    @mock.patch('time.sleep')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_plug_vifs_failure_no_conductor(self, mock_node, mock_sleep):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        first_vif_id = 'aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee'
        second_vif_id = 'aaaaaaaa-vv22-cccc-dddd-eeeeeeeeeeee'
        first_vif = ironic_utils.get_test_vif(address='22:FF:FF:FF:FF:FF',
                                              id=first_vif_id)
        second_vif = ironic_utils.get_test_vif(address='11:FF:FF:FF:FF:FF',
                                               id=second_vif_id)
        msg = 'No conductor service registered which supports driver ipmi.'
        mock_node.vif_attach.side_effect = [None,
                                            ironic_exception.BadRequest(msg),
                                            None]
        network_info = [first_vif, second_vif]
        self.driver._plug_vifs(node, instance, network_info)
        calls = [mock.call(node.uuid, first_vif_id),
                 mock.call(node.uuid, second_vif_id),
                 mock.call(node.uuid, second_vif_id)]
        mock_node.vif_attach.assert_has_calls(calls, any_order=True)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_plug_vifs_already_attached(self, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        first_vif_id = 'aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee'
        second_vif_id = 'aaaaaaaa-vv22-cccc-dddd-eeeeeeeeeeee'
        first_vif = ironic_utils.get_test_vif(address='22:FF:FF:FF:FF:FF',
                                              id=first_vif_id)
        second_vif = ironic_utils.get_test_vif(address='11:FF:FF:FF:FF:FF',
                                               id=second_vif_id)
        mock_node.vif_attach.side_effect = [ironic_exception.Conflict(),
                                            None]
        network_info = [first_vif, second_vif]
        self.driver._plug_vifs(node, instance, network_info)
        self.assertEqual(2, mock_node.vif_attach.call_count)

    @mock.patch.object(FAKE_CLIENT.node, 'vif_attach')
    def test_plug_vifs_no_network_info(self, mock_vatt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(uuid=node_uuid)

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = []
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        self.assertFalse(mock_vatt.called)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_unplug_vifs(self, mock_node):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(id=node_id)
        self.mock_conn.get_node.return_value = node

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_id)
        network_info = utils.get_test_network_info()
        vif_id = six.text_type(network_info[0]['id'])
        self.driver.unplug_vifs(instance, network_info)

        # asserts
        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        mock_node.vif_detach.assert_called_once_with(node.id, vif_id)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_unplug_vifs_port_not_associated(self, mock_node):
        node_id = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = _get_cached_node(id=node_id)

        self.mock_conn.get_node.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_id)
        network_info = utils.get_test_network_info()
        self.driver.unplug_vifs(instance, network_info)

        self.mock_conn.get_node.assert_called_once_with(
            node_id, fields=ironic_driver._NODE_FIELDS)
        self.assertEqual(len(network_info), mock_node.vif_detach.call_count)

    @mock.patch.object(FAKE_CLIENT.node, 'vif_detach')
    def test_unplug_vifs_no_network_info(self, mock_vdet):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = []
        self.driver.unplug_vifs(instance, network_info)
        self.assertFalse(mock_vdet.called)

    @mock.patch.object(ironic_driver.IronicDriver, 'plug_vifs')
    def test_attach_interface(self, mock_pv):
        self.driver.attach_interface('fake_context', 'fake_instance',
                                     'fake_image_meta', 'fake_vif')
        mock_pv.assert_called_once_with('fake_instance', ['fake_vif'])

    @mock.patch.object(ironic_driver.IronicDriver, 'unplug_vifs')
    def test_detach_interface(self, mock_uv):
        self.driver.detach_interface('fake_context', 'fake_instance',
                                     'fake_vif')
        mock_uv.assert_called_once_with('fake_instance', ['fake_vif'])

    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_add_instance_info_to_node')
    @mock.patch.object(objects.Instance, 'save')
    def _test_rebuild(self, mock_save, mock_add_instance_info, mock_set_pstate,
                      mock_looping, mock_wait_active, preserve=False):
        node_id = uuidutils.generate_uuid()
        node = _get_cached_node(id=node_id, instance_id=self.instance_id,
                                instance_type_id=5)
        self.mock_conn.get_node.return_value = node

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = objects.Flavor(flavor_id=flavor_id, name='baremetal')

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_id,
                                                   instance_type_id=flavor_id)
        instance.flavor = flavor

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        self.driver.rebuild(
            context=self.ctx, instance=instance, image_meta=image_meta,
            injected_files=None, admin_password=None, allocations={},
            bdms=None, detach_block_devices=None, attach_block_devices=None,
            preserve_ephemeral=preserve)

        mock_save.assert_called_once_with(
            expected_task_state=[task_states.REBUILDING])
        mock_add_instance_info.assert_called_once_with(
            node, instance,
            test.MatchType(objects.ImageMeta),
            flavor, preserve)
        mock_set_pstate.assert_called_once_with(node_id,
                                                ironic_states.REBUILD,
                                                configdrive=mock.ANY)
        mock_looping.assert_called_once_with(mock_wait_active, instance)
        fake_looping_call.start.assert_called_once_with(
            interval=CONF.ironic.api_retry_interval)
        fake_looping_call.wait.assert_called_once_with()

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    def test_rebuild_preserve_ephemeral(self, mock_required_by,
                                        mock_configdrive):
        mock_required_by.return_value = False
        self._test_rebuild(preserve=True)
        # assert configdrive was not generated
        mock_configdrive.assert_not_called()

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    def test_rebuild_no_preserve_ephemeral(self, mock_required_by,
                                           mock_configdrive):
        mock_required_by.return_value = False
        self._test_rebuild(preserve=False)

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    def test_rebuild_with_configdrive(self, mock_required_by,
                                      mock_configdrive):
        mock_required_by.return_value = True
        self._test_rebuild()
        # assert configdrive was generated
        mock_configdrive.assert_called_once_with(
            self.ctx, mock.ANY, mock.ANY, mock.ANY, extra_md={}, files=None)

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_add_instance_info_to_node')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def test_rebuild_with_configdrive_failure(self, mock_save, mock_get,
                                              mock_add_instance_info,
                                              mock_required_by,
                                              mock_configdrive):
        node_uuid = uuidutils.generate_uuid()
        node = _get_cached_node(
                uuid=node_uuid, instance_uuid=self.instance_uuid,
                instance_type_id=5)
        mock_get.return_value = node
        mock_required_by.return_value = True
        mock_configdrive.side_effect = exception.NovaException()

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = objects.Flavor(flavor_id=flavor_id, name='baremetal')

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_uuid,
                                                   instance_type_id=flavor_id)
        instance.flavor = flavor

        self.assertRaises(exception.InstanceDeployFailure,
            self.driver.rebuild,
            context=self.ctx, instance=instance, image_meta=image_meta,
            injected_files=None, admin_password=None, allocations={},
            bdms=None, detach_block_devices=None,
            attach_block_devices=None)

    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_add_instance_info_to_node')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def test_rebuild_failures(self, mock_save, mock_get,
                              mock_add_instance_info, mock_set_pstate,
                              mock_required_by, mock_configdrive):
        node_uuid = uuidutils.generate_uuid()
        node = _get_cached_node(
                uuid=node_uuid, instance_uuid=self.instance_uuid,
                instance_type_id=5)
        mock_get.return_value = node
        mock_required_by.return_value = False

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = objects.Flavor(flavor_id=flavor_id, name='baremetal')

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_uuid,
                                                   instance_type_id=flavor_id)
        instance.flavor = flavor

        exceptions = [
            exception.NovaException(),
            ironic_exception.BadRequest(),
            ironic_exception.InternalServerError(),
        ]
        for e in exceptions:
            mock_set_pstate.side_effect = e
            self.assertRaises(exception.InstanceDeployFailure,
                self.driver.rebuild,
                context=self.ctx, instance=instance, image_meta=image_meta,
                injected_files=None, admin_password=None, allocations={},
                bdms=None, detach_block_devices=None,
                attach_block_devices=None)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_network_binding_host_id(self, mock_get):
        node_uuid = uuidutils.generate_uuid()
        hostname = 'ironic-compute'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid,
                                                   host=hostname)
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5,
                                          network_interface='flat')
        mock_get.return_value = node
        host_id = self.driver.network_binding_host_id(self.ctx, instance)
        self.assertIsNone(host_id)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_get_volume_connector(self, mock_node):
        node_uuid = uuids.node_uuid
        node_props = {'cpu_arch': 'x86_64'}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          properties=node_props)
        connectors = [ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='iqn',
                          connector_id='iqn.test'),
                      ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='ip',
                          connector_id='1.2.3.4'),
                      ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='wwnn',
                          connector_id='200010601'),
                      ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='wwpn',
                          connector_id='200010605'),
                      ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='wwpn',
                          connector_id='200010606')]

        expected_props = {'initiator': 'iqn.test',
                          'ip': '1.2.3.4',
                          'host': '1.2.3.4',
                          'multipath': False,
                          'wwnns': ['200010601'],
                          'wwpns': ['200010605', '200010606'],
                          'os_type': 'baremetal',
                          'platform': 'x86_64'}

        mock_node.get.return_value = node
        mock_node.list_volume_connectors.return_value = connectors
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        props = self.driver.get_volume_connector(instance)

        self.assertEqual(expected_props, props)
        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.list_volume_connectors.assert_called_once_with(
            node_uuid, detail=True)

    @mock.patch.object(objects.instance.Instance, 'get_network_info')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(FAKE_CLIENT.port, 'list')
    @mock.patch.object(FAKE_CLIENT.portgroup, 'list')
    def _test_get_volume_connector_no_ip(
            self, mac_specified, mock_pgroup, mock_port, mock_node,
            mock_nw_info, portgroup_exist=False, no_fixed_ip=False):
        node_uuid = uuids.node_uuid
        node_props = {'cpu_arch': 'x86_64'}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          properties=node_props)
        connectors = [ironic_utils.get_test_volume_connector(
                          node_uuid=node_uuid, type='iqn',
                          connector_id='iqn.test')]
        if mac_specified:
            connectors.append(ironic_utils.get_test_volume_connector(
                node_uuid=node_uuid, type='mac',
                connector_id='11:22:33:44:55:66'))
        fixed_ip = network_model.FixedIP(address='1.2.3.4', version=4)
        subnet = network_model.Subnet(ips=[fixed_ip])
        network = network_model.Network(subnets=[subnet])
        vif = network_model.VIF(
            id='aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee', network=network)

        expected_props = {'initiator': 'iqn.test',
                          'ip': '1.2.3.4',
                          'host': '1.2.3.4',
                          'multipath': False,
                          'os_type': 'baremetal',
                          'platform': 'x86_64'}

        mock_node.get.return_value = node
        mock_node.list_volume_connectors.return_value = connectors
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        port = ironic_utils.get_test_port(
            node_uuid=node_uuid, address='11:22:33:44:55:66',
            internal_info={'tenant_vif_port_id': vif['id']})
        mock_port.return_value = [port]
        if no_fixed_ip:
            mock_nw_info.return_value = []
            expected_props.pop('ip')
            expected_props['host'] = instance.hostname
        else:
            mock_nw_info.return_value = [vif]
        if portgroup_exist:
            portgroup = ironic_utils.get_test_portgroup(
                node_uuid=node_uuid, address='11:22:33:44:55:66',
                extra={'vif_port_id': vif['id']})
            mock_pgroup.return_value = [portgroup]
        else:
            mock_pgroup.return_value = []
        props = self.driver.get_volume_connector(instance)

        self.assertEqual(expected_props, props)
        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.list_volume_connectors.assert_called_once_with(
            node_uuid, detail=True)
        if mac_specified:
            mock_pgroup.assert_called_once_with(
                node=node_uuid, address='11:22:33:44:55:66', detail=True)
            if not portgroup_exist:
                mock_port.assert_called_once_with(
                    node=node_uuid, address='11:22:33:44:55:66', detail=True)
            else:
                mock_port.assert_not_called()
        else:
            mock_pgroup.assert_not_called()
            mock_port.assert_not_called()

    def test_get_volume_connector_no_ip_with_mac(self):
        self._test_get_volume_connector_no_ip(True)

    def test_get_volume_connector_no_ip_with_mac_with_portgroup(self):
        self._test_get_volume_connector_no_ip(True, portgroup_exist=True)

    def test_get_volume_connector_no_ip_without_mac(self):
        self._test_get_volume_connector_no_ip(False)

    def test_get_volume_connector_no_ip_no_fixed_ip(self):
        self._test_get_volume_connector_no_ip(False, no_fixed_ip=True)

    @mock.patch.object(ironic_driver.IronicDriver, 'plug_vifs')
    def test_prepare_networks_before_block_device_mapping(self, mock_pvifs):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        self.driver.prepare_networks_before_block_device_mapping(instance,
                                                                 network_info)
        mock_pvifs.assert_called_once_with(instance, network_info)

    @mock.patch.object(ironic_driver.IronicDriver, 'plug_vifs')
    def test_prepare_networks_before_block_device_mapping_error(self,
                                                                mock_pvifs):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        mock_pvifs.side_effect = ironic_exception.BadRequest('fake error')
        self.assertRaises(
            ironic_exception.BadRequest,
            self.driver.prepare_networks_before_block_device_mapping,
            instance, network_info)
        mock_pvifs.assert_called_once_with(instance, network_info)

    @mock.patch.object(ironic_driver.IronicDriver, 'unplug_vifs')
    def test_clean_networks_preparation(self, mock_upvifs):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        self.driver.clean_networks_preparation(instance, network_info)
        mock_upvifs.assert_called_once_with(instance, network_info)

    @mock.patch.object(ironic_driver.IronicDriver, 'unplug_vifs')
    def test_clean_networks_preparation_error(self, mock_upvifs):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        mock_upvifs.side_effect = ironic_exception.BadRequest('fake error')
        self.driver.clean_networks_preparation(instance, network_info)
        mock_upvifs.assert_called_once_with(instance, network_info)

    @mock.patch.object(ironic_driver.LOG, 'error')
    def test_ironicclient_bad_response(self, mock_error):
        fake_nodes = [_get_cached_node(),
                      ironic_utils.get_test_node(driver='fake',
                                                 id=uuidutils.generate_uuid())]
        self.mock_conn.nodes.side_effect = [iter(fake_nodes), Exception()]

        result = self.driver._get_node_list()
        mock_error.assert_not_called()
        self.assertEqual(fake_nodes, result)

        self.assertRaises(exception.VirtDriverNotReady,
                          self.driver._get_node_list)
        mock_error.assert_called_once()

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_prepare_for_spawn(self, mock_call):
        node = ironic_utils.get_test_node(driver='fake')
        self.mock_conn.get_node.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.prepare_for_spawn(instance)
        self.mock_conn.get_node.assert_called_once_with(
            node.uuid,
            fields=('uuid', 'power_state', 'target_power_state',
                    'provision_state', 'target_provision_state', 'last_error',
                    'maintenance', 'properties', 'instance_uuid', 'traits',
                    'resource_class'))
        self.mock_conn.update_node.assert_called_once_with(
            node, retry_on_conflict=False, instance_id=instance.uuid)

    def test__set_instance_id(self):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.id)

        self.driver._set_instance_id(node, instance)

        self.mock_conn.update_node.assert_called_once_with(
            node, retry_on_conflict=False, instance_id=instance.uuid)

    def test_prepare_for_spawn_invalid_instance(self):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=None)
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.prepare_for_spawn,
                          instance)

    def test_prepare_for_spawn_conflict(self):
        node = ironic_utils.get_test_node(driver='fake')
        self.mock_conn.get_node.return_value = node
        self.mock_conn.update_node.side_effect = sdk_exc.ConflictException
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.id)
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver.prepare_for_spawn,
                          instance)

    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_failed_spawn_cleanup(self, mock_cleanup):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.mock_conn.nodes.return_value = iter([node])

        self.driver.failed_spawn_cleanup(instance)

        self.mock_conn.nodes.assert_called_once_with(
            instance_id=instance.uuid,
            fields=ironic_driver._NODE_FIELDS)
        self.assertEqual(1, mock_cleanup.call_count)

    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_cleanup_volume_target_info')
    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test__cleanup_deploy(self, mock_call, mock_vol, mock_unvif):
        # TODO(TheJulia): This REALLY should be updated to cover all of the
        # calls that take place.
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._cleanup_deploy(node, instance)
        mock_vol.assert_called_once_with(instance)
        mock_unvif.assert_called_once_with(node, instance, None)
        expected_patch = [{'path': '/instance_info', 'op': 'remove'},
                          {'path': '/instance_uuid', 'op': 'remove'}]
        mock_call.assert_called_once_with('node.update', node.uuid,
                                          expected_patch)

    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_cleanup_volume_target_info')
    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test__cleanup_deploy_no_remove_ii(self, mock_call, mock_vol,
                                          mock_unvif):
        # TODO(TheJulia): This REALLY should be updated to cover all of the
        # calls that take place.
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._cleanup_deploy(node, instance, remove_instance_info=False)
        mock_vol.assert_called_once_with(instance)
        mock_unvif.assert_called_once_with(node, instance, None)
        self.assertFalse(mock_call.called)


class IronicDriverSyncTestCase(IronicDriverTestCase):

    def setUp(self):
        super(IronicDriverSyncTestCase, self).setUp()
        self.driver.node_cache = {}
        # Since the code we're testing runs in a spawn_n green thread, ensure
        # that the thread completes.
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())

        self.mock_conn = self.useFixture(
            fixtures.MockPatchObject(self.driver, '_ironic_connection')).mock

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration(self, mock_save, mock_get_by_uuid,
            mock_get_uuids_by_host, mock_svc_by_hv, mock_get_node_list):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        mock_svc_by_hv.return_value = []
        self.driver.node_cache = {}
        mock_get_node_list.return_value = [node1, node2]

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.assertEqual({}, inst1.flavor.extra_specs)
        self.assertEqual({}, inst2.flavor.extra_specs)

        self.driver._refresh_cache()
        self.assertEqual(2, mock_save.call_count)
        expected_specs = {"resources:CUSTOM_FIRST": "1"}
        self.assertEqual(expected_specs, inst1.flavor.extra_specs)
        expected_specs = {"resources:CUSTOM_SECOND": "1"}
        self.assertEqual(expected_specs, inst2.flavor.extra_specs)

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration_instance_migrated(self, mock_save,
            mock_get_by_uuid, mock_get_uuids_by_host, mock_svc_by_hv,
            mock_get_node_list):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {"resources:CUSTOM_FIRST": "1"}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        self.driver.node_cache = {}
        mock_get_node_list.return_value = [node1, node2]
        mock_svc_by_hv.return_value = []

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.driver._refresh_cache()
        # Since one instance already had its extra_specs updated with the
        # custom resource_class, only the other one should be updated and
        # saved.
        self.assertEqual(1, mock_save.call_count)
        expected_specs = {"resources:CUSTOM_FIRST": "1"}
        self.assertEqual(expected_specs, inst1.flavor.extra_specs)
        expected_specs = {"resources:CUSTOM_SECOND": "1"}
        self.assertEqual(expected_specs, inst2.flavor.extra_specs)

    @mock.patch.object(ironic_driver.LOG, 'warning')
    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration_missing_rc(self, mock_save,
            mock_get_by_uuid, mock_get_uuids_by_host, mock_svc_by_hv,
            mock_get_node_list, mock_warning):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class=None,
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        mock_svc_by_hv.return_value = []
        self.driver.node_cache = {}
        mock_get_node_list.return_value = [node1, node2]

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.driver._refresh_cache()
        # Since one instance was on a node with no resource class set,
        # only the other one should be updated and saved.
        self.assertEqual(1, mock_save.call_count)
        expected_specs = {}
        self.assertEqual(expected_specs, inst1.flavor.extra_specs)
        expected_specs = {"resources:CUSTOM_SECOND": "1"}
        self.assertEqual(expected_specs, inst2.flavor.extra_specs)
        # Verify that the LOG.warning was called correctly
        self.assertEqual(1, mock_warning.call_count)
        self.assertIn("does not have its resource_class set.",
                mock_warning.call_args[0][0])
        self.assertEqual({"node": node1.uuid}, mock_warning.call_args[0][1])

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration_refresh_called_again(self, mock_save,
            mock_get_by_uuid, mock_get_uuids_by_host, mock_svc_by_hv,
            mock_get_node_list):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        mock_svc_by_hv.return_value = []
        self.driver.node_cache = {}
        mock_get_node_list.return_value = [node1, node2]

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.driver._refresh_cache()
        self.assertEqual(2, mock_get_by_uuid.call_count)
        # Refresh the cache again. The mock for getting an instance by uuid
        # should not be called again.
        mock_get_by_uuid.reset_mock()
        self.driver._refresh_cache()
        mock_get_by_uuid.assert_not_called()

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration_no_node_change(self, mock_save,
            mock_get_by_uuid, mock_get_uuids_by_host, mock_svc_by_hv,
            mock_get_node_list):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {"resources:CUSTOM_FIRST": "1"}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {"resources:CUSTOM_SECOND": "1"}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        self.driver.node_cache = {node1_uuid: node1, node2_uuid: node2}
        self.driver._migrated_instance_uuids = set([inst1.uuid, inst2.uuid])
        mock_get_node_list.return_value = [node1, node2]
        mock_svc_by_hv.return_value = []

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.driver._refresh_cache()
        # Since the nodes did not change in the call to _refresh_cache(), and
        # their instance_uuids were in the cache, none of the mocks in the
        # migration script should have been called.
        self.assertFalse(mock_get_by_uuid.called)
        self.assertFalse(mock_save.called)

    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    @mock.patch.object(objects.Instance, 'save')
    def test_pike_flavor_migration_just_instance_change(self, mock_save,
            mock_get_by_uuid, mock_get_uuids_by_host, mock_svc_by_hv,
            mock_get_node_list):
        node1_uuid = uuidutils.generate_uuid()
        node2_uuid = uuidutils.generate_uuid()
        node3_uuid = uuidutils.generate_uuid()
        hostname = "ironic-compute"
        fake_flavor1 = objects.Flavor()
        fake_flavor1.extra_specs = {}
        fake_flavor2 = objects.Flavor()
        fake_flavor2.extra_specs = {}
        fake_flavor3 = objects.Flavor()
        fake_flavor3.extra_specs = {}
        inst1 = fake_instance.fake_instance_obj(self.ctx,
                node=node1_uuid,
                host=hostname,
                flavor=fake_flavor1)
        inst2 = fake_instance.fake_instance_obj(self.ctx,
                node=node2_uuid,
                host=hostname,
                flavor=fake_flavor2)
        inst3 = fake_instance.fake_instance_obj(self.ctx,
                node=node3_uuid,
                host=hostname,
                flavor=fake_flavor3)
        node1 = _get_cached_node(
                uuid=node1_uuid,
                instance_uuid=inst1.uuid,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        node2 = _get_cached_node(
                uuid=node2_uuid,
                instance_uuid=inst2.uuid,
                instance_type_id=2,
                resource_class="second",
                network_interface="flat")
        inst_dict = {inst1.uuid: inst1, inst2.uuid: inst2, inst3.uuid: inst3}
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst2.uuid]
        self.driver.node_cache = {node1_uuid: node1, node2_uuid: node2}
        mock_get_node_list.return_value = [node1, node2]
        mock_svc_by_hv.return_value = []

        def fake_inst_by_uuid(ctx, uuid, expected_attrs=None):
            return inst_dict.get(uuid)

        mock_get_by_uuid.side_effect = fake_inst_by_uuid

        self.driver._refresh_cache()
        # Since this is a fresh driver, neither will be in the migration cache,
        # so the migration mocks should have been called.
        self.assertTrue(mock_get_by_uuid.called)
        self.assertTrue(mock_save.called)

        # Now call _refresh_cache() again.  Since neither the nodes nor their
        # instances change, none of the mocks in the migration script should
        # have been called.
        mock_get_by_uuid.reset_mock()
        mock_save.reset_mock()
        self.driver._refresh_cache()
        self.assertFalse(mock_get_by_uuid.called)
        self.assertFalse(mock_save.called)

        # Now change the node on node2 to inst3
        node2.instance_uuid = inst3.uuid
        mock_get_uuids_by_host.return_value = [inst1.uuid, inst3.uuid]
        # Call _refresh_cache() again. Since the instance on node2 changed, the
        # migration mocks should have been called.
        mock_get_by_uuid.reset_mock()
        mock_save.reset_mock()
        self.driver._refresh_cache()
        self.assertTrue(mock_get_by_uuid.called)
        self.assertTrue(mock_save.called)

    @mock.patch.object(nova_utils, 'normalize_rc_name')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_pike_flavor_migration_empty_node(self, mock_node_from_cache,
            mock_normalize):
        mock_node_from_cache.return_value = None
        self.driver._pike_flavor_migration([uuids.node])
        mock_normalize.assert_not_called()

    @mock.patch.object(nova_utils, 'normalize_rc_name')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_from_cache')
    def test_pike_flavor_migration_already_migrated(self, mock_node_from_cache,
            mock_normalize):
        node1 = _get_cached_node(
                uuid=uuids.node1,
                instance_uuid=uuids.instance,
                instance_type_id=1,
                resource_class="first",
                network_interface="flat")
        mock_node_from_cache.return_value = node1
        self.driver._migrated_instance_uuids = set([uuids.instance])
        self.driver._pike_flavor_migration([uuids.node1])
        mock_normalize.assert_not_called()

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_rescue(self, mock_sps, mock_looping):
        node = ironic_utils.get_test_node()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)

        self.driver.rescue(self.ctx, instance, None, None, 'xyz', None)
        mock_sps.assert_called_once_with(node.uuid, 'rescue',
                                         rescue_password='xyz')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_rescue_provision_state_fail(self, mock_sps, mock_looping):
        node = ironic_utils.get_test_node()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        mock_sps.side_effect = ironic_exception.BadRequest()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)

        self.assertRaises(exception.InstanceRescueFailure,
                          self.driver.rescue,
                          self.ctx, instance, None, None, 'xyz', None)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_rescue_instance_not_found(self, mock_sps, fake_validate):
        node = ironic_utils.get_test_node(driver='fake')

        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        fake_validate.side_effect = exception.InstanceNotFound(
            instance_id='fake')

        self.assertRaises(exception.InstanceRescueFailure,
                          self.driver.rescue,
                          self.ctx, instance, None, None, 'xyz', None)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_rescue_rescue_fail(self, mock_sps, fake_validate):
        node = ironic_utils.get_test_node(
                   provision_state=ironic_states.RESCUEFAIL,
                   last_error='rescue failed')

        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)

        self.assertRaises(exception.InstanceRescueFailure,
                          self.driver.rescue,
                          self.ctx, instance, None, None, 'xyz', None)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_unrescue(self, mock_sps, mock_looping):
        node = ironic_utils.get_test_node()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)

        self.driver.unrescue(self.ctx, instance)
        mock_sps.assert_called_once_with(node.uuid, 'unrescue')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_unrescue_provision_state_fail(self, mock_sps, mock_looping):
        node = ironic_utils.get_test_node()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        mock_sps.side_effect = ironic_exception.BadRequest()

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.assertRaises(exception.InstanceUnRescueFailure,
                          self.driver.unrescue, self.ctx, instance)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_unrescue_instance_not_found(self, mock_sps, fake_validate):
        node = ironic_utils.get_test_node(driver='fake')

        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        fake_validate.side_effect = exception.InstanceNotFound(
            instance_id='fake')

        self.assertRaises(exception.InstanceUnRescueFailure,
                          self.driver.unrescue, self.ctx, instance)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    def test_unrescue_unrescue_fail(self, mock_sps, fake_validate):
        node = ironic_utils.get_test_node(
                   provision_state=ironic_states.UNRESCUEFAIL,
                   last_error='unrescue failed')

        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)

        self.assertRaises(exception.InstanceUnRescueFailure,
                          self.driver.unrescue, self.ctx, instance)

    def test__can_send_version(self):
        self.assertIsNone(
            self.driver._can_send_version(
                min_version='%d.%d' % cw.IRONIC_API_VERSION))

    def test__can_send_version_too_new(self):
        self.assertRaises(exception.IronicAPIVersionNotAvailable,
                          self.driver._can_send_version,
                          min_version='%d.%d' % (cw.IRONIC_API_VERSION[0],
                                                 cw.IRONIC_API_VERSION[1] + 1))

    def test__can_send_version_too_old(self):
        self.assertRaises(
            exception.IronicAPIVersionNotAvailable,
            self.driver._can_send_version,
            max_version='%d.%d' % (cw.PRIOR_IRONIC_API_VERSION[0],
                                   cw.PRIOR_IRONIC_API_VERSION[1] - 1))

    @mock.patch.object(cw.IronicClientWrapper, 'current_api_version',
                       autospec=True)
    @mock.patch.object(cw.IronicClientWrapper, 'is_api_version_negotiated',
                       autospec=True)
    def test__can_send_version_not_negotiated(self, mock_is_negotiated,
                                              mock_api_version):
        mock_is_negotiated.return_value = False
        self.assertIsNone(self.driver._can_send_version())
        self.assertFalse(mock_api_version.called)


@mock.patch.object(instance_metadata, 'InstanceMetadata')
@mock.patch.object(configdrive, 'ConfigDriveBuilder')
class IronicDriverGenerateConfigDriveTestCase(test.NoDBTestCase):

    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(cw, 'IronicClientWrapper',
                       lambda *_: FAKE_CLIENT_WRAPPER)
    def setUp(self, mock_services):
        super(IronicDriverGenerateConfigDriveTestCase, self).setUp()
        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()
        node_id = uuidutils.generate_uuid()
        self.node = _get_cached_node(driver='fake', id=node_id)
        self.instance = fake_instance.fake_instance_obj(self.ctx,
                                                        node=node_id)
        self.network_info = utils.get_test_network_info()

        self.mock_conn = self.useFixture(
            fixtures.MockPatchObject(self.driver, '_ironic_connection')).mock

    def test_generate_configdrive(self, mock_cd_builder, mock_instance_meta):
        mock_instance_meta.return_value = 'fake-instance'
        mock_make_drive = mock.MagicMock(make_drive=lambda *_: None)
        mock_cd_builder.return_value.__enter__.return_value = mock_make_drive
        network_metadata_mock = mock.Mock()
        self.driver._get_network_metadata = network_metadata_mock
        self.driver._generate_configdrive(None, self.instance,
                                          self.node, self.network_info)
        mock_cd_builder.assert_called_once_with(instance_md='fake-instance')
        mock_instance_meta.assert_called_once_with(
            self.instance, content=None, extra_md={},
            network_info=self.network_info,
            network_metadata=network_metadata_mock.return_value,
            request_context=None)

    def test_generate_configdrive_fail(self, mock_cd_builder,
                                       mock_instance_meta):
        mock_cd_builder.side_effect = exception.ConfigDriveMountFailed(
            operation='foo', error='error')
        mock_instance_meta.return_value = 'fake-instance'
        mock_make_drive = mock.MagicMock(make_drive=lambda *_: None)
        mock_cd_builder.return_value.__enter__.return_value = mock_make_drive
        network_metadata_mock = mock.Mock()
        self.driver._get_network_metadata = network_metadata_mock

        self.assertRaises(exception.ConfigDriveMountFailed,
                          self.driver._generate_configdrive, None,
                          self.instance, self.node, self.network_info)

        mock_cd_builder.assert_called_once_with(instance_md='fake-instance')
        mock_instance_meta.assert_called_once_with(
            self.instance, content=None, extra_md={},
            network_info=self.network_info,
            network_metadata=network_metadata_mock.return_value,
            request_context=None)

    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_CLIENT.portgroup, 'list')
    def _test_generate_network_metadata(self, mock_portgroups, mock_ports,
                                        address=None, vif_internal_info=True):
        internal_info = ({'tenant_vif_port_id': utils.FAKE_VIF_UUID}
                         if vif_internal_info else {})
        extra = ({'vif_port_id': utils.FAKE_VIF_UUID}
                 if not vif_internal_info else {})
        portgroup = ironic_utils.get_test_portgroup(
            node_uuid=self.node.uuid, address=address,
            extra=extra, internal_info=internal_info,
            properties={'bond_miimon': 100, 'xmit_hash_policy': 'layer3+4'}
        )
        port1 = ironic_utils.get_test_port(uuid=uuidutils.generate_uuid(),
                                           node_uuid=self.node.uuid,
                                           address='00:00:00:00:00:01',
                                           portgroup_uuid=portgroup.uuid)
        port2 = ironic_utils.get_test_port(uuid=uuidutils.generate_uuid(),
                                           node_uuid=self.node.uuid,
                                           address='00:00:00:00:00:02',
                                           portgroup_uuid=portgroup.uuid)
        mock_ports.return_value = [port1, port2]
        mock_portgroups.return_value = [portgroup]

        metadata = self.driver._get_network_metadata(self.node,
                                                     self.network_info)

        pg_vif = metadata['links'][0]
        self.assertEqual('bond', pg_vif['type'])
        self.assertEqual('active-backup', pg_vif['bond_mode'])
        self.assertEqual(address if address else utils.FAKE_VIF_MAC,
                         pg_vif['ethernet_mac_address'])
        self.assertEqual('layer3+4',
                         pg_vif['bond_xmit_hash_policy'])
        self.assertEqual(100, pg_vif['bond_miimon'])
        self.assertEqual([port1.uuid, port2.uuid],
                         pg_vif['bond_links'])
        self.assertEqual([{'id': port1.uuid, 'type': 'phy',
                           'ethernet_mac_address': port1.address},
                          {'id': port2.uuid, 'type': 'phy',
                           'ethernet_mac_address': port2.address}],
                         metadata['links'][1:])
        # assert there are no duplicate links
        link_ids = [link['id'] for link in metadata['links']]
        self.assertEqual(len(set(link_ids)), len(link_ids),
                         'There are duplicate link IDs: %s' % link_ids)

    def test_generate_network_metadata_with_pg_address(self, mock_cd_builder,
                                       mock_instance_meta):
        self._test_generate_network_metadata(address='00:00:00:00:00:00')

    def test_generate_network_metadata_no_pg_address(self, mock_cd_builder,
                                                     mock_instance_meta):
        self._test_generate_network_metadata()

    def test_generate_network_metadata_vif_in_extra(self, mock_cd_builder,
                                                    mock_instance_meta):
        self._test_generate_network_metadata(vif_internal_info=False)

    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_CLIENT.portgroup, 'list')
    def test_generate_network_metadata_ports_only(self, mock_portgroups,
                                                  mock_ports, mock_cd_builder,
                                                  mock_instance_meta):
        address = self.network_info[0]['address']
        port = ironic_utils.get_test_port(
            node_uuid=self.node.uuid, address=address,
            internal_info={'tenant_vif_port_id': utils.FAKE_VIF_UUID})
        mock_ports.return_value = [port]
        mock_portgroups.return_value = []

        metadata = self.driver._get_network_metadata(self.node,
                                                     self.network_info)

        self.assertEqual(port.address,
                         metadata['links'][0]['ethernet_mac_address'])
        self.assertEqual('phy', metadata['links'][0]['type'])


class HashRingTestCase(test.NoDBTestCase):

    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    @mock.patch.object(servicegroup, 'API', autospec=True)
    def setUp(self, mock_sg, mock_services):
        super(HashRingTestCase, self).setUp()

        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()
        self.mock_is_up = (
            self.driver.servicegroup_api.service_is_up)

    @mock.patch.object(ironic_driver.IronicDriver, '_refresh_hash_ring')
    def test_hash_ring_refreshed_on_init(self, mock_hr):
        d = ironic_driver.IronicDriver(None)
        self.assertFalse(mock_hr.called)
        d.init_host('foo')
        mock_hr.assert_called_once_with(mock.ANY)

    @mock.patch.object(hash_ring, 'HashRing')
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def _test__refresh_hash_ring(self, services, expected_hosts, mock_services,
                                 mock_hash_ring, uncalled=None):
        uncalled = uncalled or []
        services = [_make_compute_service(host) for host in services]
        is_up_calls = [mock.call(svc) for svc in services
                       if svc.host not in uncalled]
        self.flags(host='host1')
        mock_services.return_value = services
        mock_hash_ring.return_value = SENTINEL

        self.driver._refresh_hash_ring(self.ctx)

        mock_services.assert_called_once_with(
            mock.ANY, self.driver._get_hypervisor_type())
        mock_hash_ring.assert_called_once_with(expected_hosts, partitions=32)
        self.assertEqual(SENTINEL, self.driver.hash_ring)
        self.mock_is_up.assert_has_calls(is_up_calls)

    def test__refresh_hash_ring_same_host_different_case(self):
        # Test that we treat Host1 and host1 as the same host
        # CONF.host is set to 'host1' in __test_refresh_hash_ring
        services = ['Host1']
        expected_hosts = {'host1'}
        self.mock_is_up.return_value = True
        self._test__refresh_hash_ring(services, expected_hosts)

    def test__refresh_hash_ring_one_compute(self):
        services = ['host1']
        expected_hosts = {'host1'}
        self.mock_is_up.return_value = True
        self._test__refresh_hash_ring(services, expected_hosts)

    @mock.patch('nova.virt.ironic.driver.LOG.debug')
    def test__refresh_hash_ring_many_computes(self, mock_log_debug):
        services = ['host1', 'host2', 'host3']
        expected_hosts = {'host1', 'host2', 'host3'}
        self.mock_is_up.return_value = True
        self._test__refresh_hash_ring(services, expected_hosts)
        expected_msg = 'Hash ring members are %s'
        mock_log_debug.assert_called_once_with(expected_msg, set(services))

    def test__refresh_hash_ring_one_compute_new_compute(self):
        services = []
        expected_hosts = {'host1'}
        self.mock_is_up.return_value = True
        self._test__refresh_hash_ring(services, expected_hosts)

    def test__refresh_hash_ring_many_computes_new_compute(self):
        services = ['host2', 'host3']
        expected_hosts = {'host1', 'host2', 'host3'}
        self.mock_is_up.return_value = True
        self._test__refresh_hash_ring(services, expected_hosts)

    def test__refresh_hash_ring_some_computes_down(self):
        services = ['host1', 'host2', 'host3', 'host4']
        expected_hosts = {'host1', 'host2', 'host4'}
        self.mock_is_up.side_effect = [True, True, False, True]
        self._test__refresh_hash_ring(services, expected_hosts)

    @mock.patch.object(ironic_driver.IronicDriver, '_can_send_version')
    def test__refresh_hash_ring_peer_list(self, mock_can_send):
        services = ['host1', 'host2', 'host3']
        expected_hosts = {'host1', 'host2'}
        self.mock_is_up.return_value = True
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=['host1', 'host2'], group='ironic')
        self._test__refresh_hash_ring(services, expected_hosts,
                                      uncalled=['host3'])
        mock_can_send.assert_called_once_with(min_version='1.46')

    @mock.patch.object(ironic_driver.IronicDriver, '_can_send_version')
    def test__refresh_hash_ring_peer_list_old_api(self, mock_can_send):
        mock_can_send.side_effect = (
            exception.IronicAPIVersionNotAvailable(version='1.46'))
        services = ['host1', 'host2', 'host3']
        expected_hosts = {'host1', 'host2', 'host3'}
        self.mock_is_up.return_value = True
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=['host1', 'host2'], group='ironic')
        self._test__refresh_hash_ring(services, expected_hosts,
                                      uncalled=['host3'])
        mock_can_send.assert_called_once_with(min_version='1.46')

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__check_peer_list(self, mock_log):
        self.flags(host='host1')
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=['host1', 'host2'], group='ironic')
        ironic_driver._check_peer_list()
        # happy path, nothing happens
        self.assertFalse(mock_log.error.called)
        self.assertFalse(mock_log.warning.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__check_peer_list_empty(self, mock_log):
        self.flags(host='host1')
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=[], group='ironic')
        self.assertRaises(exception.InvalidPeerList,
                          ironic_driver._check_peer_list)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__check_peer_list_missing_self(self, mock_log):
        self.flags(host='host1')
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=['host2'], group='ironic')
        self.assertRaises(exception.InvalidPeerList,
                          ironic_driver._check_peer_list)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__check_peer_list_only_self(self, mock_log):
        self.flags(host='host1')
        self.flags(partition_key='not-none', group='ironic')
        self.flags(peer_list=['host1'], group='ironic')
        ironic_driver._check_peer_list()
        self.assertTrue(mock_log.warning.called)


class NodeCacheTestCase(test.NoDBTestCase):

    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def setUp(self, mock_services):
        super(NodeCacheTestCase, self).setUp()

        self.driver = ironic_driver.IronicDriver(None)
        self.driver.init_host('foo')
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()

        self.host = 'host1'
        self.flags(host=self.host)

    @mock.patch.object(ironic_driver.IronicDriver, '_can_send_version')
    @mock.patch.object(ironic_driver.IronicDriver, '_refresh_hash_ring')
    @mock.patch.object(hash_ring.HashRing, 'get_nodes')
    @mock.patch.object(ironic_driver.IronicDriver, '_get_node_list')
    @mock.patch.object(objects.InstanceList, 'get_uuids_by_host')
    def _test__refresh_cache(self, instances, nodes, hosts, mock_instances,
                             mock_nodes, mock_hosts, mock_hash_ring,
                             mock_can_send, partition_key=None,
                             can_send_146=True):
        mock_instances.return_value = instances
        mock_nodes.return_value = nodes
        mock_hosts.side_effect = hosts
        if not can_send_146:
            mock_can_send.side_effect = (
                exception.IronicAPIVersionNotAvailable(version='1.46'))
        self.driver.node_cache = {}
        self.driver.node_cache_time = None

        kwargs = {}
        if partition_key is not None and can_send_146:
            kwargs['conductor_group'] = partition_key

        self.driver._refresh_cache()

        mock_hash_ring.assert_called_once_with(mock.ANY)
        mock_instances.assert_called_once_with(mock.ANY, self.host)
        mock_nodes.assert_called_once_with(fields=ironic_driver._NODE_FIELDS,
                                           **kwargs)
        self.assertIsNotNone(self.driver.node_cache_time)

    def test__refresh_cache_same_host_different_case(self):
        # Test that we treat Host1 and host1 as the same host
        self.host = 'Host1'
        self.flags(host=self.host)
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = ['host1', 'host1', 'host1']

        self._test__refresh_cache(instances, nodes, hosts)

        expected_cache = {n.uuid: n for n in nodes}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache(self):
        # normal operation, one compute service
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = [self.host, self.host, self.host]

        self._test__refresh_cache(instances, nodes, hosts)

        expected_cache = {n.uuid: n for n in nodes}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache_partition_key(self):
        # normal operation, one compute service
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = [self.host, self.host, self.host]
        partition_key = 'some-group'
        self.flags(partition_key=partition_key, group='ironic')

        self._test__refresh_cache(instances, nodes, hosts,
                                  partition_key=partition_key)

        expected_cache = {n.uuid: n for n in nodes}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache_partition_key_old_api(self):
        # normal operation, one compute service
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = [self.host, self.host, self.host]
        partition_key = 'some-group'
        self.flags(partition_key=partition_key, group='ironic')

        self._test__refresh_cache(instances, nodes, hosts,
                                  partition_key=partition_key,
                                  can_send_146=False)

        expected_cache = {n.uuid: n for n in nodes}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache_multiple_services(self):
        # normal operation, many compute services
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = [self.host, 'host2', 'host3']

        self._test__refresh_cache(instances, nodes, hosts)

        expected_cache = {n.uuid: n for n in nodes[0:1]}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache_our_instances(self):
        # we should manage a node we have an instance for, even if it doesn't
        # map to us
        instances = [uuidutils.generate_uuid()]
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=instances[0]),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        # only two calls, having the instance will short-circuit the first node
        hosts = [{self.host}, {self.host}]

        self._test__refresh_cache(instances, nodes, hosts)

        expected_cache = {n.uuid: n for n in nodes}
        self.assertEqual(expected_cache, self.driver.node_cache)

    def test__refresh_cache_their_instances(self):
        # we should never manage a node that another compute service has
        # an instance for, even if it maps to us
        instances = []
        nodes = [
            _get_cached_node(
                uuid=uuidutils.generate_uuid(),
                instance_uuid=uuidutils.generate_uuid()),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
            _get_cached_node(
                uuid=uuidutils.generate_uuid(), instance_uuid=None),
        ]
        hosts = [self.host, self.host]

        # only two calls, having the instance will short-circuit the first node
        self._test__refresh_cache(instances, nodes, hosts)

        expected_cache = {n.uuid: n for n in nodes[1:]}
        self.assertEqual(expected_cache, self.driver.node_cache)


@mock.patch.object(FAKE_CLIENT, 'node')
class IronicDriverConsoleTestCase(test.NoDBTestCase):
    @mock.patch.object(cw, 'IronicClientWrapper',
                       lambda *_: FAKE_CLIENT_WRAPPER)
    @mock.patch.object(objects.ServiceList, 'get_all_computes_by_hv_type')
    def setUp(self, mock_services):
        super(IronicDriverConsoleTestCase, self).setUp()

        self.driver = ironic_driver.IronicDriver(fake.FakeVirtAPI())

        self.mock_conn = self.useFixture(
            fixtures.MockPatchObject(self.driver, '_ironic_connection')).mock

        self.ctx = nova_context.get_admin_context()

        node_id = uuidutils.generate_uuid()
        self.node = _get_cached_node(driver='fake', id=node_id)
        self.instance = fake_instance.fake_instance_obj(self.ctx,
                                                        node=node_id)

        # mock retries configs to avoid sleeps and make tests run quicker
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

        self.stub_out('nova.virt.ironic.driver.IronicDriver.'
                      '_validate_instance_and_node',
                      lambda _, inst: self.node)

    def _create_console_data(self, enabled=True, console_type='socat',
                             url='tcp://127.0.0.1:10000'):
        return {
            'console_enabled': enabled,
            'console_info': {
                'type': console_type,
                'url': url
            }
        }

    def test__get_node_console_with_reset_success(self, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'])

        def _fake_set_console_mode(node_uuid, mode):
            # Set it up so that _fake_get_console() returns 'mode'
            temp_data['target_mode'] = mode

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode

        expected = self._create_console_data()['console_info']

        result = self.driver._get_node_console_with_reset(self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertEqual(self.node.uuid, result['node'].uuid)
        self.assertThat(result['console_info'],
                        nova_matchers.DictMatches(expected))

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__get_node_console_with_reset_console_disabled(self, mock_log,
                                                           mock_node):
        def _fake_log_debug(msg, *args, **kwargs):
            regex = r'Console is disabled for instance .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.return_value = \
            self._create_console_data(enabled=False)
        mock_log.debug.side_effect = _fake_log_debug

        self.assertRaises(exception.ConsoleNotAvailable,
                          self.driver._get_node_console_with_reset,
                          self.instance)

        mock_node.get_console.assert_called_once_with(self.node.uuid)
        mock_node.set_console_mode.assert_not_called()
        self.assertTrue(mock_log.debug.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__get_node_console_with_reset_set_mode_failed(self, mock_log,
                                                          mock_node):
        def _fake_log_error(msg, *args, **kwargs):
            regex = r'Failed to set console mode .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.return_value = self._create_console_data()
        mock_node.set_console_mode.side_effect = exception.NovaException()
        mock_log.error.side_effect = _fake_log_error

        self.assertRaises(exception.ConsoleNotAvailable,
                          self.driver._get_node_console_with_reset,
                          self.instance)

        mock_node.get_console.assert_called_once_with(self.node.uuid)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__get_node_console_with_reset_wait_failed(self, mock_log,
                                                      mock_node):
        def _fake_get_console(node_uuid):
            if mock_node.set_console_mode.called:
                # After the call to set_console_mode(), then _wait_state()
                # will call _get_console() to check the result.
                raise exception.NovaException()
            else:
                return self._create_console_data()

        def _fake_log_error(msg, *args, **kwargs):
            regex = r'Failed to acquire console information for instance .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.side_effect = _fake_get_console
        mock_log.error.side_effect = _fake_log_error

        self.assertRaises(exception.ConsoleNotAvailable,
                          self.driver._get_node_console_with_reset,
                          self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, '_CONSOLE_STATE_CHECKING_INTERVAL', 0.05)
    @mock.patch.object(loopingcall, 'BackOffLoopingCall')
    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test__get_node_console_with_reset_wait_timeout(self, mock_log,
                                                       mock_looping,
                                                       mock_node):
        CONF.set_override('serial_console_state_timeout', 1, group='ironic')
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'])

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = not mode

        def _fake_log_error(msg, *args, **kwargs):
            regex = r'Timeout while waiting for console mode to be set .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode
        mock_log.error.side_effect = _fake_log_error

        mock_timer = mock_looping.return_value
        mock_event = mock_timer.start.return_value
        mock_event.wait.side_effect = loopingcall.LoopingCallTimeOut

        self.assertRaises(exception.ConsoleNotAvailable,
                          self.driver._get_node_console_with_reset,
                          self.instance)

        self.assertEqual(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.error.called)

        mock_timer.start.assert_called_with(starting_interval=0.05, timeout=1,
                                            jitter=0.5)

    def test_get_serial_console_socat(self, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'])

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode

        result = self.driver.get_serial_console(self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertIsInstance(result, console_type.ConsoleSerial)
        self.assertEqual('127.0.0.1', result.host)
        self.assertEqual(10000, result.port)

    def test_get_serial_console_socat_disabled(self, mock_node):
        mock_node.get_console.return_value = \
            self._create_console_data(enabled=False)

        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.driver.get_serial_console,
                          self.ctx, self.instance)
        mock_node.get_console.assert_called_once_with(self.node.uuid)
        mock_node.set_console_mode.assert_not_called()

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test_get_serial_console_socat_invalid_url(self, mock_log, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'],
                                             url='an invalid url')

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        def _fake_log_error(msg, *args, **kwargs):
            regex = r'Invalid Socat console URL .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode
        mock_log.error.side_effect = _fake_log_error

        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.driver.get_serial_console,
                          self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test_get_serial_console_socat_invalid_url_2(self, mock_log, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'],
                                             url='http://abcxyz:1a1b')

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        def _fake_log_error(msg, *args, **kwargs):
            regex = r'Invalid Socat console URL .*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode
        mock_log.error.side_effect = _fake_log_error

        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.driver.get_serial_console,
                          self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.error.called)

    @mock.patch.object(ironic_driver, 'LOG', autospec=True)
    def test_get_serial_console_socat_unsupported_scheme(self, mock_log,
                                                         mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'],
                                             url='ssl://127.0.0.1:10000')

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        def _fake_log_warning(msg, *args, **kwargs):
            regex = r'Socat serial console only supports \"tcp\".*'
            self.assertThat(msg, matchers.MatchesRegex(regex))

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode
        mock_log.warning.side_effect = _fake_log_warning

        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.driver.get_serial_console,
                          self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertTrue(mock_log.warning.called)

    def test_get_serial_console_socat_tcp6(self, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'],
                                             url='tcp://[::1]:10000')

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode

        result = self.driver.get_serial_console(self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
        self.assertIsInstance(result, console_type.ConsoleSerial)
        self.assertEqual('::1', result.host)
        self.assertEqual(10000, result.port)

    def test_get_serial_console_shellinabox(self, mock_node):
        temp_data = {'target_mode': True}

        def _fake_get_console(node_uuid):
            return self._create_console_data(enabled=temp_data['target_mode'],
                                             console_type='shellinabox')

        def _fake_set_console_mode(node_uuid, mode):
            temp_data['target_mode'] = mode

        mock_node.get_console.side_effect = _fake_get_console
        mock_node.set_console_mode.side_effect = _fake_set_console_mode

        self.assertRaises(exception.ConsoleTypeUnavailable,
                          self.driver.get_serial_console,
                          self.ctx, self.instance)

        self.assertGreater(mock_node.get_console.call_count, 1)
        self.assertEqual(2, mock_node.set_console_mode.call_count)
