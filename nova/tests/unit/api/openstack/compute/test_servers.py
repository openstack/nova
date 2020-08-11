# Copyright 2010-2011 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc.
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

import collections
import copy
import datetime
import ddt
import functools

import fixtures
import iso8601
import mock
from oslo_policy import policy as oslo_policy
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import fixture as utils_fixture
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from six.moves import range
import six.moves.urllib.parse as urlparse
import testtools
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack import compute
from nova.api.openstack.compute import ips
from nova.api.openstack.compute.schemas import servers as servers_schema
from nova.api.openstack.compute import servers
from nova.api.openstack.compute import views
from nova.api.openstack import wsgi as os_wsgi
from nova import availability_zones
from nova import block_device
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import context
from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import models
from nova import exception
from nova.image import glance
from nova import objects
from nova.objects import instance as instance_obj
from nova.objects.instance_group import InstanceGroup
from nova.objects import tag
from nova.policies import servers as server_policies
from nova import policy
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_flavor
from nova.tests.unit import fake_instance
from nova.tests.unit import matchers
from nova import utils as nova_utils


CONF = nova.conf.CONF

FAKE_UUID = fakes.FAKE_UUID

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'

INSTANCE_IDS = {FAKE_UUID: 1}
FIELDS = instance_obj.INSTANCE_DEFAULT_FIELDS

GET_ONLY_FIELDS = ['OS-EXT-AZ:availability_zone', 'config_drive',
                   'OS-EXT-SRV-ATTR:host',
                   'OS-EXT-SRV-ATTR:hypervisor_hostname',
                   'OS-EXT-SRV-ATTR:instance_name',
                   'OS-EXT-SRV-ATTR:hostname',
                   'OS-EXT-SRV-ATTR:kernel_id',
                   'OS-EXT-SRV-ATTR:launch_index',
                   'OS-EXT-SRV-ATTR:ramdisk_id',
                   'OS-EXT-SRV-ATTR:reservation_id',
                   'OS-EXT-SRV-ATTR:root_device_name',
                   'OS-EXT-SRV-ATTR:user_data', 'host_status',
                   'key_name', 'OS-SRV-USG:launched_at',
                   'OS-SRV-USG:terminated_at',
                   'OS-EXT-STS:task_state', 'OS-EXT-STS:vm_state',
                   'OS-EXT-STS:power_state', 'security_groups',
                   'os-extended-volumes:volumes_attached']


def instance_update_and_get_original(context, instance_uuid, values,
                                     columns_to_join=None,
                                     ):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return (inst, inst)


def instance_update(context, instance_uuid, values):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return inst


def fake_compute_api(cls, req, id):
    return True


def fake_start_stop_not_ready(self, context, instance):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_start_stop_invalid_state(self, context, instance):
    raise exception.InstanceInvalidState(
        instance_uuid=instance['uuid'], attr='fake_attr',
        method='fake_method', state='fake_state')


def fake_instance_get_by_uuid_not_found(context, uuid,
                                        columns_to_join, use_slave=False):
    raise exception.InstanceNotFound(instance_id=uuid)


def fake_instance_get_all_with_locked(context, list_locked, **kwargs):
    obj_list = []
    s_id = 0
    for locked in list_locked:
        uuid = fakes.get_fake_uuid(locked)
        s_id = s_id + 1
        kwargs['locked_by'] = None if locked == 'not_locked' else locked
        server = fakes.stub_instance_obj(context, id=s_id, uuid=uuid, **kwargs)
        obj_list.append(server)
    return objects.InstanceList(objects=obj_list)


def fake_instance_get_all_with_description(context, list_desc, **kwargs):
    obj_list = []
    s_id = 0
    for desc in list_desc:
        uuid = fakes.get_fake_uuid(desc)
        s_id = s_id + 1
        kwargs['display_description'] = desc
        server = fakes.stub_instance_obj(context, id=s_id, uuid=uuid, **kwargs)
        obj_list.append(server)
    return objects.InstanceList(objects=obj_list)


def fake_compute_get_empty_az(*args, **kwargs):
    inst = fakes.stub_instance(vm_state=vm_states.ACTIVE,
                               availability_zone='')
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_bdms_get_all_by_instance_uuids(*args, **kwargs):
    return [
        fake_block_device.FakeDbBlockDeviceDict({
            'id': 1,
            'volume_id': 'some_volume_1',
            'instance_uuid': FAKE_UUID,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': True,
        }),
        fake_block_device.FakeDbBlockDeviceDict({
            'id': 2,
            'volume_id': 'some_volume_2',
            'instance_uuid': FAKE_UUID,
            'source_type': 'volume',
            'destination_type': 'volume',
            'delete_on_termination': False,
        }),
    ]


