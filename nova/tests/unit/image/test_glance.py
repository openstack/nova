# Copyright 2011 OpenStack Foundation
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


import datetime
from six.moves import StringIO

import cryptography
import glanceclient.exc
import mock

from oslo_service import sslutils
import six
import testtools

import nova.conf
from nova import context
from nova import exception
from nova.image import glance
from nova import test

CONF = nova.conf.CONF
NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"


class tzinfo(datetime.tzinfo):
    @staticmethod
    def utcoffset(*args, **kwargs):
        return datetime.timedelta()

NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22, tzinfo=tzinfo())


class TestConversions(test.NoDBTestCase):
    def test_convert_timestamps_to_datetimes(self):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'is_public': None,
                   'created_at': NOW_GLANCE_FORMAT,
                   'updated_at': NOW_GLANCE_FORMAT,
                   'deleted_at': NOW_GLANCE_FORMAT}
        result = glance._convert_timestamps_to_datetimes(fixture)
        self.assertEqual(result['created_at'], NOW_DATETIME)
        self.assertEqual(result['updated_at'], NOW_DATETIME)
        self.assertEqual(result['deleted_at'], NOW_DATETIME)

    def _test_extracting_missing_attributes(self, include_locations):
        # Verify behavior from glance objects that are missing attributes
        # TODO(jaypipes): Find a better way of testing this crappy
        #                 glanceclient magic object stuff.
        class MyFakeGlanceImage(object):
            def __init__(self, metadata):
                IMAGE_ATTRIBUTES = ['size', 'owner', 'id', 'created_at',
                                    'updated_at', 'status', 'min_disk',
                                    'min_ram', 'is_public']
                raw = dict.fromkeys(IMAGE_ATTRIBUTES)
                raw.update(metadata)
                self.__dict__['raw'] = raw

            def __getattr__(self, key):
                try:
                    return self.__dict__['raw'][key]
                except KeyError:
                    raise AttributeError(key)

            def __setattr__(self, key, value):
                try:
                    self.__dict__['raw'][key] = value
                except KeyError:
                    raise AttributeError(key)

        metadata = {
            'id': 1,
            'created_at': NOW_DATETIME,
            'updated_at': NOW_DATETIME,
        }
        image = MyFakeGlanceImage(metadata)
        observed = glance._extract_attributes(
            image, include_locations=include_locations)
        expected = {
            'id': 1,
            'name': None,
            'is_public': None,
            'size': 0,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': NOW_DATETIME,
            'updated_at': NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None
        }
        if include_locations:
            expected['locations'] = None
            expected['direct_url'] = None
        self.assertEqual(expected, observed)

    def test_extracting_missing_attributes_include_locations(self):
        self._test_extracting_missing_attributes(include_locations=True)

    def test_extracting_missing_attributes_exclude_locations(self):
        self._test_extracting_missing_attributes(include_locations=False)


class TestExceptionTranslations(test.NoDBTestCase):

    def test_client_forbidden_to_imagenotauthed(self):
        in_exc = glanceclient.exc.Forbidden('123')
        out_exc = glance._translate_image_exception('123', in_exc)
        self.assertIsInstance(out_exc, exception.ImageNotAuthorized)

    def test_client_httpforbidden_converts_to_imagenotauthed(self):
        in_exc = glanceclient.exc.HTTPForbidden('123')
        out_exc = glance._translate_image_exception('123', in_exc)
        self.assertIsInstance(out_exc, exception.ImageNotAuthorized)

    def test_client_notfound_converts_to_imagenotfound(self):
        in_exc = glanceclient.exc.NotFound('123')
        out_exc = glance._translate_image_exception('123', in_exc)
        self.assertIsInstance(out_exc, exception.ImageNotFound)

    def test_client_httpnotfound_converts_to_imagenotfound(self):
        in_exc = glanceclient.exc.HTTPNotFound('123')
        out_exc = glance._translate_image_exception('123', in_exc)
        self.assertIsInstance(out_exc, exception.ImageNotFound)


class TestGlanceSerializer(test.NoDBTestCase):
    def test_serialize(self):
        metadata = {'name': 'image1',
                    'is_public': True,
                    'foo': 'bar',
                    'properties': {
                        'prop1': 'propvalue1',
                        'mappings': [
                            {'virtual': 'aaa',
                             'device': 'bbb'},
                            {'virtual': 'xxx',
                             'device': 'yyy'}],
                        'block_device_mapping': [
                            {'virtual_device': 'fake',
                             'device_name': '/dev/fake'},
                            {'virtual_device': 'ephemeral0',
                             'device_name': '/dev/fake0'}]}}
        # NOTE(tdurakov): Assertion of serialized objects won't work
        # during using of random PYTHONHASHSEED. Assertion of
        # serialized/deserialized object and initial one is enough
        converted = glance._convert_to_string(metadata)
        self.assertEqual(glance._convert_from_string(converted), metadata)


class TestGetImageService(test.NoDBTestCase):
    @mock.patch.object(glance.GlanceClientWrapper, '__init__',
                       return_value=None)
    def test_get_remote_service_from_id(self, gcwi_mocked):
        id_or_uri = '123'
        _ignored, image_id = glance.get_remote_image_service(
                mock.sentinel.ctx, id_or_uri)
        self.assertEqual(id_or_uri, image_id)
        gcwi_mocked.assert_called_once_with()

    @mock.patch.object(glance.GlanceClientWrapper, '__init__',
                       return_value=None)
    def test_get_remote_service_from_href(self, gcwi_mocked):
        id_or_uri = 'http://127.0.0.1/v1/images/123'
        _ignored, image_id = glance.get_remote_image_service(
                mock.sentinel.ctx, id_or_uri)
        self.assertEqual('123', image_id)
        gcwi_mocked.assert_called_once_with(context=mock.sentinel.ctx,
                                            endpoint='http://127.0.0.1')


