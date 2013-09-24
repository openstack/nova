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
from lxml import etree
import webob

from nova.api.openstack.compute.contrib import availability_zone
from nova import availability_zones
from nova import context
from nova import db
from nova.openstack.common import jsonutils
from nova import servicegroup
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import matchers


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


def fake_get_availability_zones(context):
    return ['nova'], []


class AvailabilityZoneApiTest(test.NoDBTestCase):
    def setUp(self):
        super(AvailabilityZoneApiTest, self).setUp()
        availability_zones.reset_cache()
        self.stubs.Set(db, 'service_get_all', fake_service_get_all)
        self.stubs.Set(availability_zones, 'set_availability_zones',
                       fake_set_availability_zones)
        self.stubs.Set(servicegroup.API, 'service_is_up', fake_service_is_up)

    def test_filtered_availability_zones(self):
        az = availability_zone.AvailabilityZoneController()
        zones = ['zone1', 'internal']
        expected = [{'zoneName': 'zone1',
                    'zoneState': {'available': True},
                     "hosts": None}]
        result = az._get_filtered_availability_zones(zones, True)
        self.assertEqual(result, expected)

        expected = [{'zoneName': 'zone1',
                    'zoneState': {'available': False},
                     "hosts": None}]
        result = az._get_filtered_availability_zones(zones, False)
        self.assertEqual(result, expected)

    def test_availability_zone_index(self):
        req = webob.Request.blank('/v2/fake/os-availability-zone')
        resp = req.get_response(fakes.wsgi_app())
        self.assertEqual(resp.status_int, 200)
        resp_dict = jsonutils.loads(resp.body)

        self.assertTrue('availabilityZoneInfo' in resp_dict)
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

        availabilityZone = availability_zone.AvailabilityZoneController()

        req = webob.Request.blank('/v2/fake/os-availability-zone/detail')
        req.method = 'GET'
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = availabilityZone.detail(req)

        self.assertTrue('availabilityZoneInfo' in resp_dict)
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
        availabilityZone = availability_zone.AvailabilityZoneController()

        req = webob.Request.blank('/v2/fake/os-availability-zone/detail')
        req.method = 'GET'
        req.environ['nova.context'] = context.get_admin_context()
        resp_dict = availabilityZone.detail(req)

        self.assertThat(resp_dict,
                        matchers.DictMatches(expected_response))


class AvailabilityZoneSerializerTest(test.NoDBTestCase):
    def test_availability_zone_index_detail_serializer(self):
        def _verify_zone(zone_dict, tree):
            self.assertEqual(tree.tag, 'availabilityZone')
            self.assertEqual(zone_dict['zoneName'], tree.get('name'))
            self.assertEqual(str(zone_dict['zoneState']['available']),
                             tree[0].get('available'))

            for _idx, host_child in enumerate(tree[1]):
                self.assertTrue(host_child.get('name') in zone_dict['hosts'])
                svcs = zone_dict['hosts'][host_child.get('name')]
                for _idx, svc_child in enumerate(host_child[0]):
                    self.assertTrue(svc_child.get('name') in svcs)
                    svc = svcs[svc_child.get('name')]
                    self.assertEqual(len(svc_child), 1)

                    self.assertEqual(str(svc['available']),
                                     svc_child[0].get('available'))
                    self.assertEqual(str(svc['active']),
                                     svc_child[0].get('active'))
                    self.assertEqual(str(svc['updated_at']),
                                     svc_child[0].get('updated_at'))

        serializer = availability_zone.AvailabilityZonesTemplate()
        raw_availability_zones = \
            [{'zoneName': 'zone-1',
              'zoneState': {'available': True},
              'hosts': {'fake_host-1': {
                            'nova-compute': {'active': True, 'available': True,
                                'updated_at':
                                    datetime.datetime(
                                        2012, 12, 26, 14, 45, 25)}}}},
             {'zoneName': 'internal',
              'zoneState': {'available': True},
              'hosts': {'fake_host-1': {
                            'nova-sched': {'active': True, 'available': True,
                                'updated_at':
                                    datetime.datetime(
                                        2012, 12, 26, 14, 45, 25)}},
                        'fake_host-2': {
                            'nova-network': {'active': True,
                                             'available': False,
                                             'updated_at':
                                    datetime.datetime(
                                        2012, 12, 26, 14, 45, 24)}}}},
             {'zoneName': 'zone-2',
              'zoneState': {'available': False},
              'hosts': None}]

        text = serializer.serialize(
                  dict(availabilityZoneInfo=raw_availability_zones))
        tree = etree.fromstring(text)

        self.assertEqual('availabilityZones', tree.tag)
        self.assertEqual(len(raw_availability_zones), len(tree))
        for idx, child in enumerate(tree):
            _verify_zone(raw_availability_zones[idx], child)