def fake_get_inst_mappings_by_instance_uuids_from_db(*args, **kwargs):
    return [{
        'id': 1,
        'instance_uuid': UUID1,
        'cell_mapping': {
            'id': 1, 'uuid': uuids.cell1, 'name': 'fake',
            'transport_url': 'fake://nowhere/', 'updated_at': None,
            'database_connection': uuids.cell1, 'created_at': None,
            'disabled': False},
        'project_id': 'fake-project'
    }]


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class ControllerTest(test.TestCase):
    project_id = fakes.FAKE_PROJECT_ID
    path = '/%s/servers' % project_id
    path_v2 = '/v2' + path
    path_with_id = path + '/%s'
    path_with_id_v2 = path_v2 + '/%s'
    path_with_query = path + '?%s'
    path_detail = path + '/detail'
    path_detail_v2 = path_v2 + '/detail'
    path_detail_with_query = path_detail + '?%s'
    path_action = path + '/%s/action'

    def setUp(self):
        super(ControllerTest, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_key_pair_funcs(self)
        self.useFixture(nova_fixtures.GlanceFixture(self))
        fakes.stub_out_secgroup_api(
            self, security_groups=[{'name': 'default'}])
        return_server = fakes.fake_compute_get(id=2, availability_zone='nova',
                                               launched_at=None,
                                               terminated_at=None,
                                               task_state=None,
                                               vm_state=vm_states.ACTIVE,
                                               power_state=1)
        return_servers = fakes.fake_compute_get_all()
        # Server sort keys extension is enabled in v21 so sort data is passed
        # to the instance API and the sorted DB API is invoked
        self.mock_get_all = self.useFixture(fixtures.MockPatchObject(
            compute_api.API, 'get_all', side_effect=return_servers)).mock
        self.mock_get = self.useFixture(fixtures.MockPatchObject(
            compute_api.API, 'get', side_effect=return_server)).mock
        self.stub_out('nova.db.api.instance_update_and_get_original',
                      instance_update_and_get_original)
        self.stub_out('nova.db.api.'
                      'block_device_mapping_get_all_by_instance_uuids',
                      fake_bdms_get_all_by_instance_uuids)
        self.stub_out('nova.objects.InstanceMappingList.'
                      '_get_by_instance_uuids_from_db',
                      fake_get_inst_mappings_by_instance_uuids_from_db)
        self.flags(group='glance', api_servers=['http://localhost:9292'])

        self.controller = servers.ServersController()
        self.ips_controller = ips.IPsController()
        # Assume that anything that hits the compute API and looks for a
        # RequestSpec doesn't care about it, since testing logic that deep
        # should be done in nova.tests.unit.compute.test_api.
        mock_reqspec = mock.patch('nova.objects.RequestSpec')
        mock_reqspec.start()
        self.addCleanup(mock_reqspec.stop)
        # Similarly we shouldn't care about anything hitting conductor from
        # these tests.
        mock_conductor = mock.patch.object(
            self.controller.compute_api, 'compute_task_api')
        mock_conductor.start()
        self.addCleanup(mock_conductor.stop)


class ServersControllerTest(ControllerTest):
    wsgi_api_version = os_wsgi.DEFAULT_API_VERSION

    def setUp(self):
        super(ServersControllerTest, self).setUp()
        self.request = fakes.HTTPRequest.blank(
            self.path_with_id_v2 % FAKE_UUID,
            use_admin_context=False,
            version=self.wsgi_api_version)
        return_server = fakes.fake_compute_get(
            id=2, availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=self.request.environ['nova.context'].project_id)
        self.mock_get.side_effect = return_server

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    @mock.patch('nova.objects.Instance.get_by_uuid')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_instance_lookup_targets(self, mock_get_im, mock_get_inst):
        ctxt = context.RequestContext('fake', self.project_id)
        mock_get_im.return_value.cell_mapping.database_connection = uuids.cell1
        self.controller._get_instance(ctxt, 'foo')
        mock_get_im.assert_called_once_with(ctxt, 'foo')
        self.assertIsNotNone(ctxt.db_connection)

    def test_requested_networks_prefix(self):
        """Tests that we no longer support the legacy br-<uuid> format for
        a network id.
        """
        uuid = 'br-00000000-0000-0000-0000-000000000000'
        requested_networks = [{'uuid': uuid}]
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller._get_requested_networks,
                               requested_networks)
        self.assertIn('Bad networks format: network uuid is not in proper '
                      'format', six.text_type(ex))

    def test_requested_networks_enabled_with_port(self):
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual([(None, None, port, None)], res.as_tuples())

    def test_requested_networks_enabled_with_network(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual([(network, None, None, None)], res.as_tuples())

    def test_requested_networks_enabled_with_network_and_port(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual([(None, None, port, None)], res.as_tuples())

    def test_requested_networks_with_and_duplicate_networks(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}, {'uuid': network}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual([(network, None, None, None),
                          (network, None, None, None)], res.as_tuples())

    def test_requested_networks_enabled_conflict_on_fixed_ip(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        addr = '10.0.0.1'
        requested_networks = [{'uuid': network,
                               'fixed_ip': addr,
                               'port': port}]
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller._get_requested_networks,
            requested_networks)

    def test_requested_networks_api_enabled_with_v2_subclass(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual([(None, None, port, None)], res.as_tuples())

    def test_get_server_by_uuid(self):
        res_dict = self.controller.show(self.request, FAKE_UUID)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)

    def test_get_server_joins(self):
        def fake_get(*args, **kwargs):
            expected_attrs = kwargs['expected_attrs']
            self.assertEqual(['flavor', 'info_cache', 'metadata',
                              'numa_topology'], expected_attrs)
            ctxt = context.RequestContext('fake', self.project_id)
            return fake_instance.fake_instance_obj(
                ctxt, expected_attrs=expected_attrs,
                project_id=self.request.environ['nova.context'].project_id)
        self.mock_get.side_effect = fake_get

        self.controller.show(self.request, FAKE_UUID)

    def test_unique_host_id(self):
        """Create two servers with the same host and different
        project_ids and check that the host_id's are unique.
        """
        def return_instance_with_host(context, *args, **kwargs):
            project_id = context.project_id
            return fakes.stub_instance_obj(context, id=1, uuid=FAKE_UUID,
                                           project_id=project_id,
                                           host='fake_host')

        req1 = self.req(self.path_with_id % FAKE_UUID)
        project_id = uuidutils.generate_uuid()
        req2 = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID,
                                       version=self.wsgi_api_version,
                                       project_id=project_id)

        self.mock_get.side_effect = return_instance_with_host
        server1 = self.controller.show(req1, FAKE_UUID)
        server2 = self.controller.show(req2, FAKE_UUID)

        self.assertNotEqual(server1['server']['hostId'],
                            server2['server']['hostId'])

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        return {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "created": "2010-10-10T12:00:00Z",
                "updated": "2010-11-11T11:00:00Z",
                "progress": progress,
                "name": "server2",
                "status": status,
                "hostId": '',
                "image": {
                    "id": "10",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "2",
                  "links": [
                      {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'}
                    ]
                },
                "metadata": {
                    "seq": "2",
                },
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost%s/%s" % (self.path_v2, uuid),
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost%s/%s" % (self.path, uuid),
                    },
                ],
                "OS-DCF:diskConfig": "MANUAL",
                "accessIPv4": '',
                "accessIPv6": '',
                "OS-EXT-AZ:availability_zone": "nova",
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000002",
                "key_name": '',
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ACTIVE,
                "OS-EXT-STS:power_state": 1,
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1'},
                    {'id': 'some_volume_2'},
                ],
                "tenant_id": self.request.environ['nova.context'].project_id
            }
        }

    def test_get_server_by_id(self):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id

        uuid = FAKE_UUID
        res_dict = self.controller.show(self.request, uuid)

        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        expected_server['server']['tenant_id'] = self.request.environ[
                'nova.context'].project_id
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_empty_az(self):
        uuid = FAKE_UUID
        req = self.req(self.path_with_id_v2 % uuid)

        self.mock_get.side_effect = fakes.fake_compute_get(
            availability_zone='',
            project_id=req.environ['nova.context'].project_id)
        res_dict = self.controller.show(req, uuid)
        self.assertEqual(res_dict['server']['OS-EXT-AZ:availability_zone'], '')

    def test_get_server_with_active_status_by_id(self):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id

        res_dict = self.controller.show(self.request, FAKE_UUID)
        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        expected_server['server']['tenant_id'] = self.request.environ[
                'nova.context'].project_id

        self.assertThat(res_dict, matchers.DictMatches(expected_server))
        self.mock_get.assert_called_once_with(
            self.request.environ['nova.context'], FAKE_UUID,
            expected_attrs=['flavor', 'info_cache', 'metadata',
                            'numa_topology'], cell_down_support=False)

    def test_get_server_with_id_image_ref_by_id(self):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id

        res_dict = self.controller.show(self.request, FAKE_UUID)
        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        expected_server['server']['tenant_id'] = self.request.environ[
                'nova.context'].project_id

        self.assertThat(res_dict, matchers.DictMatches(expected_server))
        self.mock_get.assert_called_once_with(
            self.request.environ['nova.context'], FAKE_UUID,
            expected_attrs=['flavor', 'info_cache', 'metadata',
                            'numa_topology'], cell_down_support=False)

    def _generate_nw_cache_info(self):
        pub0 = ('172.19.0.1', '172.19.0.2',)
        pub1 = ('1.2.3.4',)
        pub2 = ('b33f::fdee:ddff:fecc:bbaa',)
        priv0 = ('192.168.0.3', '192.168.0.4',)

        def _ip(ip):
            return {'address': ip, 'type': 'fixed'}

        nw_cache = [
            {'address': 'aa:aa:aa:aa:aa:aa',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'public',
                         'subnets': [{'cidr': '172.19.0.0/24',
                                      'ips': [_ip(ip) for ip in pub0]},
                                      {'cidr': '1.2.3.0/16',
                                       'ips': [_ip(ip) for ip in pub1]},
                                      {'cidr': 'b33f::/64',
                                       'ips': [_ip(ip) for ip in pub2]}]}},
            {'address': 'bb:bb:bb:bb:bb:bb',
             'id': 2,
             'network': {'bridge': 'br1',
                         'id': 2,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip(ip) for ip in priv0]}]}}]
        return nw_cache

    def test_get_server_addresses_from_cache(self):
        nw_cache = self._generate_nw_cache_info()
        self.mock_get.side_effect = fakes.fake_compute_get(nw_cache=nw_cache,
            availability_zone='nova')

        req = self.req((self.path_with_id % FAKE_UUID) + '/ips')
        res_dict = self.ips_controller.index(req, FAKE_UUID)

        expected = {
            'addresses': {
                'private': [
                    {'version': 4, 'addr': '192.168.0.3'},
                    {'version': 4, 'addr': '192.168.0.4'},
                ],
                'public': [
                    {'version': 4, 'addr': '172.19.0.1'},
                    {'version': 4, 'addr': '172.19.0.2'},
                    {'version': 4, 'addr': '1.2.3.4'},
                    {'version': 6, 'addr': 'b33f::fdee:ddff:fecc:bbaa'},
                ],
            },
        }
        self.assertThat(res_dict, matchers.DictMatches(expected))
        self.mock_get.assert_called_once_with(
            req.environ['nova.context'], FAKE_UUID,
            expected_attrs=None, cell_down_support=False)
        # Make sure we kept the addresses in order
        self.assertIsInstance(res_dict['addresses'], collections.OrderedDict)
        labels = [vif['network']['label'] for vif in nw_cache]
        for index, label in enumerate(res_dict['addresses'].keys()):
            self.assertEqual(label, labels[index])

    def test_get_server_addresses_nonexistent_network(self):
        url = ((self.path_with_id_v2 % FAKE_UUID) + '/ips/network_0')
        req = self.req(url)
        self.assertRaises(webob.exc.HTTPNotFound, self.ips_controller.show,
                          req, FAKE_UUID, 'network_0')

    def test_get_server_addresses_nonexistent_server(self):
        self.mock_get.side_effect = exception.InstanceNotFound(
            instance_id='fake')
        req = self.req((self.path_with_id % uuids.fake) + '/ips')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.ips_controller.index, req, uuids.fake)
        self.mock_get.assert_called_once_with(
            req.environ['nova.context'], uuids.fake, expected_attrs=None,
            cell_down_support=False)

    def test_show_server_hide_addresses_in_building(self):
        uuid = FAKE_UUID
        req = self.req(self.path_with_id_v2 % uuid)
        self.mock_get.side_effect = fakes.fake_compute_get(
            uuid=uuid, vm_state=vm_states.BUILDING,
            project_id=req.environ['nova.context'].project_id)
        res_dict = self.controller.show(req, uuid)
        self.assertEqual({}, res_dict['server']['addresses'])

    def test_show_server_addresses_in_non_building(self):
        uuid = FAKE_UUID
        nw_cache = self._generate_nw_cache_info()
        expected = {
            'addresses': {
                'private': [
                    {'version': 4, 'addr': '192.168.0.3',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'},
                    {'version': 4, 'addr': '192.168.0.4',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'},
                ],
                'public': [
                    {'version': 4, 'addr': '172.19.0.1',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '172.19.0.2',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '1.2.3.4',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 6, 'addr': 'b33f::fdee:ddff:fecc:bbaa',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                ],
            },
        }
        req = self.req(self.path_with_id_v2 % uuid)
        self.mock_get.side_effect = fakes.fake_compute_get(
            nw_cache=nw_cache, uuid=uuid, vm_state=vm_states.ACTIVE,
            project_id=req.environ['nova.context'].project_id)
        res_dict = self.controller.show(req, uuid)
        self.assertThat(res_dict['server']['addresses'],
                        matchers.DictMatches(expected['addresses']))

    def test_detail_server_hide_addresses(self):
        nw_cache = self._generate_nw_cache_info()
        expected = {
            'addresses': {
                'private': [
                    {'version': 4, 'addr': '192.168.0.3',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'},
                    {'version': 4, 'addr': '192.168.0.4',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'},
                ],
                'public': [
                    {'version': 4, 'addr': '172.19.0.1',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '172.19.0.2',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '1.2.3.4',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 6, 'addr': 'b33f::fdee:ddff:fecc:bbaa',
                     'OS-EXT-IPS:type': 'fixed',
                     'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                ],
            },
        }

        def fake_get_all(context, **kwargs):
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(1,
                                                 vm_state=vm_states.BUILDING,
                                                 uuid=uuids.fake,
                                                 nw_cache=nw_cache),
                         fakes.stub_instance_obj(2,
                                                 vm_state=vm_states.ACTIVE,
                                                 uuid=uuids.fake2,
                                                 nw_cache=nw_cache)])

        self.mock_get_all.side_effect = fake_get_all
        req = self.req(self.path_with_query % 'deleted=true',
                       use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        for server in servers:
            if server['OS-EXT-STS:vm_state'] == 'building':
                self.assertEqual({}, server['addresses'])
            else:
                self.assertThat(server['addresses'],
                                matchers.DictMatches(expected['addresses']))

    def test_get_server_list_empty(self):
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = objects.InstanceList(objects=[])
        req = self.req(self.path)
        res_dict = self.controller.index(req)

        self.assertEqual(0, len(res_dict['servers']))
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'], expected_attrs=[], limit=1000,
            marker=None, search_opts={'deleted': False,
                                      'project_id': self.project_id},
            sort_dirs=['desc'], sort_keys=['created_at'],
            cell_down_support=False, all_tenants=False)

    def test_get_server_list_with_reservation_id(self):
        req = self.req(self.path_with_query % 'reservation_id=foo')
        res_dict = self.controller.index(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_empty(self):
        req = self.req(self.path_detail_with_query % 'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_details(self):
        req = self.req(self.path_detail_with_query % 'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list(self):
        req = self.req(self.path)
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['servers']), 5)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertIsNone(s.get('image', None))

            expected_links = [
                {
                    "rel": "self",
                    "href": "http://localhost" + (
                                 self.path_with_id_v2 % s['id']),
                },
                {
                    "rel": "bookmark",
                    "href": "http://localhost" + (
                                self.path_with_id % s['id']),
                },
            ]

            self.assertEqual(s['links'], expected_links)

    def test_get_servers_with_limit(self):
        req = self.req(self.path_with_query % 'limit=3')
        res_dict = self.controller.index(req)

        servers = res_dict['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in range(len(servers))])

        servers_links = res_dict['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')
        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v2' + self.path,
                         href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected_params = {'limit': ['3'],
                           'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected_params))

    def test_get_servers_with_limit_bad_value(self):
        req = self.req(self.path_with_query % 'limit=aaa')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_server_details_empty(self):
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = objects.InstanceList(objects=[])
        req = self.req(self.path_detail)
        expected_attrs = ['flavor', 'info_cache', 'metadata']
        if api_version_request.is_supported(req, '2.16'):
            expected_attrs.append('services')

        res_dict = self.controller.detail(req)

        self.assertEqual(0, len(res_dict['servers']))
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'],
            expected_attrs=sorted(expected_attrs),
            limit=1000, marker=None,
            search_opts={'deleted': False, 'project_id': self.project_id},
            sort_dirs=['desc'], sort_keys=['created_at'],
            cell_down_support=False, all_tenants=False)

    def test_get_server_details_with_bad_name(self):
        req = self.req(self.path_detail_with_query % 'name=%2Binstance')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_server_details_with_limit(self):
        req = self.req(self.path_detail_with_query % 'limit=3')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in range(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual(self.path_detail_v2, href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected = {'limit': ['3'], 'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_server_details_with_limit_bad_value(self):
        req = self.req(self.path_detail_with_query % 'limit=aaa')
        self.assertRaises(exception.ValidationError,
                          self.controller.detail, req)

    def test_get_server_details_with_limit_and_other_params(self):
        req = self.req(self.path_detail_with_query %
                       'limit=3&blah=2:t&sort_key=uuid&sort_dir=asc')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in range(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual(self.path_detail_v2, href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected = {'limit': ['3'],
                    'sort_key': ['uuid'], 'sort_dir': ['asc'],
                    'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_servers_with_too_big_limit(self):
        req = self.req(self.path_with_query % 'limit=30')
        res_dict = self.controller.index(req)
        self.assertNotIn('servers_links', res_dict)

    def test_get_servers_with_bad_limit(self):
        req = self.req(self.path_with_query % 'limit=asdf')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_servers_with_marker(self):
        url = '%s?marker=%s' % (self.path_v2, fakes.get_fake_uuid(2))
        req = self.req(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ["server4", "server5"])

    def test_get_servers_with_limit_and_marker(self):
        url = '%s?limit=2&marker=%s' % (self.path_v2,
                                        fakes.get_fake_uuid(1))
        req = self.req(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ['server3', 'server4'])

    def test_get_servers_with_bad_marker(self):
        req = self.req(self.path_with_query % 'limit=2&marker=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_invalid_filter_param(self):
        req = self.req(self.path_with_query % 'info_cache=asdf',
                       use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)
        req = self.req(self.path_with_query % '__foo__=asdf',
                       use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_invalid_regex_filter_param(self):
        req = self.req(self.path_with_query % 'flavor=[[[',
                       use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_servers_with_empty_regex_filter_param(self):
        req = self.req(self.path_with_query % 'flavor=',
                       use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_servers_detail_with_empty_regex_filter_param(self):
        req = self.req(self.path_detail_with_query % 'flavor=',
                       use_admin_context=True)
        self.assertRaises(exception.ValidationError,
                          self.controller.detail, req)

    def test_get_servers_invalid_sort_key(self):
        # "hidden" is a real field for instances but not exposed in the API.
        req = self.req(self.path_with_query %
                       'sort_key=hidden&sort_dir=desc')
        self.assertRaises(exception.ValidationError,
                          self.controller.index, req)

    def test_get_servers_ignore_sort_key(self):
        req = self.req(self.path_with_query %
                       'sort_key=vcpus&sort_dir=asc')
        self.controller.index(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=[], sort_dirs=[],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_ignore_locked_sort_key(self):
        # Prior to microversion 2.73 locked sort key is ignored.
        req = self.req(self.path_with_query %
                       'sort_key=locked&sort_dir=asc')
        self.controller.detail(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=[], sort_dirs=[],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_ignore_sort_key_only_one_dir(self):
        req = self.req(self.path_with_query %
                'sort_key=user_id&sort_key=vcpus&sort_dir=asc')
        self.controller.index(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=['user_id'],
            sort_dirs=['asc'], cell_down_support=False, all_tenants=False)

    def test_get_servers_ignore_sort_key_with_no_sort_dir(self):
        req = self.req(self.path_with_query %
                       'sort_key=vcpus&sort_key=user_id')
        self.controller.index(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=['user_id'], sort_dirs=[],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_ignore_sort_key_with_bad_sort_dir(self):
        req = self.req(self.path_with_query %
                       'sort_key=vcpus&sort_dir=bad_dir')
        self.controller.index(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=[], sort_dirs=[],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_non_admin_with_admin_only_sort_key(self):
        req = self.req(self.path_with_query %
                       'sort_key=host&sort_dir=desc')
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.index, req)

    def test_get_servers_admin_with_admin_only_sort_key(self):
        req = self.req(self.path_with_query %
                       'sort_key=node&sort_dir=desc',
                       use_admin_context=True)
        self.controller.detail(req)
        self.mock_get_all.assert_called_once_with(
            mock.ANY, search_opts=mock.ANY, limit=mock.ANY, marker=mock.ANY,
            expected_attrs=mock.ANY, sort_keys=['node'], sort_dirs=['desc'],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_with_bad_option(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(100, uuid=uuids.fake)]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'unknownoption=whee')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'], expected_attrs=[],
            limit=1000, marker=None,
            search_opts={'deleted': False, 'project_id': self.project_id},
            sort_dirs=['desc'], sort_keys=['created_at'],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_with_locked_filter(self):
        # Prior to microversion 2.73 locked filter parameter is ignored.
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(100, uuid=uuids.fake)]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'locked=true')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'], expected_attrs=[],
            limit=1000, marker=None,
            search_opts={'deleted': False, 'project_id': self.project_id},
            sort_dirs=['desc'], sort_keys=['created_at'],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_allows_image(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('image', search_opts)
            self.assertEqual(search_opts['image'], '12345')
            db_list = [fakes.stub_instance(100, uuid=uuids.fake)]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'image=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_tenant_id_filter_no_admin_context(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('tenant_id', search_opts)
            self.assertEqual(self.project_id, search_opts['project_id'])
            return [fakes.stub_instance_obj(100)]

        req = self.req(self.path_with_query % 'tenant_id=newfake')
        self.mock_get_all.side_effect = fake_get_all
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 1)

    def test_tenant_id_filter_admin_context(self):
        """"Test tenant_id search opt is dropped if all_tenants is not set."""
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('tenant_id', search_opts)
            self.assertEqual(self.project_id, search_opts['project_id'])
            return [fakes.stub_instance_obj(100)]

        req = self.req(self.path_with_query % 'tenant_id=newfake',
                       use_admin_context=True)
        self.mock_get_all.side_effect = fake_get_all
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 1)

    def test_all_tenants_param_normal(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertNotIn('project_id', search_opts)
            return [fakes.stub_instance_obj(100)]

        req = self.req(self.path_with_query % 'all_tenants',
                       use_admin_context=True)
        self.mock_get_all.side_effect = fake_get_all
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 1)

    def test_all_tenants_param_one(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertNotIn('project_id', search_opts)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'all_tenants=1',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']
        self.assertEqual(1, len(servers))

    def test_all_tenants_param_zero(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertNotIn('all_tenants', search_opts)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'all_tenants=0',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']
        self.assertEqual(1, len(servers))

    def test_all_tenants_param_false(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertNotIn('all_tenants', search_opts)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'all_tenants=false',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']
        self.assertEqual(1, len(servers))

    def test_all_tenants_param_invalid(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertNotIn('all_tenants', search_opts)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'all_tenants=xxx',
                       use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_admin_restricted_tenant(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            self.assertEqual(search_opts['project_id'], self.project_id)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all
        req = self.req(self.path, use_admin_context=True)
        servers = self.controller.index(req)['servers']
        self.assertEqual(1, len(servers))

    def test_all_tenants_pass_policy(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('project_id', search_opts)
            self.assertTrue(context.is_admin)
            return [fakes.stub_instance_obj(100)]

        self.mock_get_all.side_effect = fake_get_all

        rules = {
            "os_compute_api:servers:index": "project_id:%s" % self.project_id,
            "os_compute_api:servers:index:get_all_tenants":
                "project_id:%s" % self.project_id
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        req = self.req(self.path_with_query % 'all_tenants=1')
        servers = self.controller.index(req)['servers']
        self.assertEqual(1, len(servers))

    def test_all_tenants_fail_policy(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            return [fakes.stub_instance_obj(100)]

        rules = {
            "os_compute_api:servers:index:get_all_tenants":
                "project_id:non_fake",
            "os_compute_api:servers:get_all":
                "project_id:%s" % self.project_id,
        }

        policy.set_rules(oslo_policy.Rules.from_dict(rules))
        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'all_tenants=1')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_get_servers_allows_flavor(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('flavor', search_opts)
            # flavor is an integer ID
            self.assertEqual(search_opts['flavor'], '12345')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'flavor=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_with_bad_flavor(self):
        req = self.req(self.path_with_query % 'flavor=abcde')
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = objects.InstanceList(objects=[])
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 0)

    def test_get_server_details_with_bad_flavor(self):
        req = self.req(self.path_with_query % 'flavor=abcde')
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = objects.InstanceList(objects=[])
        servers = self.controller.detail(req)['servers']

        self.assertThat(servers, testtools.matchers.HasLength(0))

    def test_get_servers_allows_status(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], [vm_states.ACTIVE])
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'status=active')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_allows_task_status(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('task_state', search_opts)
            self.assertEqual([task_states.REBOOT_PENDING,
                              task_states.REBOOT_STARTED,
                              task_states.REBOOTING],
                             search_opts['task_state'])
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(
                    100, uuid=uuids.fake, task_state=task_states.REBOOTING)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'status=reboot')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_resize_status(self):
        # Test when resize status, it maps list of vm states.
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'],
                             [vm_states.ACTIVE, vm_states.STOPPED])

            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'status=resize')

        servers = self.controller.detail(req)['servers']
        self.assertEqual(1, len(servers), 1)
        self.assertEqual(servers[0]['id'], uuids.fake)

    def test_get_servers_invalid_status(self):
        # Test getting servers by invalid status.
        req = self.req(self.path_with_query % 'status=baloney',
                       use_admin_context=False)
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 0)

    def test_get_servers_deleted_status_as_user(self):
        req = self.req(self.path_with_query % 'status=deleted',
                       use_admin_context=False)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.detail, req)

    def test_get_servers_deleted_status_as_admin(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], ['deleted'])

            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'status=deleted',
                       use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_deleted_filter_str_to_bool(self):
        db_list = objects.InstanceList(
            objects=[fakes.stub_instance_obj(100, uuid=uuids.fake,
                                             vm_state='deleted')])
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = db_list

        req = self.req(self.path_with_query % 'deleted=true',
                       use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

        # Assert that 'deleted' filter value is converted to boolean
        # while calling get_all() method.
        expected_search_opts = {'deleted': True, 'project_id': self.project_id}
        self.assertEqual(expected_search_opts,
                         self.mock_get_all.call_args[1]['search_opts'])

    def test_get_servers_deleted_filter_invalid_str(self):
        db_list = objects.InstanceList(
            objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = db_list

        req = fakes.HTTPRequest.blank(self.path_with_query % 'deleted=abc',
                                      use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

        # Assert that invalid 'deleted' filter value is converted to boolean
        # False while calling get_all() method.
        expected_search_opts = {'deleted': False,
                                'project_id': self.project_id}
        self.assertEqual(expected_search_opts,
                         self.mock_get_all.call_args[1]['search_opts'])

    def test_get_servers_allows_name(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('name', search_opts)
            self.assertEqual(search_opts['name'], 'whee.*')
            self.assertEqual([], expected_attrs)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'name=whee.*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_flavor_not_found(self):
        self.mock_get_all.side_effect = exception.FlavorNotFound(flavor_id=1)

        req = fakes.HTTPRequest.blank(
                self.path_with_query % 'status=active&flavor=abc')
        servers = self.controller.index(req)['servers']
        self.assertEqual(0, len(servers))

    def test_get_servers_allows_changes_since(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('changes-since', search_opts)
            changes_since = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertNotIn('deleted', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        params = 'changes-since=2011-01-24T17:08:01Z'
        req = self.req(self.path_with_query % params)
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_allows_changes_since_bad_value(self):
        params = 'changes-since=asdf'
        req = self.req(self.path_with_query % params)
        self.assertRaises(exception.ValidationError, self.controller.index,
                          req)

    def test_get_servers_allows_changes_since_bad_value_on_compat_mode(self):
        params = 'changes-since=asdf'
        req = self.req(self.path_with_query % params)
        req.set_legacy_v2()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index,
                          req)

    def test_get_servers_admin_filters_as_user(self):
        """Test getting servers by admin-only or unknown options when
        context is not admin. Make sure the admin and unknown options
        are stripped before they get to compute_api.get_all()
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            self.assertIn('ip', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertNotIn('unknown_option', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank(self.path_with_query % query_str)
        res = self.controller.index(req)

        servers = res['servers']
        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_admin_options_as_admin(self):
        """Test getting servers by admin-only or unknown options when
        context is admin. All options should be passed
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            self.assertIn('terminated_at', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertIn('ip', search_opts)
            self.assertNotIn('unknown_option', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        query_str = ("name=foo&ip=10.*&status=active&unknown_option=meow&"
                     "terminated_at=^2016-02-01.*")
        req = self.req(self.path_with_query % query_str,
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_admin_filters_as_user_with_policy_override(self):
        """Test getting servers by admin-only or unknown options when
        context is not admin but policy allows.
        """
        server_uuid = uuids.fake

        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            self.assertIn('terminated_at', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertIn('ip', search_opts)
            self.assertNotIn('unknown_option', search_opts)
            # "hidden" is ignored as a filter parameter since it is only used
            # internally
            self.assertNotIn('hidden', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=server_uuid)])

        rules = {
            "os_compute_api:servers:index": "project_id:%s" % self.project_id,
            "os_compute_api:servers:allow_all_filters":
                "project_id:%s" % self.project_id,
        }
        policy.set_rules(oslo_policy.Rules.from_dict(rules))

        self.mock_get_all.side_effect = fake_get_all

        query_str = ("name=foo&ip=10.*&status=active&unknown_option=meow&"
                     "terminated_at=^2016-02-01.*&hidden=true")
        req = self.req(self.path_with_query % query_str)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_ip(self):
        """Test getting servers by ip."""
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip', search_opts)
            self.assertEqual(search_opts['ip'], r'10\..*')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % r'ip=10\..*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_admin_allows_ip6(self):
        """Test getting servers by ip6 with admin_api enabled and
        admin context
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip6', search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'ip6=ffff.*',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_allows_ip6_with_new_version(self):
        """Test getting servers by ip6 with new version requested
        and no admin context
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip6', search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'ip6=ffff.*')
        req.api_version_request = api_version_request.APIVersionRequest('2.5')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_admin_allows_access_ip_v4(self):
        """Test getting servers by access_ip_v4 with admin_api enabled and
        admin context
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('access_ip_v4', search_opts)
            self.assertEqual(search_opts['access_ip_v4'], 'ffff.*')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'access_ip_v4=ffff.*',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_admin_allows_access_ip_v6(self):
        """Test getting servers by access_ip_v6 with admin_api enabled and
        admin context
        """
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('access_ip_v6', search_opts)
            self.assertEqual(search_opts['access_ip_v6'], 'ffff.*')
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'access_ip_v6=ffff.*',
                       use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def _assertServerUsage(self, server, launched_at, terminated_at):
        resp_launched_at = timeutils.parse_isotime(
            server.get('OS-SRV-USG:launched_at'))
        self.assertEqual(timeutils.normalize_time(resp_launched_at),
                         launched_at)
        resp_terminated_at = timeutils.parse_isotime(
            server.get('OS-SRV-USG:terminated_at'))
        self.assertEqual(timeutils.normalize_time(resp_terminated_at),
                         terminated_at)

    def test_show_server_usage(self):
        DATE1 = datetime.datetime(year=2013, month=4, day=5, hour=12)
        DATE2 = datetime.datetime(year=2013, month=4, day=5, hour=13)
        req = self.req(self.path_with_id % FAKE_UUID)
        req.accept = 'application/json'
        req.method = 'GET'
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=1, uuid=FAKE_UUID, launched_at=DATE1, terminated_at=DATE2,
            project_id=req.environ['nova.context'].project_id)
        res = req.get_response(compute.APIRouterV21())
        self.assertEqual(res.status_int, 200)
        self.useFixture(utils_fixture.TimeFixture())
        self._assertServerUsage(jsonutils.loads(res.body).get('server'),
                                launched_at=DATE1,
                                terminated_at=DATE2)

    def test_detail_server_usage(self):
        DATE1 = datetime.datetime(year=2013, month=4, day=5, hour=12)
        DATE2 = datetime.datetime(year=2013, month=4, day=5, hour=13)
        DATE3 = datetime.datetime(year=2013, month=4, day=5, hour=14)

        def fake_compute_get_all(*args, **kwargs):
            db_list = [
                fakes.stub_instance_obj(context, id=2, uuid=FAKE_UUID,
                                        launched_at=DATE2,
                                        terminated_at=DATE3),
                fakes.stub_instance_obj(context, id=3, uuid=FAKE_UUID,
                                        launched_at=DATE1,
                                        terminated_at=DATE3),
            ]
            return objects.InstanceList(objects=db_list)
        self.mock_get_all.side_effect = fake_compute_get_all
        req = self.req(self.path_detail)
        req.accept = 'application/json'
        servers = req.get_response(compute.APIRouterV21())
        self.assertEqual(servers.status_int, 200)
        self._assertServerUsage(jsonutils.loads(
                                    servers.body).get('servers')[0],
                                launched_at=DATE2,
                                terminated_at=DATE3)
        self._assertServerUsage(jsonutils.loads(
                                    servers.body).get('servers')[1],
                                launched_at=DATE1,
                                terminated_at=DATE3)

    def test_get_all_server_details(self):
        expected_flavor = {
                "id": "2",
                "links": [
                    {
                        "rel": "bookmark",
                        "href": ('http://localhost/%s/flavors/2' %
                                 self.project_id),
                        },
                    ],
                }
        expected_image = {
            "id": "10",
            "links": [
                {
                    "rel": "bookmark",
                    "href": ('http://localhost/%s/images/10' %
                             self.project_id),
                    },
                ],
            }
        req = self.req(self.path_detail)
        res_dict = self.controller.detail(req)

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['hostId'], '')
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertEqual(s['image'], expected_image)
            self.assertEqual(s['flavor'], expected_flavor)
            self.assertEqual(s['status'], 'ACTIVE')
            self.assertEqual(s['metadata']['seq'], str(i + 1))

    def test_get_all_server_details_with_host(self):
        """We want to make sure that if two instances are on the same host,
        then they return the same hostId. If two instances are on different
        hosts, they should return different hostIds. In this test,
        there are 5 instances - 2 on one host and 3 on another.
        """

        def return_servers_with_host(*args, **kwargs):
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(None,
                                                 id=i + 1,
                                                 user_id='fake',
                                                 project_id='fake',
                                                 host=i % 2,
                                                 uuid=fakes.get_fake_uuid(i))
                    for i in range(5)])

        self.mock_get_all.side_effect = return_servers_with_host

        req = self.req(self.path_detail)
        res_dict = self.controller.detail(req)

        server_list = res_dict['servers']
        host_ids = [server_list[0]['hostId'], server_list[1]['hostId']]
        self.assertTrue(host_ids[0] and host_ids[1])
        self.assertNotEqual(host_ids[0], host_ids[1])

        for i, s in enumerate(server_list):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['hostId'], host_ids[i % 2])
            self.assertEqual(s['name'], 'server%d' % (i + 1))

    def test_get_servers_joins_services(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            cur = api_version_request.APIVersionRequest(self.wsgi_api_version)
            v216 = api_version_request.APIVersionRequest('2.16')
            if cur >= v216:
                self.assertIn('services', expected_attrs)
            else:
                self.assertNotIn('services', expected_attrs)
            return objects.InstanceList()

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_detail, use_admin_context=True)
        self.assertIn('servers', self.controller.detail(req))

        req = fakes.HTTPRequest.blank(self.path_detail,
                                      use_admin_context=True,
                                      version=self.wsgi_api_version)
        self.assertIn('servers', self.controller.detail(req))


class ServersControllerTestV23(ServersControllerTest):
    wsgi_api_version = '2.3'

    def setUp(self):
        super(ServersControllerTestV23, self).setUp()
        self.request = self.req(self.path_with_id % FAKE_UUID)
        self.project_id = self.request.environ['nova.context'].project_id
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, uuid=FAKE_UUID,
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=self.project_id)

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        server_dict = super(ServersControllerTestV23,
                            self)._get_server_data_dict(uuid,
                                                        image_bookmark,
                                                        flavor_bookmark,
                                                        status,
                                                        progress)
        server_dict['server']["OS-EXT-SRV-ATTR:hostname"] = "server2"
        server_dict['server'][
            "OS-EXT-SRV-ATTR:hypervisor_hostname"] = "node-fake"
        server_dict['server']["OS-EXT-SRV-ATTR:kernel_id"] = UUID1
        server_dict['server']["OS-EXT-SRV-ATTR:launch_index"] = 0
        server_dict['server']["OS-EXT-SRV-ATTR:ramdisk_id"] = UUID2
        server_dict['server']["OS-EXT-SRV-ATTR:reservation_id"] = "r-1"
        server_dict['server']["OS-EXT-SRV-ATTR:root_device_name"] = "/dev/vda"
        server_dict['server']["OS-EXT-SRV-ATTR:user_data"] = "userdata"
        server_dict['server']["OS-EXT-STS:task_state"] = None
        server_dict['server']["OS-EXT-STS:vm_state"] = vm_states.ACTIVE
        server_dict['server']["OS-EXT-STS:power_state"] = 1
        server_dict['server']["os-extended-volumes:volumes_attached"] = [
            {'id': 'some_volume_1', 'delete_on_termination': True},
            {'id': 'some_volume_2', 'delete_on_termination': False}]
        server_dict['server']["tenant_id"] = self.project_id
        return server_dict

    def test_show(self):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id

        res_dict = self.controller.show(self.request, FAKE_UUID)

        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_detail(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None):
            obj_list = []
            for i in range(2):
                server = fakes.stub_instance_obj(context,
                              id=2, uuid=FAKE_UUID,
                              node="node-fake",
                              reservation_id="r-1", launch_index=0,
                              kernel_id=UUID1, ramdisk_id=UUID2,
                              display_name="server2",
                              root_device_name="/dev/vda",
                              user_data="userdata",
                              metadata={"seq": "2"},
                              availability_zone='nova',
                              launched_at=None,
                              terminated_at=None,
                              task_state=None,
                              vm_state=vm_states.ACTIVE,
                              power_state=1,
                              project_id=context.project_id)
                obj_list.append(server)
            return objects.InstanceList(objects=obj_list)

        self.mock_get_all.side_effect = None
        req = self.req(self.path_detail)
        self.mock_get_all.return_value = fake_get_all(
            req.environ['nova.context'])

        servers_list = self.controller.detail(req)
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id
        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)

        self.assertIn(expected_server['server'], servers_list['servers'])


class ServersControllerTestV29(ServersControllerTest):
    wsgi_api_version = '2.9'

    def setUp(self):
        super(ServersControllerTestV29, self).setUp()
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, uuid=FAKE_UUID,
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=self.request.environ['nova.context'].project_id)

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        server_dict = super(ServersControllerTestV29,
                            self)._get_server_data_dict(uuid,
                                                        image_bookmark,
                                                        flavor_bookmark,
                                                        status,
                                                        progress)
        server_dict['server']['locked'] = False
        server_dict['server']["OS-EXT-SRV-ATTR:hostname"] = "server2"
        server_dict['server'][
            "OS-EXT-SRV-ATTR:hypervisor_hostname"] = "node-fake"
        server_dict['server']["OS-EXT-SRV-ATTR:kernel_id"] = UUID1
        server_dict['server']["OS-EXT-SRV-ATTR:launch_index"] = 0
        server_dict['server']["OS-EXT-SRV-ATTR:ramdisk_id"] = UUID2
        server_dict['server']["OS-EXT-SRV-ATTR:reservation_id"] = "r-1"
        server_dict['server']["OS-EXT-SRV-ATTR:root_device_name"] = "/dev/vda"
        server_dict['server']["OS-EXT-SRV-ATTR:user_data"] = "userdata"
        server_dict['server']["OS-EXT-STS:task_state"] = None
        server_dict['server']["OS-EXT-STS:vm_state"] = vm_states.ACTIVE
        server_dict['server']["OS-EXT-STS:power_state"] = 1
        server_dict['server']["os-extended-volumes:volumes_attached"] = [
            {'id': 'some_volume_1', 'delete_on_termination': True},
            {'id': 'some_volume_2', 'delete_on_termination': False}]
        server_dict['server']["tenant_id"] = self.request.environ[
            'nova.context'].project_id
        return server_dict

    def _test_get_server_with_lock(self, locked_by):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id
        req = self.req(self.path_with_id % FAKE_UUID)
        project_id = req.environ['nova.context'].project_id
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, locked_by=locked_by, uuid=FAKE_UUID,
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=project_id)

        res_dict = self.controller.show(req, FAKE_UUID)

        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        expected_server['server']['locked'] = True if locked_by else False
        expected_server['server']['tenant_id'] = project_id
        self.assertThat(res_dict, matchers.DictMatches(expected_server))
        return res_dict

    def test_get_server_with_locked_by_admin(self):
        res_dict = self._test_get_server_with_lock('admin')
        self.assertTrue(res_dict['server']['locked'])

    def test_get_server_with_locked_by_owner(self):
        res_dict = self._test_get_server_with_lock('owner')
        self.assertTrue(res_dict['server']['locked'])

    def test_get_server_not_locked(self):
        res_dict = self._test_get_server_with_lock(None)
        self.assertFalse(res_dict['server']['locked'])

    def _test_list_server_detail_with_lock(self,
                                           s1_locked,
                                           s2_locked):
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = fake_instance_get_all_with_locked(
            context, [s1_locked, s2_locked],
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1)

        req = self.req(self.path_detail)
        servers_list = self.controller.detail(req)
        # Check that each returned server has the same 'locked' value
        # and 'id' as they were created.
        for locked in [s1_locked, s2_locked]:
            server = next(server for server in servers_list['servers']
                          if (server['id'] == fakes.get_fake_uuid(locked)))
            expected = False if locked == 'not_locked' else True
            self.assertEqual(expected, server['locked'])

    def test_list_server_detail_with_locked_s1_admin_s2_owner(self):
        self._test_list_server_detail_with_lock('admin', 'owner')

    def test_list_server_detail_with_locked_s1_owner_s2_admin(self):
        self._test_list_server_detail_with_lock('owner', 'admin')

    def test_list_server_detail_with_locked_s1_admin_s2_admin(self):
        self._test_list_server_detail_with_lock('admin', 'admin')

    def test_list_server_detail_with_locked_s1_admin_s2_not_locked(self):
        self._test_list_server_detail_with_lock('admin', 'not_locked')

    def test_list_server_detail_with_locked_s1_s2_not_locked(self):
        self._test_list_server_detail_with_lock('not_locked',
                                                'not_locked')

    def test_get_servers_remove_non_search_options(self):
        self.mock_get_all.side_effect = None
        req = fakes.HTTPRequestV21.blank('/servers'
                                         '?sort_key=uuid&sort_dir=asc'
                                         '&sort_key=user_id&sort_dir=desc'
                                         '&limit=1&marker=123',
                                         use_admin_context=True)
        self.controller.index(req)
        kwargs = self.mock_get_all.call_args[1]
        search_opts = kwargs['search_opts']
        for key in ('sort_key', 'sort_dir', 'limit', 'marker'):
            self.assertNotIn(key, search_opts)


class ServersControllerTestV216(ServersControllerTest):
    wsgi_api_version = '2.16'

    def setUp(self):
        super(ServersControllerTestV216, self).setUp()
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, uuid=FAKE_UUID,
            host="node-fake",
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=self.request.environ['nova.context'].project_id)
        self.mock_get_instance_host_status = self.useFixture(
            fixtures.MockPatchObject(
                compute_api.API, 'get_instance_host_status',
                return_value='UP')).mock

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        server_dict = super(ServersControllerTestV216,
                            self)._get_server_data_dict(uuid,
                                                        image_bookmark,
                                                        flavor_bookmark,
                                                        status,
                                                        progress)
        server_dict['server']['locked'] = False
        server_dict['server']["host_status"] = "UP"
        server_dict['server']["OS-EXT-SRV-ATTR:hostname"] = "server2"
        server_dict['server']['hostId'] = nova_utils.generate_hostid(
            'node-fake', server_dict['server']['tenant_id'])
        server_dict['server']["OS-EXT-SRV-ATTR:host"] = "node-fake"
        server_dict['server'][
            "OS-EXT-SRV-ATTR:hypervisor_hostname"] = "node-fake"
        server_dict['server']["OS-EXT-SRV-ATTR:kernel_id"] = UUID1
        server_dict['server']["OS-EXT-SRV-ATTR:launch_index"] = 0
        server_dict['server']["OS-EXT-SRV-ATTR:ramdisk_id"] = UUID2
        server_dict['server']["OS-EXT-SRV-ATTR:reservation_id"] = "r-1"
        server_dict['server']["OS-EXT-SRV-ATTR:root_device_name"] = "/dev/vda"
        server_dict['server']["OS-EXT-SRV-ATTR:user_data"] = "userdata"
        server_dict['server']["OS-EXT-STS:task_state"] = None
        server_dict['server']["OS-EXT-STS:vm_state"] = vm_states.ACTIVE
        server_dict['server']["OS-EXT-STS:power_state"] = 1
        server_dict['server']["os-extended-volumes:volumes_attached"] = [
            {'id': 'some_volume_1', 'delete_on_termination': True},
            {'id': 'some_volume_2', 'delete_on_termination': False}]
        server_dict['server']['tenant_id'] = self.request.environ[
            'nova.context'].project_id

        return server_dict

    @mock.patch('nova.compute.api.API.get_instance_host_status')
    def _verify_host_status_policy_behavior(self, func, mock_get_host_status):
        # Set policy to disallow both host_status cases and verify we don't
        # call the get_instance_host_status compute RPC API.
        rules = {
            'os_compute_api:servers:show:host_status': '!',
            'os_compute_api:servers:show:host_status:unknown-only': '!',
        }
        orig_rules = policy.get_rules()
        policy.set_rules(oslo_policy.Rules.from_dict(rules), overwrite=False)
        func()
        mock_get_host_status.assert_not_called()
        # Restore the original rules.
        policy.set_rules(orig_rules)

    def test_show(self):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id
        res_dict = self.controller.show(self.request, FAKE_UUID)
        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))
        func = functools.partial(self.controller.show, self.request,
                                 FAKE_UUID)
        self._verify_host_status_policy_behavior(func)

    def test_detail(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None):
            obj_list = []
            for i in range(2):
                server = fakes.stub_instance_obj(context,
                              id=2, uuid=FAKE_UUID,
                              host="node-fake",
                              node="node-fake",
                              reservation_id="r-1", launch_index=0,
                              kernel_id=UUID1, ramdisk_id=UUID2,
                              display_name="server2",
                              root_device_name="/dev/vda",
                              user_data="userdata",
                              metadata={"seq": "2"},
                              availability_zone='nova',
                              launched_at=None,
                              terminated_at=None,
                              task_state=None,
                              vm_state=vm_states.ACTIVE,
                              power_state=1,
                              project_id=context.project_id)
                obj_list.append(server)
            return objects.InstanceList(objects=obj_list)

        self.mock_get_all.side_effect = None
        req = self.req(self.path_detail)
        self.mock_get_all.return_value = fake_get_all(
            req.environ['nova.context'])

        servers_list = self.controller.detail(req)
        self.assertEqual(2, len(servers_list['servers']))
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id
        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0)

        self.assertIn(expected_server['server'], servers_list['servers'])
        # We should have only gotten the host status once per host (and the
        # 2 servers in the response are using the same host).
        self.mock_get_instance_host_status.assert_called_once()

        func = functools.partial(self.controller.detail, req)
        self._verify_host_status_policy_behavior(func)


class ServersControllerTestV219(ServersControllerTest):
    wsgi_api_version = '2.19'

    def setUp(self):
        super(ServersControllerTestV219, self).setUp()
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, uuid=FAKE_UUID,
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=self.request.environ['nova.context'].project_id)
        self.useFixture(fixtures.MockPatchObject(
            compute_api.API, 'get_instance_host_status',
            return_value='UP')).mock

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100, description=None):
        server_dict = super(ServersControllerTestV219,
                            self)._get_server_data_dict(uuid,
                                                        image_bookmark,
                                                        flavor_bookmark,
                                                        status,
                                                        progress)
        server_dict['server']['locked'] = False
        server_dict['server']['description'] = description
        server_dict['server']["host_status"] = "UP"
        server_dict['server']["OS-EXT-SRV-ATTR:hostname"] = "server2"
        server_dict['server'][
            "OS-EXT-SRV-ATTR:hypervisor_hostname"] = "node-fake"
        server_dict['server']["OS-EXT-SRV-ATTR:kernel_id"] = UUID1
        server_dict['server']["OS-EXT-SRV-ATTR:launch_index"] = 0
        server_dict['server']["OS-EXT-SRV-ATTR:ramdisk_id"] = UUID2
        server_dict['server']["OS-EXT-SRV-ATTR:reservation_id"] = "r-1"
        server_dict['server']["OS-EXT-SRV-ATTR:root_device_name"] = "/dev/vda"
        server_dict['server']["OS-EXT-SRV-ATTR:user_data"] = "userdata"
        server_dict['server']["OS-EXT-STS:task_state"] = None
        server_dict['server']["OS-EXT-STS:vm_state"] = vm_states.ACTIVE
        server_dict['server']["OS-EXT-STS:power_state"] = 1
        server_dict['server']["os-extended-volumes:volumes_attached"] = [
            {'id': 'some_volume_1', 'delete_on_termination': True},
            {'id': 'some_volume_2', 'delete_on_termination': False}]

        return server_dict

    def _test_get_server_with_description(self, description):
        image_bookmark = "http://localhost/%s/images/10" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/2" % self.project_id
        req = self.req(self.path_with_id % FAKE_UUID)
        project_id = req.environ['nova.context'].project_id
        self.mock_get.side_effect = fakes.fake_compute_get(
            id=2, display_description=description, uuid=FAKE_UUID,
            node="node-fake",
            reservation_id="r-1", launch_index=0,
            kernel_id=UUID1, ramdisk_id=UUID2,
            display_name="server2",
            root_device_name="/dev/vda",
            user_data="userdata",
            metadata={"seq": "2"},
            availability_zone='nova',
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1,
            project_id=project_id)

        res_dict = self.controller.show(req, FAKE_UUID)

        expected_server = self._get_server_data_dict(FAKE_UUID,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     progress=0,
                                                     description=description)
        expected_server['server']['tenant_id'] = project_id
        self.assertThat(res_dict, matchers.DictMatches(expected_server))
        return res_dict

    def _test_list_server_detail_with_descriptions(self,
                                           s1_desc,
                                           s2_desc):
        self.mock_get_all.side_effect = None
        self.mock_get_all.return_value = (
            fake_instance_get_all_with_description(context,
                                                   [s1_desc, s2_desc],
                                                   launched_at=None,
                                                   terminated_at=None))
        req = self.req(self.path_detail)
        servers_list = self.controller.detail(req)
        # Check that each returned server has the same 'description' value
        # and 'id' as they were created.
        for desc in [s1_desc, s2_desc]:
            server = next(server for server in servers_list['servers']
                          if (server['id'] == fakes.get_fake_uuid(desc)))
            expected = desc
            self.assertEqual(expected, server['description'])

    def test_get_server_with_description(self):
        self._test_get_server_with_description('test desc')

    def test_list_server_detail_with_descriptions(self):
        self._test_list_server_detail_with_descriptions('desc1', 'desc2')


class ServersControllerTestV226(ControllerTest):
    wsgi_api_version = '2.26'

    def test_get_server_with_tags_by_id(self):
        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID,
                                      version=self.wsgi_api_version)
        ctxt = req.environ['nova.context']
        tags = ['tag1', 'tag2']

        def fake_get(*args, **kwargs):
            self.assertIn('tags', kwargs['expected_attrs'])
            fake_server = fakes.stub_instance_obj(
                ctxt, id=2, vm_state=vm_states.ACTIVE, progress=100,
                project_id=ctxt.project_id)

            tag_list = objects.TagList(objects=[
                objects.Tag(resource_id=FAKE_UUID, tag=tag)
                for tag in tags])

            fake_server.tags = tag_list
            return fake_server

        self.mock_get.side_effect = fake_get

        res_dict = self.controller.show(req, FAKE_UUID)

        self.assertIn('tags', res_dict['server'])
        self.assertEqual(tags, res_dict['server']['tags'])

    def _test_get_servers_allows_tag_filters(self, filter_name):
        query_string = '%s=t1,t2' % filter_name
        req = fakes.HTTPRequest.blank(self.path_with_query % query_string,
                                      version=self.wsgi_api_version)

        def fake_get_all(*a, **kw):
            self.assertIsNotNone(kw['search_opts'])
            self.assertIn(filter_name, kw['search_opts'])
            self.assertEqual(kw['search_opts'][filter_name], ['t1', 't2'])
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(req.environ['nova.context'],
                                                 uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_allows_tags_filter(self):
        self._test_get_servers_allows_tag_filters('tags')

    def test_get_servers_allows_tags_any_filter(self):
        self._test_get_servers_allows_tag_filters('tags-any')

    def test_get_servers_allows_not_tags_filter(self):
        self._test_get_servers_allows_tag_filters('not-tags')

    def test_get_servers_allows_not_tags_any_filter(self):
        self._test_get_servers_allows_tag_filters('not-tags-any')


class ServerControllerTestV238(ControllerTest):
    wsgi_api_version = '2.38'

    def _test_invalid_status(self, is_admin):
        req = fakes.HTTPRequest.blank(
                self.path_detail_with_query % 'status=invalid',
                version=self.wsgi_api_version, use_admin_context=is_admin)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_list_servers_detail_invalid_status_for_admin(self):
        self._test_invalid_status(True)

    def test_list_servers_detail_invalid_status_for_non_admin(self):
        self._test_invalid_status(False)


class ServerControllerTestV247(ControllerTest):
    """Server controller test for microversion 2.47

    The intent here is simply to verify that when showing server details
    after microversion 2.47 that the flavor is shown as a dict of flavor
    information rather than as dict of id/links.  The existence of the
    'extra_specs' key is controlled by policy.
    """
    wsgi_api_version = '2.47'

    @mock.patch.object(objects.TagList, 'get_by_resource_id')
    def test_get_all_server_details(self, mock_get_by_resource_id):
        # Fake out tags on the instances
        mock_get_by_resource_id.return_value = objects.TagList()

        expected_flavor = {
            'disk': 20,
            'ephemeral': 0,
            'extra_specs': {},
            'original_name': u'm1.small',
            'ram': 2048,
            'swap': 0,
            'vcpus': 1}

        req = fakes.HTTPRequest.blank(self.path_detail,
                                      version=self.wsgi_api_version)

        hits = []
        real_auth = policy.authorize

        # Wrapper for authorize to count the number of times
        # we authorize for extra-specs
        def fake_auth(context, action, target):
            if 'extra-specs' in action:
                hits.append(1)
            return real_auth(context, action, target)

        with mock.patch('nova.policy.authorize') as mock_auth:
            mock_auth.side_effect = fake_auth
            res_dict = self.controller.detail(req)

        # We should have found more than one servers, but only hit the
        # policy check once
        self.assertGreater(len(res_dict['servers']), 1)
        self.assertEqual(1, len(hits))

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['flavor'], expected_flavor)

    @mock.patch.object(objects.TagList, 'get_by_resource_id')
    def test_get_all_server_details_no_extra_spec(self,
            mock_get_by_resource_id):
        # Fake out tags on the instances
        mock_get_by_resource_id.return_value = objects.TagList()
        # Set the policy so we don't have permission to index
        # flavor extra-specs but are able to get server details.
        servers_rule = 'os_compute_api:servers:detail'
        extraspec_rule = 'os_compute_api:os-flavor-extra-specs:index'
        self.policy.set_rules({
            extraspec_rule: 'rule:admin_api',
            servers_rule: '@'})

        expected_flavor = {
            'disk': 20,
            'ephemeral': 0,
            'original_name': u'm1.small',
            'ram': 2048,
            'swap': 0,
            'vcpus': 1}

        req = fakes.HTTPRequest.blank(self.path_detail,
                                      version=self.wsgi_api_version)
        res_dict = self.controller.detail(req)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['flavor'], expected_flavor)


class ServerControllerTestV266(ControllerTest):
    """Server controller test for microversion 2.66

    Add changes-before parameter to get servers or servers details of
    2.66 microversion.

    Filters the response by a date and time stamp when the server last
    changed. Those changed before the specified date and time stamp are
    returned.
    """
    wsgi_api_version = '2.66'

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def test_get_servers_allows_changes_before(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('changes-before', search_opts)
            changes_before = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-before'], changes_before)
            self.assertNotIn('deleted', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        params = 'changes-before=2011-01-24T17:08:01Z'
        req = self.req(self.path_with_query % params)
        req.api_version_request = api_version_request.APIVersionRequest('2.66')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_allows_changes_before_bad_value(self):
        params = 'changes-before=asdf'
        req = self.req(self.path_with_query % params)
        req.api_version_request = api_version_request.APIVersionRequest('2.66')
        self.assertRaises(exception.ValidationError, self.controller.index,
                          req)

    def test_get_servers_allows_changes_before_bad_value_on_compat_mode(self):
        params = 'changes-before=asdf'
        req = self.req(self.path_with_query % params)
        req.api_version_request = api_version_request.APIVersionRequest('2.66')
        req.set_legacy_v2()
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_get_servers_allows_changes_since_and_changes_before(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            self.assertIsNotNone(search_opts)
            self.assertIn('changes-since', search_opts)
            changes_since = datetime.datetime(2011, 1, 23, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertIn('changes-before', search_opts)
            changes_before = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertEqual(search_opts['changes-before'], changes_before)
            self.assertNotIn('deleted', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        params = 'changes-since=2011-01-23T17:08:01Z&' \
                 'changes-before=2011-01-24T17:08:01Z'
        req = self.req(self.path_with_query % params)
        req.api_version_request = api_version_request.APIVersionRequest('2.66')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_filters_with_distinct_changes_time_bad_request(self):
        changes_since = '2018-09-04T05:45:27Z'
        changes_before = '2018-09-03T05:45:27Z'
        query_string = ('changes-since=%s&changes-before=%s' %
                        (changes_since, changes_before))
        req = self.req(self.path_with_query % query_string)
        req.api_version_request = api_version_request.APIVersionRequest('2.66')
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)


class ServersControllerTestV271(ControllerTest):
    wsgi_api_version = '2.71'

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def test_show_server_group_not_exist(self):
        req = self.req(self.path_with_id % FAKE_UUID)
        return_server = fakes.fake_compute_get(
            id=2, vm_state=vm_states.ACTIVE,
            project_id=req.environ['nova.context'].project_id)
        self.mock_get.side_effect = return_server
        servers = self.controller.show(req, FAKE_UUID)
        expect_sg = []
        self.assertEqual(expect_sg, servers['server']['server_groups'])


class ServersControllerTestV273(ControllerTest):
    """Server Controller test for microversion 2.73

    The intent here is simply to verify that when showing server details
    after microversion 2.73 the response will also have the locked_reason
    key for the servers.
    """
    wsgi_api_version = '2.73'

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def test_get_servers_with_locked_filter(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(
                       100, uuid=uuids.fake, locked_by='fake')]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'locked=true')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])
        search = {'deleted': False, 'project_id': self.project_id,
                  'locked': True}
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'], expected_attrs=[],
            limit=1000, marker=None,
            search_opts=search,
            sort_dirs=['desc'], sort_keys=['created_at'],
            cell_down_support=False, all_tenants=False)

    def test_get_servers_with_locked_filter_invalid_value(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(
                       100, uuid=uuids.fake, locked_by='fake')]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'locked=price')
        exp = self.assertRaises(webob.exc.HTTPBadRequest,
                                self.controller.index, req)
        self.assertIn("Unrecognized value 'price'", six.text_type(exp))

    def test_get_servers_with_locked_filter_empty_value(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(
                       100, uuid=uuids.fake, locked_by='fake')]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query % 'locked=')
        exp = self.assertRaises(webob.exc.HTTPBadRequest,
                                self.controller.index, req)
        self.assertIn("Unrecognized value ''", six.text_type(exp))

    def test_get_servers_with_locked_sort_key(self):
        def fake_get_all(context, search_opts=None,
                         limit=None, marker=None,
                         expected_attrs=None, sort_keys=None, sort_dirs=None,
                         cell_down_support=False, all_tenants=False):
            db_list = [fakes.stub_instance(
                       100, uuid=uuids.fake, locked_by='fake')]
            return instance_obj._make_instance_list(
                context, objects.InstanceList(), db_list, FIELDS)

        self.mock_get_all.side_effect = fake_get_all

        req = self.req(self.path_with_query %
                       'sort_dir=desc&sort_key=locked')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])
        self.mock_get_all.assert_called_once_with(
            req.environ['nova.context'], expected_attrs=[],
            limit=1000, marker=None,
            search_opts={'deleted': False, 'project_id': self.project_id},
            sort_dirs=['desc'], sort_keys=['locked'],
            cell_down_support=False, all_tenants=False)


class ServersControllerTestV275(ControllerTest):
    wsgi_api_version = '2.75'
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

    @mock.patch('nova.compute.api.API.get_all')
    def test_get_servers_additional_query_param_old_version(self, mock_get):
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version='2.74')
        self.controller.index(req)

    @mock.patch('nova.compute.api.API.get_all')
    def test_get_servers_ignore_sort_key_old_version(self, mock_get):
        req = fakes.HTTPRequest.blank(
                self.path_with_query % 'sort_key=deleted',
                use_admin_context=True, version='2.74')
        self.controller.index(req)

    def test_get_servers_additional_query_param(self):
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version=self.wsgi_api_version)
        self.assertRaises(exception.ValidationError, self.controller.index,
                          req)

    def test_get_servers_previously_ignored_sort_key(self):
        for s_ignore in servers_schema.SERVER_LIST_IGNORE_SORT_KEY_V273:
            req = fakes.HTTPRequest.blank(
                self.path_with_query % 'sort_key=%s' % s_ignore,
                use_admin_context=True,
                version=self.wsgi_api_version)
            self.assertRaises(exception.ValidationError, self.controller.index,
                              req)

    def test_get_servers_additional_sort_key(self):
        req = fakes.HTTPRequest.blank(
                self.path_with_query % 'sort_key=unknown',
                use_admin_context=True, version=self.wsgi_api_version)
        self.assertRaises(exception.ValidationError, self.controller.index,
                          req)

    def test_update_response_no_show_server_only_attributes_old_version(self):
        # There are some old server attributes which were added only for
        # GET server APIs not for PUT. GET server and PUT server share the
        # same view builder method SHOW() to build the response, So make sure
        # attributes which are not supposed to be included for PUT
        # response are not present.
        body = {'server': {'name': 'server_test'}}
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version='2.74')
        res_dict = self.controller.update(req, FAKE_UUID, body=body)
        for field in GET_ONLY_FIELDS:
            self.assertNotIn(field, res_dict['server'])
        for items in res_dict['server']['addresses'].values():
            for item in items:
                self.assertNotIn('OS-EXT-IPS:type', item)
                self.assertNotIn('OS-EXT-IPS-MAC:mac_addr', item)

    def test_update_response_has_show_server_all_attributes(self):
        body = {'server': {'name': 'server_test'}}
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version=self.wsgi_api_version)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)
        for field in GET_ONLY_FIELDS:
            self.assertIn(field, res_dict['server'])
        for items in res_dict['server']['addresses'].values():
            for item in items:
                self.assertIn('OS-EXT-IPS:type', item)
                self.assertIn('OS-EXT-IPS-MAC:mac_addr', item)

    def test_rebuild_response_no_show_server_only_attributes_old_version(self):
        # There are some old server attributes which were added only for
        # GET server APIs not for Rebuild. GET server and Rebuild server share
        # same view builder method SHOW() to build the response, So make sure
        # the attributes which are not supposed to be included for Rebuild
        # response are not present.
        body = {'rebuild': {"imageRef": self.image_uuid}}
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version='2.74')
        fake_get = fakes.fake_compute_get(
            vm_state=vm_states.ACTIVE,
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get

        res_dict = self.controller._action_rebuild(req, FAKE_UUID,
                                                   body=body).obj
        get_only_fields_Rebuild = copy.deepcopy(GET_ONLY_FIELDS)
        get_only_fields_Rebuild.remove('key_name')
        for field in get_only_fields_Rebuild:
            self.assertNotIn(field, res_dict['server'])
        for items in res_dict['server']['addresses'].values():
            for item in items:
                self.assertNotIn('OS-EXT-IPS:type', item)
                self.assertNotIn('OS-EXT-IPS-MAC:mac_addr', item)

    def test_rebuild_response_has_show_server_all_attributes(self):
        body = {'rebuild': {"imageRef": self.image_uuid}}
        req = fakes.HTTPRequest.blank(self.path_with_query % 'unknown=1',
                                      use_admin_context=True,
                                      version=self.wsgi_api_version)
        fake_get = fakes.fake_compute_get(
            vm_state=vm_states.ACTIVE,
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get
        res_dict = self.controller._action_rebuild(req, FAKE_UUID,
                                                   body=body).obj
        for field in GET_ONLY_FIELDS:
            if field == 'OS-EXT-SRV-ATTR:user_data':
                self.assertNotIn(field, res_dict['server'])
                field = 'user_data'
            self.assertIn(field, res_dict['server'])
        for items in res_dict['server']['addresses'].values():
            for item in items:
                self.assertIn('OS-EXT-IPS:type', item)
                self.assertIn('OS-EXT-IPS-MAC:mac_addr', item)


class ServersControllerTestV283(ControllerTest):
    filters = ['availability_zone', 'config_drive', 'key_name',
               'created_at', 'launched_at', 'terminated_at',
               'power_state', 'task_state', 'vm_state', 'progress',
               'user_id']

    def test_get_servers_by_new_filter_for_non_admin(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            for f in self.filters:
                self.assertIn(f, search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        self.mock_get_all.side_effect = fake_get_all

        query_str = '&'.join('%s=test_value' % f for f in self.filters)
        req = fakes.HTTPRequest.blank(self.path_with_query % query_str,
                                      version='2.83')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])

    def test_get_servers_new_filters_for_non_admin_old_version(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            for f in self.filters:
                self.assertNotIn(f, search_opts)
            return objects.InstanceList(
                objects=[])

        # Without policy edition, test will fail and admin filter will work.
        self.policy.set_rules({'os_compute_api:servers:index': ''})
        self.mock_get_all.side_effect = fake_get_all

        query_str = '&'.join('%s=test_value' % f for f in self.filters)
        req = fakes.HTTPRequest.blank(self.path_with_query % query_str,
                                      version='2.82')
        servers = self.controller.index(req)['servers']

        self.assertEqual(0, len(servers))

    def test_get_servers_by_node_fail_non_admin(self):
        def fake_get_all(context, search_opts=None, **kwargs):
            self.assertIsNotNone(search_opts)
            self.assertNotIn('node', search_opts)
            return objects.InstanceList(
                objects=[fakes.stub_instance_obj(100, uuid=uuids.fake)])

        server_filter_rule = 'os_compute_api:servers:allow_all_filters'
        self.policy.set_rules({'os_compute_api:servers:index': '',
                               server_filter_rule: 'role:admin'})
        self.mock_get_all.side_effect = fake_get_all

        query_str = "node=node1"
        req = fakes.HTTPRequest.blank(self.path_with_query % query_str,
                                      version='2.83')
        servers = self.controller.index(req)['servers']

        self.assertEqual(1, len(servers))
        self.assertEqual(uuids.fake, servers[0]['id'])


class ServersControllerDeleteTest(ControllerTest):

    def setUp(self):
        super(ServersControllerDeleteTest, self).setUp()
        self.server_delete_called = False

        def fake_delete(api, context, instance):
            if instance.uuid == uuids.non_existent_uuid:
                raise exception.InstanceNotFound(instance_id=instance.uuid)
            self.server_delete_called = True

        self.stub_out('nova.compute.api.API.delete', fake_delete)

    def _create_delete_request(self, uuid):
        fakes.stub_out_instance_quota(self, 0, 10)
        req = fakes.HTTPRequestV21.blank(self.path_with_id % uuid)
        req.method = 'DELETE'
        fake_get = fakes.fake_compute_get(
            uuid=uuid,
            vm_state=vm_states.ACTIVE,
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get
        return req

    def _delete_server_instance(self, uuid=FAKE_UUID):
        req = self._create_delete_request(uuid)
        self.controller.delete(req, uuid)

    def test_delete_server_instance(self):
        self._delete_server_instance()
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self._delete_server_instance,
                          uuid=uuids.non_existent_uuid)

    def test_delete_server_instance_while_building(self):
        req = self._create_delete_request(FAKE_UUID)
        self.controller.delete(req, FAKE_UUID)

        self.assertTrue(self.server_delete_called)

    @mock.patch.object(compute_api.API, 'delete',
                       side_effect=exception.InstanceIsLocked(
                           instance_uuid=FAKE_UUID))
    def test_delete_locked_server(self, mock_delete):
        req = self._create_delete_request(FAKE_UUID)

        self.assertRaises(webob.exc.HTTPConflict, self.controller.delete,
                          req, FAKE_UUID)
        mock_delete.assert_called_once_with(
            req.environ['nova.context'], test.MatchType(objects.Instance))

    def test_delete_server_instance_while_resize(self):
        req = self._create_delete_request(FAKE_UUID)
        fake_get = fakes.fake_compute_get(
            vm_state=vm_states.ACTIVE,
            task_state=task_states.RESIZE_PREP,
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get

        self.controller.delete(req, FAKE_UUID)

    def test_delete_server_instance_if_not_launched(self):
        self.flags(reclaim_instance_interval=3600)
        req = fakes.HTTPRequestV21.blank(self.path_with_id % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        fake_get = fakes.fake_compute_get(
            launched_at=None,
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get

        def instance_destroy_mock(*args, **kwargs):
            self.server_delete_called = True
            deleted_at = timeutils.utcnow()
            return fake_instance.fake_db_instance(deleted_at=deleted_at)
        self.stub_out('nova.db.api.instance_destroy', instance_destroy_mock)

        self.controller.delete(req, FAKE_UUID)
        # delete() should be called for instance which has never been active,
        # even if reclaim_instance_interval has been set.
        self.assertTrue(self.server_delete_called)


class ServersControllerRebuildInstanceTest(ControllerTest):

    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    expected_key_name = False

    def setUp(self):
        super(ServersControllerRebuildInstanceTest, self).setUp()
        self.req = fakes.HTTPRequest.blank(self.path_action % FAKE_UUID)
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"
        self.req_user_id = self.req.environ['nova.context'].user_id
        self.req_project_id = self.req.environ['nova.context'].project_id
        self.useFixture(nova_fixtures.SingleCellSimple())

        def fake_get(ctrl, ctxt, uuid):
            if uuid == 'test_inst':
                raise webob.exc.HTTPNotFound(explanation='fakeout')
            return fakes.stub_instance_obj(None,
                                           vm_state=vm_states.ACTIVE,
                                           project_id=self.req_project_id,
                                           user_id=self.req_user_id)

        self.useFixture(
            fixtures.MonkeyPatch('nova.api.openstack.compute.servers.'
                                 'ServersController._get_instance',
                                 fake_get))
        fake_get = fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                          project_id=self.req_project_id,
                                          user_id=self.req_user_id)
        self.mock_get.side_effect = fake_get

        self.body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': self.image_uuid,
                'metadata': {
                    'open': 'stack',
                },
            },
        }

    def test_rebuild_server_with_image_not_uuid(self):
        self.body['rebuild']['imageRef'] = 'not-uuid'
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID,
                          body=self.body)

    def test_rebuild_server_with_image_as_full_url(self):
        image_href = (
            'http://localhost/v2/%s/images/'
            '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6' % self.project_id)
        self.body['rebuild']['imageRef'] = image_href
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID,
                          body=self.body)

    def test_rebuild_server_with_image_as_empty_string(self):
        self.body['rebuild']['imageRef'] = ''
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID,
                          body=self.body)

    def test_rebuild_instance_name_with_spaces_in_the_middle(self):
        self.body['rebuild']['name'] = 'abc   def'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.controller._action_rebuild(self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_name_with_leading_trailing_spaces(self):
        self.body['rebuild']['name'] = '  abc   def  '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_name_with_leading_trailing_spaces_compat_mode(
            self):
        self.body['rebuild']['name'] = '  abc  def  '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.set_legacy_v2()

        def fake_rebuild(*args, **kwargs):
            self.assertEqual('abc  def', kwargs['display_name'])

        with mock.patch.object(compute_api.API, 'rebuild') as mock_rebuild:
            mock_rebuild.side_effect = fake_rebuild
            self.controller._action_rebuild(self.req, FAKE_UUID,
                                            body=self.body)

    def test_rebuild_instance_with_blank_metadata_key(self):
        self.body['rebuild']['metadata'][''] = 'world'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_metadata_key_too_long(self):
        self.body['rebuild']['metadata'][('a' * 260)] = 'world'

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_metadata_value_too_long(self):
        self.body['rebuild']['metadata']['key1'] = ('a' * 260)

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_metadata_value_not_string(self):
        self.body['rebuild']['metadata']['key1'] = 1

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=self.body)

    @mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                       return_value=dict(
                           id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                           name='public image', is_public=True,
                           status='active', properties={'key1': 'value1'},
                           min_ram="4096", min_disk="10"))
    def test_rebuild_instance_fails_when_min_ram_too_small(self, mock_show):
        # make min_ram larger than our instance ram size
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)
        mock_show.assert_called_once_with(
            self.req.environ['nova.context'], self.image_uuid,
            include_locations=False, show_deleted=True)

    @mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                       return_value=dict(
                           id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                           name='public image', is_public=True,
                           status='active', properties={'key1': 'value1'},
                           min_ram="128", min_disk="100000"))
    def test_rebuild_instance_fails_when_min_disk_too_small(self, mock_show):
        # make min_disk larger than our instance disk size
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=self.body)
        mock_show.assert_called_once_with(
            self.req.environ['nova.context'], self.image_uuid,
            include_locations=False, show_deleted=True)

    @mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                       return_value=dict(
                           id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                           name='public image', is_public=True,
                           status='active', size=str(1000 * (1024 ** 3))))
    def test_rebuild_instance_image_too_large(self, mock_show):
        # make image size larger than our instance disk size
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)
        mock_show.assert_called_once_with(
            self.req.environ['nova.context'], self.image_uuid,
            include_locations=False, show_deleted=True)

    def test_rebuild_instance_name_all_blank(self):
        self.body['rebuild']['name'] = '     '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    @mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                       return_value=dict(
                           id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                           name='public image', is_public=True,
                           status='DELETED'))
    def test_rebuild_instance_with_deleted_image(self, mock_show):
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)
        mock_show.assert_called_once_with(
            self.req.environ['nova.context'], self.image_uuid,
            include_locations=False, show_deleted=True)

    def test_rebuild_instance_onset_file_limit_over_quota(self):
        def fake_get_image(self, context, image_href, **kwargs):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True, status='active')

        with test.nested(
            mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                              side_effect=fake_get_image),
            mock.patch.object(self.controller.compute_api, 'rebuild',
                              side_effect=exception.OnsetFileLimitExceeded)
        ) as (
            show_mock, rebuild_mock
        ):
            self.req.body = jsonutils.dump_as_bytes(self.body)
            self.assertRaises(webob.exc.HTTPForbidden,
                              self.controller._action_rebuild,
                              self.req, FAKE_UUID, body=self.body)

    def test_rebuild_bad_personality(self):
        # Personality files have been deprecated as of v2.57
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.56')

        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "personality": [{
                    "path": "/path/to/file",
                    "contents": "INVALID b64",
                }]
            },
        }

        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_personality(self):
        # Personality files have been deprecated as of v2.57
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.56')

        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "personality": [{
                    "path": "/path/to/file",
                    "contents": base64.encode_as_text("Test String"),
                }]
            },
        }

        body = self.controller._action_rebuild(self.req, FAKE_UUID,
                                               body=body).obj

        self.assertNotIn('personality', body['server'])

    def test_rebuild_response_has_no_show_server_only_attributes(self):
        # There are some old server attributes which were added only for
        # GET server APIs not for rebuild. GET server and Rebuild share the
        # same view builder method SHOW() to build the response, So make sure
        # attributes which are not supposed to be included for Rebuild
        # response are not present.

        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
            },
        }

        body = self.controller._action_rebuild(self.req, FAKE_UUID,
                                               body=body).obj
        get_only_fields = copy.deepcopy(GET_ONLY_FIELDS)
        if self.expected_key_name:
            get_only_fields.remove('key_name')
        for field in get_only_fields:
            self.assertNotIn(field, body['server'])

    @mock.patch.object(compute_api.API, 'start')
    def test_start(self, mock_start):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(start="")
        self.controller._start_server(req, FAKE_UUID, body)
        mock_start.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(compute_api.API, 'start', fake_start_stop_not_ready)
    def test_start_not_ready(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    @mock.patch.object(
        compute_api.API, 'start', fakes.fake_actions_to_locked_server)
    def test_start_locked_server(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    @mock.patch.object(compute_api.API, 'start', fake_start_stop_invalid_state)
    def test_start_invalid(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    @mock.patch.object(compute_api.API, 'stop')
    def test_stop(self, mock_stop):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(stop="")
        self.controller._stop_server(req, FAKE_UUID, body)
        mock_stop.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(compute_api.API, 'stop', fake_start_stop_not_ready)
    def test_stop_not_ready(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    @mock.patch.object(
        compute_api.API, 'stop', fakes.fake_actions_to_locked_server)
    def test_stop_locked_server(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    @mock.patch.object(compute_api.API, 'stop', fake_start_stop_invalid_state)
    def test_stop_invalid_state(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    @mock.patch(
        'nova.db.api.instance_get_by_uuid',
        fake_instance_get_by_uuid_not_found)
    def test_start_with_bogus_id(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % 'test_inst')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, req, 'test_inst', body)

    @mock.patch(
        'nova.db.api.instance_get_by_uuid',
        fake_instance_get_by_uuid_not_found)
    def test_stop_with_bogus_id(self):
        req = fakes.HTTPRequestV21.blank(self.path_action % 'test_inst')
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, req, 'test_inst', body)


class ServersControllerRebuildTestV254(ServersControllerRebuildInstanceTest):
    expected_key_name = True

    def setUp(self):
        super(ServersControllerRebuildTestV254, self).setUp()
        fakes.stub_out_key_pair_funcs(self)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.54')

    def _test_set_key_name_rebuild(self, set_key_name=True):
        key_name = "key"
        fake_get = fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                          key_name=key_name,
                                          project_id=self.req_project_id,
                                          user_id=self.req_user_id)
        self.mock_get.side_effect = fake_get

        if set_key_name:
            self.body['rebuild']['key_name'] = key_name
        self.req.body = jsonutils.dump_as_bytes(self.body)
        server = self.controller._action_rebuild(
            self.req, FAKE_UUID,
            body=self.body).obj['server']
        self.assertEqual(server['id'], FAKE_UUID)
        self.assertEqual(server['key_name'], key_name)

    def test_rebuild_accepted_with_keypair_name(self):
        self._test_set_key_name_rebuild()

    def test_rebuild_key_not_changed(self):
        self._test_set_key_name_rebuild(set_key_name=False)

    def test_rebuild_invalid_microversion_253(self):
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.53')
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": "key"
            },
        }
        excpt = self.assertRaises(exception.ValidationError,
                                  self.controller._action_rebuild,
                                  self.req, FAKE_UUID, body=body)
        self.assertIn('key_name', six.text_type(excpt))

    def test_rebuild_with_not_existed_keypair_name(self):
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": "nonexistentkey"
            },
        }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_user_has_no_key_pair(self):
        def no_key_pair(context, user_id, name):
            raise exception.KeypairNotFound(user_id=user_id, name=name)
        self.stub_out('nova.db.api.key_pair_get', no_key_pair)
        fake_get = fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                          key_name=None,
                                          project_id=self.req_project_id,
                                          user_id=self.req_user_id)
        self.mock_get.side_effect = fake_get
        self.body['rebuild']['key_name'] = "a-key-name"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_with_non_string_keypair_name(self):
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": 12345
            },
        }
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_with_invalid_keypair_name(self):
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": "123\0d456"
            },
        }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_with_empty_keypair_name(self):
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": ''
            },
        }
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)

    def test_rebuild_with_none_keypair_name(self):
        key_name = None
        fake_get = fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                          key_name=key_name,
                                          project_id=self.req_project_id,
                                          user_id=self.req_user_id)
        self.mock_get.side_effect = fake_get
        with mock.patch.object(objects.KeyPair, 'get_by_name') as key_get:
            self.body['rebuild']['key_name'] = key_name
            self.req.body = jsonutils.dump_as_bytes(self.body)
            self.controller._action_rebuild(
                self.req, FAKE_UUID,
                body=self.body)
            # NOTE: because the api will call _get_server twice. The server
            # response will always be the same one. So we just use
            # objects.KeyPair.get_by_name to verify test.
            key_get.assert_not_called()

    def test_rebuild_with_too_large_keypair_name(self):
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "key_name": 256 * "k"
            },
        }
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=body)


class ServersControllerRebuildTestV257(ServersControllerRebuildTestV254):
    """Tests server rebuild at microversion 2.57 where user_data can be
    provided and personality files are no longer accepted.
    """

    def setUp(self):
        super(ServersControllerRebuildTestV257, self).setUp()
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.57')

    def test_rebuild_personality(self):
        """Tests that trying to rebuild with personality files fails."""
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "personality": [{
                    "path": "/path/to/file",
                    "contents": base64.encode_as_text("Test String"),
                }]
            }
        }
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=body)
        self.assertIn('personality', six.text_type(ex))

    def test_rebuild_user_data_old_version(self):
        """Tests that trying to rebuild with user_data before 2.57 fails."""
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "user_data": "ZWNobyAiaGVsbG8gd29ybGQi"
            }
        }
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.55')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=body)
        self.assertIn('user_data', six.text_type(ex))

    def test_rebuild_user_data_malformed(self):
        """Tests that trying to rebuild with malformed user_data fails."""
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "user_data": b'invalid'
            }
        }
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=body)
        self.assertIn('user_data', six.text_type(ex))

    def test_rebuild_user_data_too_large(self):
        """Tests that passing user_data to rebuild that is too large fails."""
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "user_data": ('MQ==' * 16384)
            }
        }
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=body)
        self.assertIn('user_data', six.text_type(ex))

    @mock.patch.object(context.RequestContext, 'can')
    @mock.patch('nova.db.api.instance_update_and_get_original')
    def test_rebuild_reset_user_data(self, mock_update, mock_policy):
        """Tests that passing user_data=None resets the user_data on the
        instance.
        """
        body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "user_data": None
            }
        }

        self.mock_get.side_effect = None
        self.mock_get.return_value = fakes.stub_instance_obj(
            context.RequestContext(self.req_user_id, self.req_project_id),
            user_data='ZWNobyAiaGVsbG8gd29ybGQi')

        def fake_instance_update_and_get_original(
                ctxt, instance_uuid, values, **kwargs):
            # save() is called twice and the second one has system_metadata
            # in the updates, so we can ignore that one.
            if 'system_metadata' not in values:
                self.assertIn('user_data', values)
                self.assertIsNone(values['user_data'])
            return instance_update_and_get_original(
                ctxt, instance_uuid, values, **kwargs)
        mock_update.side_effect = fake_instance_update_and_get_original
        self.controller._action_rebuild(self.req, FAKE_UUID, body=body)
        self.assertEqual(2, mock_update.call_count)


class ServersControllerRebuildTestV219(ServersControllerRebuildInstanceTest):

    def setUp(self):
        super(ServersControllerRebuildTestV219, self).setUp()
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.19')

    def _rebuild_server(self, set_desc, desc):
        fake_get = fakes.fake_compute_get(vm_state=vm_states.ACTIVE,
                                          display_description=desc,
                                          project_id=self.req_project_id,
                                          user_id=self.req_user_id)
        self.mock_get.side_effect = fake_get

        if set_desc:
            self.body['rebuild']['description'] = desc
        self.req.body = jsonutils.dump_as_bytes(self.body)
        server = self.controller._action_rebuild(self.req, FAKE_UUID,
                                                 body=self.body).obj['server']
        self.assertEqual(server['id'], FAKE_UUID)
        self.assertEqual(server['description'], desc)

    def test_rebuild_server_with_description(self):
        self._rebuild_server(True, 'server desc')

    def test_rebuild_server_empty_description(self):
        self._rebuild_server(True, '')

    def test_rebuild_server_without_description(self):
        self._rebuild_server(False, '')

    def test_rebuild_server_remove_description(self):
        self._rebuild_server(True, None)

    def test_rebuild_server_description_too_long(self):
        self.body['rebuild']['description'] = 'x' * 256
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_server_description_invalid(self):
        # Invalid non-printable control char in the desc.
        self.body['rebuild']['description'] = "123\0d456"
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)


# NOTE(jaypipes): Not based from ServersControllerRebuildInstanceTest because
# that test case's setUp is completely b0rked
class ServersControllerRebuildTestV263(ControllerTest):

    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

    def setUp(self):
        super(ServersControllerRebuildTestV263, self).setUp()
        self.req = fakes.HTTPRequest.blank(self.path_action % FAKE_UUID)
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"
        self.req_user_id = self.req.environ['nova.context'].user_id
        self.req_project_id = self.req.environ['nova.context'].project_id
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.63')
        self.body = {
            'rebuild': {
                'name': 'new_name',
                'imageRef': self.image_uuid,
                'metadata': {
                    'open': 'stack',
                },
            },
        }

    @mock.patch('nova.compute.api.API.get')
    def _rebuild_server(self, mock_get, certs=None,
                        conf_enabled=True, conf_certs=None):
        fakes.stub_out_trusted_certs(self, certs=certs)
        ctx = self.req.environ['nova.context']
        mock_get.return_value = fakes.stub_instance_obj(ctx,
            vm_state=vm_states.ACTIVE, trusted_certs=certs,
            project_id=self.req_project_id, user_id=self.req_user_id)

        self.flags(default_trusted_certificate_ids=conf_certs, group='glance')

        if conf_enabled:
            self.flags(verify_glance_signatures=True, group='glance')
            self.flags(enable_certificate_validation=True, group='glance')

        self.body['rebuild']['trusted_image_certificates'] = certs
        self.req.body = jsonutils.dump_as_bytes(self.body)
        server = self.controller._action_rebuild(
            self.req, FAKE_UUID, body=self.body).obj['server']

        if certs:
            self.assertEqual(certs, server['trusted_image_certificates'])
        else:
            if conf_enabled:
                # configuration file default is used
                self.assertEqual(
                    conf_certs, server['trusted_image_certificates'])
            else:
                # either not set or empty
                self.assertIsNone(server['trusted_image_certificates'])

    def test_rebuild_server_with_trusted_certs(self):
        """Test rebuild with valid trusted_image_certificates argument"""
        self._rebuild_server(
            certs=['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8',
                   '674736e3-f25c-405c-8362-bbf991e0ce0a'])

    def test_rebuild_server_without_trusted_certs(self):
        """Test rebuild without trusted image certificates"""
        self._rebuild_server()

    def test_rebuild_server_conf_options_turned_off_set(self):
        """Test rebuild with feature disabled and certs specified"""
        self._rebuild_server(
            certs=['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8'], conf_enabled=False)

    def test_rebuild_server_conf_options_turned_off_empty(self):
        """Test rebuild with feature disabled"""
        self._rebuild_server(conf_enabled=False)

    def test_rebuild_server_default_trusted_certificates_empty(self):
        """Test rebuild with feature enabled and no certs specified"""
        self._rebuild_server(conf_enabled=True)

    def test_rebuild_server_default_trusted_certificates(self):
        """Test rebuild with certificate specified in configurations"""
        self._rebuild_server(conf_enabled=True, conf_certs=['conf-id'])

    def test_rebuild_server_with_empty_trusted_cert_id(self):
        """Make sure that we can't rebuild with an empty certificate ID"""
        self.body['rebuild']['trusted_image_certificates'] = ['']
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('is too short', six.text_type(ex))

    def test_rebuild_server_with_empty_trusted_certs(self):
        """Make sure that we can't rebuild with an empty array of IDs"""
        self.body['rebuild']['trusted_image_certificates'] = []
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('is too short', six.text_type(ex))

    def test_rebuild_server_with_too_many_trusted_certs(self):
        """Make sure that we can't rebuild with an array of >50 unique IDs"""
        self.body['rebuild']['trusted_image_certificates'] = [
            'cert{}'.format(i) for i in range(51)]
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('is too long', six.text_type(ex))

    def test_rebuild_server_with_nonunique_trusted_certs(self):
        """Make sure that we can't rebuild with a non-unique array of IDs"""
        self.body['rebuild']['trusted_image_certificates'] = ['cert', 'cert']
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('has non-unique elements', six.text_type(ex))

    def test_rebuild_server_with_invalid_trusted_cert_id(self):
        """Make sure that we can't rebuild with non-string certificate IDs"""
        self.body['rebuild']['trusted_image_certificates'] = [1, 2]
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('is not of type', six.text_type(ex))

    def test_rebuild_server_with_invalid_trusted_certs(self):
        """Make sure that we can't rebuild with certificates in a non-array"""
        self.body['rebuild']['trusted_image_certificates'] = "not-an-array"
        self.req.body = jsonutils.dump_as_bytes(self.body)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('is not of type', six.text_type(ex))

    def test_rebuild_server_with_trusted_certs_pre_2_63_fails(self):
        """Make sure we can't use trusted_certs before 2.63"""
        self._rebuild_server(certs=['trusted-cert-id'])
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.62')
        ex = self.assertRaises(exception.ValidationError,
                               self.controller._action_rebuild,
                               self.req, FAKE_UUID, body=self.body)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    def test_rebuild_server_with_trusted_certs_policy_failed(self):
        rule_name = "os_compute_api:servers:rebuild:trusted_certs"
        rules = {"os_compute_api:servers:rebuild": "@",
                 rule_name: "project:%s" % fakes.FAKE_PROJECT_ID}
        self.policy.set_rules(rules)
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self._rebuild_server,
                                certs=['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8'])
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch.object(compute_api.API, 'rebuild')
    def test_rebuild_server_with_cert_validation_error(
            self, mock_rebuild):
        mock_rebuild.side_effect = exception.CertificateValidationFailed(
            cert_uuid="cert id", reason="test cert validation error")

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._rebuild_server,
                               certs=['trusted-cert-id'])
        self.assertIn('test cert validation error',
                      six.text_type(ex))


class ServersControllerRebuildTestV271(ControllerTest):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'

    def setUp(self):
        super(ServersControllerRebuildTestV271, self).setUp()
        self.req = fakes.HTTPRequest.blank(self.path_action % FAKE_UUID,
                                           use_admin_context=True)
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"
        self.req_user_id = self.req.environ['nova.context'].user_id
        self.req_project_id = self.req.environ['nova.context'].project_id
        self.req.api_version_request = (api_version_request.
                                         APIVersionRequest('2.71'))
        self.body = {
            "rebuild": {
                "imageRef": self.image_uuid,
                "user_data": None
            }
        }

    @mock.patch('nova.compute.api.API.get')
    def _rebuild_server(self, mock_get):
        ctx = self.req.environ['nova.context']
        mock_get.return_value = fakes.stub_instance_obj(ctx,
            vm_state=vm_states.ACTIVE, project_id=self.req_project_id,
            user_id=self.req_user_id)
        server = self.controller._action_rebuild(
            self.req, FAKE_UUID, body=self.body).obj['server']
        return server

    @mock.patch.object(InstanceGroup, 'get_by_instance_uuid',
            side_effect=exception.InstanceGroupNotFound(group_uuid=FAKE_UUID))
    def test_rebuild_with_server_group_not_exist(self, mock_sg_get):
        server = self._rebuild_server()
        self.assertEqual([], server['server_groups'])


class ServersControllerUpdateTest(ControllerTest):

    def _get_request(self, body=None):
        req = fakes.HTTPRequestV21.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dump_as_bytes(body)
        fake_get = fakes.fake_compute_get(
            project_id=req.environ['nova.context'].project_id,
            user_id=req.environ['nova.context'].user_id)
        self.mock_get.side_effect = fake_get
        return req

    def test_update_server_all_attributes(self):
        body = {'server': {
                  'name': 'server_test',
               }}
        req = self._get_request(body)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_name(self):
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_response_has_no_show_server_only_attributes(self):
        # There are some old server attributes which were added only for
        # GET server APIs not for PUT. GET server and PUT server share the
        # same view builder method SHOW() to build the response, So make sure
        # attributes which are not supposed to be included for PUT
        # response are not present.
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)
        for field in GET_ONLY_FIELDS:
            self.assertNotIn(field, res_dict['server'])

    def test_update_server_name_too_long(self):
        body = {'server': {'name': 'x' * 256}}
        req = self._get_request(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_name_all_blank_spaces(self):
        self.stub_out('nova.db.api.instance_get',
                fakes.fake_instance_get(name='server_test'))
        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': ' ' * 64}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_name_with_spaces_in_the_middle(self):
        body = {'server': {'name': 'abc   def'}}
        req = self._get_request(body)
        self.controller.update(req, FAKE_UUID, body=body)

    def test_update_server_name_with_leading_trailing_spaces(self):
        self.stub_out('nova.db.api.instance_get',
                fakes.fake_instance_get(name='server_test'))
        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': '  abc   def  '}}
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError,
                          self.controller.update, req, FAKE_UUID, body=body)

    def test_update_server_name_with_leading_trailing_spaces_compat_mode(self):
        body = {'server': {'name': '  abc   def  '}}
        req = self._get_request(body)
        req.set_legacy_v2()
        self.controller.update(req, FAKE_UUID, body=body)

    def test_update_server_admin_password_extra_arg(self):
        inst_dict = dict(name='server_test', admin_password='bacon')
        body = dict(server=inst_dict)

        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_host_id(self):
        inst_dict = dict(host_id='123')
        body = dict(server=inst_dict)

        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_not_found(self):
        self.mock_get.side_effect = exception.InstanceNotFound(
            instance_id='fake')
        body = {'server': {'name': 'server_test'}}
        req = fakes.HTTPRequest.blank(self.path_with_id % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = jsonutils.dump_as_bytes(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body=body)

    @mock.patch.object(compute_api.API, 'update_instance')
    def test_update_server_not_found_on_update(self, mock_update_instance):
        def fake_update(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        mock_update_instance.side_effect = fake_update
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_policy_fail(self):
        rule = {'compute:update': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rule))
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller.update, req, FAKE_UUID, body=body)


class ServersControllerTriggerCrashDumpTest(ControllerTest):

    def setUp(self):
        super(ServersControllerTriggerCrashDumpTest, self).setUp()

        self.instance = fakes.stub_instance_obj(None,
                                                vm_state=vm_states.ACTIVE,
                                                project_id=self.project_id)

        def fake_get(ctrl, ctxt, uuid):
            if uuid != FAKE_UUID:
                raise webob.exc.HTTPNotFound(explanation='fakeout')
            return self.instance

        self.useFixture(
            fixtures.MonkeyPatch('nova.api.openstack.compute.servers.'
                                 'ServersController._get_instance',
                                 fake_get))

        self.req = fakes.HTTPRequest.blank(self.path_action % FAKE_UUID)
        self.req.api_version_request =\
            api_version_request.APIVersionRequest('2.17')
        self.body = dict(trigger_crash_dump=None)

    @mock.patch.object(compute_api.API, 'trigger_crash_dump')
    def test_trigger_crash_dump(self, mock_trigger_crash_dump):
        ctxt = self.req.environ['nova.context']
        self.controller._action_trigger_crash_dump(self.req, FAKE_UUID,
                                                   body=self.body)
        mock_trigger_crash_dump.assert_called_with(ctxt, self.instance)

    def test_trigger_crash_dump_policy_failed(self):
        rule_name = "os_compute_api:servers:trigger_crash_dump"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._action_trigger_crash_dump,
                                self.req, FAKE_UUID, body=self.body)
        self.assertIn("os_compute_api:servers:trigger_crash_dump",
                      exc.format_message())

    @mock.patch.object(compute_api.API, 'trigger_crash_dump',
                       fake_start_stop_not_ready)
    def test_trigger_crash_dump_not_ready(self):
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_trigger_crash_dump,
                          self.req, FAKE_UUID, body=self.body)

    @mock.patch.object(compute_api.API, 'trigger_crash_dump',
                       fakes.fake_actions_to_locked_server)
    def test_trigger_crash_dump_locked_server(self):
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_trigger_crash_dump,
                          self.req, FAKE_UUID, body=self.body)

    @mock.patch.object(compute_api.API, 'trigger_crash_dump',
                       fake_start_stop_invalid_state)
    def test_trigger_crash_dump_invalid_state(self):
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._action_trigger_crash_dump,
                          self.req, FAKE_UUID, body=self.body)

    def test_trigger_crash_dump_with_bogus_id(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_trigger_crash_dump,
                          self.req, 'test_inst', body=self.body)

    def test_trigger_crash_dump_schema_invalid_type(self):
        self.body['trigger_crash_dump'] = 'not null'
        self.assertRaises(exception.ValidationError,
                          self.controller._action_trigger_crash_dump,
                          self.req, FAKE_UUID, body=self.body)

    def test_trigger_crash_dump_schema_extra_property(self):
        self.body['extra_property'] = 'extra'
        self.assertRaises(exception.ValidationError,
                          self.controller._action_trigger_crash_dump,
                          self.req, FAKE_UUID, body=self.body)


class ServersControllerUpdateTestV219(ServersControllerUpdateTest):
    def _get_request(self, body=None):
        req = super(ServersControllerUpdateTestV219, self)._get_request(
            body=body)
        req.api_version_request = api_version_request.APIVersionRequest('2.19')
        return req

    def _update_server_desc(self, set_desc, desc=None):
        body = {'server': {}}
        if set_desc:
            body['server']['description'] = desc
        req = self._get_request()
        res_dict = self.controller.update(req, FAKE_UUID, body=body)
        return res_dict

    def test_update_server_description(self):
        res_dict = self._update_server_desc(True, 'server_desc')
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['description'], 'server_desc')

    def test_update_server_empty_description(self):
        res_dict = self._update_server_desc(True, '')
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['description'], '')

    def test_update_server_without_description(self):
        res_dict = self._update_server_desc(False)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertIsNone(res_dict['server']['description'])

    def test_update_server_remove_description(self):
        res_dict = self._update_server_desc(True)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertIsNone(res_dict['server']['description'])

    def test_update_server_all_attributes(self):
        body = {'server': {
                  'name': 'server_test',
                  'description': 'server_desc'
               }}
        req = self._get_request(body)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')
        self.assertEqual(res_dict['server']['description'], 'server_desc')

    def test_update_server_description_too_long(self):
        body = {'server': {'description': 'x' * 256}}
        req = self._get_request(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_description_invalid(self):
        # Invalid non-printable control char in the desc.
        body = {'server': {'description': "123\0d456"}}
        req = self._get_request(body)
        self.assertRaises(exception.ValidationError, self.controller.update,
                          req, FAKE_UUID, body=body)


class ServersControllerUpdateTestV271(ServersControllerUpdateTest):
    body = {'server': {'name': 'server_test'}}

    def _get_request(self, body=None):
        req = super(ServersControllerUpdateTestV271, self)._get_request(
            body=body)
        req.api_version_request = api_version_request.APIVersionRequest('2.71')
        return req

    @mock.patch.object(InstanceGroup, 'get_by_instance_uuid',
             side_effect=exception.InstanceGroupNotFound(group_uuid=FAKE_UUID))
    def test_update_with_server_group_not_exist(self, mock_sg_get):
        req = self._get_request(self.body)
        res_dict = self.controller.update(req, FAKE_UUID, body=self.body)
        self.assertEqual([], res_dict['server']['server_groups'])


class ServerStatusTest(test.TestCase):
    project_id = fakes.FAKE_PROJECT_ID
    path = '/%s/servers' % project_id
    path_with_id = path + '/%s'
    path_action = path + '/%s/action'

    def setUp(self):
        super(ServerStatusTest, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(
            self, security_groups=[{'name': 'default'}])

        self.controller = servers.ServersController()

    def _get_with_state(self, vm_state, task_state=None):
        request = fakes.HTTPRequestV21.blank(self.path_with_id % FAKE_UUID)
        self.stub_out('nova.compute.api.API.get',
                fakes.fake_compute_get(
                    vm_state=vm_state,
                    task_state=task_state,
                    project_id=request.environ['nova.context'].project_id))

        return self.controller.show(request, FAKE_UUID)

    def test_active(self):
        response = self._get_with_state(vm_states.ACTIVE)
        self.assertEqual(response['server']['status'], 'ACTIVE')

    def test_reboot(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING)
        self.assertEqual(response['server']['status'], 'REBOOT')

    def test_reboot_hard(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING_HARD)
        self.assertEqual(response['server']['status'], 'HARD_REBOOT')

    def test_reboot_resize_policy_fail(self):
        rule = {'compute:reboot': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rule))
        req = fakes.HTTPRequestV21.blank(self.path_action % '1234')
        self.stub_out('nova.compute.api.API.get',
                fakes.fake_compute_get(
                    vm_state='ACTIVE',
                    task_state=None,
                    project_id=req.environ['nova.context'].project_id))
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_reboot, req, '1234',
                body={'reboot': {'type': 'HARD'}})

    def test_rebuild(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBUILDING)
        self.assertEqual(response['server']['status'], 'REBUILD')

    def test_rebuild_error(self):
        response = self._get_with_state(vm_states.ERROR)
        self.assertEqual(response['server']['status'], 'ERROR')

    def test_resize(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.RESIZE_PREP)
        self.assertEqual(response['server']['status'], 'RESIZE')

    def test_confirm_resize_policy_fail(self):
        rule = {'compute:confirm_resize': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rule))
        req = fakes.HTTPRequestV21.blank(self.path_action % '1234')
        self.stub_out('nova.compute.api.API.get',
                fakes.fake_compute_get(
                    vm_state='ACTIVE',
                    task_state=None,
                    project_id=req.environ['nova.context'].project_id))

        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_confirm_resize, req, '1234', {})

    def test_verify_resize(self):
        response = self._get_with_state(vm_states.RESIZED, None)
        self.assertEqual(response['server']['status'], 'VERIFY_RESIZE')

    def test_revert_resize(self):
        response = self._get_with_state(vm_states.RESIZED,
                                        task_states.RESIZE_REVERTING)
        self.assertEqual(response['server']['status'], 'REVERT_RESIZE')

    def test_revert_resize_policy_fail(self):
        rule = {'compute:revert_resize': 'role:admin'}
        policy.set_rules(oslo_policy.Rules.from_dict(rule))
        req = fakes.HTTPRequestV21.blank(self.path_action % '1234')
        self.stub_out('nova.compute.api.API.get',
                fakes.fake_compute_get(
                    vm_state='ACTIVE',
                    task_state=None,
                    project_id=req.environ['nova.context'].project_id))

        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_revert_resize, req, '1234', {})

    def test_password_update(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.UPDATING_PASSWORD)
        self.assertEqual(response['server']['status'], 'PASSWORD')

    def test_stopped(self):
        response = self._get_with_state(vm_states.STOPPED)
        self.assertEqual(response['server']['status'], 'SHUTOFF')


class ServersControllerCreateTest(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    flavor_ref = 'http://localhost/123/flavors/3'
    project_id = fakes.FAKE_PROJECT_ID

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(enable_instance_password=True, group='api')
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        fakes.stub_out_nw_api(self)

        self.controller = servers.ServersController()

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/%s/images/%s' % (self.project_id,
                                                               image_uuid)
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'display_description': inst['display_description'] or '',
                'uuid': FAKE_UUID,
                'instance_type': inst_type,
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': fakes.FAKE_PROJECT_ID,
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "config_drive": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "root_device_name": inst.get('root_device_name', 'vda'),
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update_and_get_original(
                context, instance_uuid, params, columns_to_join=None):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        fakes.stub_out_key_pair_funcs(self)
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.stub_out('nova.db.api.instance_create', instance_create)
        self.stub_out('nova.db.api.instance_system_metadata_update',
                      lambda *a, **kw: None)
        self.stub_out('nova.db.api.instance_get', instance_get)
        self.stub_out('nova.db.api.instance_update', instance_update)
        self.stub_out('nova.db.api.instance_update_and_get_original',
                server_update_and_get_original)
        self.body = {
            'server': {
                'name': 'server_test',
                'imageRef': self.image_uuid,
                'flavorRef': self.flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'networks': [{
                    'uuid': 'ff608d40-75e9-48cb-b745-77bb55b5eaf2'
                }],
            },
        }
        self.bdm_v2 = [{
            'no_device': None,
            'source_type': 'volume',
            'destination_type': 'volume',
            'uuid': 'fake',
            'device_name': 'vdb',
            'delete_on_termination': False,
        }]

        self.bdm = [{
            'no_device': None,
            'virtual_name': 'root',
            'volume_id': fakes.FAKE_UUID,
            'device_name': 'vda',
            'delete_on_termination': False
        }]

        self.req = fakes.HTTPRequest.blank('/%s/servers' % self.project_id)
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"
        server = dict(name='server_test', imageRef=FAKE_UUID, flavorRef=2)
        body = {'server': server}
        self.req.body = encodeutils.safe_encode(jsonutils.dumps(body))

    def _check_admin_password_len(self, server_dict):
        """utility function - check server_dict for admin_password length."""
        self.assertEqual(CONF.password_length,
                         len(server_dict["adminPass"]))

    def _check_admin_password_missing(self, server_dict):
        """utility function - check server_dict for admin_password absence."""
        self.assertNotIn("adminPass", server_dict)

    def _test_create_instance(self, flavor=2):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        self.body['server']['imageRef'] = image_uuid
        self.body['server']['flavorRef'] = flavor
        self.req.body = jsonutils.dump_as_bytes(self.body)
        server = self.controller.create(self.req, body=self.body).obj['server']
        self._check_admin_password_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_with_none_value_port(self):
        self.body['server'] = {'networks': [{'port': None, 'uuid': FAKE_UUID}]}
        self.body['server']['name'] = 'test'
        self._test_create_instance()

    def test_create_instance_private_flavor(self):
        values = {
            'name': 'fake_name',
            'memory': 512,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': '1324',
            'swap': 0,
            'rxtx_factor': 0.5,
            'is_public': False,
        }
        flavors.create(**values)
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._test_create_instance,
                               flavor=1324)
        self.assertEqual('Flavor 1324 could not be found.', six.text_type(ex))

    def test_create_server_bad_image_uuid(self):
        self.body['server']['min_count'] = 1
        self.body['server']['imageRef'] = 1,
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_server_with_deleted_image(self):
        # Get the fake image service so we can set the status to deleted
        (image_service, image_id) = glance.get_remote_image_service(
                context, '')
        image_service.update(context, self.image_uuid, {'status': 'DELETED'})
        self.addCleanup(image_service.update, context, self.image_uuid,
                        {'status': 'active'})

        self.body['server']['flavorRef'] = 2
        self.req.body = jsonutils.dump_as_bytes(self.body)
        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                'Image 76fa36fc-c930-4bf3-8c8a-ea2a2420deb6 is not active.'):
            self.controller.create(self.req, body=self.body)

    def test_create_server_image_too_large(self):
        # Get the fake image service so we can update the size of the image
        (image_service, image_id) = glance.get_remote_image_service(
                                    context, self.image_uuid)

        image = image_service.show(context, image_id)

        orig_size = image['size']
        new_size = str(1000 * (1024 ** 3))
        image_service.update(context, self.image_uuid, {'size': new_size})

        self.addCleanup(image_service.update, context, self.image_uuid,
                        {'size': orig_size})

        self.body['server']['flavorRef'] = 2
        self.req.body = jsonutils.dump_as_bytes(self.body)

        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                "Flavor's disk is too small for requested image."):
            self.controller.create(self.req, body=self.body)

    @mock.patch.object(nova_fixtures.GlanceFixture, 'show',
                       return_value=dict(
                           id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                           status='active',
                           properties=dict(
                               cinder_encryption_key_id=fakes.FAKE_UUID)))
    def test_create_server_image_nonbootable(self, mock_show):
        self.req.body = jsonutils.dump_as_bytes(self.body)

        expected_msg = ("Image {} is unacceptable: Direct booting of an image "
                        "uploaded from an encrypted volume is unsupported.")
        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                expected_msg.format(self.image_uuid)):
            self.controller.create(self.req, body=self.body)

    def test_create_instance_with_image_non_uuid(self):
        self.body['server']['imageRef'] = 'not-uuid'
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_with_image_as_full_url(self):
        image_href = ('http://localhost/v2/%s/images/'
            '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6' % self.project_id)
        self.body['server']['imageRef'] = image_href
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_with_image_as_empty_string(self):
        self.body['server']['imageRef'] = ''
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_no_key_pair(self):
        fakes.stub_out_key_pair_funcs(self, have_key_pair=False)
        self._test_create_instance()

    def _test_create_extra(self, params, no_image=False):
        self.body['server']['flavorRef'] = 2
        if no_image:
            self.body['server'].pop('imageRef', None)
        self.body['server'].update(params)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.headers["content-type"] = "application/json"
        self.controller.create(self.req, body=self.body).obj['server']

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.PortRequiresFixedIP(
                           port_id=uuids.port))
    def test_create_instance_with_port_with_no_fixed_ips(self, mock_create):
        requested_networks = [{'port': uuids.port}]
        params = {'networks': requested_networks}

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_raise_user_data_too_large(self):
        self.body['server']['user_data'] = (b'1' * 65536)
        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               self.req, body=self.body)
        # Make sure the failure was about user_data and not something else.
        self.assertIn('user_data', six.text_type(ex))

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.NetworkRequiresSubnet(
                           network_uuid=uuids.network))
    def test_create_instance_with_network_with_no_subnet(self, mock_create):
        requested_networks = [{'uuid': uuids.network}]
        params = {'networks': requested_networks}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.NoUniqueMatch(
                           "No Unique match found for ..."))
    def test_create_instance_with_non_unique_secgroup_name(self, mock_create):
        requested_networks = [{'uuid': uuids.network}]
        params = {'networks': requested_networks,
                  'security_groups': [{'name': 'dup'}, {'name': 'dup'}]}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, params)

    def test_create_instance_secgroup_leading_trailing_spaces(self):
        network = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks,
                  'security_groups': [{'name': '  sg  '}]}

        self.assertRaises(exception.ValidationError,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_secgroup_leading_trailing_spaces_compat_mode(
            self, mock_create):
        requested_networks = [{'uuid': uuids.network}]
        params = {'networks': requested_networks,
                  'security_groups': [{'name': '  sg  '}]}

        def fake_create(*args, **kwargs):
            self.assertEqual(['  sg  '], kwargs['security_groups'])
            return (objects.InstanceList(objects=[fakes.stub_instance_obj(
                self.req.environ['nova.context'])]), None)
        mock_create.side_effect = fake_create

        self.req.set_legacy_v2()
        self._test_create_extra(params)

    def test_create_instance_with_networks_disabled_neutronv2(self):
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            result = [('76fa36fc-c930-4bf3-8c8a-ea2a2420deb6', None,
                       None, None)]
            self.assertEqual(result, kwargs['requested_networks'].as_tuples())
            return old_create(*args, **kwargs)

        with mock.patch('nova.compute.api.API.create', create):
            self._test_create_extra(params)

    def test_create_instance_with_pass_disabled(self):
        # test with admin passwords disabled See lp bug 921814
        self.flags(enable_instance_password=False, group='api')
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        self.flags(enable_instance_password=False, group='api')
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_name_too_long(self):
        self.body['server']['name'] = 'X' * 256
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError, self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_name_with_spaces_in_the_middle(self):
        self.body['server']['name'] = 'abc    def'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.controller.create(self.req, body=self.body)

    def test_create_instance_name_with_leading_trailing_spaces(self):
        self.body['server']['name'] = '   abc    def   '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_name_with_leading_trailing_spaces_in_compat_mode(
            self):
        self.body['server']['name'] = '   abc    def   '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.set_legacy_v2()
        self.controller.create(self.req, body=self.body)

    def test_create_instance_name_all_blank_spaces(self):
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/%s/flavors/3' % self.project_id
        body = {
            'server': {
                'name': ' ' * 64,
                'imageRef': image_uuid,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }

        req = fakes.HTTPRequest.blank('/%s/servers' % self.project_id)
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_az_with_leading_trailing_spaces(self):
        self.body['server']['availability_zone'] = '  zone1  '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_az_with_leading_trailing_spaces_in_compat_mode(
            self):
        self.body['server']['name'] = '   abc    def   '
        self.body['server']['availability_zones'] = '  zone1  '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.set_legacy_v2()
        with mock.patch.object(availability_zones, 'get_availability_zones',
                               return_value=['  zone1  ']):
            self.controller.create(self.req, body=self.body)

    def test_create_instance(self):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_pass_disabled(self):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        self.flags(enable_instance_password=False, group='api')
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    @mock.patch('nova.virt.hardware.numa_get_constraints')
    def _test_create_instance_numa_topology_wrong(self, exc,
                                                  numa_constraints_mock):
        numa_constraints_mock.side_effect = exc(**{
            'name': None,
            'source': 'flavor',
            'requested': 'dummy',
            'available': str(objects.fields.CPUAllocationPolicy.ALL),
            'cpunum': 0,
            'cpumax': 0,
            'cpuset': None,
            'memsize': 0,
            'memtotal': 0})
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_numa_topology_wrong(self):
        for exc in [exception.ImageNUMATopologyIncomplete,
                    exception.ImageNUMATopologyForbidden,
                    exception.ImageNUMATopologyAsymmetric,
                    exception.ImageNUMATopologyCPUOutOfRange,
                    exception.ImageNUMATopologyCPUDuplicates,
                    exception.ImageNUMATopologyCPUsUnassigned,
                    exception.InvalidCPUAllocationPolicy,
                    exception.InvalidCPUThreadAllocationPolicy,
                    exception.ImageNUMATopologyMemoryOutOfRange]:
            self._test_create_instance_numa_topology_wrong(exc)

    def test_create_instance_too_much_metadata(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata']['vote'] = 'fiddletown'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_too_long(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = {('a' * 260): '12345'}

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_value_too_long(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = {'key1': ('a' * 260)}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_blank(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = {'': 'abcd'}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_not_dict(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = 'string'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_not_string(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = {1: 'test'}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_value_not_string(self):
        self.flags(metadata_items=1, group='quota')
        self.body['server']['metadata'] = {'test': ['a', 'list']}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_user_data_malformed_bad_request(self):
        params = {'user_data': 'u1234'}
        self.assertRaises(exception.ValidationError,
                          self._test_create_extra, params)

    def _create_instance_body_of_config_drive(self, param):
        def create(*args, **kwargs):
            self.assertIn('config_drive', kwargs)
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stub_out('nova.compute.api.API.create', create)
        self.body['server']['config_drive'] = param
        self.req.body = jsonutils.dump_as_bytes(self.body)

    def test_create_instance_with_config_drive(self):
        param = True
        self._create_instance_body_of_config_drive(param)
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_config_drive_as_boolean_string(self):
        param = 'false'
        self._create_instance_body_of_config_drive(param)
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_bad_config_drive(self):
        param = 12345
        self._create_instance_body_of_config_drive(param)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_without_config_drive(self):
        def create(*args, **kwargs):
            self.assertIsNone(kwargs['config_drive'])
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stub_out('nova.compute.api.API.create', create)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_empty_config_drive(self):
        param = ''
        self._create_instance_body_of_config_drive(param)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def _test_create(self, params, no_image=False):
        self. body['server'].update(params)
        if no_image:
            del self.body['server']['imageRef']

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.controller.create(self.req, body=self.body).obj['server']

    def test_create_instance_with_volumes_enabled_no_image(self):
        """Test that the create will fail if there is no image
        and no bdms supplied in the request
        """
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create, {}, no_image=True)

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    @mock.patch.object(compute_api.API, '_validate_bdm')
    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_with_bdms_and_no_image(
            self, mock_bdm_image_metadata, mock_validate_bdm, mock_get_vols):
        mock_bdm_image_metadata.return_value = {}
        mock_validate_bdm.return_value = True
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertThat(
                block_device.BlockDeviceDict(self.bdm_v2[0]),
                matchers.DictMatches(kwargs['block_device_mapping'][0])
            )
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self._test_create(params, no_image=True)

        mock_validate_bdm.assert_called_once()
        mock_bdm_image_metadata.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY, mock.ANY, False)

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    @mock.patch.object(compute_api.API, '_validate_bdm')
    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_with_bdms_and_empty_imageRef(
        self, mock_bdm_image_metadata, mock_validate_bdm, mock_get_volumes):
        mock_bdm_image_metadata.return_value = {}
        mock_validate_bdm.return_value = True
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertThat(
                block_device.BlockDeviceDict(self.bdm_v2[0]),
                matchers.DictMatches(kwargs['block_device_mapping'][0])
            )
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2,
                  'imageRef': ''}
        self._test_create(params)

    def test_create_instance_with_imageRef_as_full_url(self):
        bdm = [{'device_name': 'foo'}]
        image_href = ('http://localhost/v2/%s/images/'
                      '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6' % self.project_id)
        params = {'block_device_mapping_v2': bdm,
                  'imageRef': image_href}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    def test_create_instance_with_non_uuid_imageRef(self):
        bdm = [{'device_name': 'foo'}]

        params = {'block_device_mapping_v2': bdm,
                  'imageRef': '123123abcd'}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    def test_create_instance_with_invalid_bdm_in_2nd_dict(self):
        bdm_1st = {"source_type": "image", "delete_on_termination": True,
                   "boot_index": 0,
                   "uuid": "2ff3a1d3-ed70-4c3f-94ac-941461153bc0",
                   "destination_type": "local"}
        bdm_2nd = {"source_type": "volume",
                   "uuid": "99d92140-3d0c-4ea5-a49c-f94c38c607f0",
                   "destination_type": "invalid"}
        bdm = [bdm_1st, bdm_2nd]

        params = {'block_device_mapping_v2': bdm,
                  'imageRef': '2ff3a1d3-ed70-4c3f-94ac-941461153bc0'}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    def test_create_instance_with_boot_index_none_ok(self):
        """Tests creating a server with two block devices. One is the boot
        device and the other is a non-bootable device.
        """
        # From the docs:
        # To disable a device from booting, set the boot index to a negative
        # value or use the default boot index value, which is None. The
        # simplest usage is, set the boot index of the boot device to 0 and use
        # the default boot index value, None, for any other devices.
        bdms = [
            # This is the bootable device that would create a 20GB cinder
            # volume from the given image.
            {
                'source_type': 'image',
                'destination_type': 'volume',
                'boot_index': 0,
                'uuid': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'volume_size': 20
            },
            # This is the non-bootable 10GB ext4 ephemeral block device.
            {
                'source_type': 'blank',
                'destination_type': 'local',
                'boot_index': None,
                # If 'guest_format' is 'swap' then a swap device is created.
                'guest_format': 'ext4'
            }
        ]
        params = {'block_device_mapping_v2': bdms}
        self._test_create(params, no_image=True)

    def test_create_instance_with_boot_index_none_image_local_fails(self):
        """Tests creating a server with a local image-based block device which
        has a boot_index of None which is invalid.
        """
        bdms = [{
            'source_type': 'image',
            'destination_type': 'local',
            'boot_index': None,
            'uuid': '155d900f-4e14-4e4c-a73d-069cbf4541e6'
        }]
        params = {'block_device_mapping_v2': bdms}
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_create,
                          params, no_image=True)

    def test_create_instance_with_invalid_boot_index(self):
        bdm = [{"source_type": "image", "delete_on_termination": True,
                "boot_index": 'invalid',
                "uuid": "2ff3a1d3-ed70-4c3f-94ac-941461153bc0",
                "destination_type": "local"}]

        params = {'block_device_mapping_v2': bdm,
                  'imageRef': '2ff3a1d3-ed70-4c3f-94ac-941461153bc0'}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params)

    def test_create_instance_with_device_name_not_string(self):
        self.bdm_v2[0]['device_name'] = 123
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm_v2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_bdm_param_not_list(self, mock_create):
        self.params = {'block_device_mapping': '/dev/vdb'}
        self.assertRaises(exception.ValidationError,
                          self._test_create, self.params)

    def test_create_instance_with_device_name_empty(self):
        self.bdm_v2[0]['device_name'] = ''

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm_v2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    def test_create_instance_with_device_name_too_long(self):
        self.bdm_v2[0]['device_name'] = 'a' * 256

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm_v2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    def test_create_instance_with_space_in_device_name(self):
        self.bdm_v2[0]['device_name'] = 'v da'

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertTrue(kwargs['legacy_bdm'])
            self.assertEqual(kwargs['block_device_mapping'], self.bdm_v2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    def test_create_instance_with_invalid_size(self):
        self.bdm_v2[0]['volume_size'] = 'hello world'

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm_v2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    def _test_create_instance_with_destination_type_error(self,
                                                          destination_type):
        self.bdm_v2[0]['destination_type'] = destination_type

        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(exception.ValidationError,
                          self._test_create, params, no_image=True)

    def test_create_instance_with_destination_type_empty_string(self):
        self._test_create_instance_with_destination_type_error('')

    def test_create_instance_with_invalid_destination_type(self):
        self._test_create_instance_with_destination_type_error('fake')

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    @mock.patch.object(compute_api.API, '_validate_bdm')
    def test_create_instance_bdm(self, mock_validate_bdm, mock_get_volumes):
        bdm = [{
            'source_type': 'volume',
            'device_name': 'fake_dev',
            'uuid': 'fake_vol'
        }]
        bdm_expected = [{
            'source_type': 'volume',
            'device_name': 'fake_dev',
            'volume_id': 'fake_vol'
        }]

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertFalse(kwargs['legacy_bdm'])
            for expected, received in zip(bdm_expected,
                                          kwargs['block_device_mapping']):
                self.assertThat(block_device.BlockDeviceDict(expected),
                                matchers.DictMatches(received))
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': bdm}
        self._test_create(params, no_image=True)
        mock_validate_bdm.assert_called_once()

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    @mock.patch.object(compute_api.API, '_validate_bdm')
    def test_create_instance_bdm_missing_device_name(self, mock_validate_bdm,
                                                     mock_get_volumes):
        del self.bdm_v2[0]['device_name']

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertFalse(kwargs['legacy_bdm'])
            self.assertNotIn(None,
                             kwargs['block_device_mapping'][0]['device_name'])
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        params = {'block_device_mapping_v2': self.bdm_v2}
        self._test_create(params, no_image=True)
        mock_validate_bdm.assert_called_once()

    @mock.patch.object(
        block_device.BlockDeviceDict, '_validate',
        side_effect=exception.InvalidBDMFormat(details='Wrong BDM'))
    def test_create_instance_bdm_validation_error(self, mock_validate):
        params = {'block_device_mapping_v2': self.bdm_v2}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create, params, no_image=True)

    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_non_bootable_volume_fails(self, fake_bdm_meta):
        params = {'block_device_mapping_v2': self.bdm_v2}
        fake_bdm_meta.side_effect = exception.InvalidBDMVolumeNotBootable(id=1)
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_create, params,
                          no_image=True)

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    def test_create_instance_bdm_api_validation_fails(self, mock_get_volumes):
        self.validation_fail_test_validate_called = False
        self.validation_fail_instance_destroy_called = False

        bdm_exceptions = ((exception.InvalidBDMSnapshot, {'id': 'fake'}),
                          (exception.InvalidBDMVolume, {'id': 'fake'}),
                          (exception.InvalidBDMImage, {'id': 'fake'}),
                          (exception.InvalidBDMBootSequence, {}),
                          (exception.InvalidBDMLocalsLimit, {}),
                          (exception.InvalidBDMDiskBus, {'disk_bus': 'foo'}))

        ex_iter = iter(bdm_exceptions)

        def _validate_bdm(*args, **kwargs):
            self.validation_fail_test_validate_called = True
            ex, kargs = next(ex_iter)
            raise ex(**kargs)

        def _instance_destroy(*args, **kwargs):
            self.validation_fail_instance_destroy_called = True

        self.stub_out('nova.compute.api.API._validate_bdm', _validate_bdm)
        self.stub_out('nova.objects.Instance.destroy', _instance_destroy)

        for _unused in range(len(bdm_exceptions)):
            params = {'block_device_mapping_v2':
                      [self.bdm_v2[0].copy()]}
            self.assertRaises(webob.exc.HTTPBadRequest,
                              self._test_create, params)
            self.assertTrue(self.validation_fail_test_validate_called)
            self.assertFalse(self.validation_fail_instance_destroy_called)
            self.validation_fail_test_validate_called = False
            self.validation_fail_instance_destroy_called = False

    @mock.patch('nova.compute.api.API._get_volumes_for_bdms')
    @mock.patch.object(compute_api.API, '_validate_bdm')
    def _test_create_bdm(self, params, mock_validate_bdm, mock_get_volumes,
                         no_image=False):
        self.body['server'].update(params)
        if no_image:
            del self.body['server']['imageRef']
        self.req.body = jsonutils.dump_as_bytes(self.body)

        self.controller.create(self.req, body=self.body).obj['server']
        mock_validate_bdm.assert_called_once_with(
            test.MatchType(fakes.FakeRequestContext),
            test.MatchType(objects.Instance),
            test.MatchType(objects.Flavor),
            test.MatchType(objects.BlockDeviceMappingList),
            {},
            mock_get_volumes.return_value,
            False)

    def test_create_instance_with_volumes_enabled(self):
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_bdm(params)

    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_with_volumes_enabled_and_bdms_no_image(
        self, mock_get_bdm_image_metadata):
        """Test that the create works if there is no image supplied but
        os-volumes extension is enabled and bdms are supplied
        """
        volume = {
            'id': uuids.volume_id,
            'status': 'active',
            'volume_image_metadata':
                {'test_key': 'test_value'}
        }
        mock_get_bdm_image_metadata.return_value = volume
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            self.assertNotIn('imageRef', kwargs)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_bdm(params, no_image=True)
        mock_get_bdm_image_metadata.assert_called_once_with(
            mock.ANY, mock.ANY, mock.ANY, self.bdm, True)

    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_with_imageRef_as_empty_string(
        self, mock_bdm_image_metadata):
        volume = {
            'id': uuids.volume_id,
            'status': 'active',
            'volume_image_metadata':
                {'test_key': 'test_value'}
        }
        mock_bdm_image_metadata.return_value = volume
        params = {'block_device_mapping': self.bdm,
                  'imageRef': ''}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_bdm(params)

    def test_create_instance_with_imageRef_as_full_url_legacy_bdm(self):
        bdm = [{
            'volume_id': fakes.FAKE_UUID,
            'device_name': 'vda'
        }]
        image_href = ('http://localhost/v2/%s/images/'
                      '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6' % self.project_id)
        params = {'block_device_mapping': bdm,
                  'imageRef': image_href}
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def test_create_instance_with_non_uuid_imageRef_legacy_bdm(self):
        bdm = [{
            'volume_id': fakes.FAKE_UUID,
            'device_name': 'vda'
        }]
        params = {'block_device_mapping': bdm,
                  'imageRef': 'bad-format'}
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    @mock.patch('nova.block_device.get_bdm_image_metadata')
    def test_create_instance_non_bootable_volume_fails_legacy_bdm(
        self, fake_bdm_meta):
        bdm = [{
            'volume_id': fakes.FAKE_UUID,
            'device_name': 'vda'
        }]
        params = {'block_device_mapping': bdm}
        fake_bdm_meta.side_effect = exception.InvalidBDMVolumeNotBootable(id=1)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_bdm, params, no_image=True)

    def test_create_instance_with_device_name_not_string_legacy_bdm(self):
        self.bdm[0]['device_name'] = 123
        old_create = compute_api.API.create
        self.params = {'block_device_mapping': self.bdm}

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, self.params)

    def test_create_instance_with_snapshot_volume_id_none(self):
        old_create = compute_api.API.create
        bdm = [{
            'no_device': None,
            'snapshot_id': None,
            'volume_id': None,
            'device_name': 'vda',
            'delete_on_termination': False
        }]
        self.params = {'block_device_mapping': bdm}

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, self.params)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_legacy_bdm_param_not_list(self, mock_create):
        self.params = {'block_device_mapping': '/dev/vdb'}
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, self.params)

    def test_create_instance_with_device_name_empty_legacy_bdm(self):
        self.bdm[0]['device_name'] = ''
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def test_create_instance_with_device_name_too_long_legacy_bdm(self):
        self.bdm[0]['device_name'] = 'a' * 256,
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def test_create_instance_with_space_in_device_name_legacy_bdm(self):
        self.bdm[0]['device_name'] = 'vd a',
        params = {'block_device_mapping': self.bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertTrue(kwargs['legacy_bdm'])
            self.assertEqual(kwargs['block_device_mapping'], self.bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def _test_create_bdm_instance_with_size_error(self, size):
        bdm = [{'delete_on_termination': True,
                'device_name': 'vda',
                'volume_size': size,
                'volume_id': '11111111-1111-1111-1111-111111111111'}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['block_device_mapping'], bdm)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def test_create_instance_with_invalid_size_legacy_bdm(self):
        self._test_create_bdm_instance_with_size_error("hello world")

    def test_create_instance_with_size_empty_string(self):
        self._test_create_bdm_instance_with_size_error('')

    def test_create_instance_with_size_zero(self):
        self._test_create_bdm_instance_with_size_error("0")

    def test_create_instance_with_size_greater_than_limit(self):
        self._test_create_bdm_instance_with_size_error(db.MAX_INT + 1)

    def test_create_instance_with_bdm_delete_on_termination(self):
        bdm = [{'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'True'},
               {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': True},
               {'device_name': 'foo3', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'False'},
               {'device_name': 'foo4', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': False},
               {'device_name': 'foo5', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': False}]
        expected_bdm = [
            {'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': True},
            {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': True},
            {'device_name': 'foo3', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False},
            {'device_name': 'foo4', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False},
            {'device_name': 'foo5', 'volume_id': fakes.FAKE_UUID,
             'delete_on_termination': False}]
        params = {'block_device_mapping': bdm}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(expected_bdm, kwargs['block_device_mapping'])
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_bdm(params)

    def test_create_instance_with_bdm_delete_on_termination_invalid_2nd(self):
        bdm = [{'device_name': 'foo1', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'True'},
               {'device_name': 'foo2', 'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': 'invalid'}]

        params = {'block_device_mapping': bdm}
        self.assertRaises(exception.ValidationError,
                          self._test_create_bdm, params)

    def test_create_instance_decide_format_legacy(self):
        bdm = [{'device_name': 'foo1',
                'volume_id': fakes.FAKE_UUID,
                'delete_on_termination': True}]

        expected_legacy_flag = True

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            legacy_bdm = kwargs.get('legacy_bdm', True)
            self.assertEqual(legacy_bdm, expected_legacy_flag)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        self._test_create_bdm({})

        params = {'block_device_mapping': bdm}
        self._test_create_bdm(params)

    def test_create_instance_both_bdm_formats(self):
        bdm = [{'device_name': 'foo'}]
        bdm_v2 = [{'source_type': 'volume',
                   'uuid': 'fake_vol'}]
        params = {'block_device_mapping': bdm,
                  'block_device_mapping_v2': bdm_v2}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_bdm, params)

    def test_create_instance_invalid_key_name(self):
        self.body['server']['key_name'] = 'nonexistentkey'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_valid_key_name(self):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        self.body['server']['key_name'] = 'key'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_password_len(res["server"])

    def test_create_server_keypair_name_with_leading_trailing(self):
        self.body['server']['key_name'] = '  abc  '
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_server_keypair_name_with_leading_trailing_compat_mode(
            self, mock_create):
        params = {'key_name': '  abc  '}

        def fake_create(*args, **kwargs):
            self.assertEqual('  abc  ', kwargs['key_name'])
            return (objects.InstanceList(objects=[fakes.stub_instance_obj(
                self.req.environ['nova.context'])]), None)
        mock_create.side_effect = fake_create

        self.req.set_legacy_v2()
        self._test_create_extra(params)

    def test_create_instance_invalid_flavor_href(self):
        flavor_ref = 'http://localhost/v2/flavors/asdf'
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_invalid_flavor_id_int(self):
        flavor_ref = -1
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    @mock.patch.object(nova.compute.flavors, 'get_flavor_by_flavor_id',
                       return_value=objects.Flavor())
    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_non_existing_snapshot_id(
            self, mock_create,
            mock_get_flavor_by_flavor_id):
        mock_create.side_effect = exception.SnapshotNotFound(snapshot_id='123')

        self.body['server'] = {'name': 'server_test',
                               'flavorRef': self.flavor_ref,
                               'block_device_mapping_v2':
                                   [{'source_type': 'snapshot',
                                     'uuid': '123'}]}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_invalid_flavor_id_empty(self):
        flavor_ref = ""
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_bad_flavor_href(self):
        flavor_ref = 'http://localhost/v2/flavors/17'
        self.body['server']['flavorRef'] = flavor_ref
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_local_href(self):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_admin_password(self):
        self.body['server']['flavorRef'] = 3
        self.body['server']['adminPass'] = 'testpass'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertEqual(server['adminPass'],
                         self.body['server']['adminPass'])

    def test_create_instance_admin_password_pass_disabled(self):
        self.flags(enable_instance_password=False, group='api')
        self.body['server']['flavorRef'] = 3
        self.body['server']['adminPass'] = 'testpass'
        self.req.body = jsonutils.dump_as_bytes(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        self.assertIn('server', res)
        self.assertIn('adminPass', self.body['server'])

    def test_create_instance_admin_password_empty(self):
        self.body['server']['flavorRef'] = 3
        self.body['server']['adminPass'] = ''
        self.req.body = jsonutils.dump_as_bytes(self.body)

        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body)

    def test_create_location(self):
        self.stub_out('uuid.uuid4', lambda: FAKE_UUID)
        selfhref = 'http://localhost/v2/%s/servers/%s' % (self.project_id,
                                                          FAKE_UUID)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        robj = self.controller.create(self.req, body=self.body)

        self.assertEqual(encodeutils.safe_decode(robj['Location']), selfhref)

    @mock.patch('nova.objects.Quotas.get_all_by_project')
    @mock.patch('nova.objects.Quotas.get_all_by_project_and_user')
    @mock.patch('nova.objects.Quotas.count_as_dict')
    def _do_test_create_instance_above_quota(self, resource, allowed,
                quota, expected_msg, mock_count, mock_get_all_pu,
                mock_get_all_p):
        count = {'project': {}, 'user': {}}
        for res in ('instances', 'ram', 'cores'):
            if res == resource:
                value = quota - allowed
                count['project'][res] = count['user'][res] = value
            else:
                count['project'][res] = count['user'][res] = 0
        mock_count.return_value = count
        mock_get_all_p.return_value = {'project_id': fakes.FAKE_PROJECT_ID}
        mock_get_all_pu.return_value = {'project_id': fakes.FAKE_PROJECT_ID,
                                        'user_id': 'fake_user'}
        if resource in db_api.PER_PROJECT_QUOTAS:
            mock_get_all_p.return_value[resource] = quota
        else:
            mock_get_all_pu.return_value[resource] = quota
        fakes.stub_out_instance_quota(self, allowed, quota, resource)
        self.body['server']['flavorRef'] = 3
        self.req.body = jsonutils.dump_as_bytes(self.body)
        try:
            self.controller.create(self.req, body=self.body).obj['server']
            self.fail('expected quota to be exceeded')
        except webob.exc.HTTPForbidden as e:
            self.assertEqual(e.explanation, expected_msg)

    def test_create_instance_above_quota_instances(self):
        msg = ('Quota exceeded for instances: Requested 1, but'
               ' already used 10 of 10 instances')
        self._do_test_create_instance_above_quota('instances', 0, 10, msg)

    def test_create_instance_above_quota_ram(self):
        msg = ('Quota exceeded for ram: Requested 4096, but'
               ' already used 8192 of 10240 ram')
        self._do_test_create_instance_above_quota('ram', 2048, 10 * 1024, msg)

    def test_create_instance_above_quota_cores(self):
        msg = ('Quota exceeded for cores: Requested 2, but'
               ' already used 9 of 10 cores')
        self._do_test_create_instance_above_quota('cores', 1, 10, msg)

    @mock.patch.object(fakes.QUOTAS, 'limit_check')
    def test_create_instance_above_quota_server_group_members(
            self, mock_limit_check):
        ctxt = self.req.environ['nova.context']
        fake_group = objects.InstanceGroup(ctxt)
        fake_group.project_id = ctxt.project_id
        fake_group.user_id = ctxt.user_id
        fake_group.create()

        real_count = fakes.QUOTAS.count_as_dict

        def fake_count(context, name, group, user_id):
            if name == 'server_group_members':
                self.assertEqual(group.uuid, fake_group.uuid)
                self.assertEqual(user_id,
                                 self.req.environ['nova.context'].user_id)
                return {'user': {'server_group_members': 10}}
            else:
                return real_count(context, name, group, user_id)

        def fake_limit_check(context, **kwargs):
            if 'server_group_members' in kwargs:
                raise exception.OverQuota(overs={})

        def fake_instance_destroy(context, uuid, constraint):
            return fakes.stub_instance(1)

        mock_limit_check.side_effect = fake_limit_check
        self.stub_out('nova.db.api.instance_destroy', fake_instance_destroy)
        self.body['os:scheduler_hints'] = {'group': fake_group.uuid}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        expected_msg = "Quota exceeded, too many servers in group"

        try:
            with mock.patch.object(fakes.QUOTAS, 'count_as_dict',
                                   side_effect=fake_count):
                self.controller.create(self.req, body=self.body).obj
                self.fail('expected quota to be exceeded')
        except webob.exc.HTTPForbidden as e:
            self.assertEqual(e.explanation, expected_msg)

    def test_create_instance_with_group_hint(self):
        ctxt = self.req.environ['nova.context']
        test_group = objects.InstanceGroup(ctxt)
        test_group.project_id = ctxt.project_id
        test_group.user_id = ctxt.user_id
        test_group.create()

        def fake_instance_destroy(context, uuid, constraint):
            return fakes.stub_instance(1)

        self.stub_out('nova.db.api.instance_destroy', fake_instance_destroy)
        self.body['os:scheduler_hints'] = {'group': test_group.uuid}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        server = self.controller.create(self.req, body=self.body).obj['server']

        test_group = objects.InstanceGroup.get_by_uuid(ctxt, test_group.uuid)
        self.assertIn(server['id'], test_group.members)

    def _test_create_instance_with_group_hint(self, hint,
            hint_name='os:scheduler_hints'):
        def fake_instance_destroy(context, uuid, constraint):
            return fakes.stub_instance(1)

        def fake_create(*args, **kwargs):
            self.assertEqual(kwargs['scheduler_hints'], hint)
            return ([fakes.stub_instance(1)], '')

        self.stub_out('nova.compute.api.API.create', fake_create)
        self.stub_out('nova.db.instance_destroy', fake_instance_destroy)
        self.body[hint_name] = hint
        self.req.body = jsonutils.dump_as_bytes(self.body)
        return self.controller.create(self.req, body=self.body).obj['server']

    def test_create_instance_with_group_hint_legacy(self):
        self._test_create_instance_with_group_hint(
            {'different_host': '9c47bf55-e9d8-42da-94ab-7f9e80cd1857'},
            hint_name='OS-SCH-HNT:scheduler_hints')

    def test_create_server_with_different_host_hint(self):
        self._test_create_instance_with_group_hint(
            {'different_host': '9c47bf55-e9d8-42da-94ab-7f9e80cd1857'})

        self._test_create_instance_with_group_hint(
            {'different_host': ['9c47bf55-e9d8-42da-94ab-7f9e80cd1857',
                                '82412fa6-0365-43a9-95e4-d8b20e00c0de']})

    def test_create_instance_with_group_hint_group_not_found(self):
        def fake_instance_destroy(context, uuid, constraint):
            return fakes.stub_instance(1)

        self.stub_out('nova.db.api.instance_destroy', fake_instance_destroy)
        self.body['os:scheduler_hints'] = {
            'group': '5b674f73-c8cf-40ef-9965-3b6fe4b304b1'}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_with_group_hint_wrong_uuid_format(self):
        self.body['os:scheduler_hints'] = {
            'group': 'non-uuid'}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_server_bad_hints_non_dict(self):
        sch_hints = ['os:scheduler_hints', 'OS-SCH-HNT:scheduler_hints']
        for hint in sch_hints:
            self.body[hint] = 'non-dict'
            self.req.body = jsonutils.dump_as_bytes(self.body)
            self.assertRaises(exception.ValidationError,
                              self.controller.create, self.req, body=self.body)

    def test_create_server_bad_hints_long_group(self):
        self.body['os:scheduler_hints'] = {
            'group': 'a' * 256}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    def test_create_server_with_bad_different_host_hint(self):
        self.body['os:scheduler_hints'] = {
            'different_host': 'non-server-id'}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

        self.body['os:scheduler_hints'] = {
            'different_host': ['non-server-id01', 'non-server-id02']}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                      side_effect=exception.PortInUse(port_id=uuids.port))
    def test_create_instance_with_port_in_use(self, mock_create):
        requested_networks = [{'uuid': uuids.network, 'port': uuids.port}]
        params = {'networks': requested_networks}
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_public_network_non_admin(self, mock_create):
        public_network_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        params = {'networks': [{'uuid': public_network_uuid}]}
        self.req.body = jsonutils.dump_as_bytes(self.body)
        mock_create.side_effect = exception.ExternalNetworkAttachForbidden(
                                             network_uuid=public_network_uuid)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self._test_create_extra, params)

    def test_multiple_create_with_string_type_min_and_max(self):
        min_count = '2'
        max_count = '3'
        params = {
            'min_count': min_count,
            'max_count': max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsInstance(kwargs['min_count'], int)
            self.assertIsInstance(kwargs['max_count'], int)
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_extra(params)

    def test_create_instance_with_multiple_create_enabled(self):
        min_count = 2
        max_count = 3
        params = {
            'min_count': min_count,
            'max_count': max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        self._test_create_extra(params)

    def test_create_instance_invalid_negative_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'min_count': -1,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_negative_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'max_count': -1,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_with_blank_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'min_count': '',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_with_blank_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'max_count': '',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_min_greater_than_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'min_count': 4,
                'max_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_alpha_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'min_count': 'abcd',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_instance_invalid_alpha_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                'max_count': 'abcd',
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req,
                          body=body)

    def test_create_multiple_instances(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            self.instance_cache_by_uuid[instance.uuid] = instance
            return instance
        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        res = self.controller.create(self.req, body=body).obj

        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)
        self._check_admin_password_len(res["server"])

    def test_create_multiple_instances_pass_disabled(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.flags(enable_instance_password=False, group='api')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            self.instance_cache_by_uuid[instance.uuid] = instance
            return instance
        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        res = self.controller.create(self.req, body=body).obj

        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)
        self._check_admin_password_missing(res["server"])

    def _create_multiple_instances_resv_id_return(self, resv_id_return):
        """Test creating multiple instances with asking for
        reservation_id
        """
        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            self.instance_cache_by_uuid[instance.uuid] = instance
            return instance

        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                'return_reservation_id': resv_id_return
            }
        }

        res = self.controller.create(self.req, body=body)
        reservation_id = res.obj['reservation_id']
        self.assertNotEqual(reservation_id, "")
        self.assertIsNotNone(reservation_id)
        self.assertGreater(len(reservation_id), 1)

    def test_create_multiple_instances_with_resv_id_return(self):
        self._create_multiple_instances_resv_id_return(True)

    def test_create_multiple_instances_with_string_resv_id_return(self):
        self._create_multiple_instances_resv_id_return("True")

    def test_create_multiple_instances_with_multiple_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested with a list of block device mappings for volumes.
        """
        min_count = 2
        bdm = [{'source_type': 'volume', 'uuid': 'vol-xxxx'},
               {'source_type': 'volume', 'uuid': 'vol-yyyy'}
        ]
        params = {
                  'block_device_mapping_v2': bdm,
                  'min_count': min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(len(kwargs['block_device_mapping']), 2)
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self._test_create_extra, params, no_image=True)
        self.assertEqual("Cannot attach one or more volumes to multiple "
                         "instances", exc.explanation)

    def test_create_multiple_instances_with_single_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested to boot from a single volume.
        """
        min_count = 2
        bdm = [{'source_type': 'volume', 'uuid': 'vol-xxxx'}]
        params = {
                 'block_device_mapping_v2': bdm,
                 'min_count': min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['block_device_mapping'][0]['volume_id'],
                            'vol-xxxx')
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)
        exc = self.assertRaises(webob.exc.HTTPBadRequest,
                                self._test_create_extra, params, no_image=True)
        self.assertEqual("Cannot attach one or more volumes to multiple "
                         "instances", exc.explanation)

    def test_create_multiple_instance_with_non_integer_max_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'max_count': 2.5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=body)

    def test_create_multiple_instance_with_non_integer_min_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2.5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        self.assertRaises(exception.ValidationError,
                          self.controller.create, self.req, body=body)

    def test_create_multiple_instance_max_count_overquota_min_count_ok(self):
        self.flags(instances=3, group='quota')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 2,
                'max_count': 5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            self.instance_cache_by_uuid[instance.uuid] = instance
            return instance
        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        res = self.controller.create(self.req, body=body).obj
        instance_uuids = self.instance_cache_by_uuid.keys()
        self.assertIn(res["server"]["id"], instance_uuids)

    def test_create_multiple_instance_max_count_overquota_min_count_over(self):
        self.flags(instances=3, group='quota')
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'min_count': 4,
                'max_count': 5,
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
            }
        }
        self.assertRaises(webob.exc.HTTPForbidden, self.controller.create,
                          self.req, body=body)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_multiple_instance_with_specified_ip_neutronv2(self,
                                                                  _api_mock):
        _api_mock.side_effect = exception.InvalidFixedIpAndMaxCountRequest(
            reason="")
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        address = '10.0.0.1'
        requested_networks = [{'uuid': network, 'fixed_ip': address,
                               'port': port}]
        params = {'networks': requested_networks}
        self.body['server']['max_count'] = 2
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.MultiplePortsNotApplicable(
                           reason="Unable to launch multiple instances with "
                                  "a single configured port ID. Please "
                                  "launch your instance one by one with "
                                  "different ports."))
    def test_create_multiple_instance_with_port(self, mock_create):
        requested_networks = [{'uuid': uuids.network, 'port': uuids.port}]
        params = {'networks': requested_networks}
        self.body['server']['max_count'] = 2
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.NetworkNotFound(
                           network_id=uuids.network))
    def test_create_instance_with_not_found_network(self, mock_create):
        requested_networks = [{'uuid': uuids.network}]
        params = {'networks': requested_networks}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.PortNotFound(port_id=uuids.port))
    def test_create_instance_with_port_not_found(self, mock_create):
        requested_networks = [{'uuid': uuids.network, 'port': uuids.port}]
        params = {'networks': requested_networks}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_network_ambiguous(self, mock_create):
        mock_create.side_effect = exception.NetworkAmbiguous()
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, {})

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.UnableToAutoAllocateNetwork(
                           project_id=FAKE_UUID))
    def test_create_instance_with_unable_to_auto_allocate_network(self,
                                                                  mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, {})

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.ImageNotAuthorized(
                           image_id=FAKE_UUID))
    def test_create_instance_with_image_not_authorized(self,
                                                       mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, {})

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InstanceExists(
                           name='instance-name'))
    def test_create_instance_raise_instance_exists(self, mock_create):
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidBDMEphemeralSize)
    def test_create_instance_raise_invalid_bdm_ephsize(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidNUMANodesNumber(
                           nodes='-1'))
    def test_create_instance_raise_invalid_numa_nodes(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidBDMFormat(details=''))
    def test_create_instance_raise_invalid_bdm_format(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidBDMSwapSize)
    def test_create_instance_raise_invalid_bdm_swapsize(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidBDM)
    def test_create_instance_raise_invalid_bdm(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.ImageBadRequest(
                        image_id='dummy', response='dummy'))
    def test_create_instance_raise_image_bad_request(self, mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_invalid_availability_zone(self):
        self.body['server']['availability_zone'] = 'invalid::::zone'
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_invalid_availability_zone_as_int(self):
        self.body['server']['availability_zone'] = 123
        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.FixedIpNotFoundForAddress(
                        address='dummy'))
    def test_create_instance_raise_fixed_ip_not_found_bad_request(self,
                                                                  mock_create):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.CPUThreadPolicyConfigurationInvalid())
    def test_create_instance_raise_cpu_thread_policy_configuration_invalid(
            self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.get_mem_encryption_constraint',
                side_effect=exception.FlavorImageConflict(
                    message="fake conflict reason"))
    def test_create_instance_raise_flavor_image_conflict(
            self, mock_conflict):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.get_mem_encryption_constraint',
                side_effect=exception.InvalidMachineType(
                    message="fake conflict reason"))
    def test_create_instance_raise_invalid_machine_type(
            self, mock_conflict):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.ImageCPUPinningForbidden())
    def test_create_instance_raise_image_cpu_pinning_forbidden(
            self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.ImageCPUThreadPolicyForbidden())
    def test_create_instance_raise_image_cpu_thread_policy_forbidden(
            self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.MemoryPageSizeInvalid(pagesize='-1'))
    def test_create_instance_raise_memory_page_size_invalid(self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.MemoryPageSizeForbidden(pagesize='1',
                                                              against='2'))
    def test_create_instance_raise_memory_page_size_forbidden(self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.RealtimeConfigurationInvalid())
    def test_create_instance_raise_realtime_configuration_invalid(
            self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch('nova.virt.hardware.numa_get_constraints',
                side_effect=exception.RealtimeMaskNotFoundOrInvalid())
    def test_create_instance_raise_realtime_mask_not_found_or_invalid(
            self, mock_numa):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_invalid_personality(self, mock_create):
        # Personality files have been deprecated as of v2.57
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.56')

        codec = 'utf8'
        content = encodeutils.safe_encode(
                'b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA==')
        start_position = 19
        end_position = 20
        msg = 'invalid start byte'
        mock_create.side_effect = UnicodeDecodeError(codec, content,
                                                     start_position,
                                                     end_position, msg)

        self.body['server']['personality'] = [
            {
                "path": "/etc/banner.txt",
                "contents": "b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA==",
            },
        ]
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_without_personality_should_get_empty_list(self):
        # Personality files have been deprecated as of v2.57
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.56')

        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual([], kwargs['injected_files'])
            return old_create(*args, **kwargs)

        self.stub_out('nova.compute.api.API.create', create)

        self._test_create_instance()

    def test_create_instance_with_extra_personality_arg(self):
        # Personality files have been deprecated as of v2.57
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.56')

        self.body['server']['personality'] = [
            {
                "path": "/etc/banner.txt",
                "contents": "b25zLiINCg0KLVJpY2hhcmQgQ$$%QQmFjaA==",
                "extra_arg": "extra value"
            },
        ]

        self.assertRaises(exception.ValidationError,
                          self.controller.create,
                          self.req, body=self.body)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.PciRequestAliasNotDefined(
                           alias='fake_name'))
    def test_create_instance_pci_alias_not_defined(self, mock_create):
        # Tests that PciRequestAliasNotDefined is translated to a 400 error.
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._test_create_extra, {})
        self.assertIn('PCI alias fake_name is not defined', six.text_type(ex))

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.PciInvalidAlias(
                           reason='just because'))
    def test_create_instance_pci_invalid_alias(self, mock_create):
        # Tests that PciInvalidAlias is translated to a 400 error.
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._test_create_extra, {})
        self.assertIn('Invalid PCI alias definition', six.text_type(ex))

    def test_create_instance_with_user_data(self):
        value = base64.encode_as_text("A random string")
        params = {'user_data': value}
        self._test_create_extra(params)

    def test_create_instance_with_bad_user_data(self):
        value = "A random string"
        params = {'user_data': value}
        self.assertRaises(exception.ValidationError,
                          self._test_create_extra, params)

    @mock.patch('nova.compute.api.API.create')
    def test_create_instance_with_none_allowd_for_v20_compat_mode(self,
            mock_create):

        def create(context, *args, **kwargs):
            self.assertIsNone(kwargs['user_data'])
            return ([fakes.stub_instance_obj(context)], None)

        mock_create.side_effect = create
        self.req.set_legacy_v2()
        params = {'user_data': None}
        self._test_create_extra(params)