class TestCreateGlanceClient(test.NoDBTestCase):
    @mock.patch('glanceclient.Client')
    def test_headers_passed_glanceclient(self, init_mock):
        self.flags(auth_strategy='keystone')
        auth_token = 'token'
        ctx = context.RequestContext('fake', 'fake', auth_token=auth_token)

        expected_endpoint = 'http://host4:9295'
        expected_params = {
            'identity_headers': {
                'X-Auth-Token': 'token',
                'X-User-Id': 'fake',
                'X-Roles': '',
                'X-Tenant-Id': 'fake',
                'X-Identity-Status': 'Confirmed'
            }
        }
        glance._glanceclient_from_endpoint(ctx, expected_endpoint)
        init_mock.assert_called_once_with('1', expected_endpoint,
                                          **expected_params)

        # Test the version is properly passed to glanceclient.
        init_mock.reset_mock()

        expected_endpoint = 'http://host4:9295'
        expected_params = {
            'identity_headers': {
                'X-Auth-Token': 'token',
                'X-User-Id': 'fake',
                'X-Roles': '',
                'X-Tenant-Id': 'fake',
                'X-Identity-Status': 'Confirmed'
            }
        }
        glance._glanceclient_from_endpoint(ctx, expected_endpoint, version=2)
        init_mock.assert_called_once_with('2', expected_endpoint,
                                          **expected_params)

        # Test that the IPv6 bracketization adapts the endpoint properly.
        init_mock.reset_mock()

        expected_endpoint = 'http://[host4]:9295'
        glance._glanceclient_from_endpoint(ctx, expected_endpoint)
        init_mock.assert_called_once_with('1', expected_endpoint,
                                          **expected_params)


