# Copyright 2016 Rackspace Australia
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
from __future__ import absolute_import

import fixtures
import jsonschema
import os
import requests

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image


class fake_result(object):
    def __init__(self, result):
        self.status_code = 200
        self.text = jsonutils.dumps(result)


real_request = requests.request


def fake_request(obj, url, method, **kwargs):
    if url.startswith('http://127.0.0.1:123'):
        return fake_result({'a': 1, 'b': 'foo'})
    if url.startswith('http://127.0.0.1:124'):
        return fake_result({'c': 3})
    if url.startswith('http://127.0.0.1:125'):
        return fake_result(jsonutils.loads(kwargs.get('data', '{}')))
    return real_request(method, url, **kwargs)


class MetadataTest(test.TestCase, integrated_helpers.InstanceHelperMixin):
    def setUp(self):
        super(MetadataTest, self).setUp()

        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.start_service('conductor')
        self.start_service('scheduler')
        self.api = self.useFixture(
            nova_fixtures.OSAPIFixture(api_version='v2.1')).api
        self.start_service('compute')

        # create a server for the tests
        server = self._build_server(name='test')
        server = self.api.post_server({'server': server})
        self.server = self._wait_for_state_change(server, 'ACTIVE')

        self.api_fixture = self.useFixture(nova_fixtures.OSMetadataServer())
        self.md_url = self.api_fixture.md_url

        # make sure that the metadata service returns information about the
        # server we created above
        def fake_get_fixed_ip_by_address(self, ctxt, address):
            return {'instance_uuid': server['id']}

        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.network.neutron.API.get_fixed_ip_by_address',
                fake_get_fixed_ip_by_address))

    def test_lookup_metadata_root_url(self):
        res = requests.request('GET', self.md_url, timeout=5)
        self.assertEqual(200, res.status_code)

    def test_lookup_metadata_openstack_url(self):
        url = '%sopenstack' % self.md_url
        res = requests.request('GET', url, timeout=5,
                               headers={'X-Forwarded-For': '127.0.0.2'})
        self.assertEqual(200, res.status_code)

    def test_lookup_metadata_data_url(self):
        url = '%sopenstack/latest/meta_data.json' % self.md_url
        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)
        j = jsonutils.loads(res.text)
        self.assertIn('hostname', j)
        self.assertEqual('test.novalocal', j['hostname'])

    def test_lookup_external_service(self):
        self.flags(
            vendordata_providers=['StaticJSON', 'DynamicJSON'],
            vendordata_dynamic_targets=[
                'testing@http://127.0.0.1:123',
                'hamster@http://127.0.0.1:123'
                ],
            group='api'
            )

        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.Session.request', fake_request))

        url = '%sopenstack/2016-10-06/vendor_data2.json' % self.md_url
        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)

        j = jsonutils.loads(res.text)
        self.assertEqual({}, j['static'])
        self.assertEqual(1, j['testing']['a'])
        self.assertEqual('foo', j['testing']['b'])
        self.assertEqual(1, j['hamster']['a'])
        self.assertEqual('foo', j['hamster']['b'])

    def test_lookup_external_service_no_overwrite(self):
        self.flags(
            vendordata_providers=['DynamicJSON'],
            vendordata_dynamic_targets=[
                'testing@http://127.0.0.1:123',
                'testing@http://127.0.0.1:124'
                ],
            group='api'
            )

        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.Session.request', fake_request))

        url = '%sopenstack/2016-10-06/vendor_data2.json' % self.md_url
        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)

        j = jsonutils.loads(res.text)
        self.assertNotIn('static', j)
        self.assertEqual(1, j['testing']['a'])
        self.assertEqual('foo', j['testing']['b'])
        self.assertNotIn('c', j['testing'])

    def test_lookup_external_service_passes_data(self):
        # Much of the data we pass to the REST service is missing because of
        # the way we've created the fake instance, but we should at least try
        # and ensure we're passing _some_ data through to the external REST
        # service.

        self.flags(
            vendordata_providers=['DynamicJSON'],
            vendordata_dynamic_targets=[
                'testing@http://127.0.0.1:125'
                ],
            group='api'
            )

        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.Session.request', fake_request))

        url = '%sopenstack/2016-10-06/vendor_data2.json' % self.md_url
        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)

        j = jsonutils.loads(res.text)
        self.assertIn('instance-id', j['testing'])
        self.assertTrue(uuidutils.is_uuid_like(j['testing']['instance-id']))
        self.assertIn('hostname', j['testing'])
        self.assertEqual(self.server['tenant_id'], j['testing']['project-id'])
        self.assertIn('metadata', j['testing'])
        self.assertIn('image-id', j['testing'])
        self.assertIn('user-data', j['testing'])

    def test_network_data_matches_schema(self):
        self.useFixture(fixtures.MonkeyPatch(
                'keystoneauth1.session.Session.request', fake_request))

        url = '%sopenstack/latest/network_data.json' % self.md_url

        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)

        # load the jsonschema for network_data
        schema_file = os.path.normpath(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "../../../doc/api_schemas/network_data.json"))
        with open(schema_file, 'rb') as f:
            schema = jsonutils.load(f)

        jsonschema.validate(res.json(), schema)