class ServersControllerCreateTestV219(ServersControllerCreateTest):
    def _create_instance_req(self, set_desc, desc=None):
        if set_desc:
            self.body['server']['description'] = desc
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.19')

    def test_create_instance_with_description(self):
        self._create_instance_req(True, 'server_desc')
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_none_description(self):
        self._create_instance_req(True)
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_empty_description(self):
        self._create_instance_req(True, '')
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_without_description(self):
        self._create_instance_req(False)
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_description_too_long(self):
        self._create_instance_req(True, 'X' * 256)
        self.assertRaises(exception.ValidationError, self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_description_invalid(self):
        self._create_instance_req(True, "abc\0ddef")
        self.assertRaises(exception.ValidationError, self.controller.create,
                          self.req, body=self.body)


class ServersControllerCreateTestV232(test.NoDBTestCase):
    def setUp(self):
        super(ServersControllerCreateTestV232, self).setUp()

        self.controller = servers.ServersController()

        self.body = {
            'server': {
                'name': 'device-tagging-server',
                'imageRef': '6b0edabb-8cde-4684-a3f4-978960a51378',
                'flavorRef': '2',
                'networks': [{
                    'uuid': 'ff608d40-75e9-48cb-b745-77bb55b5eaf2'
                }],
                'block_device_mapping_v2': [{
                    'uuid': '70a599e0-31e7-49b7-b260-868f441e862b',
                    'source_type': 'image',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'volume_size': '1'
                }]
            }
        }

        self.req = fakes.HTTPRequestV21.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID, version='2.32')
        self.req.method = 'POST'
        self.req.headers['content-type'] = 'application/json'

    def _create_server(self):
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.controller.create(self.req, body=self.body)

    def test_create_server_no_tags(self):
        with test.nested(
            mock.patch.object(nova.compute.flavors, 'get_flavor_by_flavor_id',
                              return_value=objects.Flavor()),
            mock.patch.object(
                compute_api.API, 'create',
                return_value=(
                    [{'uuid': 'f60012d9-5ba4-4547-ab48-f94ff7e62d4e'}],
                    1)),
        ):
            self._create_server()

    def test_create_server_tagged_nic(self):
        with test.nested(
            mock.patch.object(nova.compute.flavors, 'get_flavor_by_flavor_id',
                              return_value=objects.Flavor()),
            mock.patch.object(
                compute_api.API, 'create',
                return_value=(
                    [{'uuid': 'f60012d9-5ba4-4547-ab48-f94ff7e62d4e'}],
                    1)),
        ):
            self.body['server']['networks'][0]['tag'] = 'foo'
            self._create_server()

    def test_create_server_tagged_bdm(self):
        with test.nested(
            mock.patch.object(nova.compute.flavors, 'get_flavor_by_flavor_id',
                              return_value=objects.Flavor()),
            mock.patch.object(
                compute_api.API, 'create',
                return_value=(
                    [{'uuid': 'f60012d9-5ba4-4547-ab48-f94ff7e62d4e'}],
                    1)),
        ):
            self.body['server']['block_device_mapping_v2'][0]['tag'] = 'foo'
            self._create_server()


