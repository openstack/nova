# Copyright 2011 Grid Dynamics
# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
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

import copy
import datetime
import math

import iso8601
import mock
import netaddr
from oslo_config import cfg
from oslo_utils.fixture import uuidsentinel as uuids
import webob

from nova.api.openstack.compute import networks as networks_v21
from nova.api.openstack.compute import networks_associate \
        as networks_associate_v21
import nova.context
from nova import exception
from nova.network import manager
from nova.network.neutronv2 import api as neutron
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
import nova.utils


CONF = cfg.CONF
FAKE_NETWORK_PROJECT_ID = '6133f8b603924f45bc0c9e21f6df12fa'

UTC = iso8601.UTC
FAKE_NETWORKS = [
    {
        'bridge': 'br100', 'vpn_public_port': 1000,
        'dhcp_start': '10.0.0.3', 'bridge_interface': 'eth0',
        'updated_at': datetime.datetime(2011, 8, 16, 9, 26, 13, 48257,
                                        tzinfo=UTC),
        'id': 1, 'uuid': uuids.network_1,
        'cidr_v6': None, 'deleted_at': None,
        'gateway': '10.0.0.1', 'label': 'mynet_0',
        'project_id': FAKE_NETWORK_PROJECT_ID, 'rxtx_base': None,
        'vpn_private_address': '10.0.0.2', 'deleted': False,
        'vlan': 100, 'broadcast': '10.0.0.7',
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.0/29',
        'vpn_public_address': '127.0.0.1', 'multi_host': False,
        'dns1': None, 'dns2': None, 'host': 'nsokolov-desktop',
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': datetime.datetime(2011, 8, 15, 6, 19, 19, 387525,
                                        tzinfo=UTC),
        'mtu': None, 'dhcp_server': '10.0.0.1', 'enable_dhcp': True,
        'share_address': False,
    },
    {
        'bridge': 'br101', 'vpn_public_port': 1001,
        'dhcp_start': '10.0.0.11', 'bridge_interface': 'eth0',
        'updated_at': None, 'id': 2, 'cidr_v6': None,
        'uuid': uuids.network_2,
        'deleted_at': None, 'gateway': '10.0.0.9',
        'label': 'mynet_1', 'project_id': None,
        'vpn_private_address': '10.0.0.10', 'deleted': False,
        'vlan': 101, 'broadcast': '10.0.0.15', 'rxtx_base': None,
        'netmask': '255.255.255.248', 'injected': False,
        'cidr': '10.0.0.10/29', 'vpn_public_address': None,
        'multi_host': False, 'dns1': None, 'dns2': None, 'host': None,
        'gateway_v6': None, 'netmask_v6': None, 'priority': None,
        'created_at': datetime.datetime(2011, 8, 15, 6, 19, 19, 885495,
                                        tzinfo=UTC),
        'mtu': None, 'dhcp_server': '10.0.0.9', 'enable_dhcp': True,
        'share_address': False,
    },
]


FAKE_USER_NETWORKS = [
    {
        'id': 1, 'cidr': '10.0.0.0/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.1', 'broadcast': '10.0.0.7', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_0',
        'netmask_v6': None, 'uuid': uuids.network_1,
    },
    {
        'id': 2, 'cidr': '10.0.0.10/29', 'netmask': '255.255.255.248',
        'gateway': '10.0.0.9', 'broadcast': '10.0.0.15', 'dns1': None,
        'dns2': None, 'cidr_v6': None, 'gateway_v6': None, 'label': 'mynet_1',
        'netmask_v6': None, 'uuid': uuids.network_2,
    },
]

NEW_NETWORK = {
    "network": {
        "bridge_interface": "eth0",
        "cidr": "10.20.105.0/24",
        "label": "new net 111",
        "vlan_start": 111,
        "multi_host": False,
        'dhcp_server': '10.0.0.1',
        'enable_dhcp': True,
        'share_address': False,
    }
}