class TestGlanceClientWrapper(test.NoDBTestCase):
    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_static_client_without_retries(self, create_client_mock,
                                           sleep_mock):
        client_mock = mock.MagicMock()
        images_mock = mock.MagicMock()
        images_mock.get.side_effect = glanceclient.exc.ServiceUnavailable
        type(client_mock).images = mock.PropertyMock(return_value=images_mock)
        create_client_mock.return_value = client_mock
        self.flags(num_retries=0, group='glance')

        ctx = context.RequestContext('fake', 'fake')
        host = 'host4'
        port = 9295
        endpoint = 'http://%s:%s' % (host, port)
        client = glance.GlanceClientWrapper(context=ctx, endpoint=endpoint)
        create_client_mock.assert_called_once_with(ctx, mock.ANY, 1)
        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctx, 1, 'get', 'meow')
        self.assertFalse(sleep_mock.called)

    @mock.patch('nova.image.glance.LOG')
    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_static_client_with_retries_negative(self, create_client_mock,
                                                 sleep_mock, mock_log):
        client_mock = mock.Mock(spec=glanceclient.Client)
        images_mock = mock.Mock()
        images_mock.get.side_effect = glanceclient.exc.ServiceUnavailable
        client_mock.images = images_mock
        create_client_mock.return_value = client_mock
        self.flags(num_retries=-1, group='glance')

        ctx = context.RequestContext('fake', 'fake')
        host = 'host4'
        port = 9295
        endpoint = 'http://%s:%s' % (host, port)

        client = glance.GlanceClientWrapper(context=ctx, endpoint=endpoint)

        create_client_mock.assert_called_once_with(ctx, mock.ANY, 1)
        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctx, 1, 'get', 'meow')
        self.assertTrue(mock_log.warning.called)
        msg = mock_log.warning.call_args_list[0]
        self.assertIn('Treating negative config value', msg[0][0])
        self.assertFalse(sleep_mock.called)

    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_static_client_with_retries(self, create_client_mock,
                                        sleep_mock):
        self.flags(num_retries=1, group='glance')
        client_mock = mock.MagicMock()
        images_mock = mock.MagicMock()
        images_mock.get.side_effect = [
            glanceclient.exc.ServiceUnavailable,
            None
        ]
        type(client_mock).images = mock.PropertyMock(return_value=images_mock)
        create_client_mock.return_value = client_mock

        ctx = context.RequestContext('fake', 'fake')
        host = 'host4'
        port = 9295
        endpoint = 'http://%s:%s' % (host, port)

        client = glance.GlanceClientWrapper(context=ctx, endpoint=endpoint)
        client.call(ctx, 1, 'get', 'meow')
        sleep_mock.assert_called_once_with(1)

    @mock.patch('random.shuffle')
    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_default_client_without_retries(self, create_client_mock,
                                            sleep_mock, shuffle_mock):
        api_servers = [
            'host1:9292',
            'https://host2:9293',
            'http://host3:9294'
        ]
        client_mock = mock.MagicMock()
        images_mock = mock.MagicMock()
        images_mock.get.side_effect = glanceclient.exc.ServiceUnavailable
        type(client_mock).images = mock.PropertyMock(return_value=images_mock)
        create_client_mock.return_value = client_mock

        shuffle_mock.return_value = api_servers
        self.flags(num_retries=0, group='glance')
        self.flags(api_servers=api_servers, group='glance')

        # Here we are testing the behaviour that calling client.call() twice
        # when there are no retries will cycle through the api_servers and not
        # sleep (which would be an indication of a retry)
        ctx = context.RequestContext('fake', 'fake')

        client = glance.GlanceClientWrapper()
        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctx, 1, 'get', 'meow')
        self.assertEqual(str(client.api_server), "http://host1:9292")
        self.assertFalse(sleep_mock.called)

        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctx, 1, 'get', 'meow')
        self.assertEqual(str(client.api_server), "https://host2:9293")
        self.assertFalse(sleep_mock.called)

    @mock.patch('random.shuffle')
    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_default_client_with_retries(self, create_client_mock,
                                         sleep_mock, shuffle_mock):
        api_servers = [
            'host1:9292',
            'https://host2:9293',
            'http://host3:9294'
        ]
        client_mock = mock.MagicMock()
        images_mock = mock.MagicMock()
        images_mock.get.side_effect = [
            glanceclient.exc.ServiceUnavailable,
            None
        ]
        type(client_mock).images = mock.PropertyMock(return_value=images_mock)
        create_client_mock.return_value = client_mock

        self.flags(num_retries=1, group='glance')
        self.flags(api_servers=api_servers, group='glance')

        ctx = context.RequestContext('fake', 'fake')

        # And here we're testing that if num_retries is not 0, then we attempt
        # to retry the same connection action against the next client.

        client = glance.GlanceClientWrapper()
        client.call(ctx, 1, 'get', 'meow')
        self.assertEqual(str(client.api_server), "https://host2:9293")
        sleep_mock.assert_called_once_with(1)

    @mock.patch('random.shuffle')
    @mock.patch('time.sleep')
    @mock.patch('nova.image.glance._glanceclient_from_endpoint')
    def test_retry_works_with_generators(self, create_client_mock,
                                         sleep_mock, shuffle_mock):
        def some_generator(exception):
            if exception:
                raise glanceclient.exc.CommunicationError('Boom!')
            yield 'something'

        api_servers = [
            'https://host2:9292',
            'https://host2:9293',
            'http://host3:9294'
        ]
        client_mock = mock.MagicMock()
        images_mock = mock.MagicMock()
        images_mock.list.side_effect = [
            some_generator(exception=True),
            some_generator(exception=False),
        ]
        type(client_mock).images = mock.PropertyMock(return_value=images_mock)
        create_client_mock.return_value = client_mock

        self.flags(num_retries=1, group='glance')
        self.flags(api_servers=api_servers, group='glance')

        ctx = context.RequestContext('fake', 'fake')
        client = glance.GlanceClientWrapper()
        client.call(ctx, 1, 'list', 'meow')
        sleep_mock.assert_called_once_with(1)
        self.assertEqual(str(client.api_server), 'https://host2:9293')

    @mock.patch('oslo_service.sslutils.is_enabled')
    @mock.patch('glanceclient.Client')
    def test_create_glance_client_with_ssl(self, client_mock,
                                           ssl_enable_mock):
        sslutils.register_opts(CONF)
        self.flags(ca_file='foo.cert', cert_file='bar.cert',
                   key_file='wut.key', group='ssl')
        ctxt = mock.sentinel.ctx
        glance._glanceclient_from_endpoint(ctxt, 'https://host4:9295')
        client_mock.assert_called_once_with(
            '1', 'https://host4:9295', insecure=False, ssl_compression=False,
            cert_file='bar.cert', key_file='wut.key', cacert='foo.cert',
            identity_headers=mock.ANY)

    @mock.patch.object(glanceclient.common.http.HTTPClient, 'get')
    def test_determine_curr_major_version(self, http_client_mock):
        result = ("http://host1:9292/v2/", {'versions': [
            {'status': 'CURRENT', 'id': 'v2.3'},
            {'status': 'SUPPORTED', 'id': 'v1.0'}]})
        http_client_mock.return_value = result
        maj_ver = glance._determine_curr_major_version('http://host1:9292')
        self.assertEqual(2, maj_ver)

    @mock.patch.object(glanceclient.common.http.HTTPClient, 'get')
    def test_determine_curr_major_version_invalid(self, http_client_mock):
        result = ("http://host1:9292/v2/", "Invalid String")
        http_client_mock.return_value = result
        curr_major_version = glance._determine_curr_major_version('abc')
        self.assertIsNone(curr_major_version)

    @mock.patch.object(glanceclient.common.http.HTTPClient, 'get')
    def test_determine_curr_major_version_unsupported(self, http_client_mock):
        result = ("http://host1:9292/v2/", {'versions': [
            {'status': 'CURRENT', 'id': 'v666.0'},
            {'status': 'SUPPORTED', 'id': 'v1.0'}]})
        http_client_mock.return_value = result
        maj_ver = glance._determine_curr_major_version('http://host1:9292')
        self.assertIsNone(maj_ver)