class ServersControllerCreateTestV237(test.NoDBTestCase):
    """Tests server create scenarios with the v2.37 microversion.

    These tests are mostly about testing the validation on the 2.37
    server create request with emphasis on negative scenarios.
    """
    def setUp(self):
        super(ServersControllerCreateTestV237, self).setUp()
        # Create the server controller.
        self.controller = servers.ServersController()
        # Define a basic server create request body which tests can customize.
        self.body = {
            'server': {
                'name': 'auto-allocate-test',
                'imageRef': '6b0edabb-8cde-4684-a3f4-978960a51378',
                'flavorRef': '2',
            },
        }
        # Create a fake request using the 2.37 microversion.
        self.req = fakes.HTTPRequestV21.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID, version='2.37')
        self.req.method = 'POST'
        self.req.headers['content-type'] = 'application/json'

    def _create_server(self, networks):
        self.body['server']['networks'] = networks
        self.req.body = jsonutils.dump_as_bytes(self.body)
        return self.controller.create(self.req, body=self.body).obj['server']

    def test_create_server_auth_pre_2_37_fails(self):
        """Negative test to make sure you can't pass 'auto' before 2.37"""
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.36')
        self.assertRaises(exception.ValidationError, self._create_server,
                          'auto')

    def test_create_server_no_requested_networks_fails(self):
        """Negative test for a server create request with no networks requested
        which should fail with the v2.37 schema validation.
        """
        self.assertRaises(exception.ValidationError, self._create_server, None)

    def test_create_server_network_id_not_uuid_fails(self):
        """Negative test for a server create request where the requested
        network id is not one of the auto/none enums.
        """
        self.assertRaises(exception.ValidationError, self._create_server,
                          'not-auto-or-none')

    def test_create_server_network_id_empty_string_fails(self):
        """Negative test for a server create request where the requested
        network id is the empty string.
        """
        self.assertRaises(exception.ValidationError, self._create_server, '')

    @mock.patch.object(context.RequestContext, 'can')
    def test_create_server_networks_none_skip_policy(self, context_can):
        """Test to ensure skip checking policy rule create:attach_network,
        when networks is 'none' which means no network will be allocated.
        """
        with test.nested(
            mock.patch('nova.objects.service.get_minimum_version_all_cells',
                       return_value=14),
            mock.patch.object(nova.compute.flavors, 'get_flavor_by_flavor_id',
                              return_value=objects.Flavor()),
            mock.patch.object(
                compute_api.API, 'create',
                return_value=(
                    [{'uuid': 'f9bccadf-5ab1-4a56-9156-c00c178fe5f5'}],
                    1)),
        ):
            network_policy = server_policies.SERVERS % 'create:attach_network'
            self._create_server('none')
            call_list = [c for c in context_can.call_args_list
                         if c[0][0] == network_policy]
            self.assertEqual(0, len(call_list))

    @mock.patch.object(objects.Flavor, 'get_by_flavor_id',
                       side_effect=exception.FlavorNotFound(flavor_id='2'))
    def test_create_server_auto_flavornotfound(self, get_flavor):
        """Tests that requesting auto networking is OK. This test
        short-circuits on a FlavorNotFound error.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        ex = self.assertRaises(
            webob.exc.HTTPBadRequest, self._create_server, 'auto')
        # make sure it was a flavor not found error and not something else
        self.assertIn('Flavor 2 could not be found', six.text_type(ex))

    @mock.patch.object(objects.Flavor, 'get_by_flavor_id',
                       side_effect=exception.FlavorNotFound(flavor_id='2'))
    def test_create_server_none_flavornotfound(self, get_flavor):
        """Tests that requesting none for networking is OK. This test
        short-circuits on a FlavorNotFound error.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        ex = self.assertRaises(
            webob.exc.HTTPBadRequest, self._create_server, 'none')
        # make sure it was a flavor not found error and not something else
        self.assertIn('Flavor 2 could not be found', six.text_type(ex))

    @mock.patch.object(objects.Flavor, 'get_by_flavor_id',
                       side_effect=exception.FlavorNotFound(flavor_id='2'))
    def test_create_server_multiple_specific_nics_flavornotfound(self,
                                                                 get_flavor):
        """Tests that requesting multiple specific network IDs is OK. This test
        short-circuits on a FlavorNotFound error.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        ex = self.assertRaises(
            webob.exc.HTTPBadRequest, self._create_server,
                [{'uuid': 'e3b686a8-b91d-4a61-a3fc-1b74bb619ddb'},
                 {'uuid': 'e0f00941-f85f-46ec-9315-96ded58c2f14'}])
        # make sure it was a flavor not found error and not something else
        self.assertIn('Flavor 2 could not be found', six.text_type(ex))

    def test_create_server_legacy_neutron_network_id_fails(self):
        """Tests that we no longer support the legacy br-<uuid> format for
           a network id.
        """
        uuid = 'br-00000000-0000-0000-0000-000000000000'
        self.assertRaises(exception.ValidationError, self._create_server,
                          [{'uuid': uuid}])


@ddt.ddt
class ServersControllerCreateTestV252(test.NoDBTestCase):
    def setUp(self):
        super(ServersControllerCreateTestV252, self).setUp()
        self.controller = servers.ServersController()

        self.body = {
            'server': {
                'name': 'device-tagging-server',
                'imageRef': '6b0edabb-8cde-4684-a3f4-978960a51378',
                'flavorRef': '2',
                'networks': [{
                    'uuid': 'ff608d40-75e9-48cb-b745-77bb55b5eaf2'
                }]
            }
        }

        self.req = fakes.HTTPRequestV21.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID, version='2.52')
        self.req.method = 'POST'
        self.req.headers['content-type'] = 'application/json'

    def _create_server(self, tags):
        self.body['server']['tags'] = tags
        self.req.body = jsonutils.dump_as_bytes(self.body)
        return self.controller.create(self.req, body=self.body).obj['server']

    def test_create_server_with_tags_pre_2_52_fails(self):
        """Negative test to make sure you can't pass 'tags' before 2.52"""
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.51')
        self.assertRaises(
            exception.ValidationError, self._create_server, ['tag1'])

    @ddt.data([','],
              ['/'],
              ['a' * (tag.MAX_TAG_LENGTH + 1)],
              ['a'] * (instance_obj.MAX_TAG_COUNT + 1),
              [''],
              [1, 2, 3],
              {'tag': 'tag'})
    def test_create_server_with_tags_incorrect_tags(self, tags):
        """Negative test to incorrect tags are not allowed"""
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.52')
        self.assertRaises(
            exception.ValidationError, self._create_server, tags)


