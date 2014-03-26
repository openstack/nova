# Copyright 2012 IBM Corp.
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

import datetime
from oslo.config import cfg
import uuid
import webob

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import availability_zone
from nova.api.openstack.compute.plugins.v3 import servers
from nova import availability_zones
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import context
from nova import db
from nova.network import manager
from nova.openstack.common import jsonutils
from nova import servicegroup
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.image import fake
from nova.tests import matchers

CONF = cfg.CONF
FAKE_UUID = fakes.FAKE_UUID


def fake_gen_uuid():
    return FAKE_UUID


def fake_get_availability_zones(context):
    return ['nova'], []


def return_security_group(context, instance_id, security_group_id):
    pass


def fake_service_get_all(context, disabled=None):
    def __fake_service(binary, availability_zone,
                       created_at, updated_at, host, disabled):
        return {'binary': binary,
                'availability_zone': availability_zone,
                'available_zones': availability_zone,
                'created_at': created_at,
                'updated_at': updated_at,
                'host': host,
                'disabled': disabled}

    if disabled:
        return [__fake_service("nova-compute", "zone-2",
                               datetime.datetime(2012, 11, 14, 9, 53, 25, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                               "fake_host-1", True),
                __fake_service("nova-scheduler", "internal",
                               datetime.datetime(2012, 11, 14, 9, 57, 3, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                               "fake_host-1", True),
                __fake_service("nova-network", "internal",
                               datetime.datetime(2012, 11, 16, 7, 25, 46, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 24, 0),
                               "fake_host-2", True)]
    else:
        return [__fake_service("nova-compute", "zone-1",
                               datetime.datetime(2012, 11, 14, 9, 53, 25, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                               "fake_host-1", False),
                __fake_service("nova-sched", "internal",
                               datetime.datetime(2012, 11, 14, 9, 57, 3, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                               "fake_host-1", False),
                __fake_service("nova-network", "internal",
                               datetime.datetime(2012, 11, 16, 7, 25, 46, 0),
                               datetime.datetime(2012, 12, 26, 14, 45, 24, 0),
                               "fake_host-2", False)]


def fake_service_is_up(self, service):
    return service['binary'] != u"nova-network"


def fake_set_availability_zones(context, services):
    return services


class AvailabilityZoneApiTest(test.TestCase):
    def setUp(self):
        super(AvailabilityZoneApiTest, self).setUp()
        self.stubs.Set(db, 'service_get_all', fake_service_get_all)
        self.stubs.Set(availability_zones, 'set_availability_zones',
                       fake_set_availability_zones)
        self.stubs.Set(servicegroup.API, 'service_is_up', fake_service_is_up)

    def test_filtered_availability_zones(self):
        az = availability_zone.AvailabilityZoneController()
        zones = ['zone1', 'internal']
        expected = [{'zone_name': 'zone1',
                    'zone_state': {'available': True},
                     "hosts": None}]
        result = az._get_filtered_availability_zones(zones, True)
        self.assertEqual(result, expected)

        expected = [{'zone_name': 'zone1',
                    'zone_state': {'available': False},
                     "hosts": None}]
        result = az._get_filtered_availability_zones(zones, False)
        self.assertEqual(result, expected)

    def test_availability_zone_index(self):
        req = webob.Request.blank('/v3/os-availability-zone')
        resp = req.get_response(fakes.wsgi_app_v3(
                                init_only=('os-availability-zone',
                                'servers')))
        self.assertEqual(resp.status_int, 200)
        resp_dict = jsonutils.loads(resp.body)

        self.assertIn('availability_zone_info', resp_dict)
        zones = resp_dict['availability_zone_info']
        self.assertEqual(len(zones), 2)
        self.assertEqual(zones[0]['zone_name'], u'zone-1')
        self.assertTrue(zones[0]['zone_state']['available'])
        self.assertIsNone(zones[0]['hosts'])
        self.assertEqual(zones[1]['zone_name'], u'zone-2')
        self.assertFalse(zones[1]['zone_state']['available'])
        self.assertIsNone(zones[1]['hosts'])

    def test_availability_zone_detail(self):
        def _formatZone(zone_dict):
            result = []

            # Zone tree view item
            result.append({'zone_name': zone_dict['zone_name'],
                           'zone_state': u'available'
                               if zone_dict['zone_state']['available'] else
                                   u'not available'})

            if zone_dict['hosts'] is not None:
                for (host, services) in zone_dict['hosts'].items():
                    # Host tree view item
                    result.append({'zone_name': u'|- %s' % host,
                                   'zone_state': u''})
                    for (svc, state) in services.items():
                        # Service tree view item
                        result.append({'zone_name': u'| |- %s' % svc,
                                       'zone_state': u'%s %s %s' % (
                                           'enabled' if state['active'] else
                                               'disabled',
                                           ':-)' if state['available'] else
                                               'XXX',
                                           jsonutils.to_primitive(
                                               state['updated_at']))})
            return result

        def _assertZone(zone, name, status):
            self.assertEqual(zone['zone_name'], name)
            self.assertEqual(zone['zone_state'], status)

        availabilityZone = availability_zone.AvailabilityZoneController()

        req = webob.Request.blank('/v3/os-availability-zone/detail')
        req.method = 'GET'
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = availabilityZone.detail(req)

        self.assertIn('availability_zone_info', resp_dict)
        zones = resp_dict['availability_zone_info']
        self.assertEqual(len(zones), 3)

        ''' availabilityZoneInfo field content in response body:
        [{'zone_name': 'zone-1',
          'zone_state': {'available': True},
          'hosts': {'fake_host-1': {
                        'nova-compute': {'active': True, 'available': True,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 25)}}}},
         {'zone_name': 'internal',
          'zone_state': {'available': True},
          'hosts': {'fake_host-1': {
                        'nova-sched': {'active': True, 'available': True,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 25)}},
                    'fake_host-2': {
                        'nova-network': {'active': True, 'available': False,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 24)}}}},
         {'zone_name': 'zone-2',
          'zone_state': {'available': False},
          'hosts': None}]
        '''

        l0 = [u'zone-1', u'available']
        l1 = [u'|- fake_host-1', u'']
        l2 = [u'| |- nova-compute', u'enabled :-) 2012-12-26T14:45:25.000000']
        l3 = [u'internal', u'available']
        l4 = [u'|- fake_host-1', u'']
        l5 = [u'| |- nova-sched', u'enabled :-) 2012-12-26T14:45:25.000000']
        l6 = [u'|- fake_host-2', u'']
        l7 = [u'| |- nova-network', u'enabled XXX 2012-12-26T14:45:24.000000']
        l8 = [u'zone-2', u'not available']

        z0 = _formatZone(zones[0])
        z1 = _formatZone(zones[1])
        z2 = _formatZone(zones[2])

        self.assertEqual(len(z0), 3)
        self.assertEqual(len(z1), 5)
        self.assertEqual(len(z2), 1)

        _assertZone(z0[0], l0[0], l0[1])
        _assertZone(z0[1], l1[0], l1[1])
        _assertZone(z0[2], l2[0], l2[1])
        _assertZone(z1[0], l3[0], l3[1])
        _assertZone(z1[1], l4[0], l4[1])
        _assertZone(z1[2], l5[0], l5[1])
        _assertZone(z1[3], l6[0], l6[1])
        _assertZone(z1[4], l7[0], l7[1])
        _assertZone(z2[0], l8[0], l8[1])

    def test_availability_zone_detail_no_services(self):
        expected_response = {'availability_zone_info':
                                 [{'zone_name': 'nova',
                                   'hosts': {},
                                   'zone_state': {'available': True}}]}
        self.stubs.Set(availability_zones, 'get_availability_zones',
                       fake_get_availability_zones)
        availabilityZone = availability_zone.AvailabilityZoneController()

        req = webob.Request.blank('/v3/os-availability-zone/detail')
        req.method = 'GET'
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = availabilityZone.detail(req)

        self.assertThat(resp_dict,
                        matchers.DictMatches(expected_response))


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        CONF.set_override('extensions_blacklist', 'os-availability-zone',
                          'osapi_v3')
        self.no_availability_zone_controller = servers.ServersController(
            extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                availability_zone.ATTRIBUTE_NAME: None,
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
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

        def server_update(context, instance_uuid, params):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                       fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       server_update)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)

    def _test_create_extra(self, params, no_image=False,
                           override_controller=None):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', image_ref=image_uuid, flavor_ref=2)
        if no_image:
            server.pop('image_ref', None)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        if override_controller:
            server = override_controller.create(req, body=body).obj['server']
        else:
            server = self.controller.create(req, body=body).obj['server']

    def test_create_instance_with_availability_zone_disabled(self):
        availability_zone = [{'availability_zone': 'foo'}]
        params = {'availability_zone': availability_zone}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('availability_zone', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params,
            override_controller=self.no_availability_zone_controller)

    def test_create_instance_with_availability_zone(self):
        def create(*args, **kwargs):
            self.assertIn('availability_zone', kwargs)
            self.assertEqual('nova', kwargs['availability_zone'])
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stubs.Set(compute_api.API, 'create', create)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v3/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                availability_zone.ATTRIBUTE_NAME: "nova",
            },
        }

        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        admin_context = context.get_admin_context()
        service1 = db.service_create(admin_context, {'host': 'host1_zones',
                                         'binary': "nova-compute",
                                         'topic': 'compute',
                                         'report_count': 0})
        agg = db.aggregate_create(admin_context,
                {'name': 'agg1'}, {'availability_zone': 'nova'})
        db.aggregate_host_add(admin_context, agg['id'], 'host1_zones')
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_without_availability_zone(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/v3/flavors/3'
        body = {
            'server': {
                'name': 'config_drive_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }

        req = fakes.HTTPRequestV3.blank('/v3/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])
