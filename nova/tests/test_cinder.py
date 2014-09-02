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

from cinderclient import exceptions as cinder_exception
from cinderclient.v1 import client as cinder_client_v1
from cinderclient.v2 import client as cinder_client_v2
import mock
import six.moves.urllib.parse as urlparse

from nova import context
from nova import exception
from nova import test
from nova.volume import cinder


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
        "bootable": "true"
    }
    volume.update(kwargs)
    return volume


def _stub_volume_v2(**kwargs):
    volume_v2 = {
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
    volume_v2.update(kwargs)
    return volume_v2


_image_metadata = {
    'kernel_id': 'fake',
    'ramdisk_id': 'fake'
}


class FakeHTTPClient(cinder.cinder_client.HTTPClient):

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


class FakeHTTPClientV2(cinder.cinder_client.HTTPClient):

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
        volume = {'volume': _stub_volume_v2(id='1234')}
        return (200, volume)

    def get_volumes_nonexisting(self, **kw):
        raise cinder_exception.NotFound(code=404, message='Resource not found')

    def get_volumes_5678(self, **kw):
        """Volume with image metadata."""
        volume = {'volume': _stub_volume_v2(
            id='1234',
            volume_image_metadata=_image_metadata)
        }
        return (200, volume)


class FakeCinderClient(cinder_client_v1.Client):

    def __init__(self, username, password, project_id=None, auth_url=None,
                 insecure=False, retries=None, cacert=None, timeout=None):
        super(FakeCinderClient, self).__init__(username, password,
                                               project_id=project_id,
                                               auth_url=auth_url,
                                               insecure=insecure,
                                               retries=retries,
                                               cacert=cacert,
                                               timeout=timeout)
        self.client = FakeHTTPClient(username, password, project_id, auth_url,
                                     insecure=insecure, retries=retries,
                                     cacert=cacert, timeout=timeout)
        # keep a ref to the clients callstack for factory's assert_called
        self.callstack = self.client.callstack = []


class FakeCinderClientV2(cinder_client_v2.Client):

    def __init__(self, username, password, project_id=None, auth_url=None,
                 insecure=False, retries=None, cacert=None, timeout=None):
        super(FakeCinderClientV2, self).__init__(username, password,
                                                 project_id=project_id,
                                                 auth_url=auth_url,
                                                 insecure=insecure,
                                                 retries=retries,
                                                 cacert=cacert,
                                                 timeout=timeout)
        self.client = FakeHTTPClientV2(username, password, project_id,
                                       auth_url, insecure=insecure,
                                       retries=retries, cacert=cacert,
                                       timeout=timeout)
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


class FakeClientV2Factory(object):
    """Keep a ref to the FakeClient since volume.api.cinder throws it away."""

    def __call__(self, *args, **kwargs):
        self.client = FakeCinderClientV2(*args, **kwargs)
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


fake_client_factory = FakeClientFactory()
fake_client_v2_factory = FakeClientV2Factory()


@mock.patch.object(cinder_client_v1, 'Client', fake_client_factory)
class CinderTestCase(test.NoDBTestCase):
    """Test case for cinder volume v1 api."""

    def setUp(self):
        super(CinderTestCase, self).setUp()
        catalog = [{
            "type": "volume",
            "name": "cinder",
            "endpoints": [{"publicURL": "http://localhost:8776/v1/project_id"}]
        }]
        self.context = context.RequestContext('username', 'project_id',
                                              service_catalog=catalog)
        cinder.cinderclient(self.context)

        self.api = cinder.API()

    def assert_called(self, *args, **kwargs):
        fake_client_factory.assert_called(*args, **kwargs)

    def test_context_with_catalog(self):
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            fake_client_factory.client.client.management_url,
            'http://localhost:8776/v1/project_id')

    def test_cinder_endpoint_template(self):
        self.flags(
            endpoint_template='http://other_host:8776/v1/%(project_id)s',
            group='cinder'
        )
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            fake_client_factory.client.client.management_url,
            'http://other_host:8776/v1/project_id')

    def test_get_non_existing_volume(self):
        self.assertRaises(exception.VolumeNotFound, self.api.get, self.context,
                          'nonexisting')

    def test_volume_with_image_metadata(self):
        volume = self.api.get(self.context, '5678')
        self.assert_called('GET', '/volumes/5678')
        self.assertIn('volume_image_metadata', volume)
        self.assertEqual(volume['volume_image_metadata'], _image_metadata)

    def test_cinder_api_insecure(self):
        # The True/False negation is awkward, but better for the client
        # to pass us insecure=True and we check verify_cert == False
        self.flags(api_insecure=True, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            fake_client_factory.client.client.verify_cert, False)

    def test_cinder_api_cacert_file(self):
        cacert = "/etc/ssl/certs/ca-certificates.crt"
        self.flags(ca_certificates_file=cacert, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            fake_client_factory.client.client.verify_cert, cacert)

    def test_cinder_http_retries(self):
        retries = 42
        self.flags(http_retries=retries, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            fake_client_factory.client.client.retries, retries)