class ServersControllerCreateTestV257(test.NoDBTestCase):
    """Tests that trying to create a server with personality files using
    microversion 2.57 fails.
    """
    def test_create_server_with_personality_fails(self):
        controller = servers.ServersController()
        body = {
            'server': {
                'name': 'no-personality-files',
                'imageRef': '6b0edabb-8cde-4684-a3f4-978960a51378',
                'flavorRef': '2',
                'networks': 'auto',
                'personality': [{
                    'path': '/path/to/file',
                    'contents': 'ZWNobyAiaGVsbG8gd29ybGQi'
                }]
            }
        }
        req = fakes.HTTPRequestV21.blank('/servers', version='2.57')
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        ex = self.assertRaises(
            exception.ValidationError, controller.create, req, body=body)
        self.assertIn('personality', six.text_type(ex))


@mock.patch('nova.compute.utils.check_num_instances_quota',
            new=lambda *args, **kwargs: 1)
class ServersControllerCreateTestV260(test.NoDBTestCase):
    """Negative tests for creating a server with a multiattach volume."""
    def setUp(self):
        super(ServersControllerCreateTestV260, self).setUp()
        self.useFixture(nova_fixtures.NoopQuotaDriverFixture())
        self.controller = servers.ServersController()
        get_flavor_mock = mock.patch(
            'nova.compute.flavors.get_flavor_by_flavor_id',
            return_value=fake_flavor.fake_flavor_obj(
                context.get_admin_context(), flavorid='1',
                expected_attrs=['extra_specs']))
        get_flavor_mock.start()
        self.addCleanup(get_flavor_mock.stop)
        reqspec_create_mock = mock.patch(
            'nova.objects.RequestSpec.create')
        reqspec_create_mock.start()
        self.addCleanup(reqspec_create_mock.stop)
        volume_get_mock = mock.patch(
            'nova.volume.cinder.API.get',
            return_value={'id': uuids.fake_volume_id, 'multiattach': True})
        volume_get_mock.start()
        self.addCleanup(volume_get_mock.stop)

    def _post_server(self, version=None):
        body = {
            'server': {
                'name': 'multiattach',
                'flavorRef': '1',
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'uuid': uuids.fake_volume_id,
                    'source_type': 'volume',
                    'destination_type': 'volume',
                    'boot_index': 0,
                    'delete_on_termination': True}]
            }
        }
        req = fakes.HTTPRequestV21.blank(
            '/servers', version=version or '2.60')
        req.body = jsonutils.dump_as_bytes(body)
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        return self.controller.create(req, body=body)

    def test_create_server_with_multiattach_fails_old_microversion(self):
        """Tests the case that the user tries to boot from volume with a
        multiattach volume but before using microversion 2.60.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._post_server, '2.59')
        self.assertIn('Multiattach volumes are only supported starting with '
                      'compute API version 2.60', six.text_type(ex))


class ServersControllerCreateTestV263(ServersControllerCreateTest):
    def _create_instance_req(self, certs=None):
        self.body['server']['trusted_image_certificates'] = certs

        self.flags(verify_glance_signatures=True, group='glance')
        self.flags(enable_certificate_validation=True, group='glance')

        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.63')

    def test_create_instance_with_trusted_certs(self):
        """Test create with valid trusted_image_certificates argument"""
        self._create_instance_req(
            ['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8',
             '674736e3-f25c-405c-8362-bbf991e0ce0a'])
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_without_trusted_certs(self):
        """Test create without trusted image certificates"""
        self._create_instance_req()
        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body).obj

    def test_create_instance_with_empty_trusted_cert_id(self):
        """Make sure we can't create with an empty certificate ID"""
        self._create_instance_req([''])
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('is too short', six.text_type(ex))

    def test_create_instance_with_empty_trusted_certs(self):
        """Make sure we can't create with an empty array of IDs"""
        self.body['server']['trusted_image_certificates'] = []
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.63')
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('is too short', six.text_type(ex))

    def test_create_instance_with_too_many_trusted_certs(self):
        """Make sure we can't create with an array of >50 unique IDs"""
        self._create_instance_req(['cert{}'.format(i) for i in range(51)])
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('is too long', six.text_type(ex))

    def test_create_instance_with_nonunique_trusted_certs(self):
        """Make sure we can't create with a non-unique array of IDs"""
        self._create_instance_req(['cert', 'cert'])
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('has non-unique elements', six.text_type(ex))

    def test_create_instance_with_invalid_trusted_cert_id(self):
        """Make sure we can't create with non-string certificate IDs"""
        self._create_instance_req([1, 2])
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('is not of type', six.text_type(ex))

    def test_create_instance_with_invalid_trusted_certs(self):
        """Make sure we can't create with certificates in a non-array"""
        self._create_instance_req("not-an-array")
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('is not of type', six.text_type(ex))

    def test_create_server_with_trusted_certs_pre_2_63_fails(self):
        """Make sure we can't use trusted_certs before 2.63"""
        self._create_instance_req(['trusted-cert-id'])
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.62')
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn('Additional properties are not allowed',
                      six.text_type(ex))

    def test_create_server_with_trusted_certs_policy_failed(self):
        rule_name = "os_compute_api:servers:create:trusted_certs"
        rules = {"os_compute_api:servers:create": "@",
                 "os_compute_api:servers:create:forced_host": "@",
                 "os_compute_api:servers:create:attach_volume": "@",
                 "os_compute_api:servers:create:attach_network": "@",
                 rule_name: "project:fake"}
        self._create_instance_req(['0b5d2c72-12cc-4ba6-a8d7-3ff5cc1d8cb8'])
        self.policy.set_rules(rules)
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.create, self.req,
                                body=self.body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch.object(compute_api.API, 'create')
    def test_create_server_with_cert_validation_error(
            self, mock_create):
        mock_create.side_effect = exception.CertificateValidationFailed(
            cert_uuid="cert id", reason="test cert validation error")

        self._create_instance_req(['trusted-cert-id'])
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create, self.req,
                               body=self.body)
        self.assertIn('test cert validation error',
                      six.text_type(ex))


