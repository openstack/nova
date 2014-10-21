# Copyright 2014 Red Hat, Inc.
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
from oslo.config import cfg
from oslo.serialization import jsonutils

from nova.compute import power_state as nova_states
from nova.compute import task_states
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.openstack.common import loopingcall
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import utils
from nova.tests.unit.virt.ironic import utils as ironic_utils
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
    def _get_client(self):
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
            'cpu_arch': 'x86_64'}


def _get_stats():
    return {'cpu_arch': 'x86_64'}


FAKE_CLIENT_WRAPPER = FakeClientWrapper()


@mock.patch.object(cw, 'IronicClientWrapper', lambda *_: FAKE_CLIENT_WRAPPER)
class IronicDriverTestCase(test.NoDBTestCase):

    def setUp(self):
        super(IronicDriverTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)
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
        ironicclient = cw.IronicClientWrapper()

        mock_gbiui.return_value = node
        result = ironic_driver._validate_instance_and_node(ironicclient,
                                                           instance)
        self.assertEqual(result.uuid, node_uuid)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test__validate_instance_and_node_failed(self, mock_gbiui):
        ironicclient = cw.IronicClientWrapper()
        mock_gbiui.side_effect = ironic_exception.NotFound()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        self.assertRaises(exception.InstanceNotFound,
                          ironic_driver._validate_instance_and_node,
                          ironicclient, instance)

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test__wait_for_active_pass(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.DEPLOYING)

        fake_validate.return_value = node
        self.driver._wait_for_active(FAKE_CLIENT, instance)
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test__wait_for_active_done(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.ACTIVE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_active,
                FAKE_CLIENT, instance)
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test__wait_for_active_fail(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                provision_state=ironic_states.DEPLOYFAIL)

        fake_validate.return_value = node
        self.assertRaises(exception.InstanceDeployFailure,
                self.driver._wait_for_active,
                FAKE_CLIENT, instance)
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test__wait_for_power_state_pass(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                target_power_state=ironic_states.POWER_OFF)

        fake_validate.return_value = node
        self.driver._wait_for_power_state(
                FAKE_CLIENT, instance, 'fake message')
        self.assertTrue(fake_validate.called)

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test__wait_for_power_state_ok(self, fake_validate):
        instance = fake_instance.fake_instance_obj(self.ctx,
                uuid=uuidutils.generate_uuid())
        node = ironic_utils.get_test_node(
                target_power_state=ironic_states.NOSTATE)

        fake_validate.return_value = node
        self.assertRaises(loopingcall.LoopingCallDone,
                self.driver._wait_for_power_state,
                FAKE_CLIENT, instance, 'fake message')
        self.assertTrue(fake_validate.called)

    def test__node_resource(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual(props['cpus'], result['vcpus'])
        self.assertEqual(props['cpus'], result['vcpus_used'])
        self.assertEqual(props['memory_mb'], result['memory_mb'])
        self.assertEqual(props['memory_mb'], result['memory_mb_used'])
        self.assertEqual(props['local_gb'], result['local_gb'])
        self.assertEqual(props['local_gb'], result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, jsonutils.loads(result['stats']))

    def test__node_resource_canonicalizes_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        props['cpu_arch'] = 'i386'
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual('i686',
                         jsonutils.loads(result['supported_instances'])[0][0])
        self.assertEqual('i386',
                         jsonutils.loads(result['stats'])['cpu_arch'])

    def test__node_resource_unknown_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        del props['cpu_arch']
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual([], jsonutils.loads(result['supported_instances']))

    def test__node_resource_exposes_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability'
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        stats = jsonutils.loads(result['stats'])
        self.assertIsNone(stats.get('capabilities'))
        self.assertEqual('capability', stats.get('test'))

    def test__node_resource_no_capabilities(self):
        props = _get_properties()
        props['capabilities'] = None
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        self.assertIsNone(jsonutils.loads(result['stats']).get('capabilities'))

    def test__node_resource_malformed_capabilities(self):
        props = _get_properties()
        props['capabilities'] = 'test:capability,:no_key,no_val:'
        node = ironic_utils.get_test_node(properties=props)
        result = self.driver._node_resource(node)
        stats = jsonutils.loads(result['stats'])
        self.assertEqual('capability', stats.get('test'))

    def test__node_resource_no_instance_uuid(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        stats = _get_stats()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=None,
                                          power_state=ironic_states.POWER_OFF,
                                          properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual(props['cpus'], result['vcpus'])
        self.assertEqual(0, result['vcpus_used'])
        self.assertEqual(props['memory_mb'], result['memory_mb'])
        self.assertEqual(0, result['memory_mb_used'])
        self.assertEqual(props['local_gb'], result['local_gb'])
        self.assertEqual(0, result['local_gb_used'])
        self.assertEqual(node_uuid, result['hypervisor_hostname'])
        self.assertEqual(stats, jsonutils.loads(result['stats']))

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
        self.assertEqual(stats, jsonutils.loads(result['stats']))

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
                                          self.instance_uuid)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists_fail(self, mock_call):
        mock_call.side_effect = ironic_exception.NotFound
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid)
        self.assertFalse(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          self.instance_uuid)

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
        mock_get.assert_called_with(node.uuid)
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
             'power_state': ironic_states.POWER_OFF},
            # a node in maintenance /w no instance and ERROR power state
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.ERROR},
            # a node not in maintenance /w no instance and bad power state
            {'uuid': uuidutils.generate_uuid(),
             'power_state': ironic_states.NOSTATE},
        ]
        for n in node_dicts:
            node = ironic_utils.get_test_node(**n)
            self.assertTrue(self.driver._node_resources_unavailable(node))

        avail_node = ironic_utils.get_test_node(
                        power_state=ironic_states.POWER_OFF)
        self.assertFalse(self.driver._node_resources_unavailable(avail_node))

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
        mock_get.assert_called_once_with(node.uuid)

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
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn(self, mock_sf, mock_pvifs, mock_adf, mock_wait_active,
                   mock_fg_bid, mock_node, mock_looping, mock_save):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = {'ephemeral_gb': 0}

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        mock_fg_bid.return_value = fake_flavor

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        self.driver.spawn(self.ctx, instance, None, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_fg_bid.assert_called_once_with(self.ctx,
                                            instance.instance_type_id)
        mock_adf.assert_called_once_with(node, instance, None, fake_flavor)
        mock_pvifs.assert_called_once_with(node, instance, None)
        mock_sf.assert_called_once_with(instance, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'active')

        self.assertIsNone(instance.default_ephemeral_device)
        self.assertFalse(mock_save.called)

        mock_looping.assert_called_once_with(mock_wait_active,
                                             FAKE_CLIENT_WRAPPER,
                                             instance)
        fake_looping_call.start.assert_called_once_with(
            interval=CONF.ironic.api_retry_interval)
        fake_looping_call.wait.assert_called_once_with()

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn_destroyed_after_failure(self, mock_sf, mock_pvifs, mock_adf,
                                           mock_wait_active, mock_destroy,
                                           mock_fg_bid, mock_node,
                                           mock_looping):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        fake_flavor = {'ephemeral_gb': 0}

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        mock_fg_bid.return_value = fake_flavor

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        deploy_exc = exception.InstanceDeployFailure('foo')
        fake_looping_call.wait.side_effect = deploy_exc
        self.assertRaises(
            exception.InstanceDeployFailure,
            self.driver.spawn, self.ctx, instance, None, [], None)
        mock_destroy.assert_called_once_with(self.ctx, instance, None)

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__add_driver_fields_good(self, mock_update):
        node = ironic_utils.get_test_node(driver='fake')
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        image_meta = ironic_utils.get_test_image_meta()
        flavor = ironic_utils.get_test_flavor()
        self.driver._add_driver_fields(node, instance, image_meta, flavor)
        expected_patch = [{'path': '/instance_info/image_source', 'op': 'add',
                           'value': image_meta['id']},
                          {'path': '/instance_info/root_gb', 'op': 'add',
                           'value': str(instance.root_gb)},
                          {'path': '/instance_info/swap_mb', 'op': 'add',
                           'value': str(flavor['swap'])},
                          {'path': '/instance_uuid', 'op': 'add',
                           'value': instance.uuid}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

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

    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_good_with_flavor(self, mock_update):
        node = ironic_utils.get_test_node(driver='fake',
                                          instance_uuid=self.instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        flavor = ironic_utils.get_test_flavor(extra_specs={})
        self.driver._cleanup_deploy(self.ctx, node, instance, None,
                                    flavor=flavor)
        expected_patch = [{'path': '/instance_uuid', 'op': 'remove'}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_without_flavor(self, mock_update, mock_flavor):
        self._get_by_id_reads_deleted = False

        def side_effect(context, id):
            self._get_by_id_reads_deleted = context._read_deleted == 'yes'

        mock_flavor.side_effect = side_effect
        mock_flavor.return_value = ironic_utils.get_test_flavor(extra_specs={})
        node = ironic_utils.get_test_node(driver='fake',
                                          instance_uuid=self.instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver._cleanup_deploy(self.ctx, node, instance, None)

        self.assertTrue(self._get_by_id_reads_deleted,
                        'Flavor.get_by_id was not called with '
                        'read_deleted set in the context')
        expected_patch = [{'path': '/instance_uuid', 'op': 'remove'}]
        mock_update.assert_called_once_with(node.uuid, expected_patch)

    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(FAKE_CLIENT.node, 'update')
    def test__cleanup_deploy_fail(self, mock_update, mock_flavor):
        mock_flavor.return_value = ironic_utils.get_test_flavor(extra_specs={})
        mock_update.side_effect = ironic_exception.BadRequest()
        node = ironic_utils.get_test_node(driver='fake',
                                          instance_uuid=self.instance_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.assertRaises(exception.InstanceTerminationFailure,
                          self.driver._cleanup_deploy,
                          self.ctx, node, instance, None)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    def test_spawn_node_driver_validation_fail(self, mock_flavor, mock_node):
        mock_flavor.return_value = ironic_utils.get_test_flavor()
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.validate.return_value = ironic_utils.get_test_validation(
            power=False, deploy=False)
        mock_node.get.return_value = node
        image_meta = ironic_utils.get_test_image_meta()

        self.assertRaises(exception.ValidationError, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)
        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_with(mock.ANY, instance.instance_type_id)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_prepare_for_deploy_fail(self, mock_cleanup_deploy,
                                                mock_pvifs, mock_sf,
                                                mock_flavor, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        flavor = ironic_utils.get_test_flavor()
        mock_flavor.return_value = flavor
        image_meta = ironic_utils.get_test_image_meta()

        class TestException(Exception):
            pass

        mock_sf.side_effect = TestException()
        self.assertRaises(TestException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance.instance_type_id)
        mock_cleanup_deploy.assert_called_with(self.ctx, node, instance, None,
                                               flavor=flavor)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail(self, mock_cleanup_deploy,
                                            mock_pvifs, mock_sf,
                                            mock_flavor, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        mock_flavor.return_value = flavor
        image_meta = ironic_utils.get_test_image_meta()

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()

        mock_node.set_provision_state.side_effect = exception.NovaException()
        self.assertRaises(exception.NovaException, self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance.instance_type_id)
        mock_cleanup_deploy.assert_called_once_with(self.ctx, node,
                                                    instance, None,
                                                    flavor=flavor)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_spawn_node_trigger_deploy_fail2(self, mock_cleanup_deploy,
                                             mock_pvifs, mock_sf,
                                             mock_flavor, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        flavor = ironic_utils.get_test_flavor()
        mock_flavor.return_value = flavor
        image_meta = ironic_utils.get_test_image_meta()

        mock_node.get.return_value = node
        mock_node.validate.return_value = ironic_utils.get_test_validation()
        mock_node.set_provision_state.side_effect = ironic_exception.BadRequest
        self.assertRaises(ironic_exception.BadRequest,
                          self.driver.spawn,
                          self.ctx, instance, image_meta, [], None)

        mock_node.get.assert_called_once_with(node_uuid)
        mock_node.validate.assert_called_once_with(node_uuid)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance.instance_type_id)
        mock_cleanup_deploy.assert_called_once_with(self.ctx, node,
                                                    instance, None,
                                                    flavor=flavor)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, 'destroy')
    def test_spawn_node_trigger_deploy_fail3(self, mock_destroy,
                                             mock_pvifs, mock_sf,
                                             mock_flavor, mock_node,
                                             mock_looping):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        fake_net_info = utils.get_test_network_info()
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        mock_flavor.return_value = ironic_utils.get_test_flavor()
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
        mock_destroy.assert_called_once_with(self.ctx, instance,
                                             fake_net_info)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(ironic_driver.IronicDriver, '_plug_vifs')
    @mock.patch.object(ironic_driver.IronicDriver, '_start_firewall')
    def test_spawn_sets_default_ephemeral_device(self, mock_sf, mock_pvifs,
                                                 mock_wait, mock_flavor,
                                                 mock_node, mock_save,
                                                 mock_looping):
        mock_flavor.return_value = ironic_utils.get_test_flavor(ephemeral_gb=1)
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)
        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.return_value = mock.MagicMock()
        image_meta = ironic_utils.get_test_image_meta()

        self.driver.spawn(self.ctx, instance, image_meta, [], None)
        mock_flavor.assert_called_once_with(self.ctx,
                                            instance.instance_type_id)
        self.assertTrue(mock_save.called)
        self.assertEqual('/dev/sda1', instance.default_ephemeral_device)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_destroy(self, mock_cleanup_deploy, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = None

        mock_node.get_by_instance_uuid.return_value = node
        mock_node.set_provision_state.side_effect = fake_set_provision_state
        self.driver.destroy(self.ctx, instance, network_info, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)
        mock_cleanup_deploy.assert_called_with(self.ctx, node,
                                               instance, network_info)

    @mock.patch.object(FAKE_CLIENT, 'node')
    @mock.patch.object(ironic_driver.IronicDriver, '_cleanup_deploy')
    def test_destroy_ignore_unexpected_state(self, mock_cleanup_deploy,
                                             mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        network_info = 'foo'

        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                        provision_state=ironic_states.DELETING)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        mock_node.get_by_instance_uuid.return_value = node
        self.driver.destroy(self.ctx, instance, network_info, None)
        self.assertFalse(mock_node.set_provision_state.called)
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)
        mock_cleanup_deploy.assert_called_with(self.ctx, node, instance,
                                               network_info)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
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

    @mock.patch.object(FAKE_CLIENT, 'node')
    def test_destroy_unprovision_fail(self, mock_node):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid,
                                          provision_state=ironic_states.ACTIVE)
        instance = fake_instance.fake_instance_obj(self.ctx, node=node_uuid)

        def fake_set_provision_state(*_):
            node.provision_state = ironic_states.ERROR

        mock_node.get_by_instance_uuid.return_value = node
        self.assertRaises(exception.NovaException, self.driver.destroy,
                          self.ctx, instance, None, None)
        mock_node.set_provision_state.assert_called_once_with(node_uuid,
                                                              'deleted')

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
        mock_node.get_by_instance_uuid.assert_called_with(instance.uuid)

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
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
    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off(self, mock_sp, fake_validate, mock_looping):
        self._test_power_on_off(mock_sp, fake_validate, mock_looping,
                                method_name='power_off')

    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
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
        port = ironic_utils.get_test_port()

        mock_lp.return_value = [port]

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node_uuid)
        network_info = utils.get_test_network_info()

        port_id = unicode(network_info[0]['id'])
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

        mock_get.assert_called_once_with(node_uuid)
        mock__plug_vifs.assert_called_once_with(node, instance, network_info)

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
        mock_node.get.assert_called_once_with(node_uuid)
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

        mock_node.get.assert_called_once_with(node_uuid)
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
                       'refresh_provider_fw_rules', create=True)
    def test_refresh_provider_fw_rules(self, mock_rpfr):
        fake_instance.fake_instance_obj(self.ctx)
        self.driver.refresh_provider_fw_rules()
        mock_rpfr.assert_called_once_with()

    @mock.patch.object(firewall.NoopFirewallDriver,
                       'refresh_security_group_members', create=True)
    def test_refresh_security_group_members(self, mock_rsgm):
        fake_group = 'fake-security-group-members'
        self.driver.refresh_security_group_members(fake_group)
        mock_rsgm.assert_called_once_with(fake_group)

    @mock.patch.object(firewall.NoopFirewallDriver,
                      'refresh_instance_security_rules', create=True)
    def test_refresh_security_group_rules(self, mock_risr):
        fake_group = 'fake-security-group-members'
        self.driver.refresh_instance_security_rules(fake_group)
        mock_risr.assert_called_once_with(fake_group)

    @mock.patch.object(ironic_driver.IronicDriver, '_wait_for_active')
    @mock.patch.object(loopingcall, 'FixedIntervalLoopingCall')
    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def _test_rebuild(self, mock_save, mock_get, mock_driver_fields,
                      mock_fg_bid, mock_set_pstate, mock_looping,
                      mock_wait_active, preserve=False):
        node_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5)
        mock_get.return_value = node

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = {'id': flavor_id, 'name': 'baremetal'}
        mock_fg_bid.return_value = flavor

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_uuid,
                                                   instance_type_id=flavor_id)

        fake_looping_call = FakeLoopingCall()
        mock_looping.return_value = fake_looping_call

        self.driver.rebuild(
            context=self.ctx, instance=instance, image_meta=image_meta,
            injected_files=None, admin_password=None, bdms=None,
            detach_block_devices=None, attach_block_devices=None,
            preserve_ephemeral=preserve)

        mock_save.assert_called_once_with(
            expected_task_state=[task_states.REBUILDING])
        mock_driver_fields.assert_called_once_with(node, instance, image_meta,
                                                   flavor, preserve)
        mock_set_pstate.assert_called_once_with(node_uuid,
                                                ironic_states.REBUILD)
        mock_looping.assert_called_once_with(mock_wait_active,
                                             FAKE_CLIENT_WRAPPER,
                                             instance)
        fake_looping_call.start.assert_called_once_with(
            interval=CONF.ironic.api_retry_interval)
        fake_looping_call.wait.assert_called_once_with()

    def test_rebuild_preserve_ephemeral(self):
        self._test_rebuild(preserve=True)

    def test_rebuild_no_preserve_ephemeral(self):
        self._test_rebuild(preserve=False)

    @mock.patch.object(FAKE_CLIENT.node, 'set_provision_state')
    @mock.patch.object(objects.Flavor, 'get_by_id')
    @mock.patch.object(ironic_driver.IronicDriver, '_add_driver_fields')
    @mock.patch.object(FAKE_CLIENT.node, 'get')
    @mock.patch.object(objects.Instance, 'save')
    def test_rebuild_failures(self, mock_save, mock_get, mock_driver_fields,
                              mock_fg_bid, mock_set_pstate):
        node_uuid = uuidutils.generate_uuid()
        node = ironic_utils.get_test_node(uuid=node_uuid,
                                          instance_uuid=self.instance_uuid,
                                          instance_type_id=5)
        mock_get.return_value = node

        image_meta = ironic_utils.get_test_image_meta()
        flavor_id = 5
        flavor = {'id': flavor_id, 'name': 'baremetal'}
        mock_fg_bid.return_value = flavor

        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=self.instance_uuid,
                                                   node=node_uuid,
                                                   instance_type_id=flavor_id)

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