@mock.patch.object(cinder_client_v2, 'Client', fake_client_v2_factory)
class CinderV2TestCase(test.NoDBTestCase):
    """Test case for cinder volume v2 api."""

    def setUp(self):
        super(CinderV2TestCase, self).setUp()
        catalog = [{
            "type": "volumev2",
            "name": "cinderv2",
            "endpoints": [{"publicURL": "http://localhost:8776/v2/project_id"}]
        }]
        cinder.CONF.set_override('catalog_info',
                                 'volumev2:cinder:publicURL', group='cinder')
        self.context = context.RequestContext('username', 'project_id',
                                              service_catalog=catalog)

        cinder.cinderclient(self.context)
        self.api = cinder.API()

    def tearDown(self):
        cinder.CONF.reset()
        super(CinderV2TestCase, self).tearDown()

    def assert_called(self, *args, **kwargs):
        fake_client_v2_factory.assert_called(*args, **kwargs)

    def test_context_with_catalog(self):
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            'http://localhost:8776/v2/project_id',
            fake_client_v2_factory.client.client.management_url)

    def test_cinder_endpoint_template(self):
        self.flags(
            endpoint_template='http://other_host:8776/v2/%(project_id)s',
            group='cinder'
        )
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(
            'http://other_host:8776/v2/project_id',
            fake_client_v2_factory.client.client.management_url)

    def test_get_non_existing_volume(self):
        self.assertRaises(exception.VolumeNotFound, self.api.get, self.context,
                          'nonexisting')

    def test_volume_with_image_metadata(self):
        volume = self.api.get(self.context, '5678')
        self.assert_called('GET', '/volumes/5678')
        self.assertIn('volume_image_metadata', volume)
        self.assertEqual(_image_metadata, volume['volume_image_metadata'])

    def test_cinder_api_insecure(self):
        # The True/False negation is awkward, but better for the client
        # to pass us insecure=True and we check verify_cert == False
        self.flags(api_insecure=True, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertFalse(fake_client_v2_factory.client.client.verify_cert)

    def test_cinder_api_cacert_file(self):
        cacert = "/etc/ssl/certs/ca-certificates.crt"
        self.flags(ca_certificates_file=cacert, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(cacert,
                         fake_client_v2_factory.client.client.verify_cert)

    def test_cinder_http_retries(self):
        retries = 42
        self.flags(http_retries=retries, group='cinder')
        self.api.get(self.context, '1234')
        self.assert_called('GET', '/volumes/1234')
        self.assertEqual(retries, fake_client_v2_factory.client.client.retries)

    def test_cinder_http_timeout(self):
        timeout = 123
        self.flags(http_timeout=timeout, group='cinder')
        self.api.get(self.context, '1234')
        self.assertEqual(timeout,
                         fake_client_v2_factory.client.client.timeout)