class ServersControllerCreateTestV267(ServersControllerCreateTest):
    def setUp(self):
        super(ServersControllerCreateTestV267, self).setUp()

        self.block_device_mapping_v2 = [
            {'uuid': '70a599e0-31e7-49b7-b260-868f441e862b',
             'source_type': 'image',
             'destination_type': 'volume',
             'boot_index': 0,
             'volume_size': '1',
             'volume_type': 'fake-lvm-1'
            }]

    def _test_create_extra(self, *args, **kwargs):
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.67')
        return super(ServersControllerCreateTestV267, self)._test_create_extra(
            *args, **kwargs)

    def test_create_server_with_trusted_volume_type_pre_2_67_fails(self):
        """Make sure we can't use volume_type before 2.67"""
        self.body['server'].update(
            {'block_device_mapping_v2': self.block_device_mapping_v2})
        self.req.body = jsonutils.dump_as_bytes(self.block_device_mapping_v2)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest('2.66')
        ex = self.assertRaises(
            exception.ValidationError, self.controller.create, self.req,
            body=self.body)
        self.assertIn("'volume_type' was unexpected", six.text_type(ex))

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.VolumeTypeNotFound(
                           id_or_name='fake-lvm-1'))
    def test_create_instance_with_volume_type_not_found(self, mock_create):
        """Trying to boot from volume with a volume type that does not exist
        will result in a 400 error.
        """
        params = {'block_device_mapping_v2': self.block_device_mapping_v2}
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self._test_create_extra, params)
        self.assertIn('Volume type fake-lvm-1 could not be found',
                      six.text_type(ex))

    def test_create_instance_with_volume_type_empty_string(self):
        """Test passing volume_type='' which is accepted but not used."""
        self.block_device_mapping_v2[0]['volume_type'] = ''
        params = {'block_device_mapping_v2': self.block_device_mapping_v2}
        self._test_create_extra(params)

    def test_create_instance_with_none_volume_type(self):
        """Test passing volume_type=None which is accepted but not used."""
        self.block_device_mapping_v2[0]['volume_type'] = None
        params = {'block_device_mapping_v2': self.block_device_mapping_v2}
        self._test_create_extra(params)

    def test_create_instance_without_volume_type(self):
        """Test passing without volume_type which is accepted but not used."""
        self.block_device_mapping_v2[0].pop('volume_type')
        params = {'block_device_mapping_v2': self.block_device_mapping_v2}
        self._test_create_extra(params)

    def test_create_instance_with_volume_type_too_long(self):
        """Tests the maxLength schema validation on volume_type."""
        self.block_device_mapping_v2[0]['volume_type'] = 'X' * 256
        params = {'block_device_mapping_v2': self.block_device_mapping_v2}
        ex = self.assertRaises(exception.ValidationError,
                               self._test_create_extra, params)
        self.assertIn('is too long', six.text_type(ex))


