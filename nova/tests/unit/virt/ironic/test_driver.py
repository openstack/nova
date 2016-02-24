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

from ironicclient import exc as ironic_exception
import mock
from oslo_config import cfg
from oslo_service import loopingcall
from oslo_utils import uuidutils
import six
from testtools.matchers import HasLength

from nova.api.metadata import base as instance_metadata
from nova.compute import power_state as nova_states
from nova.compute import task_states
from nova.compute import vm_states
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import utils
from nova.tests.unit.virt.ironic import utils as ironic_utils
from nova.virt import configdrive
from nova.virt import driver
from nova.virt import fake
from nova.virt import firewall
from nova.virt import hardware
from nova.virt.ironic import client_wrapper as cw
from nova.virt.ironic import driver as ironic_driver
from nova.virt.ironic import ironic_states


CONF = cfg.CONF

IRONIC_FLAGS = dict(
    api_version=1,
    group='ironic',
)

FAKE_CLIENT = ironic_utils.FakeClient()


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


FAKE_CLIENT_WRAPPER = FakeClientWrapper()


@mock.patch.object(cw, 'IronicClientWrapper', lambda *_: FAKE_CLIENT_WRAPPER)
class IronicDriverTestCase(test.NoDBTestCase):

    @mock.patch.object(cw, 'IronicClientWrapper',
                       lambda *_: FAKE_CLIENT_WRAPPER)
    def setUp(self):
        super(IronicDriverTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)

        # set client log config to exercise the code that manipulates it
        CONF.set_override('client_log_level', 'DEBUG', group='ironic')

        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()
        self.instance_uuid = uuidutils.generate_uuid()

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
        self.assertFalse(self.driver.capabilities['supports_recreate'],
                         'Driver capabilities for \'supports_recreate\''
                         'is invalid')

    def test__get_hypervisor_type(self):
        self.assertEqual('ironic', self.driver._get_hypervisor_type())

    def test__get_hypervisor_version(self):
        self.assertEqual(1, self.driver._get_hypervisor_version())

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test__validate_instance_and_node(self, mock_gbiui):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        mock_gbiui.return_value = node
        result = self.driver._validate_instance_and_node(instance)
        self.assertEqual(result.uuid, node_uuid)
        mock_gbiui.assert_called_once_with(instance.uuid,
                                           fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test__validate_instance_and_node_failed(self, mock_gbiui):
        mock_gbiui.side_effect = ironic_exception.NotFound()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        self.assertRaises(exception.InstanceNotFound,
                          self.driver._validate_instance_and_node, instance)
        mock_gbiui.assert_called_once_with(instance.uuid,
                                           fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(objects.Instance, 'refresh')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_active_pass(self, fake_validate, fake_refresh):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.DEPLOYING)

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
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.DEPLOYFAIL)

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
        self._wait_for_active_abort({'vm_state': vm_states.ERROR})

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_power_state_pass(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                target_power_state=ironic_states.POWER_OFF)

        fake_validate.return_value = node
        self.driver._wait_for_power_state(instance, 'fake message')
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test__wait_for_power_state_ok(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                target_power_state=ironic_states.NOSTATE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_power_state, instance, 'fake message')
        self.assertTrue(fake_validate.called)

    def _test__node_resource(self, has_inst_info):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        if has_inst_info:
            instance_info = _get_instance_info()
        else:
            instance_info = {}
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_info=instance_info,
                                          properties=props)

        result = self.driver._node_resource(node)

        wantkeys = ["hypervisor_hostname", "hypervisor_type",
                    "hypervisor_version", "cpu_info",
                    "vcpus", "vcpus_used",
                    "memory_mb", "memory_mb_used",
                    "local_gb", "local_gb_used",
                    "disk_available_least",
                    "supported_instances",
                    "stats",
                    "numa_topology"]
        wantkeys.sort()
        gotkeys = result.keys()
        gotkeys.sort()
        self.assertEqual(wantkeys, gotkeys)

        if has_inst_info:
            props_dict = instance_info
            expected_cpus = instance_info['vcpus']
        else:
            props_dict = props
            expected_cpus = props['cpus']
        self.assertEqual(expected_cpus, result['vcpus'])
        self.assertEqual(expected_cpus, result['vcpus_used'])
        self.assertEqual(props_dict['memory_mb'], result['memory_mb'])
        self.assertEqual(props_dict['memory_mb'], result['memory_mb_used'])
        self.assertEqual(props_dict['local_gb'], result['local_gb'])
        self.assertEqual(props_dict['local_gb'], result['local_gb_used'])

        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])
        self.assertIsNone(result['numa_topology'])

    def test__node_resource(self):
        self._test__node_resource(True)

    def test__node_resource_no_instance_info(self):
        self._test__node_resource(False)

    def test__node_resource_canonicalizes_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        props['cpu_arch'] = 'i386'
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual('i686', result['supported_instances'][0][0])
        self.assertEqual('i386', result['stats']['cpu_arch'])

    def test__node_resource_unknown_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        del props['cpu_arch']
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual([], result['supported_instances'])

    def test__node_resource_exposes_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability, test2:value2'
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        stats = result['stats']
        self.assertIsNone(stats.get('capabilities'))
        self.assertEqual('capability', stats.get('test'))
        self.assertEqual('value2', stats.get('test2'))

    def test__node_resource_no_capabilities(self):
        props = _get_properties()
        props['capabilities'] = None
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        self.assertIsNone(result['stats'].get('capabilities'))

    def test__node_resource_malformed_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability,:no_key,no_val:'
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        stats = result['stats']
        self.assertEqual('capability', stats.get('test'))

    def test__node_resource_available(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = ironic_utils.get_test_node(
            uuid=node_uuid,
            instance_uuid=None,
            power_state=ironic_states.POWER_OFF,
            properties=props,
            provision_state=ironic_states.AVAILABLE)

        result = self.driver._node_resource(node)
        self.assertEqual(props['cpus'], result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(props['memory_mb'], result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(props['local_gb'], result['local_gb'])
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
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=None,
                                          properties=props)

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
        node = ironic_utils.get_test_node(
            uuid=node_uuid,
            instance_uuid=uuidutils.generate_uuid(),
            provision_state=ironic_states.ACTIVE,
            properties=props,
            instance_info=instance_info)

        result = self.driver._node_resource(node)
        self.assertEqual(instance_info['vcpus'], result['vcpus'])
        self.assertEqual(instance_info['vcpus'], result['vcpus_used'])
        self.assertEqual(instance_info['memory_mb'], result['memory_mb'])
        self.assertEqual(instance_info['memory_mb'], result['memory_mb_used'])
        self.assertEqual(instance_info['local_gb'], result['local_gb'])
        self.assertEqual(instance_info['local_gb'], result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, result['stats'])

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_properties(self, mock_warning):
        props = _get_properties()
        node = ironic_utils.get_test_node(
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
        node = ironic_utils.get_test_node(
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
    def test__parse_node_instance_info(self, mock_warning):
        props = _get_properties()
        instance_info = _get_instance_info()
        node = ironic_utils.get_test_node(
            uuid=uuidutils.generate_uuid(),
            instance_info=instance_info)
        parsed = self.driver._parse_node_instance_info(node, props)

        self.assertEqual(instance_info, parsed)
        self.assertFalse(mock_warning.called)

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_instance_info_bad_values(self, mock_warning):
        props = _get_properties()
        instance_info = _get_instance_info()
        instance_info['vcpus'] = 'bad-value'
        instance_info['memory_mb'] = 'bad-value'
        instance_info['local_gb'] = 'bad-value'
        node = ironic_utils.get_test_node(
            uuid=uuidutils.generate_uuid(),
            instance_info=instance_info)
        parsed = self.driver._parse_node_instance_info(node, props)

        expected = {
            'vcpus': props['cpus'],
            'memory_mb': props['memory_mb'],
            'local_gb': props['local_gb']
        }
        self.assertEqual(expected, parsed)
        self.assertEqual(3, mock_warning.call_count)

    @mock.patch.object(ironic_driver.LOG, 'warning')
    def test__parse_node_properties_canonicalize_cpu_arch(self, mock_warning):
        props = _get_properties()
        props['cpu_arch'] = 'amd64'
        node = ironic_utils.get_test_node(
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

    @mock.patch.object(firewall.NoopFirewallDriver, 'prepare_instance_filter',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'setup_basic_filtering',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'apply_instance_filter',
                       create=True)
    def test__start_firewall(self, mock_aif, mock_sbf, mock_pif):
        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        self.driver._start_firewall(fake_inst, fake_net_info)

        mock_aif.assert_called_once_with(fake_inst, fake_net_info)
        mock_sbf.assert_called_once_with(fake_inst, fake_net_info)
        mock_pif.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'unfilter_instance',
                       create=True)
    def test__stop_firewall(self, mock_ui):
        fake_inst = 'fake-inst'
        fake_net_info = utils.get_test_network_info()
        self.driver._stop_firewall(fake_inst, fake_net_info)
        mock_ui.assert_called_once_with(fake_inst, fake_net_info)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists(self, mock_call):
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        self.assertTrue(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          self.instance_uuid,
                                          fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists_fail(self, mock_call):
        mock_call.side_effect = ironic_exception.NotFound
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        self.assertFalse(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          self.instance_uuid,
                                          fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instances(self, mock_inst_by_uuid, mock_call):
        nodes = []
        instances = []
        for i in range(2):
            uuid = uuidutils.generate_uuid()
            instances.append(fake_instance.fake_instance_obj(self.ctx,
                                                             id=i,
                                                             uuid=uuid))
            nodes.append(ironic_utils.get_test_node(instance_uuid=uuid))

        mock_inst_by_uuid.side_effect = instances
        mock_call.return_value = nodes

        response = self.driver.list_instances()
        mock_call.assert_called_with("node.list", associated=True, limit=0)
        expected_calls = [mock.call(mock.ANY, instances[0].uuid),
                          mock.call(mock.ANY, instances[1].uuid)]
        mock_inst_by_uuid.assert_has_calls(expected_calls)
        self.assertEqual(['instance-00000000', 'instance-00000001'],
                          sorted(response))

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_list_instances_fail(self, mock_inst_by_uuid, mock_call):
        mock_call.side_effect = exception.NovaException
        response = self.driver.list_instances()
        mock_call.assert_called_with("node.list", associated=True, limit=0)
        self.assertFalse(mock_inst_by_uuid.called)
        self.assertThat(response, HasLength(0))

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_list_instance_uuids(self, mock_call):
        num_nodes = 2
        nodes = []
        for n in range(num_nodes):
            nodes.append(ironic_utils.get_test_node(
                                      instance_uuid=uuidutils.generate_uuid()))

        mock_call.return_value = nodes
        uuids = self.driver.list_instance_uuids()
        mock_call.assert_called_with('node.list', associated=True, limit=0)
        expected = [n.instance_uuid for n in nodes]
        self.assertEqual(sorted(expected), sorted(uuids))

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available_empty_cache_empty_list(self, mock_get,
                                                      mock_list):
        node = ironic_utils.get_test_node()
        mock_get.return_value = node
        mock_list.return_value = []
        self.assertTrue(self.driver.node_is_available(node.uuid))
        mock_get.assert_called_with(node.uuid,
                                    fields=ironic_driver._NODE_FIELDS)
        mock_list.assert_called_with(detail=True, limit=0)

        mock_get.side_effect = ironic_exception.NotFound
        self.assertFalse(self.driver.node_is_available(node.uuid))

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available_empty_cache(self, mock_get, mock_list):
        node = ironic_utils.get_test_node()
        mock_get.return_value = node
        mock_list.return_value = [node]
        self.assertTrue(self.driver.node_is_available(node.uuid))
        mock_list.assert_called_with(detail=True, limit=0)
        self.assertEqual(0, mock_get.call_count)

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available_with_cache(self, mock_get, mock_list):
        node = ironic_utils.get_test_node()
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
             'provision_state': ironic_states.DELETED}
        ]
        for n in node_dicts:
            node = ironic_utils.get_test_node(**n)
            self.assertTrue(self.driver._node_resources_unavailable(node))

        for ok_state in (ironic_states.AVAILABLE, ironic_states.NOSTATE):
            # these are both ok and should present as available
            avail_node = ironic_utils.get_test_node(
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
            node = ironic_utils.get_test_node(**n)
            self.assertTrue(self.driver._node_resources_used(node))

        unused_node = ironic_utils.get_test_node(
            instance_uuid=None,
            provision_state=ironic_states.AVAILABLE)
        self.assertFalse(self.driver._node_resources_used(unused_node))

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    def test_get_available_nodes(self, mock_list):
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF},
            # a node /w instance and power ON
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': self.instance_uuid,
             'power_state': ironic_states.POWER_ON},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.ERROR},
        ]
        nodes = [ironic_utils.get_test_node(**n) for n in node_dicts]
        mock_list.return_value = nodes
        available_nodes = self.driver.get_available_nodes()
        expected_uuids = [n['uuid'] for n in node_dicts]
        self.assertEqual(sorted(expected_uuids), sorted(available_nodes))

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource(self, mock_nr, mock_list, mock_get):
        node = ironic_utils.get_test_node()
        node_2 = ironic_utils.get_test_node(uuid=uuidutils.generate_uuid())
        fake_resource = 'fake-resource'
        mock_get.return_value = node
        # ensure cache gets populated without the node we want
        mock_list.return_value = [node_2]
        mock_nr.return_value = fake_resource

        result = self.driver.get_available_resource(node.uuid)
        self.assertEqual(fake_resource, result)
        mock_nr.assert_called_once_with(node)
        mock_get.assert_called_once_with(node.uuid,
                                         fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(FAKE_CLIENT.node, 'list')
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource_with_cache(self, mock_nr, mock_list,
                                               mock_get):
        node = ironic_utils.get_test_node()
        fake_resource = 'fake-resource'
        mock_list.return_value = [node]
        mock_nr.return_value = fake_resource
        # populate the cache
        self.driver.get_available_nodes(refresh=True)
        mock_list.reset_mock()

        result = self.driver.get_available_resource(node.uuid)
        self.assertEqual(fake_resource, result)
        self.assertEqual(0, mock_list.call_count)
        self.assertEqual(0, mock_get.call_count)
        mock_nr.assert_called_once_with(node)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info(self, mock_gbiu):
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = ironic_utils.get_test_node(instance_uuid=self.instance_uuid,
                                          properties=properties,
                                          power_state=power_state)

        mock_gbiu.return_value = node

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        memory_kib = properties['memory_mb'] * 1024
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=self.instance_uuid)
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.RUNNING,
                                               max_mem_kb=memory_kib,
                                               mem_kb=memory_kib,
                                               num_cpu=properties['cpus']),
                         result)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info_http_not_found(self, mock_gbiu):
        mock_gbiu.side_effect = ironic_exception.NotFound()

        instance = fake_instance.fake_instance_obj(
                                  self.ctx, uuid=uuidutils.generate_uuid())
        result = self.driver.get_info(instance)
        self.assertEqual(hardware.InstanceInfo(state=nova_states.NOSTATE),
                         result)

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_macs_for_instance(self, mock_node):
        node = ironic_utils.get_test_node()
        port = ironic_utils.get_test_port()
        mock_node.get.return_value = node
        mock_node.list_ports.return_value = [port]
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        result = self.driver.macs_for_instance(instance)
        self.assertEqual(set([port.address]), result)
        mock_node.list_ports.assert_called_once_with(node.uuid)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_macs_for_instance_http_not_found(self, mock_get):
        mock_get.side_effect = ironic_exception.NotFound()

        instance = fake_instance.fake_instance_obj(
                                  self.ctx, node=uuidutils.generate_uuid())
        result = self.driver.macs_for_instance(instance)
        self.assertIsNone(result)

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def _test_spawn(self, mock_sf, mock_pvifs, mock_adf, mock_wait_active,
                    mock_node, mock_looping, mock_save):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = objects.Flavor(ephemeral_gb=0)
        instance.flavor = fake_flavor

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        image_meta = ironic_utils.get_test_image_meta()

        self.driver.spawn(self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_adf.assert_called_once_with(node, instance,
                                         test.MatchType(objects.ImageMeta),
                                         fake_flavor)
        mock_pvifs.assert_called_once_with(node, instance, None)
        mock_sf.assert_called_once_with(instance, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                'active', configdrive=mock.ANY)

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
                                                 extra_md={}, files=[])

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn_destroyed_after_failure(self, mock_sf, mock_pvifs, mock_adf,
                                           mock_wait_active, mock_destroy,
                                           mock_node, mock_looping,
                                           mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
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
            self.driver.spawn, self.ctx, instance, None, [], None)
        self.assertEqual(0, mock_destroy.call_count)

    def _test_add_driver_fields(self, mock_update=None, mock_call=None):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        image_meta = ironic_utils.get_test_image_meta()
        flavor = ironic_utils.get_test_flavor()
        self.driver._add_driver_fields(node, instance, image_meta, flavor)
        expected_patch = [{'path': '/instance_info/image_source', 'op': 'add',
                           'value': image_meta.id},
                          {'path': '/instance_info/root_gb', 'op': 'add',
                           'value': str(instance.root_gb)},
                          {'path': '/instance_info/swap_mb', 'op': 'add',
                           'value': str(flavor['swap'])},
                          {'path': '/instance_info/display_name',
                           'value': instance.display_name, 'op': 'add'},
                          {'path': '/instance_info/vcpus', 'op': 'add',
                           'value': str(instance.vcpus)},
                          {'path': '/instance_info/memory_mb', 'op': 'add',
                           'value': str(instance.memory_mb)},
                          {'path': '/instance_info/local_gb', 'op': 'add',
                           'value': str(node.properties.get('local_gb', 0))},
                          {'path': '/instance_uuid', 'op': 'add',
                           'value': instance.uuid}]

        if mock_call is not None:
            # assert call() is invoked with retry_on_conflict False to
            # avoid bug #1341420
            mock_call.assert_called_once_with('node.update', node.uuid,
                                              expected_patch,
                                              retry_on_conflict=False)
        if mock_update is not None:
            mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_mock_update(self, mock_update):
        self._test_add_driver_fields(mock_update=mock_update)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test__add_driver_fields_mock_call(self, mock_call):
        self._test_add_driver_fields(mock_call=mock_call)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_fail(self, mock_update):
        mock_update.side_effect = ironic_exception.BadRequest()
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        image_meta = ironic_utils.get_test_image_meta()
        flavor = ironic_utils.get_test_flavor()
        self.assertRaises(exception.InstanceDeployFailure,
                          self.driver._add_driver_fields,
                          node, instance, image_meta, flavor)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_spawn_node_driver_validation_fail(self, mock_node,
                                               mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor

        mock_node.validate.return_value = ironic_utils.get_test_validation(
            power=False, deploy=False)
        mock_node.get.return_value = node
        image_meta = ironic_utils.get_test_image_meta()

        self.assertRaises(exception.ValidationError, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)
        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_prepare_for_deploy_fail(self, mock_cleanup_deploy,
                                                mock_pvifs, mock_sf,
                                                mock_node, mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        image_meta = ironic_utils.get_test_image_meta()

        class TestException(Exception):
            pass

        mock_sf.side_effect = TestException()
        self.assertRaises(TestException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_cleanup_deploy.assert_called_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_generate_configdrive')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_configdrive_fail(self, mock_cleanup_deploy,
                                         mock_pvifs, mock_sf, mock_configdrive,
                                         mock_node, mock_save,
                                         mock_required_by):
        mock_required_by.return_value = True
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        image_meta = ironic_utils.get_test_image_meta()

        class TestException(Exception):
            pass

        mock_configdrive.side_effect = TestException()
        self.assertRaises(TestException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(
                node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_cleanup_deploy.assert_called_with(self.ctx, node, instance, None,
                                               flavor=flavor)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail(self, mock_cleanup_deploy,
                                            mock_pvifs, mock_sf,
                                            mock_node, mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        mock_node.set_provision_state.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail2(self, mock_cleanup_deploy,
                                             mock_pvifs, mock_sf,
                                             mock_node, mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.set_provision_state.side_effect = ironic_exception.BadRequest
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_cleanup_deploy.assert_called_once_with(node, instance, None)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    def test_spawn_node_trigger_deploy_fail3(self, mock_destroy,
                                             mock_pvifs, mock_sf,
                                             mock_node, mock_looping,
                                             mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        image_meta = ironic_utils.get_test_image_meta()

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        fake_looping_call.wait.side_effect = ironic_exception.BadRequest
        fake_net_info = utils.get_test_network_info()
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.spawn, self.ctx, instance,
                          image_meta, [], None, fake_net_info)
        self.assertEqual(0, mock_destroy.call_count)

    @mock.patch.object(configdrive, 'required_by')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn_sets_default_ephemeral_device(self, mock_sf, mock_pvifs,
                                                 mock_wait, mock_node,
                                                 mock_save, mock_looping,
                                                 mock_required_by):
        mock_required_by.return_value = False
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        flavor = ironic_utils.get_test_flavor(ephemeral_gb=1)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        instance.flavor = flavor
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        image_meta = ironic_utils.get_test_image_meta()

        self.driver.spawn(self.ctx, instance, image_meta, [], None)
        self.assertTrue(mock_save.called)
        self.assertEqual('/dev/sda1', instance.default_ephemeral_device)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def _test_destroy(self, state, mock_cleanup_deploy, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=state)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = None

        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.side_effect = fake_set_provision_state
        self.driver.destroy(self.ctx, instance, network_info, None)

        mock_node.get_by_instance_uuid.assert_called_with(
            instance.uuid, fields=ironic_driver._NODE_FIELDS)
        mock_cleanup_deploy.assert_called_with(node, instance, network_info)

        # For states that makes sense check if set_provision_state has
        # been called
        if state in ironic_driver._UNPROVISION_STATES:
            mock_node.set_provision_state.assert_called_once_with(
                node_uuid, 'deleted')
        else:
            self.assertFalse(mock_node.set_provision_state.called)

    def test_destroy(self):
        for state in ironic_states.PROVISION_STATE_LIST:
            self._test_destroy(state)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def test_destroy_trigger_undeploy_fail(self, fake_validate, mock_sps):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        fake_validate.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        mock_sps.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    def _test__unprovision_instance(self, mock_validate_inst, mock_set_pstate,
                                    state=None):
        node = ironic_utils.get_test_node(
            driver='fake',
            provision_state=state)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)
        mock_validate_inst.return_value = node
        self.driver._unprovision(instance, node)
        mock_validate_inst.assert_called_once_with(instance)
        mock_set_pstate.assert_called_once_with(node.uuid, "deleted")

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
        node = ironic_utils.get_test_node(
            driver='fake',
            provision_state=ironic_states.ACTIVE)
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
        node = ironic_utils.get_test_node(
            driver='fake', provision_state=ironic_states.DELETING)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node.uuid)

        mock_validate_inst.side_effect = exception.InstanceNotFound(
            instance_id='fake')
        self.driver._unprovision(instance, node)
        mock_validate_inst.assert_called_once_with(instance)
        mock_set_pstate.assert_called_once_with(node.uuid, "deleted")

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_destroy_unassociate_fail(self, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get_by_instance_uuid.return_value = node
        mock_node.update.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')
        mock_node.get_by_instance_uuid.assert_called_with(
            instance.uuid, fields=ironic_driver._NODE_FIELDS)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_reboot(self, mock_sp, fake_validate, mock_looping):
        node = ironic_utils.get_test_node()
        fake_validate.side_effect = [node, node]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.reboot(self.ctx, instance, None, None)
        mock_sp.assert_called_once_with(node.uuid, 'reboot')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off(self, mock_sp, fake_validate, mock_looping):
        self._test_power_on_off(mock_sp, fake_validate, mock_looping,
                                method_name='power_off')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver.IronicDriver,
                       '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_on(self, mock_sp, fake_validate, mock_looping):
        self._test_power_on_off(mock_sp, fake_validate, mock_looping,
                                method_name='power_on')

    def _test_power_on_off(self, mock_sp, fake_validate, mock_looping,
                           method_name=None):
        node = ironic_utils.get_test_node()
        fake_validate.side_effect = [node, node]

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=self.instance_uuid)
        # Call the method under test here
        if method_name == 'power_on':
            self.driver.power_on(self.ctx, instance,
                                 utils.get_test_network_info())
            mock_sp.assert_called_once_with(node.uuid, 'on')
        elif method_name == 'power_off':
            self.driver.power_off(instance)
            mock_sp.assert_called_once_with(node.uuid, 'off')

    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_with_port(self, mock_uvifs, mock_port_udt, mock_lp):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        # make the address be consistent with network_info's
        port = ironic_utils.get_test_port(address='fake')

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()

        port_id = six.text_type(network_info[0]['id'])
        expected_patch = [{'op': 'add',
                           'path': '/extra/vif_port_id',
                           'value': port_id}]
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        mock_port_udt.assert_called_with(port.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    def test_plug_vifs(self, mock__plug_vifs, mock_get):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)

        mock_get.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()
        self.driver.plug_vifs(instance, network_info)

        mock_get.assert_called_once_with(node_uuid,
                                         fields=ironic_driver._NODE_FIELDS)
        mock__plug_vifs.assert_called_once_with(node, instance, network_info)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_multiple_ports(self, mock_uvifs, mock_lp,
                                       mock_port_udt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        first_ironic_port_uuid = 'aaaaaaaa-bbbb-1111-dddd-eeeeeeeeeeee'
        first_port = ironic_utils.get_test_port(uuid=first_ironic_port_uuid,
                                                node_uuid=node_uuid,
                                                address='11:FF:FF:FF:FF:FF')
        second_ironic_port_uuid = 'aaaaaaaa-bbbb-2222-dddd-eeeeeeeeeeee'
        second_port = ironic_utils.get_test_port(uuid=second_ironic_port_uuid,
                                                 node_uuid=node_uuid,
                                                 address='22:FF:FF:FF:FF:FF')
        mock_lp.return_value = [second_port, first_port]
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        first_vif_id = 'aaaaaaaa-vv11-cccc-dddd-eeeeeeeeeeee'
        second_vif_id = 'aaaaaaaa-vv22-cccc-dddd-eeeeeeeeeeee'
        first_vif = ironic_utils.get_test_vif(
                                            address='22:FF:FF:FF:FF:FF',
                                            id=second_vif_id)
        second_vif = ironic_utils.get_test_vif(
                                            address='11:FF:FF:FF:FF:FF',
                                            id=first_vif_id)
        network_info = [first_vif, second_vif]
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        calls = (mock.call(first_ironic_port_uuid,
                           [{'op': 'add', 'path': '/extra/vif_port_id',
                             'value': first_vif_id}]),
                 mock.call(second_ironic_port_uuid,
                           [{'op': 'add', 'path': '/extra/vif_port_id',
                             'value': second_vif_id}]))
        mock_port_udt.assert_has_calls(calls, any_order=True)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_count_mismatch(self, mock_uvifs, mock_lp,
                                      mock_port_udt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        # len(network_info) > len(ports)
        network_info = (utils.get_test_network_info() +
                        utils.get_test_network_info())
        self.assertRaises(exception.NovaException,
                          self.driver._plug_vifs, node, instance,
                          network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        # assert port.update() was not called
        self.assertFalse(mock_port_udt.called)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT.node, 'list_ports')
    @mock.patch.object(ironic_driver.IronicDriver, '_unplug_vifs')
    def test_plug_vifs_no_network_info(self, mock_uvifs, mock_lp,
                                       mock_port_udt):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = []
        self.driver._plug_vifs(node, instance, network_info)

        # asserts
        mock_uvifs.assert_called_once_with(node, instance, network_info)
        mock_lp.assert_called_once_with(node_uuid)
        # assert port.update() was not called
        self.assertFalse(mock_port_udt.called)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_unplug_vifs(self, mock_node, mock_update):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port(extra={'vif_port_id': 'fake-vif'})

        mock_node.get.return_value = node
        mock_node.list_ports.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        expected_patch = [{'op': 'remove', 'path':
                           '/extra/vif_port_id'}]
        self.driver.unplug_vifs(instance,
                                utils.get_test_network_info())

        # asserts
        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.list_ports.assert_called_once_with(node_uuid, detail=True)
        mock_update.assert_called_once_with(port.uuid, expected_patch)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_unplug_vifs_port_not_associated(self, mock_node, mock_update):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(uuid=node_uuid)
        port = ironic_utils.get_test_port(extra={})

        mock_node.get.return_value = node
        mock_node.list_ports.return_value = [port]
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        self.driver.unplug_vifs(instance, utils.get_test_network_info())

        mock_node.get.assert_called_once_with(
            node_uuid, fields=ironic_driver._NODE_FIELDS)
        mock_node.list_ports.assert_called_once_with(node_uuid, detail=True)
        # assert port.update() was not called
        self.assertFalse(mock_update.called)

    @mock.patch.object(FAKE_CLIENT.port, 'update')
    def test_unplug_vifs_no_network_info(self, mock_update):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = []
        self.driver.unplug_vifs(instance, network_info)

        # assert port.update() was not called
        self.assertFalse(mock_update.called)

    @mock.patch.object(firewall.NoopFirewallDriver, 'unfilter_instance',
                       create=True)
    def test_unfilter_instance(self, mock_ui):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        self.driver.unfilter_instance(instance, network_info)
        mock_ui.assert_called_once_with(instance, network_info)

    @mock.patch.object(firewall.NoopFirewallDriver, 'setup_basic_filtering',
                       create=True)
    @mock.patch.object(firewall.NoopFirewallDriver, 'prepare_instance_filter',
                       create=True)
    def test_ensure_filtering_rules_for_instance(self, mock_pif, mock_sbf):
        instance = fake_instance.fake_instance_obj(self.ctx)
        network_info = utils.get_test_network_info()
        self.driver.ensure_filtering_rules_for_instance(instance,
                                                        network_info)
        mock_sbf.assert_called_once_with(instance, network_info)
        mock_pif.assert_called_once_with(instance, network_info)

    @mock.patch.object(firewall.NoopFirewallDriver,
                       'refresh_instance_security_rules', create=True)
    def test_refresh_instance_security_rules(self, mock_risr):
        instance = fake_instance.fake_instance_obj(self.ctx)
        self.driver.refresh_instance_security_rules(instance)
        mock_risr.assert_called_once_with(instance)

    @mock.patch.object(firewall.NoopFirewallDriver,
                      'refresh_instance_security_rules', create=True)
    def test_refresh_security_group_rules(self, mock_risr):
        fake_group = 'fake-security-group-members'
        self.driver.refresh_instance_security_rules(fake_group)
        mock_risr.assert_called_once_with(fake_group)

    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def _test_rebuild(self, mock_save, mock_get, mock_driver_fields,
                      mock_set_pstate, mock_looping, mock_wait_active,
                      preserve=False):
        node_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5)
        mock_get.return_value = node

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = objects.Flavor(flavor_id=flavor_id, name='baremetal')

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_uuid,
                                                   instance_type_id=flavor_id)
        instance.flavor = flavor

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        self.driver.rebuild(
            context=self.ctx, instance=instance, image_meta=image_meta,
            injected_files=None, admin_password=None, bdms=None,
            detach_block_devices=None, attach_block_devices=None,
            preserve_ephemeral=preserve)

        mock_save.assert_called_once_with(
            expected_task_state=[task_states.REBUILDING])
        mock_driver_fields.assert_called_once_with(
            node, instance,
            test.MatchType(objects.ImageMeta),
            flavor, preserve)
        mock_set_pstate.assert_called_once_with(node_uuid,
                                                ironic_states.REBUILD)
        mock_looping.assert_called_once_with(mock_wait_active, instance)
        fake_looping_call.start.assert_called_once_with(
            interval=CONF.ironic.api_retry_interval)
        fake_looping_call.wait.assert_called_once_with()

    def test_rebuild_preserve_ephemeral(self):
        self._test_rebuild(preserve=True)

    def test_rebuild_no_preserve_ephemeral(self):
        self._test_rebuild(preserve=False)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def test_rebuild_failures(self, mock_save, mock_get, mock_driver_fields,
                              mock_set_pstate):
        node_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5)
        mock_get.return_value = node

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
                injected_files=None, admin_password=None, bdms=None,
                detach_block_devices=None, attach_block_devices=None)

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def _test_network_binding_host_id(self, is_neutron, mock_get):
        node_uuid = uuidutils.generate_uuid()
        hostname = 'ironic-compute'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid,
                                                   host=hostname)
        if is_neutron:
            provider = 'neutron'
            expected = None
        else:
            provider = 'none'
            expected = hostname
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5,
                                          network_provider=provider)
        mock_get.return_value = node

        host_id = self.driver.network_binding_host_id(self.ctx, instance)
        self.assertEqual(expected, host_id)

    def test_network_binding_host_id_neutron(self):
        self._test_network_binding_host_id(True)

    def test_network_binding_host_id_none(self):
        self._test_network_binding_host_id(False)


