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

import iso8601
import mock
from oslo_config import cfg

from nova.api.openstack.compute import availability_zone as az_v21
from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute import servers as servers_v21
from nova import availability_zones
from nova.compute import api as compute_api
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_service
from nova.tests import uuidsentinel


CONF = cfg.CONF
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


class AvailabilityZoneApiTestV21(test.NoDBTestCase):
    availability_zone = az_v21

    def setUp(self):
        super(AvailabilityZoneApiTestV21, self).setUp()
        availability_zones.reset_cache()
        fakes.stub_out_nw_api(self)
        self.stub_out('nova.db.service_get_all', fake_service_get_all)
        self.stub_out('nova.availability_zones.set_availability_zones',
                      lambda c, services: services)
        self.stub_out('nova.servicegroup.API.service_is_up',
                      lambda s, service: service['binary'] != u"nova-network")
        self.controller = self.availability_zone.AvailabilityZoneController()
        self.req = fakes.HTTPRequest.blank('')

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
        resp_dict = self.controller.index(self.req)

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
        resp_dict = self.controller.detail(self.req)

        self.assertIn('availabilityZoneInfo', resp_dict)
        zones = resp_dict['availabilityZoneInfo']
        self.assertEqual(len(zones), 3)
        timestamp = iso8601.parse_date("2012-12-26T14:45:25Z")
        nova_network_timestamp = iso8601.parse_date("2012-12-26T14:45:24Z")
        expected = [{'zoneName': 'zone-1',
                    'zoneState': {'available': True},
                    'hosts': {'fake_host-1': {
                        'nova-compute': {'active': True, 'available': True,
                                         'updated_at': timestamp}}}},
                   {'zoneName': 'internal',
                    'zoneState': {'available': True},
                    'hosts': {'fake_host-1': {
                        'nova-sched': {'active': True, 'available': True,
                                       'updated_at': timestamp}},
                              'fake_host-2': {
                                  'nova-network': {
                                      'active': True,
                                      'available': False,
                                      'updated_at': nova_network_timestamp}}}},
                   {'zoneName': 'zone-2',
                    'zoneState': {'available': False},
                    'hosts': None}]
        self.assertEqual(expected, zones)

    @mock.patch.object(availability_zones, 'get_availability_zones',
                       return_value=[['nova'], []])
    def test_availability_zone_detail_no_services(self, mock_get_az):
        expected_response = {'availabilityZoneInfo':
                                 [{'zoneState': {'available': True},
                             'hosts': {},
                             'zoneName': 'nova'}]}
        resp_dict = self.controller.detail(self.req)

        self.assertThat(resp_dict,
                        matchers.DictMatches(expected_response))


class ServersControllerCreateTestV21(test.TestCase):
    base_url = '/v2/fake/'

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTestV21, self).setUp()

        self.instance_cache_num = 0
        fakes.stub_out_nw_api(self)
        self._set_up_controller()

        def create_db_entry_for_new_instance(*args, **kwargs):
            instance = args[4]
            instance.uuid = FAKE_UUID
            return instance

        fake.stub_out_image_service(self)
        self.stub_out('nova.compute.api.API.create_db_entry_for_new_instance',
                      create_db_entry_for_new_instance)
        self.req = fakes.HTTPRequest.blank('')

    def _set_up_controller(self):
        ext_info = extension_info.LoadedExtensionInfo()
        self.controller = servers_v21.ServersController(
            extension_info=ext_info)

    def _create_instance_with_availability_zone(self, zone_name):
        def create(*args, **kwargs):
            self.assertIn('availability_zone', kwargs)
            self.assertEqual('nova', kwargs['availability_zone'])
            return old_create(*args, **kwargs)

        old_create = compute_api.API.create
        self.stub_out('nova.compute.api.API.create', create)
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

        admin_context = context.get_admin_context()
        db.service_create(admin_context, {'host': 'host1_zones',
                                          'binary': "nova-compute",
                                          'topic': 'compute',
                                          'report_count': 0})
        agg = db.aggregate_create(admin_context,
                {'name': 'agg1', 'uuid': uuidsentinel.agg_uuid},
                {'availability_zone': 'nova'})
        db.aggregate_host_add(admin_context, agg['id'], 'host1_zones')
        return self.req, body

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

        res = self.controller.create(self.req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])