class ServersControllerCreateTestV274(ServersControllerCreateTest):
    def setUp(self):
        super(ServersControllerCreateTestV274, self).setUp()
        self.req.environ['nova.context'] = fakes.FakeRequestContext(
            user_id='fake_user',
            project_id=self.project_id,
            is_admin=True)
        self.mock_get = self.useFixture(
            fixtures.MockPatch('nova.scheduler.client.report.'
                               'SchedulerReportClient.get')).mock

    def _generate_req(self, host=None, node=None, az=None,
                      api_version='2.74'):
        if host:
            self.body['server']['host'] = host
        if node:
            self.body['server']['hypervisor_hostname'] = node
        if az:
            self.body['server']['availability_zone'] = az
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.api_version_request = \
            api_version_request.APIVersionRequest(api_version)

    def test_create_instance_with_invalid_host(self):
        self._generate_req(host='node-invalid')

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn('Compute host node-invalid could not be found.',
                      six.text_type(ex))

    def test_create_instance_with_non_string_host(self):
        self._generate_req(host=123)

        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn("Invalid input for field/attribute host.",
                      six.text_type(ex))

    def test_create_instance_with_invalid_hypervisor_hostname(self):
        get_resp = mock.Mock()
        get_resp.status_code = 404
        self.mock_get.return_value = get_resp

        self._generate_req(node='node-invalid')

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn('Compute host node-invalid could not be found.',
                      six.text_type(ex))

    def test_create_instance_with_non_string_hypervisor_hostname(self):
        get_resp = mock.Mock()
        get_resp.status_code = 404
        self.mock_get.return_value = get_resp

        self._generate_req(node=123)

        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn("Invalid input for field/attribute hypervisor_hostname.",
                      six.text_type(ex))

    def test_create_instance_with_invalid_host_and_hypervisor_hostname(self):
        self._generate_req(host='host-invalid', node='node-invalid')

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn('Compute host host-invalid could not be found.',
                      six.text_type(ex))

    def test_create_instance_with_non_string_host_and_hypervisor_hostname(
            self):
        self._generate_req(host=123, node=123)

        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn("Invalid input for field/attribute",
                      six.text_type(ex))

    def test_create_instance_pre_274(self):
        self._generate_req(host='host', node='node', api_version='2.73')

        ex = self.assertRaises(exception.ValidationError,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn("Invalid input for field/attribute server.",
                      six.text_type(ex))

    def test_create_instance_mutual(self):
        self._generate_req(host='host', node='node', az='nova:host:node')

        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               self.controller.create,
                               self.req, body=self.body)
        self.assertIn("mutually exclusive", six.text_type(ex))

    def test_create_instance_private_flavor(self):
        # Here we use admin context, so if we do not pass it or
        # we do not anything, the test case will be failed.
        pass


