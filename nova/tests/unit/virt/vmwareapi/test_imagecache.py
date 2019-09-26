# Copyright (c) 2014 VMware, Inc.
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

import mock
from oslo_config import cfg
from oslo_utils import fixture as utils_fixture
from oslo_utils.fixture import uuidsentinel
from oslo_vmware.objects import datastore as ds_obj
from oslo_vmware import vim_util as vutil

from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.vmwareapi import fake
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import imagecache


CONF = cfg.CONF


class ImageCacheManagerTestCase(test.NoDBTestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        super(ImageCacheManagerTestCase, self).setUp()
        self._session = mock.Mock(name='session')
        self._imagecache = imagecache.ImageCacheManager(self._session,
                                                        'fake-base-folder')
        self._time = datetime.datetime(2012, 11, 22, 12, 00, 00)
        self._file_name = 'ts-2012-11-22-12-00-00'
        fake.reset()

    def tearDown(self):
        super(ImageCacheManagerTestCase, self).tearDown()
        fake.reset()

    def test_timestamp_cleanup(self):
        def fake_get_timestamp(ds_browser, ds_path):
            self.assertEqual('fake-ds-browser', ds_browser)
            self.assertEqual('[fake-ds] fake-path', str(ds_path))
            if not self.exists:
                return
            ts = '%s%s' % (imagecache.TIMESTAMP_PREFIX,
                           self._time.strftime(imagecache.TIMESTAMP_FORMAT))
            return ts

        with test.nested(
            mock.patch.object(self._imagecache, '_get_timestamp',
                              fake_get_timestamp),
            mock.patch.object(ds_util, 'file_delete')
        ) as (_get_timestamp, _file_delete):
            self.exists = False
            self._imagecache.timestamp_cleanup(
                    'fake-dc-ref', 'fake-ds-browser',
                    ds_obj.DatastorePath('fake-ds', 'fake-path'))
            self.assertEqual(0, _file_delete.call_count)
            self.exists = True
            self._imagecache.timestamp_cleanup(
                    'fake-dc-ref', 'fake-ds-browser',
                    ds_obj.DatastorePath('fake-ds', 'fake-path'))
            expected_ds_path = ds_obj.DatastorePath(
                    'fake-ds', 'fake-path', self._file_name)
            _file_delete.assert_called_once_with(self._session,
                    expected_ds_path, 'fake-dc-ref')

    def test_get_timestamp(self):
        def fake_get_sub_folders(session, ds_browser, ds_path):
            self.assertEqual('fake-ds-browser', ds_browser)
            self.assertEqual('[fake-ds] fake-path', str(ds_path))
            if self.exists:
                files = set()
                files.add(self._file_name)
                return files

        with mock.patch.object(ds_util, 'get_sub_folders',
                               fake_get_sub_folders):
            self.exists = True
            ts = self._imagecache._get_timestamp(
                    'fake-ds-browser',
                    ds_obj.DatastorePath('fake-ds', 'fake-path'))
            self.assertEqual(self._file_name, ts)
            self.exists = False
            ts = self._imagecache._get_timestamp(
                    'fake-ds-browser',
                    ds_obj.DatastorePath('fake-ds', 'fake-path'))
            self.assertIsNone(ts)

    def test_get_timestamp_filename(self):
        self.useFixture(utils_fixture.TimeFixture(self._time))
        fn = self._imagecache._get_timestamp_filename()
        self.assertEqual(self._file_name, fn)

    def test_get_datetime_from_filename(self):
        t = self._imagecache._get_datetime_from_filename(self._file_name)
        self.assertEqual(self._time, t)

    def test_get_ds_browser(self):
        cache = self._imagecache._ds_browser
        ds_browser = mock.Mock()
        moref = fake.ManagedObjectReference(value='datastore-100')
        self.assertIsNone(cache.get(moref.value))
        mock_get_method = mock.Mock(return_value=ds_browser)
        with mock.patch.object(vutil, 'get_object_property', mock_get_method):
            ret = self._imagecache._get_ds_browser(moref)
            mock_get_method.assert_called_once_with(mock.ANY, moref, 'browser')
            self.assertIs(ds_browser, ret)
            self.assertIs(ds_browser, cache.get(moref.value))

    def test_list_datastore_images(self):
        def fake_get_object_property(vim, mobj, property_name):
            return 'fake-ds-browser'

        def fake_get_sub_folders(session, ds_browser, ds_path):
            files = set()
            files.add('image-ref-uuid')
            return files

        with test.nested(
            mock.patch.object(vutil, 'get_object_property',
                              fake_get_object_property),
            mock.patch.object(ds_util, 'get_sub_folders',
                              fake_get_sub_folders)
        ) as (_get_dynamic, _get_sub_folders):
            fake_ds_ref = fake.ManagedObjectReference(value='fake-ds-ref')
            datastore = ds_obj.Datastore(name='ds', ref=fake_ds_ref)
            ds_path = datastore.build_path('base_folder')
            images = self._imagecache._list_datastore_images(
                    ds_path, datastore)
            originals = set()
            originals.add('image-ref-uuid')
            self.assertEqual({'originals': originals,
                              'unexplained_images': []},
                             images)

    @mock.patch.object(imagecache.ImageCacheManager, 'timestamp_folder_get')
    @mock.patch.object(imagecache.ImageCacheManager, 'timestamp_cleanup')
    @mock.patch.object(imagecache.ImageCacheManager, '_get_ds_browser')
    def test_enlist_image(self,
                          mock_get_ds_browser,
                          mock_timestamp_cleanup,
                          mock_timestamp_folder_get):
        image_id = "fake_image_id"
        dc_ref = "fake_dc_ref"
        fake_ds_ref = mock.Mock()
        ds = ds_obj.Datastore(
                ref=fake_ds_ref, name='fake_ds',
                capacity=1,
                freespace=1)

        ds_browser = mock.Mock()
        mock_get_ds_browser.return_value = ds_browser
        timestamp_folder_path = mock.Mock()
        mock_timestamp_folder_get.return_value = timestamp_folder_path

        self._imagecache.enlist_image(image_id, ds, dc_ref)

        cache_root_folder = ds.build_path("fake-base-folder")
        mock_get_ds_browser.assert_called_once_with(
                ds.ref)
        mock_timestamp_folder_get.assert_called_once_with(
                cache_root_folder, "fake_image_id")
        mock_timestamp_cleanup.assert_called_once_with(
                dc_ref, ds_browser, timestamp_folder_path)

    def test_age_cached_images(self):
        def fake_get_ds_browser(ds_ref):
            return 'fake-ds-browser'

        def fake_get_timestamp(ds_browser, ds_path):
            self._get_timestamp_called += 1
            path = str(ds_path)
            if path == '[fake-ds] fake-path/fake-image-1':
                # No time stamp exists
                return
            if path == '[fake-ds] fake-path/fake-image-2':
                # Timestamp that will be valid => no deletion
                return 'ts-2012-11-22-10-00-00'
            if path == '[fake-ds] fake-path/fake-image-3':
                # Timestamp that will be invalid => deletion
                return 'ts-2012-11-20-12-00-00'
            self.fail()

        def fake_mkdir(session, ts_path, dc_ref):
            self.assertEqual(
                    '[fake-ds] fake-path/fake-image-1/ts-2012-11-22-12-00-00',
                    str(ts_path))

        def fake_file_delete(session, ds_path, dc_ref):
            self.assertEqual('[fake-ds] fake-path/fake-image-3', str(ds_path))

        def fake_timestamp_cleanup(dc_ref, ds_browser, ds_path):
            self.assertEqual('[fake-ds] fake-path/fake-image-4', str(ds_path))

        with test.nested(
            mock.patch.object(self._imagecache, '_get_ds_browser',
                              fake_get_ds_browser),
            mock.patch.object(self._imagecache, '_get_timestamp',
                              fake_get_timestamp),
            mock.patch.object(ds_util, 'mkdir',
                              fake_mkdir),
            mock.patch.object(ds_util, 'file_delete',
                              fake_file_delete),
            mock.patch.object(self._imagecache, 'timestamp_cleanup',
                              fake_timestamp_cleanup),
        ) as (_get_ds_browser, _get_timestamp, _mkdir, _file_delete,
              _timestamp_cleanup):
            self.useFixture(utils_fixture.TimeFixture(self._time))
            datastore = ds_obj.Datastore(name='ds', ref='fake-ds-ref')
            dc_info = ds_util.DcInfo(ref='dc_ref', name='name',
                                     vmFolder='vmFolder')
            self._get_timestamp_called = 0
            self._imagecache.originals = set(['fake-image-1', 'fake-image-2',
                                              'fake-image-3', 'fake-image-4'])
            self._imagecache.used_images = set(['fake-image-4'])
            self._imagecache._age_cached_images(
                    'fake-context', datastore, dc_info,
                    ds_obj.DatastorePath('fake-ds', 'fake-path'))
            self.assertEqual(3, self._get_timestamp_called)

    @mock.patch.object(objects.block_device.BlockDeviceMappingList,
                       'bdms_by_instance_uuid', return_value={})
    def test_update(self, mock_bdms_by_inst):
        def fake_list_datastore_images(ds_path, datastore):
            return {'unexplained_images': [],
                    'originals': self.images}

        def fake_age_cached_images(context, datastore,
                                   dc_info, ds_path):
            self.assertEqual('[ds] fake-base-folder', str(ds_path))
            self.assertEqual(self.images,
                             self._imagecache.used_images)
            self.assertEqual(self.images,
                             self._imagecache.originals)

        with test.nested(
            mock.patch.object(self._imagecache, '_list_datastore_images',
                              fake_list_datastore_images),
            mock.patch.object(self._imagecache,
                              '_age_cached_images',
                              fake_age_cached_images)
        ) as (_list_base, _age_and_verify):
            instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': uuidsentinel.foo,
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'host': CONF.host,
                          'name': 'inst-2',
                          'uuid': uuidsentinel.bar,
                          'vm_state': '',
                          'task_state': ''}]
            all_instances = [fake_instance.fake_instance_obj(None, **instance)
                             for instance in instances]
            self.images = set(['1', '2'])
            datastore = ds_obj.Datastore(name='ds', ref='fake-ds-ref')
            dc_info = ds_util.DcInfo(ref='dc_ref', name='name',
                                     vmFolder='vmFolder')
            datastores_info = [(datastore, dc_info)]
            self._imagecache.update('context', all_instances, datastores_info)
