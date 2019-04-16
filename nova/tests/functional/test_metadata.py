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
import requests

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures


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


class MetadataTest(test.TestCase):
    def setUp(self):
        super(MetadataTest, self).setUp()
        self.api_fixture = self.useFixture(nova_fixtures.OSMetadataServer())
        self.md_url = self.api_fixture.md_url

        ctxt = context.RequestContext('fake', 'fake')
        flavor = objects.Flavor(
                id=1, name='flavor1', memory_mb=256, vcpus=1, root_gb=1,
                ephemeral_gb=1, flavorid='1', swap=0, rxtx_factor=1.0,
                vcpu_weight=1, disabled=False, is_public=True, extra_specs={},
                projects=[])
        instance = objects.Instance(ctxt, flavor=flavor, vcpus=1,
                                    memory_mb=256, root_gb=0, ephemeral_gb=0,
                                    project_id='fake', hostname='test')
        instance.create()

        # NOTE(mikal): We could create a network and a fixed IP here, but it
        # turns out to be heaps of fiddly boiler plate code, so let's just
        # fake it and hope mriedem doesn't notice.
        # TODO(mriedem): Make this all work with the Neutron fixture.
        self.flags(use_neutron=False)

        def fake_get_fixed_ip_by_address(self, ctxt, address):
            return {'instance_uuid': instance.uuid}

        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.network.api.API.get_fixed_ip_by_address',
                fake_get_fixed_ip_by_address))

        def fake_get_ip_info_for_instance_from_nw_info(nw_info):
            return {'fixed_ips': ['127.0.0.2'],
                    'fixed_ip6s': [],
                    'floating_ips': []}

        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.api.ec2.ec2utils.get_ip_info_for_instance_from_nw_info',
                fake_get_ip_info_for_instance_from_nw_info))

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
        self.assertEqual('fake', j['testing']['project-id'])
        self.assertIn('metadata', j['testing'])
        self.assertIn('image-id', j['testing'])
        self.assertIn('user-data', j['testing'])
