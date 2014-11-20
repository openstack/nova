#    Copyright 2011 OpenStack Foundation
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

from cinderclient.v1 import client as cinder_client_v1
from cinderclient.v2 import client as cinder_client_v2
from requests_mock.contrib import fixture
from testtools import matchers

from nova import context
from nova import exception
from nova import test
from nova.volume import cinder


_image_metadata = {
    'kernel_id': 'fake',
    'ramdisk_id': 'fake'
}


class BaseCinderTestCase(object):

    def setUp(self):
        super(BaseCinderTestCase, self).setUp()
        cinder.reset_globals()
        self.requests = self.useFixture(fixture.Fixture())
        self.api = cinder.API()

        self.context = context.RequestContext('username',
                                              'project_id',
                                              auth_token='token',
                                              service_catalog=self.CATALOG)

    def flags(self, *args, **kwargs):
        super(BaseCinderTestCase, self).flags(*args, **kwargs)
        cinder.reset_globals()

    def create_client(self):
        return cinder.cinderclient(self.context)

    def test_context_with_catalog(self):
        self.assertEqual(self.URL, self.create_client().client.get_endpoint())

    def test_cinder_http_retries(self):
        retries = 42
        self.flags(http_retries=retries, group='cinder')
        self.assertEqual(retries, self.create_client().client.connect_retries)

    def test_cinder_api_insecure(self):
        # The True/False negation is awkward, but better for the client
        # to pass us insecure=True and we check verify_cert == False
        self.flags(insecure=True, group='cinder')
        self.assertFalse(self.create_client().client.session.verify)

    def test_cinder_http_timeout(self):
        timeout = 123
        self.flags(timeout=timeout, group='cinder')
        self.assertEqual(timeout, self.create_client().client.session.timeout)

    def test_cinder_api_cacert_file(self):
        cacert = "/etc/ssl/certs/ca-certificates.crt"
        self.flags(cafile=cacert, group='cinder')
        self.assertEqual(self.create_client().client.session.verify, cacert)


class CinderTestCase(BaseCinderTestCase, test.NoDBTestCase):
    """Test case for cinder volume v1 api."""

    URL = "http://localhost:8776/v1/project_id"

    CATALOG = [{
        "type": "volumev2",
        "name": "cinderv2",
        "endpoints": [{"publicURL": URL}]
    }]

    def create_client(self):
        c = super(CinderTestCase, self).create_client()
        self.assertIsInstance(c, cinder_client_v1.Client)
        return c

    def stub_volume(self, **kwargs):
        volume = {
            'display_name': None,
            'display_description': None,
            "attachments": [],
            "availability_zone": "cinder",
            "created_at": "2012-09-10T00:00:00.000000",
            "id": '00000000-0000-0000-0000-000000000000',
            "metadata": {},
            "size": 1,
            "snapshot_id": None,
            "status": "available",
            "volume_type": "None",
            "bootable": "true"
        }
        volume.update(kwargs)
        return volume

    def test_cinder_endpoint_template(self):
        endpoint = 'http://other_host:8776/v1/%(project_id)s'
        self.flags(endpoint_template=endpoint, group='cinder')
        self.assertEqual('http://other_host:8776/v1/project_id',
                         self.create_client().client.endpoint_override)

    def test_get_non_existing_volume(self):
        self.requests.get(self.URL + '/volumes/nonexisting',
                          status_code=404)

        self.assertRaises(exception.VolumeNotFound, self.api.get, self.context,
                          'nonexisting')

    def test_volume_with_image_metadata(self):
        v = self.stub_volume(id='1234', volume_image_metadata=_image_metadata)
        m = self.requests.get(self.URL + '/volumes/5678', json={'volume': v})

        volume = self.api.get(self.context, '5678')
        self.assertThat(m.last_request.path,
                        matchers.EndsWith('/volumes/5678'))
        self.assertIn('volume_image_metadata', volume)
        self.assertEqual(volume['volume_image_metadata'], _image_metadata)


class CinderV2TestCase(BaseCinderTestCase, test.NoDBTestCase):
    """Test case for cinder volume v2 api."""

    URL = "http://localhost:8776/v2/project_id"

    CATALOG = [{
        "type": "volumev2",
        "name": "cinder",
        "endpoints": [{"publicURL": URL}]
    }]

    def setUp(self):
        super(CinderV2TestCase, self).setUp()
        cinder.CONF.set_override('catalog_info',
                                 'volumev2:cinder:publicURL', group='cinder')
        self.addCleanup(cinder.CONF.reset)

    def create_client(self):
        c = super(CinderV2TestCase, self).create_client()
        self.assertIsInstance(c, cinder_client_v2.Client)
        return c

    def stub_volume(self, **kwargs):
        volume = {
            'name': None,
            'description': None,
            "attachments": [],
            "availability_zone": "cinderv2",
            "created_at": "2013-08-10T00:00:00.000000",
            "id": '00000000-0000-0000-0000-000000000000',
            "metadata": {},
            "size": 1,
            "snapshot_id": None,
            "status": "available",
            "volume_type": "None",
            "bootable": "true"
        }
        volume.update(kwargs)
        return volume

    def test_cinder_endpoint_template(self):
        endpoint = 'http://other_host:8776/v2/%(project_id)s'
        self.flags(endpoint_template=endpoint, group='cinder')
        self.assertEqual('http://other_host:8776/v2/project_id',
                         self.create_client().client.endpoint_override)

    def test_get_non_existing_volume(self):
        self.requests.get(self.URL + '/volumes/nonexisting',
                          status_code=404)

        self.assertRaises(exception.VolumeNotFound, self.api.get, self.context,
                          'nonexisting')

    def test_volume_with_image_metadata(self):
        v = self.stub_volume(id='1234', volume_image_metadata=_image_metadata)
        self.requests.get(self.URL + '/volumes/5678', json={'volume': v})
        volume = self.api.get(self.context, '5678')
        self.assertIn('volume_image_metadata', volume)
        self.assertEqual(_image_metadata, volume['volume_image_metadata'])