class TestDownloadNoDirectUri(test.NoDBTestCase):

    """Tests the download method of the GlanceImageService when the
    default of not allowing direct URI transfers is set.
    """

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_no_data_no_dest_path(self, show_mock, open_mock):
        client = mock.MagicMock()
        client.call.return_value = mock.sentinel.image_chunks
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id)

        self.assertFalse(show_mock.called)
        self.assertFalse(open_mock.called)
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        self.assertEqual(mock.sentinel.image_chunks, res)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_data_no_dest_path(self, show_mock, open_mock):
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        data = mock.MagicMock()
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id, data=data)

        self.assertFalse(show_mock.called)
        self.assertFalse(open_mock.called)
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        self.assertIsNone(res)
        data.write.assert_has_calls(
                [
                    mock.call(1),
                    mock.call(2),
                    mock.call(3)
                ]
        )
        self.assertFalse(data.close.called)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_no_data_dest_path(self, show_mock, open_mock):
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        writer = mock.MagicMock()
        open_mock.return_value = writer
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id,
                               dst_path=mock.sentinel.dst_path)

        self.assertFalse(show_mock.called)
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        open_mock.assert_called_once_with(mock.sentinel.dst_path, 'wb')
        self.assertIsNone(res)
        writer.write.assert_has_calls(
                [
                    mock.call(1),
                    mock.call(2),
                    mock.call(3)
                ]
        )
        writer.close.assert_called_once_with()

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_data_dest_path(self, show_mock, open_mock):
        # NOTE(jaypipes): This really shouldn't be allowed, but because of the
        # horrible design of the download() method in GlanceImageService, no
        # error is raised, and the dst_path is ignored...
        # #TODO(jaypipes): Fix the aforementioned horrible design of
        # the download() method.
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        data = mock.MagicMock()
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id, data=data)

        self.assertFalse(show_mock.called)
        self.assertFalse(open_mock.called)
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        self.assertIsNone(res)
        data.write.assert_has_calls(
                [
                    mock.call(1),
                    mock.call(2),
                    mock.call(3)
                ]
        )
        self.assertFalse(data.close.called)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_data_dest_path_write_fails(self, show_mock, open_mock):
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)

        # NOTE(mikal): data is a file like object, which in our case always
        # raises an exception when we attempt to write to the file.
        class FakeDiskException(Exception):
            pass

        class Exceptionator(StringIO):
            def write(self, _):
                raise FakeDiskException('Disk full!')

        self.assertRaises(FakeDiskException, service.download, ctx,
                          mock.sentinel.image_id, data=Exceptionator())

    @mock.patch('nova.image.glance.GlanceImageService._get_transfer_module')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_direct_file_uri(self, show_mock, get_tran_mock):
        self.flags(allowed_direct_url_schemes=['file'], group='glance')
        show_mock.return_value = {
            'locations': [
                {
                    'url': 'file:///files/image',
                    'metadata': mock.sentinel.loc_meta
                }
            ]
        }
        tran_mod = mock.MagicMock()
        get_tran_mock.return_value = tran_mod
        client = mock.MagicMock()
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id,
                               dst_path=mock.sentinel.dst_path)

        self.assertIsNone(res)
        self.assertFalse(client.call.called)
        show_mock.assert_called_once_with(ctx,
                                          mock.sentinel.image_id,
                                          include_locations=True)
        get_tran_mock.assert_called_once_with('file')
        tran_mod.download.assert_called_once_with(ctx, mock.ANY,
                                                  mock.sentinel.dst_path,
                                                  mock.sentinel.loc_meta)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService._get_transfer_module')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_direct_exception_fallback(self, show_mock,
                                                get_tran_mock,
                                                open_mock):
        # Test that we fall back to downloading to the dst_path
        # if the download method of the transfer module raised
        # an exception.
        self.flags(allowed_direct_url_schemes=['file'], group='glance')
        show_mock.return_value = {
            'locations': [
                {
                    'url': 'file:///files/image',
                    'metadata': mock.sentinel.loc_meta
                }
            ]
        }
        tran_mod = mock.MagicMock()
        tran_mod.download.side_effect = Exception
        get_tran_mock.return_value = tran_mod
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        writer = mock.MagicMock()
        open_mock.return_value = writer
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id,
                               dst_path=mock.sentinel.dst_path)

        self.assertIsNone(res)
        show_mock.assert_called_once_with(ctx,
                                          mock.sentinel.image_id,
                                          include_locations=True)
        get_tran_mock.assert_called_once_with('file')
        tran_mod.download.assert_called_once_with(ctx, mock.ANY,
                                                  mock.sentinel.dst_path,
                                                  mock.sentinel.loc_meta)
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        # NOTE(jaypipes): log messages call open() in part of the
        # download path, so here, we just check that the last open()
        # call was done for the dst_path file descriptor.
        open_mock.assert_called_with(mock.sentinel.dst_path, 'wb')
        self.assertIsNone(res)
        writer.write.assert_has_calls(
                [
                    mock.call(1),
                    mock.call(2),
                    mock.call(3)
                ]
        )

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.GlanceImageService._get_transfer_module')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_direct_no_mod_fallback(self, show_mock,
                                              get_tran_mock,
                                              open_mock):
        # Test that we fall back to downloading to the dst_path
        # if no appropriate transfer module is found...
        # an exception.
        self.flags(allowed_direct_url_schemes=['funky'], group='glance')
        show_mock.return_value = {
            'locations': [
                {
                    'url': 'file:///files/image',
                    'metadata': mock.sentinel.loc_meta
                }
            ]
        }
        get_tran_mock.return_value = None
        client = mock.MagicMock()
        client.call.return_value = [1, 2, 3]
        ctx = mock.sentinel.ctx
        writer = mock.MagicMock()
        open_mock.return_value = writer
        service = glance.GlanceImageService(client)
        res = service.download(ctx, mock.sentinel.image_id,
                               dst_path=mock.sentinel.dst_path)

        self.assertIsNone(res)
        show_mock.assert_called_once_with(ctx,
                                          mock.sentinel.image_id,
                                          include_locations=True)
        get_tran_mock.assert_called_once_with('file')
        client.call.assert_called_once_with(ctx, 1, 'data',
                                            mock.sentinel.image_id)
        # NOTE(jaypipes): log messages call open() in part of the
        # download path, so here, we just check that the last open()
        # call was done for the dst_path file descriptor.
        open_mock.assert_called_with(mock.sentinel.dst_path, 'wb')
        self.assertIsNone(res)
        writer.write.assert_has_calls(
                [
                    mock.call(1),
                    mock.call(2),
                    mock.call(3)
                ]
        )
        writer.close.assert_called_once_with()


