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
from oslo.serialization import jsonutils
import webob

from nova.api.openstack.compute.contrib import availability_zone as az_v2
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import availability_zone as az_v21
from nova.api.openstack.compute.plugins.v3 import servers as servers_v21
from nova.api.openstack.compute import servers as servers_v2
from nova.api.openstack import extensions
from nova import availability_zones
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova import servicegroup
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit.image import fake
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_service

FAKE_UUID = fakes.FAKE_UUID


def fake_service_get_all(context, disabled=None):
    def __fake_service(binary, availability_zone,
                       created_at, updated_at, host, disabled):
        return dict(test_service.fake_service,
                    binary=binary,
                    availability_zone=availability_zone,
                    available_zones=availability_zone,
                    created_at=created_at,
                    updated_at=updated_at,
                    host=host,
                    disabled=disabled)

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


def fake_get_availability_zones(context):
    return ['nova'], []


CONF = cfg.CONF


class AvailabilityZoneApiTestV21(test.NoDBTestCase):
    availability_zone = az_v21

    def setUp(self):
        super(AvailabilityZoneApiTestV21, self).setUp()
        availability_zones.reset_cache()
        self.stubs.Set(db, 'service_get_all', fake_service_get_all)
        self.stubs.Set(availability_zones, 'set_availability_zones',
                       fake_set_availability_zones)
        self.stubs.Set(servicegroup.API, 'service_is_up', fake_service_is_up)
        self.controller = self.availability_zone.AvailabilityZoneController()

    def test_filtered_availability_zones(self):
        zones = ['zone1', 'internal']
        expected = [{'zoneName': 'zone1',
                    'zoneState': {'available': True},
                     "hosts": None}]
        result = self.controller._get_filtered_availability_zones(zones, True)
        self.assertEqual(result, expected)

        expected = [{'zoneName': 'zone1',
                    'zoneState': {'available': False},
                     "hosts": None}]
        result = self.controller._get_filtered_availability_zones(zones,
                                                                  False)
        self.assertEqual(result, expected)

    def test_availability_zone_index(self):
        req = webob.Request.blank('')
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = self.controller.index(req)

        self.assertIn('availabilityZoneInfo', resp_dict)
        zones = resp_dict['availabilityZoneInfo']
        self.assertEqual(len(zones), 2)
        self.assertEqual(zones[0]['zoneName'], u'zone-1')
        self.assertTrue(zones[0]['zoneState']['available'])
        self.assertIsNone(zones[0]['hosts'])
        self.assertEqual(zones[1]['zoneName'], u'zone-2')
        self.assertFalse(zones[1]['zoneState']['available'])
        self.assertIsNone(zones[1]['hosts'])

    def test_availability_zone_detail(self):
        def _formatZone(zone_dict):
            result = []

            # Zone tree view item
            result.append({'zoneName': zone_dict['zoneName'],
                           'zoneState': u'available'
                               if zone_dict['zoneState']['available'] else
                                   u'not available'})

            if zone_dict['hosts'] is not None:
                for (host, services) in zone_dict['hosts'].items():
                    # Host tree view item
                    result.append({'zoneName': u'|- %s' % host,
                                   'zoneState': u''})
                    for (svc, state) in services.items():
                        # Service tree view item
                        result.append({'zoneName': u'| |- %s' % svc,
                                       'zoneState': u'%s %s %s' % (
                                           'enabled' if state['active'] else
                                               'disabled',
                                           ':-)' if state['available'] else
                                               'XXX',
                                           jsonutils.to_primitive(
                                               state['updated_at']))})
            return result

        def _assertZone(zone, name, status):
            self.assertEqual(zone['zoneName'], name)
            self.assertEqual(zone['zoneState'], status)

        req = webob.Request.blank('')
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = self.controller.detail(req)

        self.assertIn('availabilityZoneInfo', resp_dict)
        zones = resp_dict['availabilityZoneInfo']
        self.assertEqual(len(zones), 3)

        ''' availabilityZoneInfo field content in response body:
        [{'zoneName': 'zone-1',
          'zoneState': {'available': True},
          'hosts': {'fake_host-1': {
                        'nova-compute': {'active': True, 'available': True,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 25)}}}},
         {'zoneName': 'internal',
          'zoneState': {'available': True},
          'hosts': {'fake_host-1': {
                        'nova-sched': {'active': True, 'available': True,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 25)}},
                    'fake_host-2': {
                        'nova-network': {'active': True, 'available': False,
                          'updated_at': datetime(2012, 12, 26, 14, 45, 24)}}}},
         {'zoneName': 'zone-2',
          'zoneState': {'available': False},
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
        expected_response = {'availabilityZoneInfo':
                                 [{'zoneState': {'available': True},
                             'hosts': {},
                             'zoneName': 'nova'}]}
        self.stubs.Set(availability_zones, 'get_availability_zones',
                       fake_get_availability_zones)

        req = webob.Request.blank('')
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = self.controller.detail(req)

        self.assertThat(resp_dict,
                        matchers.DictMatches(expected_response))


class AvailabilityZoneApiTestV2(AvailabilityZoneApiTestV21):
    availability_zone = az_v2


class ServersControllerCreateTestV21(test.TestCase):
    base_url = '/v2/fake/'

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTestV21, self).setUp()

        self.instance_cache_num = 0

        self._set_up_controller()

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': inst_type,
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'availability_zone': 'nova',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "root_device_name": inst.get('root_device_name', 'vda'),
            })

            return instance

        fake.stub_out_image_service(self.stubs)
        self.stubs.Set(db, 'instance_create', instance_create)

    def _set_up_controller(self):
        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers_v21.ServersController(
            extension_info=ext_info)
        CONF.set_override('extensions_blacklist',
                          'os-availability-zone',
                          'osapi_v3')
        self.no_availability_zone_controller = servers_v21.ServersController(
            extension_info=ext_info)

    def _verify_no_availability_zone(self, **kwargs):
        self.assertNotIn('availability_zone', kwargs)

    def _test_create_extra(self, params, controller):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', imageRef=image_uuid, flavorRef=2)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequest.blank(self.base_url + 'servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        server = controller.create(req, body=body).obj['server']

    def test_create_instance_with_availability_zone_disabled(self):
        params = {'availability_zone': 'foo'}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self._verify_no_availability_zone(**kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params, self.no_availability_zone_controller)

    def _create_instance_with_availability_zone(self, zone_name):
        def create(*args, **kwargs):
            self.assertIn('availability_zone', kwargs)
            self.assertEqual('nova', kwargs['availability_zone'])
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stubs.Set(compute_api.API, 'create', create)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = ('http://localhost' + self.base_url + 'flavors/3')
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
                'availability_zone': zone_name,
            },
        }

        req = fakes.HTTPRequest.blank(self.base_url + 'servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        admin_context = context.get_admin_context()
        db.service_create(admin_context, {'host': 'host1_zones',
                                          'binary': "nova-compute",
                                          'topic': 'compute',
                                          'report_count': 0})
        agg = db.aggregate_create(admin_context,
                {'name': 'agg1'}, {'availability_zone': 'nova'})
        db.aggregate_host_add(admin_context, agg['id'], 'host1_zones')
        return req, body

    def test_create_instance_with_availability_zone(self):
        zone_name = 'nova'
        req, body = self._create_instance_with_availability_zone(zone_name)
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])

    def test_create_instance_with_invalid_availability_zone_too_long(self):
        zone_name = 'a' * 256
        req, body = self._create_instance_with_availability_zone(zone_name)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_instance_with_invalid_availability_zone_too_short(self):
        zone_name = ''
        req, body = self._create_instance_with_availability_zone(zone_name)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_instance_with_invalid_availability_zone_not_str(self):
        zone_name = 111
        req, body = self._create_instance_with_availability_zone(zone_name)
        self.assertRaises(exception.ValidationError,
                          self.controller.create, req, body=body)

    def test_create_instance_without_availability_zone(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = ('http://localhost' + self.base_url + 'flavors/3')
        body = {
            'server': {
                'name': 'server_test',
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }

        req = fakes.HTTPRequest.blank(self.base_url + 'servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])


class ServersControllerCreateTestV2(ServersControllerCreateTestV21):

    def _set_up_controller(self):
        ext_mgr = extensions.ExtensionManager()
        ext_mgr.extensions = {'os-availability-zone': 'fake'}
        self.controller = servers_v2.Controller(ext_mgr)
        ext_mgr_no_az = extensions.ExtensionManager()
        ext_mgr_no_az.extensions = {}
        self.no_availability_zone_controller = servers_v2.Controller(
                                                   ext_mgr_no_az)

    def _verify_no_availability_zone(self, **kwargs):
        self.assertIsNone(kwargs['availability_zone'])

    def test_create_instance_with_invalid_availability_zone_too_long(self):
        # NOTE: v2.0 API does not check this bad request case.
        # So we skip this test for v2.0 API.
        pass

    def test_create_instance_with_invalid_availability_zone_too_short(self):
        # NOTE: v2.0 API does not check this bad request case.
        # So we skip this test for v2.0 API.
        pass

    def test_create_instance_with_invalid_availability_zone_not_str(self):
        # NOTE: v2.0 API does not check this bad request case.
        # So we skip this test for v2.0 API.
        pass
