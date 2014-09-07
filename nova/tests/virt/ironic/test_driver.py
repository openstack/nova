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

from nova.compute import power_state as nova_states
from nova import context as nova_context
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
from nova.tests import utils
from nova.tests.virt.ironic import utils as ironic_utils
from nova.tests.virt import test_driver
from nova.virt import fake
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
class IronicDriverTestCase(test.NoDBTestCase, test_driver.DriverAPITestHelper):

    def setUp(self):
        super(IronicDriverTestCase, self).setUp()
        self.flags(**IRONIC_FLAGS)
        self.driver = ironic_driver.IronicDriver(None)
        self.driver.virtapi = fake.FakeVirtAPI()
        self.ctx = nova_context.get_admin_context()

        # mock retries configs to avoid sleeps and make tests run quicker
        CONF.set_default('api_max_retries', default=1, group='ironic')
        CONF.set_default('api_retry_interval', default=0, group='ironic')

    def test_public_api_signatures(self):
        self.assertPublicAPISignatures(self.driver)

    def test_validate_driver_loading(self):
        self.assertIsInstance(self.driver, ironic_driver.IronicDriver)

    def test__get_hypervisor_type(self):
        self.assertEqual('ironic', self.driver._get_hypervisor_type())

    def test__get_hypervisor_version(self):
        self.assertEqual(1, self.driver._get_hypervisor_version())

    def test__node_resource_canonicalizes_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        props['cpu_arch'] = 'i386'
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual('i686',
                         jsonutils.loads(result['supported_instances'])[0][0])

    def test__node_resource_unknown_arch(self):
        node_uuid = uuidutils.generate_uuid()
        props = _get_properties()
        del props['cpu_arch']
        node = ironic_utils.get_test_node(uuid=node_uuid, properties=props)

        result = self.driver._node_resource(node)
        self.assertEqual([], jsonutils.loads(result['supported_instances']))

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists(self, mock_call):
        instance_uuid = 'fake-uuid'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        self.assertTrue(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          instance_uuid)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    def test_instance_exists_fail(self, mock_call):
        mock_call.side_effect = ironic_exception.NotFound
        instance_uuid = 'fake-uuid'
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   uuid=instance_uuid)
        self.assertFalse(self.driver.instance_exists(instance))
        mock_call.assert_called_once_with('node.get_by_instance_uuid',
                                          instance_uuid)

    @mock.patch.object(cw.IronicClientWrapper, 'call')
    @mock.patch.object(instance_obj.Instance, 'get_by_uuid')
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
        mock_call.assert_called_with("node.list", associated=True)
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
        mock_call.assert_called_with('node.list', associated=True)
        expected = [n.instance_uuid for n in nodes]
        self.assertEqual(sorted(expected), sorted(uuids))

    @mock.patch.object(FAKE_CLIENT.node, 'get')
    def test_node_is_available(self, mock_get):
        node = ironic_utils.get_test_node()
        mock_get.return_value = node
        self.assertTrue(self.driver.node_is_available(node.uuid))
        mock_get.assert_called_with(node.uuid)

        mock_get.side_effect = ironic_exception.NotFound
        self.assertFalse(self.driver.node_is_available(node.uuid))

    @mock.patch.object(FAKE_CLIENT.node, 'list')
    def test_get_available_nodes(self, mock_list):
        node_dicts = [
            # a node in maintenance /w no instance and power OFF
            {'uuid': uuidutils.generate_uuid(),
             'maintenance': True,
             'power_state': ironic_states.POWER_OFF},
            # a node /w instance and power ON
            {'uuid': uuidutils.generate_uuid(),
             'instance_uuid': uuidutils.generate_uuid(),
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
    @mock.patch.object(ironic_driver.IronicDriver, '_node_resource')
    def test_get_available_resource(self, mock_nr, mock_get):
        node = ironic_utils.get_test_node()
        fake_resource = 'fake-resource'
        mock_get.return_value = node
        mock_nr.return_value = fake_resource
        result = self.driver.get_available_resource(node.uuid)
        self.assertEqual(fake_resource, result)
        mock_nr.assert_called_once_with(node)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info(self, mock_gbiu):
        instance_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        properties = {'memory_mb': 512, 'cpus': 2}
        power_state = ironic_states.POWER_ON
        node = ironic_utils.get_test_node(instance_uuid=instance_uuid,
                                          properties=properties,
                                          power_state=power_state)

        mock_gbiu.return_value = node

        # ironic_states.POWER_ON should be mapped to
        # nova_states.RUNNING
        memory_kib = properties['memory_mb'] * 1024
        expected = {'state': nova_states.RUNNING,
                    'max_mem': memory_kib,
                    'mem': memory_kib,
                    'num_cpu': properties['cpus'],
                    'cpu_time': 0}
        instance = fake_instance.fake_instance_obj('fake-context',
                                                   uuid=instance_uuid)
        result = self.driver.get_info(instance)
        self.assertEqual(expected, result)

    @mock.patch.object(FAKE_CLIENT.node, 'get_by_instance_uuid')
    def test_get_info_http_not_found(self, mock_gbiu):
        mock_gbiu.side_effect = ironic_exception.NotFound()

        expected = {'state': nova_states.NOSTATE,
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 0,
                    'cpu_time': 0}
        instance = fake_instance.fake_instance_obj(
                                  self.ctx, uuid=uuidutils.generate_uuid())
        result = self.driver.get_info(instance)
        self.assertEqual(expected, result)

    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    def test_reboot(self, mock_val_inst, mock_set_power):
        node = ironic_utils.get_test_node()
        mock_val_inst.return_value = node
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=node.uuid)
        self.driver.reboot(self.ctx, instance, None, None)
        mock_set_power.assert_called_once_with(node.uuid, 'reboot')

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_off(self, mock_sp, fake_validate):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        fake_validate.return_value = node
        instance_uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=instance_uuid)

        self.driver.power_off(instance)
        mock_sp.assert_called_once_with(node_uuid, 'off')

    @mock.patch.object(ironic_driver, '_validate_instance_and_node')
    @mock.patch.object(FAKE_CLIENT.node, 'set_power_state')
    def test_power_on(self, mock_sp, fake_validate):
        node_uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        node = ironic_utils.get_test_node(driver='fake', uuid=node_uuid)

        fake_validate.return_value = node

        instance_uuid = uuidutils.generate_uuid()
        instance = fake_instance.fake_instance_obj(self.ctx,
                                                   node=instance_uuid)

        self.driver.power_on(self.ctx, instance,
                             utils.get_test_network_info())
        mock_sp.assert_called_once_with(node_uuid, 'on')