class TestDownloadSignatureVerification(test.NoDBTestCase):

    class MockVerifier(object):
        def update(self, data):
            return

        def verify(self):
            return True

    class BadVerifier(object):
        def update(self, data):
            return

        def verify(self):
            raise cryptography.exceptions.InvalidSignature(
                'Invalid signature.'
            )

    def setUp(self):
        super(TestDownloadSignatureVerification, self).setUp()
        self.flags(verify_glance_signatures=True, group='glance')
        self.fake_img_props = {
            'properties': {
                'img_signature': 'signature',
                'img_signature_hash_method': 'SHA-224',
                'img_signature_certificate_uuid': 'uuid',
                'img_signature_key_type': 'RSA-PSS',
            }
        }
        self.fake_img_data = ['A' * 256, 'B' * 256]
        client = mock.MagicMock()
        client.call.return_value = self.fake_img_data
        self.service = glance.GlanceImageService(client)

    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    @mock.patch('nova.signature_utils.get_verifier')
    def test_download_with_signature_verification(self,
                                                  mock_get_verifier,
                                                  mock_show,
                                                  mock_log):
        mock_get_verifier.return_value = self.MockVerifier()
        mock_show.return_value = self.fake_img_props
        res = self.service.download(context=None, image_id=None,
                                    data=None, dst_path=None)
        self.assertEqual(self.fake_img_data, res)
        mock_get_verifier.assert_called_once_with(None, 'uuid', 'SHA-224',
                                                  'signature', 'RSA-PSS')
        mock_log.info.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    @mock.patch('nova.signature_utils.get_verifier')
    def test_download_dst_path_signature_verification(self,
                                                      mock_get_verifier,
                                                      mock_show,
                                                      mock_log,
                                                      mock_open):
        mock_get_verifier.return_value = self.MockVerifier()
        mock_show.return_value = self.fake_img_props
        mock_dest = mock.MagicMock()
        fake_path = 'FAKE_PATH'
        mock_open.return_value = mock_dest
        self.service.download(context=None, image_id=None,
                              data=None, dst_path=fake_path)
        mock_get_verifier.assert_called_once_with(None, 'uuid', 'SHA-224',
                                                  'signature', 'RSA-PSS')
        mock_log.info.assert_called_once_with(mock.ANY, mock.ANY)
        self.assertEqual(len(self.fake_img_data), mock_dest.write.call_count)
        self.assertTrue(mock_dest.close.called)

    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    @mock.patch('nova.signature_utils.get_verifier')
    def test_download_with_get_verifier_failure(self,
                                                mock_get_verifier,
                                                mock_show,
                                                mock_log):
        mock_get_verifier.side_effect = exception.SignatureVerificationError(
                                            reason='Signature verification '
                                                   'failed.'
                                        )
        mock_show.return_value = self.fake_img_props
        self.assertRaises(exception.SignatureVerificationError,
                          self.service.download,
                          context=None, image_id=None,
                          data=None, dst_path=None)
        mock_log.error.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    @mock.patch('nova.signature_utils.get_verifier')
    def test_download_with_invalid_signature(self,
                                             mock_get_verifier,
                                             mock_show,
                                             mock_log):
        mock_get_verifier.return_value = self.BadVerifier()
        mock_show.return_value = self.fake_img_props
        self.assertRaises(cryptography.exceptions.InvalidSignature,
                          self.service.download,
                          context=None, image_id=None,
                          data=None, dst_path=None)
        mock_log.error.assert_called_once_with(mock.ANY, mock.ANY)

    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_missing_signature_metadata(self,
                                                 mock_show,
                                                 mock_log):
        mock_show.return_value = {'properties': {}}
        self.assertRaisesRegex(exception.SignatureVerificationError,
                               'Required image properties for signature '
                               'verification do not exist. Cannot verify '
                               'signature. Missing property: .*',
                               self.service.download,
                               context=None, image_id=None,
                               data=None, dst_path=None)

    @mock.patch.object(six.moves.builtins, 'open')
    @mock.patch('nova.signature_utils.get_verifier')
    @mock.patch('nova.image.glance.LOG')
    @mock.patch('nova.image.glance.GlanceImageService.show')
    def test_download_dst_path_signature_fail(self, mock_show,
                                              mock_log, mock_get_verifier,
                                              mock_open):
        mock_get_verifier.return_value = self.BadVerifier()
        mock_dest = mock.MagicMock()
        fake_path = 'FAKE_PATH'
        mock_open.return_value = mock_dest
        mock_show.return_value = self.fake_img_props
        self.assertRaises(cryptography.exceptions.InvalidSignature,
                          self.service.download,
                          context=None, image_id=None,
                          data=None, dst_path=fake_path)
        mock_log.error.assert_called_once_with(mock.ANY, mock.ANY)
        mock_open.assert_called_once_with(fake_path, 'wb')
        mock_dest.truncate.assert_called_once_with(0)
        self.assertTrue(mock_dest.close.called)


