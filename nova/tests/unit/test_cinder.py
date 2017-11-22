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

import collections

from cinderclient.v3 import client as cinder_client_v3
import mock
from requests_mock.contrib import fixture

import nova.conf
from nova import context
from nova import exception
from nova import test
from nova.volume import cinder


CONF = nova.conf.CONF

_image_metadata = {
    'kernel_id': 'fake',
    'ramdisk_id': 'fake'
}


_volume_id = "6edbc2f4-1507-44f8-ac0d-eed1d2608d38"
_instance_uuid = "f4fda93b-06e0-4743-8117-bc8bcecd651b"
_instance_uuid_2 = "f4fda93b-06e0-4743-8117-bc8bcecd651c"
_attachment_id = "3b4db356-253d-4fab-bfa0-e3626c0b8405"
_attachment_id_2 = "3b4db356-253d-4fab-bfa0-e3626c0b8406"
_device = "/dev/vdb"
_device_2 = "/dev/vdc"


_volume_attachment = \
    [{"server_id": _instance_uuid,
      "attachment_id": _attachment_id,
      "host_name": "",
      "volume_id": _volume_id,
      "device": _device,
      "id": _volume_id
    }]


_volume_attachment_2 = _volume_attachment
_volume_attachment_2.append({"server_id": _instance_uuid_2,
                             "attachment_id": _attachment_id_2,
                             "host_name": "",
                             "volume_id": _volume_id,
                             "device": _device_2,
                             "id": _volume_id})


exp_volume_attachment = collections.OrderedDict()
exp_volume_attachment[_instance_uuid] = {'attachment_id': _attachment_id,
                                         'mountpoint': _device}
exp_volume_attachment_2 = exp_volume_attachment
exp_volume_attachment_2[_instance_uuid_2] = {'attachment_id': _attachment_id_2,
                                             'mountpoint': _device_2}


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
        self.assertEqual(cacert, self.create_client().client.session.verify)


# NOTE(mriedem): This does not extend BaseCinderTestCase because Cinder v1 is
# no longer supported, this is just to test that trying to use v1 fails.
class CinderV1TestCase(test.NoDBTestCase):

    @mock.patch('nova.volume.cinder.cinder_client.get_volume_api_from_url',
                return_value='1')
    def test_cinderclient_unsupported_v1(self, get_api_version):
        """Tests that we fail if trying to use Cinder v1."""
        self.flags(catalog_info='volume:cinder:publicURL', group='cinder')
        # setup mocks
        get_endpoint = mock.Mock(
            return_value='http://localhost:8776/v1/%(project_id)s')
        fake_session = mock.Mock(get_endpoint=get_endpoint)
        ctxt = context.get_context()
        with mock.patch.object(cinder, '_SESSION', fake_session):
            self.assertRaises(exception.UnsupportedCinderAPIVersion,
                              cinder.cinderclient, ctxt)
        get_api_version.assert_called_once_with(get_endpoint.return_value)


# NOTE(mriedem): This does not extend BaseCinderTestCase because Cinder v2 is
# no longer supported, this is just to test that trying to use v2 fails.
class CinderV2TestCase(test.NoDBTestCase):

    @mock.patch('nova.volume.cinder.cinder_client.get_volume_api_from_url',
                return_value='2')
    def test_cinderclient_unsupported_v2(self, get_api_version):
        """Tests that we fail if trying to use Cinder v2."""
        self.flags(catalog_info='volumev2:cinderv2:publicURL', group='cinder')
        # setup mocks
        get_endpoint = mock.Mock(
            return_value='http://localhost:8776/v2/%(project_id)s')
        fake_session = mock.Mock(get_endpoint=get_endpoint)
        ctxt = context.get_context()
        with mock.patch.object(cinder, '_SESSION', fake_session):
            self.assertRaises(exception.UnsupportedCinderAPIVersion,
                              cinder.cinderclient, ctxt)
        get_api_version.assert_called_once_with(get_endpoint.return_value)


class CinderV3TestCase(BaseCinderTestCase, test.NoDBTestCase):
    """Test case for cinder volume v3 api."""

    URL = "http://localhost:8776/v3/project_id"

    CATALOG = [{
        "type": "volumev3",
        "name": "cinderv3",
        "endpoints": [{"publicURL": URL}]
    }]

    def setUp(self):
        super(CinderV3TestCase, self).setUp()
        self.addCleanup(CONF.reset)

    def create_client(self):
        c = super(CinderV3TestCase, self).create_client()
        self.assertIsInstance(c, cinder_client_v3.Client)
        self.assertEqual('3.0', c.api_version.get_string())
        return c

    def stub_volume(self, **kwargs):
        volume = {
            'name': None,
            'description': None,
            "attachments": [],
            "availability_zone": "cinderv2",
            "created_at": "2013-08-10T00:00:00.000000",
            "id": _volume_id,
            "metadata": {},
            "size": 1,
            "snapshot_id": None,
            "status": "available",
            "volume_type": "None",
            "bootable": "true",
            "multiattach": "true"
        }
        volume.update(kwargs)
        return volume

    def test_cinder_endpoint_template(self):
        endpoint = 'http://other_host:8776/v3/%(project_id)s'
        self.flags(endpoint_template=endpoint, group='cinder')
        self.assertEqual('http://other_host:8776/v3/project_id',
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

    def test_volume_without_attachment(self):
        v = self.stub_volume(id='1234')
        self.requests.get(self.URL + '/volumes/5678', json={'volume': v})
        volume = self.api.get(self.context, '5678')
        self.assertIsNone(volume.get('attachments'))

    def test_volume_with_one_attachment(self):
        v = self.stub_volume(id='1234', attachments=_volume_attachment)
        self.requests.get(self.URL + '/volumes/5678', json={'volume': v})
        volume = self.api.get(self.context, '5678')
        self.assertIn('attachments', volume)
        self.assertEqual(exp_volume_attachment, volume['attachments'])

    def test_volume_with_two_attachments(self):
        v = self.stub_volume(id='1234', attachments=_volume_attachment_2)
        self.requests.get(self.URL + '/volumes/5678', json={'volume': v})
        volume = self.api.get(self.context, '5678')
        self.assertIn('attachments', volume)
        self.assertEqual(exp_volume_attachment_2, volume['attachments'])
