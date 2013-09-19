# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import urlparse

from cinderclient import exceptions as cinder_exception
from nova import context
from nova import exception
from nova.volume import cinder

from nova import test


def _stub_volume(**kwargs):
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
    }
    volume.update(kwargs)
    return volume

_image_metadata = {
    'kernel_id': 'fake',
    'ramdisk_id': 'fake'
}


class FakeHTTPClient(cinder.cinder_client.client.HTTPClient):

    def _cs_request(self, url, method, **kwargs):
        # Check that certain things are called correctly
        if method in ['GET', 'DELETE']:
            assert 'body' not in kwargs
        elif method == 'PUT':
            assert 'body' in kwargs

        # Call the method
        args = urlparse.parse_qsl(urlparse.urlparse(url)[4])
        kwargs.update(args)
        munged_url = url.rsplit('?', 1)[0]
        munged_url = munged_url.strip('/').replace('/', '_').replace('.', '_')
        munged_url = munged_url.replace('-', '_')

        callback = "%s_%s" % (method.lower(), munged_url)

        if not hasattr(self, callback):
            raise AssertionError('Called unknown API method: %s %s, '
                                 'expected fakes method name: %s' %
                                 (method, url, callback))

        # Note the call
        self.callstack.append((method, url, kwargs.get('body', None)))

        status, body = getattr(self, callback)(**kwargs)
        if hasattr(status, 'items'):
            return status, body
        else:
            return {"status": status}, body

    def get_volumes_1234(self, **kw):
        volume = {'volume': _stub_volume(id='1234')}
        return (200, volume)

    def get_volumes_nonexisting(self, **kw):
        raise cinder_exception.NotFound(code=404, message='Resource not found')

    def get_volumes_5678(self, **kw):
        """Volume with image metadata."""
        volume = {'volume': _stub_volume(id='1234',
                                         volume_image_metadata=_image_metadata)
        }
        return (200, volume)


class FakeCinderClient(cinder.cinder_client.Client):

    def __init__(self, username, password, project_id=None, auth_url=None,
                 insecure=False, retries=None, cacert=None):
        super(FakeCinderClient, self).__init__(username, password,
                                               project_id=project_id,
                                               auth_url=auth_url,
                                               insecure=insecure,
                                               retries=retries,
                                               cacert=cacert)
        self.client = FakeHTTPClient(username, password, project_id, auth_url,
                                     insecure=insecure, retries=retries,
                                     cacert=cacert)
        # keep a ref to the clients callstack for factory's assert_called
        self.callstack = self.client.callstack = []


class FakeClientFactory(object):
    """Keep a ref to the FakeClient since volume.api.cinder throws it away."""

    def __call__(self, *args, **kwargs):
        self.client = FakeCinderClient(*args, **kwargs)
        return self.client

    def assert_called(self, method, url, body=None, pos=-1):
        expected = (method, url)
        called = self.client.callstack[pos][0:2]

        assert self.client.callstack, ("Expected %s %s but no calls "
                                       "were made." % expected)

        assert expected == called, 'Expected %s %s; got %s %s' % (expected +
                                                                  called)

        if body is not None:
            assert self.client.callstack[pos][2] == body


class CinderTestCase(test.NoDBTestCase):
    """Test case for cinder volume api."""

    def setUp(self):
        super(CinderTestCase, self).setUp()
        self.fake_client_factory = FakeClientFactory()
        self.stubs.Set(cinder.cinder_client, "Client",
                       self.fake_client_factory)
        self.api = cinder.API()
        catalog = [{
            "type": "volume",
            "name": "cinder",
            "endpoints": [{"publicURL": "http://localhost:8776/v1/project_id"}]
        }]
        self.context = context.RequestContext('username', 'project_id',
                                              service_catalog=catalog)

    def assert_called(self, *args, **kwargs):
        self.fake_client_factory.assert_called(*args, **kwargs)

    def test_context_with_catalog(self):
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEquals(
            self.fake_client_factory.client.client.management_url,
            'http://localhost:8776/v1/project_id')

    def test_cinder_endpoint_template(self):
        self.flags(
            cinder_endpoint_template='http://other_host:8776/v1/%(project_id)s'
        )
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEquals(
            self.fake_client_factory.client.client.management_url,
            'http://other_host:8776/v1/project_id')

    def test_get_non_existing_volume(self):
        self.assertRaises(exception.VolumeNotFound, self.api.get, self.context,
                          'nonexisting')

    def test_volume_with_image_metadata(self):
        volume = self.api.get(self.context, '5678')
        self.assert_called('GET', '/volumes/5678')
        self.assertTrue('volume_image_metadata' in volume)
        self.assertEqual(volume['volume_image_metadata'], _image_metadata)

    def test_cinder_api_insecure(self):
        # The True/False negation is awkward, but better for the client
        # to pass us insecure=True and we check verify_cert == False
        self.flags(cinder_api_insecure=True)
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEquals(
            self.fake_client_factory.client.client.verify_cert, False)

    def test_cinder_api_cacert_file(self):
        cacert = "/etc/ssl/certs/ca-certificates.crt"
        self.flags(cinder_ca_certificates_file=cacert)
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEquals(
            self.fake_client_factory.client.client.verify_cert, cacert)

    def test_cinder_http_retries(self):
        retries = 42
        self.flags(cinder_http_retries=retries)
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEquals(
            self.fake_client_factory.client.client.retries, retries)