class TestIsImageAvailable(test.NoDBTestCase):
    """Tests the internal _is_image_available function."""

    class ImageSpecV2(object):
        visibility = None
        properties = None

    class ImageSpecV1(object):
        is_public = None
        properties = None

    def test_auth_token_override(self):
        ctx = mock.MagicMock(auth_token=True)
        img = mock.MagicMock()

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)
        self.assertFalse(img.called)

    def test_admin_override(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=True)
        img = mock.MagicMock()

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)
        self.assertFalse(img.called)

    def test_v2_visibility(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False)
        # We emulate warlock validation that throws an AttributeError
        # if you try to call is_public on an image model returned by
        # a call to V2 image.get(). Here, the ImageSpecV2 does not have
        # an is_public attribute and MagicMock will throw an AttributeError.
        img = mock.MagicMock(visibility='PUBLIC',
                             spec=TestIsImageAvailable.ImageSpecV2)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

    def test_v1_is_public(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False)
        img = mock.MagicMock(is_public=True,
                             spec=TestIsImageAvailable.ImageSpecV1)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

    def test_project_is_owner(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False,
                             project_id='123')
        props = {
            'owner_id': '123'
        }
        img = mock.MagicMock(visibility='private', properties=props,
                             spec=TestIsImageAvailable.ImageSpecV2)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

        ctx.reset_mock()
        img = mock.MagicMock(is_public=False, properties=props,
                             spec=TestIsImageAvailable.ImageSpecV1)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

    def test_project_context_matches_project_prop(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False,
                             project_id='123')
        props = {
            'project_id': '123'
        }
        img = mock.MagicMock(visibility='private', properties=props,
                             spec=TestIsImageAvailable.ImageSpecV2)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

        ctx.reset_mock()
        img = mock.MagicMock(is_public=False, properties=props,
                             spec=TestIsImageAvailable.ImageSpecV1)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

    def test_no_user_in_props(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False,
                             project_id='123')
        props = {
        }
        img = mock.MagicMock(visibility='private', properties=props,
                             spec=TestIsImageAvailable.ImageSpecV2)

        res = glance._is_image_available(ctx, img)
        self.assertFalse(res)

        ctx.reset_mock()
        img = mock.MagicMock(is_public=False, properties=props,
                             spec=TestIsImageAvailable.ImageSpecV1)

        res = glance._is_image_available(ctx, img)
        self.assertFalse(res)

    def test_user_matches_context(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=False,
                             user_id='123')
        props = {
            'user_id': '123'
        }
        img = mock.MagicMock(visibility='private', properties=props,
                             spec=TestIsImageAvailable.ImageSpecV2)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)

        ctx.reset_mock()
        img = mock.MagicMock(is_public=False, properties=props,
                             spec=TestIsImageAvailable.ImageSpecV1)

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)


class TestShow(test.NoDBTestCase):

    """Tests the show method of the GlanceImageService."""

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_show_success(self, is_avail_mock, trans_from_mock):
        is_avail_mock.return_value = True
        trans_from_mock.return_value = {'mock': mock.sentinel.trans_from}
        client = mock.MagicMock()
        client.call.return_value = {}
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        info = service.show(ctx, mock.sentinel.image_id)

        client.call.assert_called_once_with(ctx, 1, 'get',
                                            mock.sentinel.image_id)
        is_avail_mock.assert_called_once_with(ctx, {})
        trans_from_mock.assert_called_once_with({}, include_locations=False)
        self.assertIn('mock', info)
        self.assertEqual(mock.sentinel.trans_from, info['mock'])

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_show_not_available(self, is_avail_mock, trans_from_mock):
        is_avail_mock.return_value = False
        client = mock.MagicMock()
        client.call.return_value = mock.sentinel.images_0
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)

        with testtools.ExpectedException(exception.ImageNotFound):
            service.show(ctx, mock.sentinel.image_id)

        client.call.assert_called_once_with(ctx, 1, 'get',
                                            mock.sentinel.image_id)
        is_avail_mock.assert_called_once_with(ctx, mock.sentinel.images_0)
        self.assertFalse(trans_from_mock.called)

    @mock.patch('nova.image.glance._reraise_translated_image_exception')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_show_client_failure(self, is_avail_mock, trans_from_mock,
                                 reraise_mock):
        raised = exception.ImageNotAuthorized(image_id=123)
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.Forbidden
        ctx = mock.sentinel.ctx
        reraise_mock.side_effect = raised
        service = glance.GlanceImageService(client)

        with testtools.ExpectedException(exception.ImageNotAuthorized):
            service.show(ctx, mock.sentinel.image_id)
            client.call.assert_called_once_with(ctx, 1, 'get',
                                                mock.sentinel.image_id)
            self.assertFalse(is_avail_mock.called)
            self.assertFalse(trans_from_mock.called)
            reraise_mock.assert_called_once_with(mock.sentinel.image_id)

    @mock.patch('nova.image.glance._is_image_available')
    def test_show_queued_image_without_some_attrs(self, is_avail_mock):
        is_avail_mock.return_value = True
        client = mock.MagicMock()

        # fake image cls without disk_format, container_format, name attributes
        class fake_image_cls(dict):
            id = 'b31aa5dd-f07a-4748-8f15-398346887584'
            deleted = False
            protected = False
            min_disk = 0
            created_at = '2014-05-20T08:16:48'
            size = 0
            status = 'queued'
            is_public = False
            min_ram = 0
            owner = '980ec4870033453ead65c0470a78b8a8'
            updated_at = '2014-05-20T08:16:48'
        glance_image = fake_image_cls()
        client.call.return_value = glance_image
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        image_info = service.show(ctx, glance_image.id)
        client.call.assert_called_once_with(ctx, 1, 'get',
                                            glance_image.id)
        NOVA_IMAGE_ATTRIBUTES = set(['size', 'disk_format', 'owner',
                                     'container_format', 'status', 'id',
                                     'name', 'created_at', 'updated_at',
                                     'deleted', 'deleted_at', 'checksum',
                                     'min_disk', 'min_ram', 'is_public',
                                     'properties'])

        self.assertEqual(NOVA_IMAGE_ATTRIBUTES, set(image_info.keys()))

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_include_locations_success(self, avail_mock, trans_from_mock):
        locations = [mock.sentinel.loc1]
        avail_mock.return_value = True
        trans_from_mock.return_value = {'locations': locations}

        client = mock.Mock()
        client.call.return_value = mock.sentinel.image
        service = glance.GlanceImageService(client)
        ctx = mock.sentinel.ctx
        image_id = mock.sentinel.image_id
        info = service.show(ctx, image_id, include_locations=True)

        client.call.assert_called_once_with(ctx, 2, 'get', image_id)
        avail_mock.assert_called_once_with(ctx, mock.sentinel.image)
        trans_from_mock.assert_called_once_with(mock.sentinel.image,
                                                include_locations=True)
        self.assertIn('locations', info)
        self.assertEqual(locations, info['locations'])

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_include_direct_uri_success(self, avail_mock, trans_from_mock):
        locations = [mock.sentinel.loc1]
        avail_mock.return_value = True
        trans_from_mock.return_value = {'locations': locations,
                                        'direct_uri': mock.sentinel.duri}

        client = mock.Mock()
        client.call.return_value = mock.sentinel.image
        service = glance.GlanceImageService(client)
        ctx = mock.sentinel.ctx
        image_id = mock.sentinel.image_id
        info = service.show(ctx, image_id, include_locations=True)

        client.call.assert_called_once_with(ctx, 2, 'get', image_id)
        expected = locations
        expected.append({'url': mock.sentinel.duri, 'metadata': {}})
        self.assertIn('locations', info)
        self.assertEqual(expected, info['locations'])

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_do_not_show_deleted_images(self, is_avail_mock, trans_from_mock):
        class fake_image_cls(dict):
            id = 'b31aa5dd-f07a-4748-8f15-398346887584'
            deleted = True

        glance_image = fake_image_cls()
        client = mock.MagicMock()
        client.call.return_value = glance_image
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)

        with testtools.ExpectedException(exception.ImageNotFound):
            service.show(ctx, glance_image.id, show_deleted=False)

        client.call.assert_called_once_with(ctx, 1, 'get',
                                            glance_image.id)
        self.assertFalse(is_avail_mock.called)
        self.assertFalse(trans_from_mock.called)