class FakeNetworkAPI(object):

    _sentinel = object()

    def __init__(self):
        self.networks = copy.deepcopy(FAKE_NETWORKS)

    def delete(self, context, network_id):
        if network_id == 'always_delete':
            return True
        if network_id == -1:
            raise exception.NetworkInUse(network_id=network_id)
        for i, network in enumerate(self.networks):
            if network['id'] == network_id:
                del self.networks[0]
                return True
        raise exception.NetworkNotFoundForUUID(uuid=network_id)

    def disassociate(self, context, network_uuid):
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                network['project_id'] = None
                return True
        raise exception.NetworkNotFound(network_id=network_uuid)

    def associate(self, context, network_uuid, host=_sentinel,
                  project=_sentinel):
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                if host is not FakeNetworkAPI._sentinel:
                    network['host'] = host
                if project is not FakeNetworkAPI._sentinel:
                    network['project_id'] = project
                return True
        raise exception.NetworkNotFound(network_id=network_uuid)

    def add_network_to_project(self, context,
                               project_id, network_uuid=None):
        if network_uuid:
            for network in self.networks:
                if network.get('project_id', None) is None:
                    network['project_id'] = project_id
                    return
            return
        for network in self.networks:
            if network.get('uuid') == network_uuid:
                network['project_id'] = project_id
                return

    def get_all(self, context):
        return self._fake_db_network_get_all(context, project_only=True)

    def _fake_db_network_get_all(self, context, project_only="allow_none"):
        project_id = context.project_id
        nets = self.networks
        if nova.context.is_user_context(context) and project_only:
            if project_only == 'allow_none':
                nets = [n for n in self.networks
                        if (n['project_id'] == project_id or
                            n['project_id'] is None)]
            else:
                nets = [n for n in self.networks
                        if n['project_id'] == project_id]
        objs = [objects.Network._from_db_object(context,
                                                objects.Network(),
                                                net)
                for net in nets]
        return objects.NetworkList(objects=objs)

    def get(self, context, network_id):
        for network in self.networks:
            if network.get('uuid') == network_id:
                if 'injected' in network and network['injected'] is None:
                    # NOTE: This is a workaround for passing unit tests.
                    # When using nova-network, 'injected' value should be
                    # boolean because of the definition of objects.Network().
                    # However, 'injected' value can be None if neutron.
                    # So here changes the value to False just for passing
                    # following _from_db_object().
                    network['injected'] = False
                return objects.Network._from_db_object(context,
                                                       objects.Network(),
                                                       network)
        raise exception.NetworkNotFound(network_id=network_id)

    def create(self, context, **kwargs):
        subnet_bits = int(math.ceil(math.log(kwargs.get(
                        'network_size', CONF.network_size), 2)))
        fixed_net_v4 = netaddr.IPNetwork(kwargs['cidr'])
        prefixlen_v4 = 32 - subnet_bits
        subnets_v4 = list(fixed_net_v4.subnet(
                prefixlen_v4,
                count=kwargs.get('num_networks', CONF.num_networks)))
        new_networks = []
        new_id = max((net['id'] for net in self.networks))
        for index, subnet_v4 in enumerate(subnets_v4):
            new_id += 1
            net = {'id': new_id, 'uuid': uuids.fake}

            net['cidr'] = str(subnet_v4)
            net['netmask'] = str(subnet_v4.netmask)
            net['gateway'] = kwargs.get('gateway') or str(subnet_v4[1])
            net['broadcast'] = str(subnet_v4.broadcast)
            net['dhcp_start'] = str(subnet_v4[2])

            for key in FAKE_NETWORKS[0]:
                net.setdefault(key, kwargs.get(key))
            new_networks.append(net)
        self.networks += new_networks
        return new_networks


# NOTE(vish): tests that network create Exceptions actually return
#             the proper error responses
class NetworkCreateExceptionsTestV21(test.TestCase):
    validation_error = exception.ValidationError

    class PassthroughAPI(object):
        def __init__(self):
            self.network_manager = manager.FlatDHCPManager()

        def create(self, *args, **kwargs):
            if kwargs['label'] == 'fail_NetworkNotCreated':
                raise exception.NetworkNotCreated(req='fake_fail')
            return self.network_manager.create_networks(*args, **kwargs)

    def setUp(self):
        super(NetworkCreateExceptionsTestV21, self).setUp()
        self._setup()
        fakes.stub_out_networking(self)
        self.new_network = copy.deepcopy(NEW_NETWORK)

    def _setup(self):
        self.req = fakes.HTTPRequest.blank('')
        self.controller = networks_v21.NetworkController(self.PassthroughAPI())

    def test_network_create_bad_vlan(self):
        self.new_network['network']['vlan_start'] = 'foo'
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_no_cidr(self):
        del self.new_network['network']['cidr']
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_no_label(self):
        del self.new_network['network']['label']
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_label_too_long(self):
        self.new_network['network']['label'] = "x" * 256
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_invalid_fixed_cidr(self):
        self.new_network['network']['fixed_cidr'] = 'foo'
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_invalid_start(self):
        self.new_network['network']['allowed_start'] = 'foo'
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_bad_cidr(self):
        self.new_network['network']['cidr'] = '128.0.0.0/900'
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_handle_network_not_created(self):
        self.new_network['network']['label'] = 'fail_NetworkNotCreated'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req,
                          body=self.new_network)

    @mock.patch.object(objects.NetworkList, 'get_all')
    def test_network_create_cidr_conflict(self, mock_get_all):
        def fake_get_all(context):
            ret = objects.NetworkList(context=context, objects=[])
            net = objects.Network(cidr='10.0.0.0/23')
            ret.objects.append(net)
            return ret

        mock_get_all.side_effect = fake_get_all

        self.new_network['network']['cidr'] = '10.0.0.0/24'
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create, self.req,
                          body=self.new_network)

    def test_network_create_vlan_conflict(self):

        @staticmethod
        def get_all(context):
            ret = objects.NetworkList(context=context, objects=[])
            net = objects.Network(cidr='10.0.0.0/24', vlan=100)
            ret.objects.append(net)
            return ret

        def fake_create(context):
            raise exception.DuplicateVlan(vlan=100)

        self.stub_out('nova.objects.NetworkList.get_all', get_all)
        self.stub_out('nova.objects.Network.create', fake_create)

        self.new_network['network']['cidr'] = '20.0.0.0/24'
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create, self.req,
                          body=self.new_network)


