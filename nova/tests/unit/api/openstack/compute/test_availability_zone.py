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
from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel

from nova.api.openstack.compute import availability_zone as az_v21
from nova.api.openstack.compute import servers as servers_v21
from nova import availability_zones
from nova.compute import api as compute_api
from nova import context
from nova.db import api as db
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake
from nova.tests.unit import matchers
from nova.tests.unit.objects import test_service


FAKE_UUID = fakes.FAKE_UUID


def fake_service_get_all(context, filters=None, **kwargs):

    def __fake_service(binary, availability_zone,
                       created_at, updated_at, host, disabled):
        db_s = dict(test_service.fake_service,
                    binary=binary,
                    availability_zone=availability_zone,
                    available_zones=availability_zone,
                    created_at=created_at,
                    updated_at=updated_at,
                    host=host,
                    disabled=disabled)
        # The version field is immutable so remove that before creating the obj
        db_s.pop('version', None)
        return objects.Service(context, **db_s)

    svcs = [__fake_service("nova-compute", "zone-2",
                           datetime.datetime(2012, 11, 14, 9, 53, 25, 0),
                           datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                           "fake_host-1", True),
            __fake_service("nova-scheduler", "internal",
                           datetime.datetime(2012, 11, 14, 9, 57, 3, 0),
                           datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                           "fake_host-1", True),
            __fake_service("nova-compute", "zone-1",
                           datetime.datetime(2012, 11, 14, 9, 53, 25, 0),
                           datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                           "fake_host-1", False),
            __fake_service("nova-sched", "internal",
                           datetime.datetime(2012, 11, 14, 9, 57, 3, 0),
                           datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                           "fake_host-1", False),
            # nova-conductor is in the same zone and host as nova-sched
            # and is here to make sure /detail filters out duplicates.
            __fake_service("nova-conductor", "internal",
                           datetime.datetime(2012, 11, 14, 9, 57, 3, 0),
                           datetime.datetime(2012, 12, 26, 14, 45, 25, 0),
                           "fake_host-1", False)]

    if filters and 'disabled' in filters:
        svcs = [svc for svc in svcs if svc.disabled == filters['disabled']]

    return objects.ServiceList(objects=svcs)


class AvailabilityZoneApiTestV21(test.NoDBTestCase):
    availability_zone = az_v21

    def setUp(self):
        super(AvailabilityZoneApiTestV21, self).setUp()
        availability_zones.reset_cache()
        fakes.stub_out_nw_api(self)
        self.stub_out('nova.availability_zones.set_availability_zones',
                      lambda c, services: services)
        self.stub_out('nova.servicegroup.API.service_is_up',
                      lambda s, service: True)
        self.controller = self.availability_zone.AvailabilityZoneController()
        self.mock_service_get_all = mock.patch.object(
            self.controller.host_api, 'service_get_all',
            side_effect=fake_service_get_all).start()
        self.addCleanup(self.mock_service_get_all.stop)

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
        req = fakes.HTTPRequest.blank('')
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
        req = fakes.HTTPRequest.blank('')
        resp_dict = self.controller.detail(req)

        self.assertIn('availabilityZoneInfo', resp_dict)
        zones = resp_dict['availabilityZoneInfo']
        self.assertEqual(len(zones), 3)
        timestamp = iso8601.parse_date("2012-12-26T14:45:25Z")
        expected = [
            {
                'zoneName': 'internal',
                'zoneState': {'available': True},
                'hosts': {
                    'fake_host-1': {
                        'nova-sched': {
                            'active': True,
                            'available': True,
                            'updated_at': timestamp
                        },
                        'nova-conductor': {
                            'active': True,
                            'available': True,
                            'updated_at': timestamp
                        }
                    }
                }
            },
            {
                'zoneName': 'zone-1',
                'zoneState': {'available': True},
                'hosts': {
                    'fake_host-1': {
                        'nova-compute': {
                            'active': True,
                            'available': True,
                            'updated_at': timestamp
                        }
                    }
                }
            },
            {
                'zoneName': 'zone-2',
                'zoneState': {'available': False},
                'hosts': None
            }
        ]
        self.assertEqual(expected, zones)
        self.assertEqual(1, self.mock_service_get_all.call_count,
                         self.mock_service_get_all.call_args_list)

    @mock.patch.object(availability_zones, 'get_availability_zones',
                       return_value=[['nova'], []])
    def test_availability_zone_detail_no_services(self, mock_get_az):
        expected_response = {'availabilityZoneInfo':
                                 [{'zoneState': {'available': True},
                             'hosts': {},
                             'zoneName': 'nova'}]}
        req = fakes.HTTPRequest.blank('')
        resp_dict = self.controller.detail(req)

        self.assertThat(resp_dict,
                        matchers.DictMatches(expected_response))


class ServersControllerCreateTestV21(test.TestCase):
    base_url = '/v2/%s/' % fakes.FAKE_PROJECT_ID

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

    def _set_up_controller(self):
        self.controller = servers_v21.ServersController()

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

        req = fakes.HTTPRequest.blank('')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'

        admin_context = context.get_admin_context()
        db.service_create(admin_context, {'host': 'host1_zones',
                                          'binary': "nova-compute",
                                          'topic': 'compute',
                                          'report_count': 0})
        agg = objects.Aggregate(admin_context,
                                name='agg1',
                                uuid=uuidsentinel.agg_uuid,
                                metadata={'availability_zone': 'nova'})
        agg.create()
        agg.add_host('host1_zones')
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
        req = fakes.HTTPRequest.blank('')
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        req.headers['content-type'] = 'application/json'

        res = self.controller.create(req, body=body).obj
        server = res['server']
        self.assertEqual(fakes.FAKE_UUID, server['id'])