class TestDetail(test.NoDBTestCase):

    """Tests the detail method of the GlanceImageService."""

    @mock.patch('nova.image.glance._extract_query_params')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_success_available(self, is_avail_mock, trans_from_mock,
                                      ext_query_mock):
        params = {}
        is_avail_mock.return_value = True
        ext_query_mock.return_value = params
        trans_from_mock.return_value = mock.sentinel.trans_from
        client = mock.MagicMock()
        client.call.return_value = [mock.sentinel.images_0]
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        images = service.detail(ctx, **params)

        client.call.assert_called_once_with(ctx, 1, 'list')
        is_avail_mock.assert_called_once_with(ctx, mock.sentinel.images_0)
        trans_from_mock.assert_called_once_with(mock.sentinel.images_0)
        self.assertEqual([mock.sentinel.trans_from], images)

    @mock.patch('nova.image.glance._extract_query_params')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_success_unavailable(self, is_avail_mock, trans_from_mock,
                                        ext_query_mock):
        params = {}
        is_avail_mock.return_value = False
        ext_query_mock.return_value = params
        trans_from_mock.return_value = mock.sentinel.trans_from
        client = mock.MagicMock()
        client.call.return_value = [mock.sentinel.images_0]
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        images = service.detail(ctx, **params)

        client.call.assert_called_once_with(ctx, 1, 'list')
        is_avail_mock.assert_called_once_with(ctx, mock.sentinel.images_0)
        self.assertFalse(trans_from_mock.called)
        self.assertEqual([], images)

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_params_passed(self, is_avail_mock, _trans_from_mock):
        client = mock.MagicMock()
        client.call.return_value = [mock.sentinel.images_0]
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        service.detail(ctx, page_size=5, limit=10)

        expected_filters = {
            'is_public': 'none'
        }
        client.call.assert_called_once_with(ctx, 1, 'list',
                                            filters=expected_filters,
                                            page_size=5,
                                            limit=10)

    @mock.patch('nova.image.glance._reraise_translated_exception')
    @mock.patch('nova.image.glance._extract_query_params')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_client_failure(self, is_avail_mock, trans_from_mock,
                                   ext_query_mock, reraise_mock):
        params = {}
        ext_query_mock.return_value = params
        raised = exception.Forbidden()
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.Forbidden
        ctx = mock.sentinel.ctx
        reraise_mock.side_effect = raised
        service = glance.GlanceImageService(client)

        with testtools.ExpectedException(exception.Forbidden):
            service.detail(ctx, **params)

        client.call.assert_called_once_with(ctx, 1, 'list')
        self.assertFalse(is_avail_mock.called)
        self.assertFalse(trans_from_mock.called)
        reraise_mock.assert_called_once_with()


