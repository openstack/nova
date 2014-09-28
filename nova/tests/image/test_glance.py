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
import filecmp
import os
import random
import tempfile
import time

import sys
import testtools

import mock
import mox

import glanceclient.exc
from oslo.config import cfg

from nova import context
from nova import exception
from nova.image import glance
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.glance import stubs as glance_stubs
from nova.tests import matchers
from nova import utils

import nova.virt.libvirt.utils as lv_utils

CONF = cfg.CONF


class NullWriter(object):
    """Used to test ImageService.get which takes a writer object."""

    def write(self, *arg, **kwargs):
        pass


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

        converted_expected = {
            'name': 'image1',
            'is_public': True,
            'foo': 'bar',
            'properties': {
                'prop1': 'propvalue1',
                'mappings':
                '[{"device": "bbb", "virtual": "aaa"}, '
                '{"device": "yyy", "virtual": "xxx"}]',
                'block_device_mapping':
                '[{"virtual_device": "fake", "device_name": "/dev/fake"}, '
                '{"virtual_device": "ephemeral0", '
                '"device_name": "/dev/fake0"}]'}}
        converted = glance._convert_to_string(metadata)
        self.assertEqual(converted, converted_expected)
        self.assertEqual(glance._convert_from_string(converted), metadata)


class TestGlanceImageService(test.NoDBTestCase):
    """Tests the Glance image service.

    At a high level, the translations involved are:

        1. Glance -> ImageService - This is needed so we can support
           multple ImageServices (Glance, Local, etc)

        2. ImageService -> API - This is needed so we can support multple
           APIs (OpenStack, EC2)

    """
    NOW_GLANCE_OLD_FORMAT = "2010-10-11T10:30:22"
    NOW_GLANCE_FORMAT = "2010-10-11T10:30:22.000000"

    class tzinfo(datetime.tzinfo):
        @staticmethod
        def utcoffset(*args, **kwargs):
            return datetime.timedelta()

    NOW_DATETIME = datetime.datetime(2010, 10, 11, 10, 30, 22, tzinfo=tzinfo())

    def setUp(self):
        super(TestGlanceImageService, self).setUp()
        fakes.stub_out_compute_api_snapshot(self.stubs)

        self.client = glance_stubs.StubGlanceClient()
        self.service = self._create_image_service(self.client)
        self.context = context.RequestContext('fake', 'fake', auth_token=True)
        self.mox = mox.Mox()
        self.files_to_clean = []

    def tearDown(self):
        super(TestGlanceImageService, self).tearDown()
        self.mox.UnsetStubs()
        for f in self.files_to_clean:
            try:
                os.unlink(f)
            except os.error:
                pass

    def _get_tempfile(self):
        (outfd, config_filename) = tempfile.mkstemp(prefix='nova_glance_tests')
        self.files_to_clean.append(config_filename)
        return (outfd, config_filename)

    def _create_image_service(self, client):
        def _fake_create_glance_client(context, host, port, use_ssl, version):
            return client

        self.stubs.Set(glance, '_create_glance_client',
                _fake_create_glance_client)

        client_wrapper = glance.GlanceClientWrapper(
                'fake', 'fake_host', 9292)
        return glance.GlanceImageService(client=client_wrapper)

    @staticmethod
    def _make_fixture(**kwargs):
        fixture = {'name': None,
                   'properties': {},
                   'status': None,
                   'is_public': None}
        fixture.update(kwargs)
        return fixture

    def _make_datetime_fixture(self):
        return self._make_fixture(created_at=self.NOW_GLANCE_FORMAT,
                                  updated_at=self.NOW_GLANCE_FORMAT,
                                  deleted_at=self.NOW_GLANCE_FORMAT)

    def test_create_with_instance_id(self):
        # Ensure instance_id is persisted as an image-property.
        fixture = {'name': 'test image',
                   'is_public': False,
                   'properties': {'instance_id': '42', 'user_id': 'fake'}}

        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {'instance_id': '42', 'user_id': 'fake'},
            'owner': None,
        }
        self.assertThat(image_meta, matchers.DictMatches(expected))

        image_metas = self.service.detail(self.context)
        self.assertThat(image_metas[0], matchers.DictMatches(expected))

    def test_create_without_instance_id(self):
        """Ensure we can create an image without having to specify an
        instance_id. Public images are an example of an image not tied to an
        instance.
        """
        fixture = {'name': 'test image', 'is_public': False}
        image_id = self.service.create(self.context, fixture)['id']

        expected = {
            'id': image_id,
            'name': 'test image',
            'is_public': False,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        actual = self.service.show(self.context, image_id)
        self.assertThat(actual, matchers.DictMatches(expected))

    def test_create(self):
        fixture = self._make_fixture(name='test image')
        num_images = len(self.service.detail(self.context))
        image_id = self.service.create(self.context, fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertEqual(num_images + 1,
                         len(self.service.detail(self.context)))

    def test_create_and_show_non_existing_image(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']

        self.assertIsNotNone(image_id)
        self.assertRaises(exception.ImageNotFound,
                          self.service.show,
                          self.context,
                          'bad image id')

    def test_show_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        image_id = self.service.create(self.context, fixture)['id']
        image_meta = self.service.show(self.context, image_id)
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_detail_makes_datetimes(self):
        fixture = self._make_datetime_fixture()
        self.service.create(self.context, fixture)
        image_meta = self.service.detail(self.context)[0]
        self.assertEqual(image_meta['created_at'], self.NOW_DATETIME)
        self.assertEqual(image_meta['updated_at'], self.NOW_DATETIME)

    def test_page_size(self):
        with mock.patch.object(glance.GlanceClientWrapper, 'call') as a_mock:
            self.service.detail(self.context, page_size=5)
            self.assertEqual(a_mock.called, True)
            a_mock.assert_called_with(self.context, 1, 'list',
                                      filters={'is_public': 'none'},
                                      page_size=5)

    def test_update(self):
        fixture = self._make_fixture(name='test image')
        image = self.service.create(self.context, fixture)
        image_id = image['id']
        fixture['name'] = 'new image name'
        self.service.update(self.context, image_id, fixture)

        new_image_data = self.service.show(self.context, image_id)
        self.assertEqual('new image name', new_image_data['name'])

    def test_delete(self):
        fixture1 = self._make_fixture(name='test image 1')
        fixture2 = self._make_fixture(name='test image 2')
        fixtures = [fixture1, fixture2]

        num_images = len(self.service.detail(self.context))
        self.assertEqual(0, num_images)

        ids = []
        for fixture in fixtures:
            new_id = self.service.create(self.context, fixture)['id']
            ids.append(new_id)

        num_images = len(self.service.detail(self.context))
        self.assertEqual(2, num_images)

        self.service.delete(self.context, ids[0])
        # When you delete an image from glance, it sets the status to DELETED
        # and doesn't actually remove the image.

        # Check the image is still there.
        num_images = len(self.service.detail(self.context))
        self.assertEqual(2, num_images)

        # Check the image is marked as deleted.
        num_images = reduce(lambda x, y: x + (0 if y['deleted'] else 1),
                            self.service.detail(self.context), 0)
        self.assertEqual(1, num_images)

    def test_download_with_retries(self):
        tries = [0]

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that fails the first time, then succeeds."""
            def get(self, image_id):
                if tries[0] == 0:
                    tries[0] = 1
                    raise glanceclient.exc.ServiceUnavailable('')
                else:
                    return {}

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        writer = NullWriter()

        # When retries are disabled, we should get an exception
        self.flags(glance_num_retries=0)
        self.assertRaises(exception.GlanceConnectionFailed,
                service.download, self.context, image_id, data=writer)

        # Now lets enable retries. No exception should happen now.
        tries = [0]
        self.flags(glance_num_retries=1)
        service.download(self.context, image_id, data=writer)

    def test_download_file_url(self):
        self.flags(allowed_direct_url_schemes=['file'])

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that returns a file url."""

            (outfd, s_tmpfname) = tempfile.mkstemp(prefix='directURLsrc')
            outf = os.fdopen(outfd, 'w')
            inf = open('/dev/urandom', 'r')
            for i in range(10):
                _data = inf.read(1024)
                outf.write(_data)
            outf.close()

            def get(self, image_id):
                return type('GlanceTestDirectUrlMeta', (object,),
                            {'direct_url': 'file://%s' + self.s_tmpfname})

        client = MyGlanceStubClient()
        (outfd, tmpfname) = tempfile.mkstemp(prefix='directURLdst')
        os.close(outfd)

        service = self._create_image_service(client)
        image_id = 1  # doesn't matter

        service.download(self.context, image_id, dst_path=tmpfname)

        # compare the two files
        rc = filecmp.cmp(tmpfname, client.s_tmpfname)
        self.assertTrue(rc, "The file %s and %s should be the same" %
                        (tmpfname, client.s_tmpfname))
        os.remove(client.s_tmpfname)
        os.remove(tmpfname)

    def test_download_module_filesystem_match(self):

        mountpoint = '/'
        fs_id = 'someid'
        desc = {'id': fs_id, 'mountpoint': mountpoint}

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            outer_test = self

            def get(self, image_id):
                return type('GlanceLocations', (object,),
                            {'locations': [
                                {'url': 'file:///' + os.devnull,
                                 'metadata': desc}]})

            def data(self, image_id):
                self.outer_test.fail('This should not be called because the '
                                     'transfer module should have intercepted '
                                     'it.')

        self.mox.StubOutWithMock(lv_utils, 'copy_image')

        image_id = 1  # doesn't matter
        client = MyGlanceStubClient()
        self.flags(allowed_direct_url_schemes=['file'])
        self.flags(group='image_file_url', filesystems=['gluster'])
        service = self._create_image_service(client)
        #NOTE(Jbresnah) The following options must be added after the module
        # has added the specific groups.
        self.flags(group='image_file_url:gluster', id=fs_id)
        self.flags(group='image_file_url:gluster', mountpoint=mountpoint)

        dest_file = os.devnull
        lv_utils.copy_image(mox.IgnoreArg(), dest_file)

        self.mox.ReplayAll()
        service.download(self.context, image_id, dst_path=dest_file)
        self.mox.VerifyAll()

    def test_download_module_no_filesystem_match(self):
        mountpoint = '/'
        fs_id = 'someid'
        desc = {'id': fs_id, 'mountpoint': mountpoint}
        some_data = "sfxvdwjer"

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            outer_test = self

            def get(self, image_id):
                return type('GlanceLocations', (object,),
                            {'locations': [
                                {'url': 'file:///' + os.devnull,
                                 'metadata': desc}]})

            def data(self, image_id):
                return some_data

        def _fake_copyfile(source, dest):
            self.fail('This should not be called because a match should not '
                      'have been found.')
        self.stubs.Set(lv_utils, 'copy_image', _fake_copyfile)

        image_id = 1  # doesn't matter
        client = MyGlanceStubClient()
        self.flags(allowed_direct_url_schemes=['file'])
        self.flags(group='image_file_url', filesystems=['gluster'])
        service = self._create_image_service(client)
        #NOTE(Jbresnah) The following options must be added after the module
        # has added the specific groups.
        self.flags(group='image_file_url:gluster', id='someotherid')
        self.flags(group='image_file_url:gluster', mountpoint=mountpoint)

        service.download(self.context, image_id,
                         dst_path=os.devnull,
                         data=None)

    def test_download_module_mountpoints(self):
        glance_mount = '/glance/mount/point'
        _, data_filename = self._get_tempfile()
        nova_mount = os.path.dirname(data_filename)
        source_path = os.path.basename(data_filename)
        file_url = 'file://%s' % os.path.join(glance_mount, source_path)
        file_system_id = 'test_FS_ID'
        file_system_desc = {'id': file_system_id, 'mountpoint': glance_mount}

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            outer_test = self

            def get(self, image_id):
                return type('GlanceLocations', (object,),
                            {'locations': [{'url': file_url,
                                            'metadata': file_system_desc}]})

            def data(self, image_id):
                self.outer_test.fail('This should not be called because the '
                                     'transfer module should have intercepted '
                                     'it.')

        self.copy_called = False

        def _fake_copyfile(source, dest):
            self.assertEqual(source, data_filename)
            self.copy_called = True
        self.stubs.Set(lv_utils, 'copy_image', _fake_copyfile)

        self.flags(allowed_direct_url_schemes=['file'])
        self.flags(group='image_file_url', filesystems=['gluster'])
        image_id = 1  # doesn't matter
        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        self.flags(group='image_file_url:gluster', id=file_system_id)
        self.flags(group='image_file_url:gluster', mountpoint=nova_mount)

        service.download(self.context, image_id, dst_path=os.devnull)
        self.assertTrue(self.copy_called)

    def test_download_module_file_bad_module(self):
        _, data_filename = self._get_tempfile()
        file_url = 'applesauce://%s' % data_filename
        data_called = False

        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            data_called = False

            def get(self, image_id):
                return type('GlanceLocations', (object,),
                            {'locations': [{'url': file_url,
                                            'metadata': {}}]})

            def data(self, image_id):
                self.data_called = True
                return "someData"

        self.flags(allowed_direct_url_schemes=['applesauce'])

        self.mox.StubOutWithMock(lv_utils, 'copy_image')
        self.flags(allowed_direct_url_schemes=['file'])
        image_id = 1  # doesn't matter
        client = MyGlanceStubClient()
        service = self._create_image_service(client)

        # by not calling copyfileobj in the file download module we verify
        # that the requirements were not met for its use
        self.mox.ReplayAll()
        service.download(self.context, image_id, dst_path=os.devnull)
        self.mox.VerifyAll()

        self.assertTrue(client.data_called)

    def test_client_forbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a Forbidden exception."""
            def get(self, image_id):
                raise glanceclient.exc.Forbidden(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        self.assertRaises(exception.ImageNotAuthorized, service.download,
                          self.context, image_id, dst_path=os.devnull)

    def test_client_httpforbidden_converts_to_imagenotauthed(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a HTTPForbidden exception."""
            def get(self, image_id):
                raise glanceclient.exc.HTTPForbidden(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        self.assertRaises(exception.ImageNotAuthorized, service.download,
                          self.context, image_id, dst_path=os.devnull)

    def test_client_notfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a NotFound exception."""
            def get(self, image_id):
                raise glanceclient.exc.NotFound(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        self.assertRaises(exception.ImageNotFound, service.download,
                          self.context, image_id, dst_path=os.devnull)

    def test_client_httpnotfound_converts_to_imagenotfound(self):
        class MyGlanceStubClient(glance_stubs.StubGlanceClient):
            """A client that raises a HTTPNotFound exception."""
            def get(self, image_id):
                raise glanceclient.exc.HTTPNotFound(image_id)

        client = MyGlanceStubClient()
        service = self._create_image_service(client)
        image_id = 1  # doesn't matter
        self.assertRaises(exception.ImageNotFound, service.download,
                          self.context, image_id, dst_path=os.devnull)

    def test_glance_client_image_id(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        (service, same_id) = glance.get_remote_image_service(
                self.context, image_id)
        self.assertEqual(same_id, image_id)

    def test_glance_client_image_ref(self):
        fixture = self._make_fixture(name='test image')
        image_id = self.service.create(self.context, fixture)['id']
        image_url = 'http://something-less-likely/%s' % image_id
        (service, same_id) = glance.get_remote_image_service(
                self.context, image_url)
        self.assertEqual(same_id, image_id)
        self.assertEqual(service._client.host, 'something-less-likely')

    def test_extracting_missing_attributes(self):
        """Verify behavior from glance objects that are missing attributes

        This fakes the image class and is missing attribute as the client can
        return if they're not set in the database.
        """
        class MyFakeGlanceImage(glance_stubs.FakeImage):
            def __init__(self, metadata):
                IMAGE_ATTRIBUTES = ['size', 'owner', 'id', 'created_at',
                                    'updated_at', 'status', 'min_disk',
                                    'min_ram', 'is_public']
                raw = dict.fromkeys(IMAGE_ATTRIBUTES)
                raw.update(metadata)
                self.__dict__['raw'] = raw

        metadata = {
            'id': 1,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
        }
        image = MyFakeGlanceImage(metadata)
        observed = glance._extract_attributes(image)
        expected = {
            'id': 1,
            'name': None,
            'is_public': None,
            'size': None,
            'min_disk': None,
            'min_ram': None,
            'disk_format': None,
            'container_format': None,
            'checksum': None,
            'created_at': self.NOW_DATETIME,
            'updated_at': self.NOW_DATETIME,
            'deleted_at': None,
            'deleted': None,
            'status': None,
            'properties': {},
            'owner': None,
        }
        self.assertEqual(expected, observed)


def _create_failing_glance_client(info):
    class MyGlanceStubClient(glance_stubs.StubGlanceClient):
        """A client that fails the first time, then succeeds."""
        def get(self, image_id):
            info['num_calls'] += 1
            if info['num_calls'] == 1:
                raise glanceclient.exc.ServiceUnavailable('')
            return {}

    return MyGlanceStubClient()


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
        img.assert_not_called()

    def test_admin_override(self):
        ctx = mock.MagicMock(auth_token=False, is_admin=True)
        img = mock.MagicMock()

        res = glance._is_image_available(ctx, img)
        self.assertTrue(res)
        img.assert_not_called()

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
        trans_from_mock.return_value = mock.sentinel.trans_from
        client = mock.MagicMock()
        client.call.return_value = mock.sentinel.images_0
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        info = service.show(ctx, mock.sentinel.image_id)

        client.call.assert_called_once_with(ctx, 1, 'get',
                                            mock.sentinel.image_id)
        is_avail_mock.assert_called_once_with(ctx, mock.sentinel.images_0)
        trans_from_mock.assert_called_once_with(mock.sentinel.images_0)
        self.assertEqual(mock.sentinel.trans_from, info)

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
        trans_from_mock.assert_not_called()

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
            is_avail_mock.assert_not_called()
            trans_from_mock.assert_not_called()
            reraise_mock.assert_called_once_with(mock.sentinel.image_id)

    @mock.patch('nova.image.glance._is_image_available')
    def test_show_queued_image_without_some_attrs(self, is_avail_mock):
        is_avail_mock.return_value = True
        client = mock.MagicMock()

        # fake image cls without disk_format, container_format, name attributes
        class fake_image_cls(object):
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


class TestDetail(test.NoDBTestCase):

    """Tests the show method of the GlanceImageService."""

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
        trans_from_mock.assert_not_called()
        self.assertEqual([], images)

    @mock.patch('nova.image.glance._extract_query_params')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_params_passed(self, is_avail_mock, _trans_from_mock,
                                  ext_query_mock):
        params = dict(limit=10)
        ext_query_mock.return_value = params
        client = mock.MagicMock()
        client.call.return_value = [mock.sentinel.images_0]
        ctx = mock.sentinel.ctx
        service = glance.GlanceImageService(client)
        images = service.detail(ctx, **params)

        client.call.assert_called_once_with(ctx, 1, 'list', limit=10)

    @mock.patch('nova.image.glance._reraise_translated_exception')
    @mock.patch('nova.image.glance._extract_query_params')
    @mock.patch('nova.image.glance._translate_from_glance')
    @mock.patch('nova.image.glance._is_image_available')
    def test_detail_client_failure(self, is_avail_mock, trans_from_mock,
                                   ext_query_mock, reraise_mock):
        params = {}
        ext_query_mock.return_value = params
        raised = exception.NotAuthorized()
        client = mock.MagicMock()
        client.call.side_effect = glanceclient.exc.Forbidden
        ctx = mock.sentinel.ctx
        reraise_mock.side_effect = raised
        service = glance.GlanceImageService(client)

        with testtools.ExpectedException(exception.NotAuthorized):
            service.detail(ctx, **params)

        client.call.assert_called_once_with(ctx, 1, 'list')
        is_avail_mock.assert_not_called()
        trans_from_mock.assert_not_called()
        reraise_mock.assert_called_once_with()


class TestGlanceClientWrapper(test.NoDBTestCase):

    def setUp(self):
        super(TestGlanceClientWrapper, self).setUp()
        # host1 has no scheme, which is http by default
        self.flags(glance_api_servers=['host1:9292', 'https://host2:9293',
            'http://host3:9294'])

        # Make the test run fast
        def _fake_sleep(secs):
            pass
        self.stubs.Set(time, 'sleep', _fake_sleep)

    def test_headers_passed_glanceclient(self):
        auth_token = 'auth_token'
        ctxt = context.RequestContext('fake', 'fake', auth_token=auth_token)
        fake_host = 'host4'
        fake_port = 9295
        fake_use_ssl = False

        def _get_fake_glanceclient(version, endpoint, **params):
            fake_client = glance_stubs.StubGlanceClient(version,
                                       endpoint, **params)
            self.assertIsNotNone(fake_client.auth_token)
            self.assertIsNotNone(fake_client.identity_headers)
            self.assertEqual(fake_client.identity_header['X-Auth_Token'],
                             auth_token)
            self.assertEqual(fake_client.identity_header['X-User-Id'], 'fake')
            self.assertIsNone(fake_client.identity_header['X-Roles'])
            self.assertIsNone(fake_client.identity_header['X-Tenant-Id'])
            self.assertIsNone(fake_client.identity_header['X-Service-Catalog'])
            self.assertEqual(fake_client.
                             identity_header['X-Identity-Status'],
                             'Confirmed')

        self.stubs.Set(glanceclient.Client, '__init__',
                       _get_fake_glanceclient)

        glance._create_glance_client(ctxt, fake_host, fake_port, fake_use_ssl)

    def test_static_client_without_retries(self):
        self.flags(glance_num_retries=0)

        ctxt = context.RequestContext('fake', 'fake')
        fake_host = 'host4'
        fake_port = 9295
        fake_use_ssl = False

        info = {'num_calls': 0}

        def _fake_create_glance_client(context, host, port, use_ssl, version):
            self.assertEqual(host, fake_host)
            self.assertEqual(port, fake_port)
            self.assertEqual(use_ssl, fake_use_ssl)
            return _create_failing_glance_client(info)

        self.stubs.Set(glance, '_create_glance_client',
                _fake_create_glance_client)

        client = glance.GlanceClientWrapper(context=ctxt,
                host=fake_host, port=fake_port, use_ssl=fake_use_ssl)
        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 1)

    def test_default_client_without_retries(self):
        self.flags(glance_num_retries=0)

        ctxt = context.RequestContext('fake', 'fake')

        info = {'num_calls': 0,
                'host': 'host1',
                'port': 9292,
                'use_ssl': False}

        # Leave the list in a known-order
        def _fake_shuffle(servers):
            pass

        def _fake_create_glance_client(context, host, port, use_ssl, version):
            self.assertEqual(host, info['host'])
            self.assertEqual(port, info['port'])
            self.assertEqual(use_ssl, info['use_ssl'])
            return _create_failing_glance_client(info)

        self.stubs.Set(random, 'shuffle', _fake_shuffle)
        self.stubs.Set(glance, '_create_glance_client',
                _fake_create_glance_client)

        client = glance.GlanceClientWrapper()
        client2 = glance.GlanceClientWrapper()
        self.assertRaises(exception.GlanceConnectionFailed,
                client.call, ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 1)

        info = {'num_calls': 0,
                'host': 'host2',
                'port': 9293,
                'use_ssl': True}

        def _fake_shuffle2(servers):
            # fake shuffle in a known manner
            servers.append(servers.pop(0))

        self.stubs.Set(random, 'shuffle', _fake_shuffle2)

        self.assertRaises(exception.GlanceConnectionFailed,
                client2.call, ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 1)

    def test_static_client_with_retries(self):
        self.flags(glance_num_retries=1)

        ctxt = context.RequestContext('fake', 'fake')
        fake_host = 'host4'
        fake_port = 9295
        fake_use_ssl = False

        info = {'num_calls': 0}

        def _fake_create_glance_client(context, host, port, use_ssl, version):
            self.assertEqual(host, fake_host)
            self.assertEqual(port, fake_port)
            self.assertEqual(use_ssl, fake_use_ssl)
            return _create_failing_glance_client(info)

        self.stubs.Set(glance, '_create_glance_client',
                _fake_create_glance_client)

        client = glance.GlanceClientWrapper(context=ctxt,
                host=fake_host, port=fake_port, use_ssl=fake_use_ssl)
        client.call(ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 2)

    def test_default_client_with_retries(self):
        self.flags(glance_num_retries=1)

        ctxt = context.RequestContext('fake', 'fake')

        info = {'num_calls': 0,
                'host0': 'host1',
                'port0': 9292,
                'use_ssl0': False,
                'host1': 'host2',
                'port1': 9293,
                'use_ssl1': True}

        # Leave the list in a known-order
        def _fake_shuffle(servers):
            pass

        def _fake_create_glance_client(context, host, port, use_ssl, version):
            attempt = info['num_calls']
            self.assertEqual(host, info['host%s' % attempt])
            self.assertEqual(port, info['port%s' % attempt])
            self.assertEqual(use_ssl, info['use_ssl%s' % attempt])
            return _create_failing_glance_client(info)

        self.stubs.Set(random, 'shuffle', _fake_shuffle)
        self.stubs.Set(glance, '_create_glance_client',
                _fake_create_glance_client)

        client = glance.GlanceClientWrapper()
        client2 = glance.GlanceClientWrapper()
        client.call(ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 2)

        def _fake_shuffle2(servers):
            # fake shuffle in a known manner
            servers.append(servers.pop(0))

        self.stubs.Set(random, 'shuffle', _fake_shuffle2)

        info = {'num_calls': 0,
                'host0': 'host2',
                'port0': 9293,
                'use_ssl0': True,
                'host1': 'host3',
                'port1': 9294,
                'use_ssl1': False}

        client2.call(ctxt, 1, 'get', 'meow')
        self.assertEqual(info['num_calls'], 2)


class TestGlanceUrl(test.NoDBTestCase):

    def test_generate_glance_http_url(self):
        generated_url = glance.generate_glance_url()
        glance_host = CONF.glance_host
        # ipv6 address, need to wrap it with '[]'
        if utils.is_valid_ipv6(glance_host):
            glance_host = '[%s]' % glance_host
        http_url = "http://%s:%d" % (glance_host, CONF.glance_port)
        self.assertEqual(generated_url, http_url)

    def test_generate_glance_https_url(self):
        self.flags(glance_protocol="https")
        generated_url = glance.generate_glance_url()
        glance_host = CONF.glance_host
        # ipv6 address, need to wrap it with '[]'
        if utils.is_valid_ipv6(glance_host):
            glance_host = '[%s]' % glance_host
        https_url = "https://%s:%d" % (glance_host, CONF.glance_port)
        self.assertEqual(generated_url, https_url)


class TestGlanceApiServers(test.TestCase):

    def test_get_ipv4_api_servers(self):
        self.flags(glance_api_servers=['10.0.1.1:9292',
                              'https://10.0.0.1:9293',
                              'http://10.0.2.2:9294'])
        glance_host = ['10.0.1.1', '10.0.0.1',
                        '10.0.2.2']
        api_servers = glance.get_api_servers()
        i = 0
        for server in api_servers:
            i += 1
            self.assertIn(server[0], glance_host)
            if i > 2:
                break

    # Python 2.6 can not parse ipv6 address correctly
    @testtools.skipIf(sys.version_info < (2, 7), "py27 or greater only")
    def test_get_ipv6_api_servers(self):
        self.flags(glance_api_servers=['[2001:2012:1:f101::1]:9292',
                              'https://[2010:2013:1:f122::1]:9293',
                              'http://[2001:2011:1:f111::1]:9294'])
        glance_host = ['2001:2012:1:f101::1', '2010:2013:1:f122::1',
                        '2001:2011:1:f111::1']
        api_servers = glance.get_api_servers()
        i = 0
        for server in api_servers:
            i += 1
            self.assertIn(server[0], glance_host)
            if i > 2:
                break


class TestUpdateGlanceImage(test.NoDBTestCase):
    def test_start(self):
        consumer = glance.UpdateGlanceImage(
            'context', 'id', 'metadata', 'stream')
        image_service = self.mox.CreateMock(glance.GlanceImageService)

        self.mox.StubOutWithMock(glance, 'get_remote_image_service')

        glance.get_remote_image_service(
            'context', 'id').AndReturn((image_service, 'image_id'))
        image_service.update(
            'context', 'image_id', 'metadata', 'stream', purge_props=False)

        self.mox.ReplayAll()

        consumer.start()