@mock.patch.object(instance_metadata, 'InstanceMetadata')
@mock.patch.object(configdrive, 'ConfigDriveBuilder')
class IronicDriverGenerateConfigDriveTestCase(test.NoDBTestCase):

    @mock.patch.object(cw, 'IronicClientWrapper',
                       lambda *_: FAKE_CLIENT_WRAPPER)
    def setUp(self):
        super(IronicDriverGenerateConfigDriveTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)
        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()
        node_uuid = uuidutils.generate_uuid()
        self.node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        self.instance = fake_instance.fake_instance_obj(self.ctx,
                                                        node=node_uuid)
        self.network_info = utils.get_test_network_info()

    def test_generate_configdrive(self, mock_cd_builder, mock_instance_meta):
        mock_instance_meta.return_value = 'fake-instance'
        mock_make_drive = mock.MagicMock(make_drive=lambda *_: None)
        mock_cd_builder.return_value.__enter__.return_value = mock_make_drive
        self.driver._generate_configdrive(self.instance, self.node,
                                          self.network_info)
        mock_cd_builder.assert_called_once_with(instance_md='fake-instance')
        mock_instance_meta.assert_called_once_with(self.instance,
            network_info=self.network_info, extra_md={}, content=None)

    def test_generate_configdrive_fail(self, mock_cd_builder,
                                       mock_instance_meta):
        mock_cd_builder.side_effect = exception.ConfigDriveMountFailed(
            operation='foo', error='error')
        mock_instance_meta.return_value = 'fake-instance'
        mock_make_drive = mock.MagicMock(make_drive=lambda *_: None)
        mock_cd_builder.return_value.__enter__.return_value = mock_make_drive

        self.assertRaises(exception.ConfigDriveMountFailed,
                          self.driver._generate_configdrive,
                          self.instance, self.node, self.network_info)

        mock_cd_builder.assert_called_once_with(instance_md='fake-instance')
        mock_instance_meta.assert_called_once_with(self.instance,
            network_info=self.network_info, extra_md={}, content=None)