class NetworksTestV21(test.NoDBTestCase):
    validation_error = exception.ValidationError

    def setUp(self):
        super(NetworksTestV21, self).setUp()
        self.fake_network_api = FakeNetworkAPI()
        self._setup()
        fakes.stub_out_networking(self)
        self.new_network = copy.deepcopy(NEW_NETWORK)
        self.non_admin_req = fakes.HTTPRequest.blank(
            '', project_id=fakes.FAKE_PROJECT_ID)
        self.admin_req = fakes.HTTPRequest.blank('',
                              project_id=fakes.FAKE_PROJECT_ID,
                              use_admin_context=True)

    def _setup(self):
        self.controller = networks_v21.NetworkController(
            self.fake_network_api)
        self.neutron_ctrl = networks_v21.NetworkController(
            neutron.API())
        self.req = fakes.HTTPRequest.blank('',
                                           project_id=fakes.FAKE_PROJECT_ID)

    def _check_status(self, res, method, code):
        self.assertEqual(method.wsgi_code, code)

    @staticmethod
    def network_uuid_to_id(network):
        network['id'] = network['uuid']
        del network['uuid']

    def test_network_list_all_as_user(self):
        self.maxDiff = None
        res_dict = self.controller.index(self.non_admin_req)
        self.assertEqual(res_dict, {'networks': []})

        project_id = self.req.environ["nova.context"].project_id
        cxt = self.req.environ["nova.context"]
        uuid = FAKE_NETWORKS[0]['uuid']
        self.fake_network_api.associate(context=cxt,
                                        network_uuid=uuid,
                                        project=project_id)
        res_dict = self.controller.index(self.non_admin_req)
        expected = [copy.deepcopy(FAKE_USER_NETWORKS[0])]
        for network in expected:
            self.network_uuid_to_id(network)
        self.assertEqual({'networks': expected}, res_dict)

    def test_network_list_all_as_admin(self):
        res_dict = self.controller.index(self.admin_req)
        expected = copy.deepcopy(FAKE_NETWORKS)
        for network in expected:
            self.network_uuid_to_id(network)
        self.assertEqual({'networks': expected}, res_dict)

    def test_network_disassociate(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        disassociate = self.controller._disassociate_host_and_project
        res = disassociate(self.req, uuid, {'disassociate': None})
        self._check_status(res, disassociate, 202)
        self.assertIsNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._disassociate_host_and_project,
                          self.req, 100, {'disassociate': None})

    def test_network_get_as_user(self):
        uuid = FAKE_USER_NETWORKS[0]['uuid']
        res_dict = self.controller.show(self.non_admin_req, uuid)
        expected = {'network': copy.deepcopy(FAKE_USER_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(expected, res_dict)

    def test_network_get_as_admin(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        res_dict = self.controller.show(self.admin_req, uuid)
        expected = {'network': copy.deepcopy(FAKE_NETWORKS[0])}
        self.network_uuid_to_id(expected['network'])
        self.assertEqual(expected, res_dict)

    def test_network_get_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, self.req, 100)

    def test_network_delete(self):
        delete_method = self.controller.delete
        res = delete_method(self.req, 1)
        self._check_status(res, delete_method, 202)

    def test_network_delete_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, self.req, 100)

    def test_network_delete_in_use(self):
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.delete, self.req, -1)

    def test_network_add(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        add = self.controller.add
        res = add(self.req, body={'id': uuid})
        self._check_status(res, add, 202)
        res_dict = self.controller.show(self.admin_req,
                                        uuid)
        self.assertEqual(res_dict['network']['project_id'],
                         fakes.FAKE_PROJECT_ID)

    @mock.patch('nova.tests.unit.api.openstack.compute.test_networks.'
                'FakeNetworkAPI.add_network_to_project',
                side_effect=exception.NoMoreNetworks)
    def test_network_add_no_more_networks_fail(self, mock_add):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.add,
                          self.req, body={'id': uuid})

    @mock.patch('nova.tests.unit.api.openstack.compute.test_networks.'
                'FakeNetworkAPI.add_network_to_project',
                side_effect=exception.
                NetworkNotFoundForUUID(uuid=fakes.FAKE_PROJECT_ID))
    def test_network_add_network_not_found_networks_fail(self, mock_add):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.add,
                          self.req, body={'id': uuid})

    def test_network_add_network_without_body(self):
        self.assertRaises(self.validation_error, self.controller.add,
                          self.req,
                          body=None)

    def test_network_add_network_with_invalid_id(self):
        self.assertRaises(exception.ValidationError, self.controller.add,
                          self.req,
                          body={'id': 123})

    def test_network_add_network_with_extra_arg(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(exception.ValidationError, self.controller.add,
                          self.req,
                          body={'id': uuid,
                                'extra_arg': 123})

    def test_network_add_network_with_none_id(self):
        add = self.controller.add
        res = add(self.req, body={'id': None})
        self._check_status(res, add, 202)

    def test_network_create(self):
        res_dict = self.controller.create(self.req, body=self.new_network)
        self.assertIn('network', res_dict)
        uuid = res_dict['network']['id']
        res_dict = self.controller.show(self.req, uuid)
        self.assertTrue(res_dict['network']['label'].
                        startswith(NEW_NETWORK['network']['label']))

    def test_network_create_large(self):
        self.new_network['network']['cidr'] = '128.0.0.0/4'
        res_dict = self.controller.create(self.req, body=self.new_network)
        self.assertEqual(res_dict['network']['cidr'],
                         self.new_network['network']['cidr'])

    def test_network_neutron_disassociate_not_implemented(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.neutron_ctrl._disassociate_host_and_project,
                          self.req, uuid, {'disassociate': None})


class NetworksAssociateTestV21(test.NoDBTestCase):

    def setUp(self):
        super(NetworksAssociateTestV21, self).setUp()
        self.fake_network_api = FakeNetworkAPI()
        self._setup()
        fakes.stub_out_networking(self)
        self.admin_req = fakes.HTTPRequest.blank('', use_admin_context=True)

    def _setup(self):
        self.controller = networks_v21.NetworkController(self.fake_network_api)
        self.associate_controller = networks_associate_v21\
            .NetworkAssociateActionController(self.fake_network_api)
        self.neutron_assoc_ctrl = (
            networks_associate_v21.NetworkAssociateActionController(
                neutron.API()))
        self.req = fakes.HTTPRequest.blank('')

    def _check_status(self, res, method, code):
        self.assertEqual(method.wsgi_code, code)

    def test_network_disassociate_host_only(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        disassociate = self.associate_controller._disassociate_host_only
        res = disassociate(
            self.req, uuid, {'disassociate_host': None})
        self._check_status(res,
                           disassociate,
                           202)
        self.assertIsNotNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_project_only(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        disassociate = self.associate_controller._disassociate_project_only
        res = disassociate(self.req, uuid, {'disassociate_project': None})
        self._check_status(res, disassociate, 202)
        self.assertIsNone(self.fake_network_api.networks[0]['project_id'])
        self.assertIsNotNone(self.fake_network_api.networks[0]['host'])

    def test_network_disassociate_project_network_delete(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        disassociate = self.associate_controller._disassociate_project_only
        res = disassociate(
            self.req, uuid, {'disassociate_project': None})
        self._check_status(res, disassociate, 202)
        self.assertIsNone(self.fake_network_api.networks[1]['project_id'])
        delete = self.controller.delete
        res = delete(self.req, 1)

        # NOTE: On v2.1 code, delete method doesn't return anything and
        # the status code is decorated on wsgi_code of the method.
        self.assertIsNone(res)
        self.assertEqual(202, delete.wsgi_code)

    def test_network_associate_project_delete_fail(self):
        uuid = FAKE_NETWORKS[0]['uuid']
        req = fakes.HTTPRequest.blank('/v2/1234/os-networks/%s/action' % uuid)
        self.assertRaises(webob.exc.HTTPConflict,
                                    self.controller.delete, req, -1)

    def test_network_associate_with_host(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        associate = self.associate_controller._associate_host
        res = associate(self.req, uuid, body={'associate_host': "TestHost"})
        self._check_status(res, associate, 202)
        res_dict = self.controller.show(self.admin_req, uuid)
        self.assertEqual(res_dict['network']['host'], 'TestHost')

    def test_network_neutron_associate_not_implemented(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.neutron_assoc_ctrl._associate_host,
                          self.req, uuid, body={'associate_host': "TestHost"})

    def _test_network_neutron_associate_host_validation_failed(self, body):
        uuid = FAKE_NETWORKS[1]['uuid']

        self.assertRaises(exception.ValidationError,
                          self.associate_controller._associate_host,
                          self.req, uuid, body=body)

    def test_network_neutron_associate_host_non_string(self):
        self._test_network_neutron_associate_host_validation_failed(
                                            {'associate_host': 123})

    def test_network_neutron_associate_host_empty_body(self):
        self._test_network_neutron_associate_host_validation_failed({})

    def test_network_neutron_associate_bad_associate_host_key(self):
        self._test_network_neutron_associate_host_validation_failed(
                                            {'badassociate_host': "TestHost"})

    def test_network_neutron_associate_host_extra_arg(self):
        self._test_network_neutron_associate_host_validation_failed(
                                            {'associate_host': "TestHost",
                                             'extra_arg': "extra_arg"})

    def test_network_neutron_disassociate_project_not_implemented(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.neutron_assoc_ctrl._disassociate_project_only,
                          self.req, uuid, {'disassociate_project': None})

    def test_network_neutron_disassociate_host_not_implemented(self):
        uuid = FAKE_NETWORKS[1]['uuid']
        self.assertRaises(webob.exc.HTTPNotImplemented,
                          self.neutron_assoc_ctrl._disassociate_host_only,
                          self.req, uuid, {'disassociate_host': None})


class NetworksEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(NetworksEnforcementV21, self).setUp()
        self.controller = networks_v21.NetworkController()
        self.req = fakes.HTTPRequest.blank('')

    def test_show_policy_failed(self):
        rule_name = 'os_compute_api:os-networks:view'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        rule_name = 'os_compute_api:os-networks:view'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_create_policy_failed(self):
        rule_name = 'os_compute_api:os-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.create, self.req, body=NEW_NETWORK)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_policy_failed(self):
        rule_name = 'os_compute_api:os-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_add_policy_failed(self):
        rule_name = 'os_compute_api:os-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.add, self.req,
            body={'id': fakes.FAKE_UUID})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_disassociate_policy_failed(self):
        rule_name = 'os_compute_api:os-networks'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._disassociate_host_and_project,
            self.req, fakes.FAKE_UUID, body={'network': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class NetworksAssociateEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(NetworksAssociateEnforcementV21, self).setUp()
        self.controller = (networks_associate_v21.
                           NetworkAssociateActionController())
        self.req = fakes.HTTPRequest.blank('')

    def test_disassociate_host_policy_failed(self):
        rule_name = 'os_compute_api:os-networks-associate'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._disassociate_host_only,
            self.req, fakes.FAKE_UUID, body={'disassociate_host': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_disassociate_project_only_policy_failed(self):
        rule_name = 'os_compute_api:os-networks-associate'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._disassociate_project_only,
            self.req, fakes.FAKE_UUID, body={'disassociate_project': {}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_disassociate_host_only_policy_failed(self):
        rule_name = 'os_compute_api:os-networks-associate'
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._associate_host,
            self.req, fakes.FAKE_UUID, body={'associate_host': 'fake_host'})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class NetworksDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(NetworksDeprecationTest, self).setUp()
        self.controller = networks_v21.NetworkController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_api_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._disassociate_host_and_project, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.add, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})


class NetworksAssociateDeprecationTest(test.NoDBTestCase):

    def setUp(self):
        super(NetworksAssociateDeprecationTest, self).setUp()
        self.controller = networks_associate_v21\
            .NetworkAssociateActionController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_api_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._associate_host, self.req, fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._disassociate_project_only, self.req,
            fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._disassociate_host_only, self.req,
            fakes.FAKE_UUID, {})