class ServersControllerCreateTestWithMock(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    flavor_ref = 'http://localhost/123/flavors/3'

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTestWithMock, self).setUp()

        self.flags(enable_instance_password=True, group='api')
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        self.controller = servers.ServersController()

        self.body = {
            'server': {
                'name': 'server_test',
                'imageRef': self.image_uuid,
                'flavorRef': self.flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                    },
                },
            }
        self.req = fakes.HTTPRequest.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID)
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"

    def _test_create_extra(self, params, no_image=False):
        self.body['server']['flavorRef'] = 2
        if no_image:
            self.body['server'].pop('imageRef', None)
        self.body['server'].update(params)
        self.req.body = jsonutils.dump_as_bytes(self.body)
        self.req.headers["content-type"] = "application/json"
        self.controller.create(self.req, body=self.body).obj['server']

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_fixed_ip_already_in_use(self, create_mock):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '10.0.2.3'
        requested_networks = [{'uuid': network, 'fixed_ip': address}]
        params = {'networks': requested_networks}
        create_mock.side_effect = exception.FixedIpAlreadyInUse(
            address=address,
            instance_uuid=network)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)
        self.assertEqual(1, len(create_mock.call_args_list))

    @mock.patch.object(compute_api.API, 'create')
    def test_create_instance_with_invalid_fixed_ip(self, create_mock):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        address = '999.0.2.3'
        requested_networks = [{'uuid': network, 'fixed_ip': address}]
        params = {'networks': requested_networks}
        self.assertRaises(exception.ValidationError,
                          self._test_create_extra, params)
        self.assertFalse(create_mock.called)

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=exception.InvalidVolume(reason='error'))
    def test_create_instance_with_invalid_volume_error(self, create_mock):
        # Tests that InvalidVolume is translated to a 400 error.
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, {})


class ServersViewBuilderTest(test.TestCase):
    project_id = fakes.FAKE_PROJECT_ID

    def setUp(self):
        super(ServersViewBuilderTest, self).setUp()
        fakes.stub_out_nw_api(self)
        self.flags(group='glance', api_servers=['http://localhost:9292'])
        nw_cache_info = self._generate_nw_cache_info()
        db_inst = fakes.stub_instance(
            id=1,
            image_ref="5",
            uuid=FAKE_UUID,
            display_name="test_server",
            include_fake_metadata=False,
            availability_zone='nova',
            nw_cache=nw_cache_info,
            launched_at=None,
            terminated_at=None,
            task_state=None,
            vm_state=vm_states.ACTIVE,
            power_state=1)

        fakes.stub_out_secgroup_api(
            self, security_groups=[{'name': 'default'}])

        self.stub_out('nova.db.api.'
                      'block_device_mapping_get_all_by_instance_uuids',
                      fake_bdms_get_all_by_instance_uuids)
        self.stub_out('nova.objects.InstanceMappingList.'
                      '_get_by_instance_uuids_from_db',
                      fake_get_inst_mappings_by_instance_uuids_from_db)

        self.uuid = db_inst['uuid']
        self.view_builder = views.servers.ViewBuilder()
        self.request = fakes.HTTPRequestV21.blank("/%s" % self.project_id)
        self.request.context = context.RequestContext('fake', self.project_id)
        self.instance = fake_instance.fake_instance_obj(
                    self.request.context,
                    expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS,
                    **db_inst)
        self.self_link = "http://localhost/v2/%s/servers/%s" % (
                             self.project_id, self.uuid)
        self.bookmark_link = "http://localhost/%s/servers/%s" % (
                             self.project_id, self.uuid)

    def _generate_nw_cache_info(self):
        fixed_ipv4 = ('192.168.1.100', '192.168.2.100', '192.168.3.100')
        fixed_ipv6 = ('2001:db8:0:1::1',)

        def _ip(ip):
            return {'address': ip, 'type': 'fixed'}

        nw_cache = [
            {'address': 'aa:aa:aa:aa:aa:aa',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'test1',
                         'subnets': [{'cidr': '192.168.1.0/24',
                                      'ips': [_ip(fixed_ipv4[0])]},
                                      {'cidr': 'b33f::/64',
                                       'ips': [_ip(fixed_ipv6[0])]}]}},
            {'address': 'bb:bb:bb:bb:bb:bb',
             'id': 2,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'test1',
                         'subnets': [{'cidr': '192.168.2.0/24',
                                      'ips': [_ip(fixed_ipv4[1])]}]}},
            {'address': 'cc:cc:cc:cc:cc:cc',
             'id': 3,
             'network': {'bridge': 'br0',
                         'id': 2,
                         'label': 'test2',
                         'subnets': [{'cidr': '192.168.3.0/24',
                                      'ips': [_ip(fixed_ipv4[2])]}]}}]
        return nw_cache

    def test_get_flavor_valid_instance_type(self):
        flavor_bookmark = "http://localhost/%s/flavors/1" % self.project_id
        expected = {"id": "1",
                    "links": [{"rel": "bookmark",
                               "href": flavor_bookmark}]}
        result = self.view_builder._get_flavor(self.request, self.instance,
                                               False)
        self.assertEqual(result, expected)

    @mock.patch('nova.context.scatter_gather_cells')
    def test_get_volumes_attached_with_faily_cells(self, mock_sg):
        bdms = fake_bdms_get_all_by_instance_uuids()
        # just faking a nova list scenario
        mock_sg.return_value = {
            uuids.cell1: bdms[0],
            uuids.cell2: exception.BDMNotFound(id='fake')
        }
        ctxt = context.RequestContext('fake', fakes.FAKE_PROJECT_ID)
        result = self.view_builder._get_instance_bdms_in_multiple_cells(
            ctxt, [self.instance.uuid])
        # will get the result from cell1
        self.assertEqual(result, bdms[0])
        mock_sg.assert_called_once()

    def test_build_server(self):
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_with_project_id(self):
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail(self):
        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/1" % self.project_id
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "ACTIVE",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 4, 'addr': '192.168.2.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'}
                    ],
                    'test2': [
                        {'version': 4, 'addr': '192.168.3.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'cc:cc:cc:cc:cc:cc'},
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
                "OS-DCF:diskConfig": "MANUAL",
                "accessIPv4": '',
                "accessIPv6": '',
                "OS-EXT-AZ:availability_zone": "nova",
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                "key_name": '',
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ACTIVE,
                "OS-EXT-STS:power_state": 1,
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1'},
                    {'id': 'some_volume_2'},
                ]
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail_with_fault(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/1" % self.project_id
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "name": "test_server",
                "status": "ERROR",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 4, 'addr': '192.168.2.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'}
                    ],
                    'test2': [
                        {'version': 4, 'addr': '192.168.3.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'cc:cc:cc:cc:cc:cc'},
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
                "fault": {
                    "code": 404,
                    "created": "2010-10-10T12:00:00Z",
                    "message": "HTTPNotFound",
                    "details": "Stock details for test",
                },
                "OS-DCF:diskConfig": "MANUAL",
                "accessIPv4": '',
                "accessIPv6": '',
                "OS-EXT-AZ:availability_zone": "nova",
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                "key_name": '',
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ERROR,
                "OS-EXT-STS:power_state": 1,
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1'},
                    {'id': 'some_volume_2'},
                ]
            }
        }

        self.request.context = context.RequestContext('fake', self.project_id)
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail_with_fault_that_has_been_deleted(self):
        self.instance['deleted'] = 1
        self.instance['vm_state'] = vm_states.ERROR
        fault = fake_instance.fake_fault_obj(self.request.context,
                                             self.uuid, code=500,
                                             message="No valid host was found")
        self.instance['fault'] = fault

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "No valid host was found"}

        self.request.context = context.RequestContext('fake', self.project_id)
        output = self.view_builder.show(self.request, self.instance)
        # Regardless of vm_state deleted servers should be DELETED
        self.assertEqual("DELETED", output['server']['status'])
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_build_server_detail_with_fault_no_instance_mapping(self,
                                                                mock_im):
        self.instance['vm_state'] = vm_states.ERROR

        mock_im.side_effect = exception.InstanceMappingNotFound(uuid='foo')

        self.request.context = context.RequestContext('fake', self.project_id)
        self.view_builder.show(self.request, self.instance)
        mock_im.assert_called_once_with(mock.ANY, self.uuid)

    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    def test_build_server_detail_with_fault_loaded(self, mock_im):
        self.instance['vm_state'] = vm_states.ERROR
        fault = fake_instance.fake_fault_obj(self.request.context,
                                             self.uuid, code=500,
                                             message="No valid host was found")
        self.instance['fault'] = fault

        self.request.context = context.RequestContext('fake', self.project_id)
        self.view_builder.show(self.request, self.instance)
        self.assertFalse(mock_im.called)

    def test_build_server_detail_with_fault_no_details_not_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.context = context.RequestContext('fake', self.project_id)
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error",
                          'details': 'Stock details for test'}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_no_details_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error',
                                                   details='')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_but_active(self):
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        output = self.view_builder.show(self.request, self.instance)
        self.assertNotIn('fault', output['server'])

    def test_build_server_detail_active_status(self):
        # set the power state of the instance to running
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/1" % self.project_id
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 100,
                "name": "test_server",
                "status": "ACTIVE",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 4, 'addr': '192.168.2.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'}
                    ],
                    'test2': [
                        {'version': 4, 'addr': '192.168.3.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'cc:cc:cc:cc:cc:cc'},
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
                "OS-DCF:diskConfig": "MANUAL",
                "accessIPv4": '',
                "accessIPv6": '',
                "OS-EXT-AZ:availability_zone": "nova",
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                "key_name": '',
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ACTIVE,
                "OS-EXT-STS:power_state": 1,
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1'},
                    {'id': 'some_volume_2'},
                ]
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail_with_metadata(self):

        metadata = []
        metadata.append(models.InstanceMetadata(key="Open", value="Stack"))
        metadata = nova_utils.metadata_to_dict(metadata)
        self.instance['metadata'] = metadata

        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        flavor_bookmark = "http://localhost/%s/flavors/1" % self.project_id
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "ACTIVE",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                                              {
                            "rel": "bookmark",
                            "href": flavor_bookmark,
                        },
                    ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 4, 'addr': '192.168.2.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'}
                    ],
                    'test2': [
                        {'version': 4, 'addr': '192.168.3.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'cc:cc:cc:cc:cc:cc'},
                    ]
                },
                "metadata": {"Open": "Stack"},
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
                "OS-DCF:diskConfig": "MANUAL",
                "accessIPv4": '',
                "accessIPv6": '',
                "OS-EXT-AZ:availability_zone": "nova",
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                "key_name": '',
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ACTIVE,
                "OS-EXT-STS:power_state": 1,
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1'},
                    {'id': 'some_volume_2'},
                ]
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))


class ServersViewBuilderTestV269(ServersViewBuilderTest):
    """Server ViewBuilder test for microversion 2.69

    The intent here is simply to verify that when showing server details
    after microversion 2.69 the response could have missing keys for those
    servers from the down cells.
    """
    wsgi_api_version = '2.69'

    def setUp(self):
        super(ServersViewBuilderTestV269, self).setUp()
        self.view_builder = views.servers.ViewBuilder()
        self.ctxt = context.RequestContext('fake', self.project_id)

        def fake_is_supported(req, min_version="2.1", max_version="2.69"):
            return (fakes.api_version.APIVersionRequest(max_version) >=
                    req.api_version_request >=
                    fakes.api_version.APIVersionRequest(min_version))
        self.stub_out('nova.api.openstack.api_version_request.is_supported',
                      fake_is_supported)

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                                       use_admin_context=use_admin_context,
                                       version=self.wsgi_api_version)

    def test_get_server_list_detail_with_down_cells(self):
        # Fake out 1 partially constructued instance and one full instance.
        self.instances = [
                self.instance,
                objects.Instance(
                    context=self.ctxt,
                    uuid=uuids.fake1,
                    project_id=fakes.FAKE_PROJECT_ID,
                    created_at=datetime.datetime(1955, 11, 5)
                )
            ]

        req = self.req('/%s/servers/detail' % self.project_id)
        output = self.view_builder.detail(req, self.instances, True)

        self.assertEqual(2, len(output['servers']))
        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        expected = {
            "servers": [{
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "ACTIVE",
                "hostId": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    'disk': 1,
                    'ephemeral': 1,
                    'vcpus': 1,
                    'ram': 256,
                    'original_name': 'flavor1',
                    'extra_specs': {},
                    'swap': 0
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 4, 'addr': '192.168.2.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'bb:bb:bb:bb:bb:bb'}
                    ],
                    'test2': [
                        {'version': 4, 'addr': '192.168.3.100',
                         'OS-EXT-IPS:type': 'fixed',
                         'OS-EXT-IPS-MAC:mac_addr': 'cc:cc:cc:cc:cc:cc'},
                    ]
                },
                "metadata": {},
                "tags": [],
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ],
                "OS-DCF:diskConfig": "MANUAL",
                "OS-EXT-SRV-ATTR:root_device_name": None,
                "accessIPv4": '',
                "accessIPv6": '',
                "host_status": '',
                "OS-EXT-SRV-ATTR:user_data": None,
                "trusted_image_certificates": None,
                "OS-EXT-AZ:availability_zone": "nova",
                "OS-EXT-SRV-ATTR:kernel_id": '',
                "OS-EXT-SRV-ATTR:reservation_id": '',
                "config_drive": None,
                "OS-EXT-SRV-ATTR:host": None,
                "OS-EXT-SRV-ATTR:hypervisor_hostname": None,
                "OS-EXT-SRV-ATTR:hostname": 'test_server',
                "OS-EXT-SRV-ATTR:instance_name": "instance-00000001",
                "key_name": '',
                "locked": False,
                "description": None,
                "OS-SRV-USG:launched_at": None,
                "OS-SRV-USG:terminated_at": None,
                "security_groups": [{'name': 'default'}],
                "OS-EXT-STS:task_state": None,
                "OS-EXT-STS:vm_state": vm_states.ACTIVE,
                "OS-EXT-STS:power_state": 1,
                "OS-EXT-SRV-ATTR:launch_index": 0,
                "OS-EXT-SRV-ATTR:ramdisk_id": '',
                "os-extended-volumes:volumes_attached": [
                    {'id': 'some_volume_1', 'delete_on_termination': True},
                    {'id': 'some_volume_2', 'delete_on_termination': False},
                ]
            },
            {
                'created': '1955-11-05T00:00:00Z',
                'id': uuids.fake1,
                'tenant_id': fakes.FAKE_PROJECT_ID,
                "status": "UNKNOWN",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/%s/servers/%s" %
                                (self.project_id, uuids.fake1),
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/%s/servers/%s" %
                                (self.project_id, uuids.fake1),
                    },
                ],
            }]
        }
        self.assertThat(output, matchers.DictMatches(expected))

    def test_get_server_list_with_down_cells(self):
        # Fake out 1 partially constructued instance and one full instance.
        self.instances = [
                self.instance,
                objects.Instance(
                    context=self.ctxt,
                    uuid=uuids.fake1,
                    project_id=fakes.FAKE_PROJECT_ID,
                    created_at=datetime.datetime(1955, 11, 5)
                )
            ]

        req = self.req('/%s/servers' % self.project_id)
        output = self.view_builder.index(req, self.instances, True)

        self.assertEqual(2, len(output['servers']))

        expected = {
            "servers": [{
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self.self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": self.bookmark_link,
                    },
                ]
            },
            {
                'id': uuids.fake1,
                "status": "UNKNOWN",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/%s/servers/%s" %
                                (self.project_id, uuids.fake1),
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/%s/servers/%s" %
                                (self.project_id, uuids.fake1),
                    },
                ],
            }]
        }

        self.assertThat(output, matchers.DictMatches(expected))

    def test_get_server_with_down_cells(self):
        # Fake out 1 partially constructued instance.
        self.instance = objects.Instance(
            context=self.ctxt,
            uuid=self.uuid,
            project_id=self.instance.project_id,
            created_at=datetime.datetime(1955, 11, 5),
            user_id=self.instance.user_id,
            image_ref=self.instance.image_ref,
            power_state=0,
            flavor=self.instance.flavor,
            availability_zone=self.instance.availability_zone
        )

        req = self.req('/%s/servers/%s' % (self.project_id, FAKE_UUID))
        output = self.view_builder.show(req, self.instance,
                                        cell_down_support=True)
        # ten fields from request_spec and instance_mapping
        self.assertEqual(10, len(output['server']))
        image_bookmark = "http://localhost/%s/images/5" % self.project_id
        expected = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "created": '1955-11-05T00:00:00Z',
                "status": "UNKNOWN",
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    'disk': 1,
                    'ephemeral': 1,
                    'vcpus': 1,
                    'ram': 256,
                    'original_name': 'flavor1',
                    'extra_specs': {},
                    'swap': 0
                },
                "OS-EXT-AZ:availability_zone": "nova",
                "OS-EXT-STS:power_state": 0,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/%s/servers/%s" %
                                (self.project_id, self.uuid),
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/%s/servers/%s" %
                                (self.project_id, self.uuid),
                    },
                ]
            }
        }
        self.assertThat(output, matchers.DictMatches(expected))

    def test_get_server_without_image_avz_user_id_set_from_down_cells(self):
        # Fake out 1 partially constructued instance.
        self.instance = objects.Instance(
            context=self.ctxt,
            uuid=self.uuid,
            project_id=self.instance.project_id,
            created_at=datetime.datetime(1955, 11, 5),
            user_id=None,
            image_ref=None,
            power_state=0,
            flavor=self.instance.flavor,
            availability_zone=None
        )

        req = self.req('/%s/servers/%s' % (self.project_id, FAKE_UUID))
        output = self.view_builder.show(req, self.instance,
                                        cell_down_support=True)
        # nine fields from request_spec and instance_mapping
        self.assertEqual(10, len(output['server']))
        expected = {
            "server": {
                "id": self.uuid,
                "user_id": "UNKNOWN",
                "tenant_id": "fake_project",
                "created": '1955-11-05T00:00:00Z',
                "status": "UNKNOWN",
                "image": "",
                "flavor": {
                    'disk': 1,
                    'ephemeral': 1,
                    'vcpus': 1,
                    'ram': 256,
                    'original_name': 'flavor1',
                    'extra_specs': {},
                    'swap': 0
                },
                "OS-EXT-AZ:availability_zone": "UNKNOWN",
                "OS-EXT-STS:power_state": 0,
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/%s/servers/%s" %
                                (self.project_id, self.uuid),
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/%s/servers/%s" %
                                (self.project_id, self.uuid),
                    },
                ]
            }
        }
        self.assertThat(output, matchers.DictMatches(expected))


class ServersAllExtensionsTestCase(test.TestCase):
    """Servers tests using default API router with all extensions enabled.

    The intent here is to catch cases where extensions end up throwing
    an exception because of a malformed request before the core API
    gets a chance to validate the request and return a 422 response.

    For example, AccessIPsController extends servers.Controller::

        |   @wsgi.extends
        |   def create(self, req, resp_obj, body):
        |       context = req.environ['nova.context']
        |       if authorize(context) and 'server' in resp_obj.obj:
        |           resp_obj.attach(xml=AccessIPTemplate())
        |           server = resp_obj.obj['server']
        |           self._extend_server(req, server)

    we want to ensure that the extension isn't barfing on an invalid
    body.
    """

    def setUp(self):
        super(ServersAllExtensionsTestCase, self).setUp()
        self.app = compute.APIRouterV21()

    @mock.patch.object(compute_api.API, 'create',
                       side_effect=test.TestingException(
                           "Should not reach the compute API."))
    def test_create_missing_server(self, mock_create):
        # Test create with malformed body.
        req = fakes.HTTPRequestV21.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID)
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}

        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)

    def test_update_missing_server(self):
        # Test update with malformed body.

        req = fakes.HTTPRequestV21.blank(
                '/%s/servers/1' % fakes.FAKE_PROJECT_ID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}
        req.body = jsonutils.dump_as_bytes(body)
        with mock.patch('nova.objects.Instance.save') as mock_save:
            res = req.get_response(self.app)
            self.assertFalse(mock_save.called)
        self.assertEqual(400, res.status_int)


class ServersInvalidRequestTestCase(test.TestCase):
    """Tests of places we throw 400 Bad Request from."""

    def setUp(self):
        super(ServersInvalidRequestTestCase, self).setUp()
        self.controller = servers.ServersController()

    def _invalid_server_create(self, body):
        req = fakes.HTTPRequestV21.blank(
                '/%s/servers' % fakes.FAKE_PROJECT_ID)
        req.method = 'POST'

        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_server_no_body(self):
        self._invalid_server_create(body=None)

    def test_create_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._invalid_server_create(body=body)

    def test_create_server_malformed_entity(self):
        body = {'server': 'string'}
        self._invalid_server_create(body=body)

    def _unprocessable_server_update(self, body):
        req = fakes.HTTPRequestV21.blank(
                '/%s/servers/%s' % (fakes.FAKE_PROJECT_ID, FAKE_UUID))
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, FAKE_UUID, body=body)

    def test_update_server_no_body(self):
        self._invalid_server_create(body=None)

    def test_update_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._invalid_server_create(body=body)

    def test_create_update_malformed_entity(self):
        body = {'server': 'string'}
        self._invalid_server_create(body=body)


class ServersActionsJsonTestV239(test.NoDBTestCase):

    def setUp(self):
        super(ServersActionsJsonTestV239, self).setUp()
        self.controller = servers.ServersController()
        self.req = fakes.HTTPRequest.blank('', version='2.39')

    @mock.patch.object(common, 'check_img_metadata_properties_quota')
    @mock.patch.object(common, 'get_instance')
    def test_server_create_image_no_quota_checks(self, mock_get_instance,
                                                 mock_check_quotas):
        # 'mock_get_instance' helps to skip the whole logic of the action,
        # but to make the test
        mock_get_instance.side_effect = webob.exc.HTTPNotFound
        body = {
            'createImage': {
                'name': 'Snapshot 1',
            },
        }
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._action_create_image, self.req,
                          FAKE_UUID, body=body)
        # starting from version 2.39 no quota checks on Nova side are performed
        # for 'createImage' action after removing 'image-metadata' proxy API
        mock_check_quotas.assert_not_called()