class TestCreate(test.NoDBTestCase):

    """Tests the create method of the GlanceImageService."""

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._translate_to_glance')
    def test_create_success(self, trans_to_mock, trans_from_mock):
        translated = {
            'image_id': mock.sentinel.image_id
        }
        trans_to_mock.return_value = translated
        trans_from_mock.return_value = mock.sentinel.trans_from
        image_mock = mock.MagicMock(spec=dict)
        client = mock.MagicMock()
        client.call.return_value = mock.sentinel.image_meta
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        image_meta = service.create(ctx, image_mock)

        trans_to_mock.assert_called_once_with(image_mock)
        client.call.assert_called_once_with(ctx, 1, 'create',
                                            image_id=mock.sentinel.image_id)
        trans_from_mock.assert_called_once_with(mock.sentinel.image_meta)

        self.assertEqual(mock.sentinel.trans_from, image_meta)

        # Now verify that if we supply image data to the call,
        # that the client is also called with the data kwarg
        client.reset_mock()
        service.create(ctx, image_mock, data=mock.sentinel.data)

        client.call.assert_called_once_with(ctx, 1, 'create',
                                            image_id=mock.sentinel.image_id,
                                            data=mock.sentinel.data)

    @mock.patch('nova.image.glance._reraise_translated_exception')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._translate_to_glance')
    def test_create_client_failure(self, trans_to_mock, trans_from_mock,
                                   reraise_mock):
        translated = {}
        trans_to_mock.return_value = translated
        image_mock = mock.MagicMock(spec=dict)
        raised = exception.Invalid()
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.BadRequest
        ctx = mock.sentinel.ctx
        reraise_mock.side_effect = raised
        service = glance.GlanceImageService(client)

        self.assertRaises(exception.Invalid, service.create, ctx, image_mock)
        trans_to_mock.assert_called_once_with(image_mock)
        self.assertFalse(trans_from_mock.called)


class TestUpdate(test.NoDBTestCase):

    """Tests the update method of the GlanceImageService."""

    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._translate_to_glance')
    def test_update_success(self, trans_to_mock, trans_from_mock):
        translated = {
            'id': mock.sentinel.image_id,
            'name': mock.sentinel.name
        }
        trans_to_mock.return_value = translated
        trans_from_mock.return_value = mock.sentinel.trans_from
        image_mock = mock.MagicMock(spec=dict)
        client = mock.MagicMock()
        client.call.return_value = mock.sentinel.image_meta
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        image_meta = service.update(ctx, mock.sentinel.image_id, image_mock)

        trans_to_mock.assert_called_once_with(image_mock)
        # Verify that the 'id' element has been removed as a kwarg to
        # the call to glanceclient's update (since the image ID is
        # supplied as a positional arg), and that the
        # purge_props default is True.
        client.call.assert_called_once_with(ctx, 1, 'update',
                                            mock.sentinel.image_id,
                                            name=mock.sentinel.name,
                                            purge_props=True)
        trans_from_mock.assert_called_once_with(mock.sentinel.image_meta)
        self.assertEqual(mock.sentinel.trans_from, image_meta)

        # Now verify that if we supply image data to the call,
        # that the client is also called with the data kwarg
        client.reset_mock()
        service.update(ctx, mock.sentinel.image_id,
                       image_mock, data=mock.sentinel.data)

        client.call.assert_called_once_with(ctx, 1, 'update',
                                            mock.sentinel.image_id,
                                            name=mock.sentinel.name,
                                            purge_props=True,
                                            data=mock.sentinel.data)

    @mock.patch('nova.image.glance._reraise_translated_image_exception')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._translate_to_glance')
    def test_update_client_failure(self, trans_to_mock, trans_from_mock,
                                   reraise_mock):
        translated = {
            'name': mock.sentinel.name
        }
        trans_to_mock.return_value = translated
        trans_from_mock.return_value = mock.sentinel.trans_from
        image_mock = mock.MagicMock(spec=dict)
        raised = exception.ImageNotAuthorized(image_id=123)
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.Forbidden
        ctx = mock.sentinel.ctx
        reraise_mock.side_effect = raised
        service = glance.GlanceImageService(client)

        self.assertRaises(exception.ImageNotAuthorized,
                          service.update, ctx, mock.sentinel.image_id,
                          image_mock)
        client.call.assert_called_once_with(ctx, 1, 'update',
                                            mock.sentinel.image_id,
                                            purge_props=True,
                                            name=mock.sentinel.name)
        self.assertFalse(trans_from_mock.called)
        reraise_mock.assert_called_once_with(mock.sentinel.image_id)


class TestDelete(test.NoDBTestCase):

    """Tests the delete method of the GlanceImageService."""

    def test_delete_success(self):
        client = mock.MagicMock()
        client.call.return_value = True
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        service.delete(ctx, mock.sentinel.image_id)
        client.call.assert_called_once_with(ctx, 1, 'delete',
                                            mock.sentinel.image_id)

    def test_delete_client_failure(self):
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.NotFound
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        self.assertRaises(exception.ImageNotFound, service.delete, ctx,
                          mock.sentinel.image_id)


class TestGlanceApiServers(test.NoDBTestCase):

    def test_get_api_servers(self):
        glance_servers = ['10.0.1.1:9292',
                          'https://10.0.0.1:9293',
                          'http://10.0.2.2:9294']
        expected_servers = ['http://10.0.1.1:9292',
                          'https://10.0.0.1:9293',
                          'http://10.0.2.2:9294']
        self.flags(api_servers=glance_servers, group='glance')
        api_servers = glance.get_api_servers()
        i = 0
        for server in api_servers:
            i += 1
            self.assertIn(server, expected_servers)
            if i > 2:
                break


class TestUpdateGlanceImage(test.NoDBTestCase):
    @mock.patch('nova.image.glance.GlanceImageService')
    def test_start(self, mock_glance_image_service):
        consumer = glance.UpdateGlanceImage(
            'context', 'id', 'metadata', 'stream')

        with mock.patch.object(glance, 'get_remote_image_service') as a_mock:
            a_mock.return_value = (mock_glance_image_service, 'image_id')

            consumer.start()
            mock_glance_image_service.update.assert_called_with(
                'context', 'image_id', 'metadata', 'stream', purge_props=False)
