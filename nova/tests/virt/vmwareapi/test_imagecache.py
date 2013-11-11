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

import contextlib
import mock
from oslo.config import cfg

from nova.openstack.common import timeutils
from nova import test
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import imagecache
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vmops

CONF = cfg.CONF


class ImageCacheManagerTestCase(test.NoDBTestCase):
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
            self.assertEqual('fake-ds-path', ds_path)
            if not self.exists:
                return
            ts = '%s%s' % (imagecache.TIMESTAMP_PREFIX,
                    timeutils.strtime(at=self._time,
                                      fmt=imagecache.TIMESTAMP_FORMAT))
            return ts

        with contextlib.nested(
            mock.patch.object(self._imagecache, '_get_timestamp',
                              fake_get_timestamp),
            mock.patch.object(ds_util, 'file_delete')
        ) as (_get_timestamp, _file_delete):
            self.exists = False
            self._imagecache.timestamp_cleanup(
                    'fake-dc-ref', 'fake-ds-browser', 'fake-ds-ref',
                    'fake-ds-name', 'fake-ds-path')
            self.assertEqual(0, _file_delete.call_count)
            self.exists = True
            self._imagecache.timestamp_cleanup(
                    'fake-dc-ref', 'fake-ds-browser', 'fake-ds-ref',
                    'fake-ds-name', 'fake-ds-path')
            _file_delete.assert_called_once_with(self._session,
                    'fake-ds-path/ts-2012-11-22-12-00-00',
                    'fake-dc-ref')

    def test_get_timestamp(self):
        def fake_get_sub_folders(session, ds_browser, ds_path):
            self.assertEqual('fake-ds-browser', ds_browser)
            self.assertEqual('fake-ds-path', ds_path)
            if self.exists:
                files = set()
                files.add(self._file_name)
                return files

        with contextlib.nested(
            mock.patch.object(ds_util, 'get_sub_folders',
                              fake_get_sub_folders)
        ) as (_get_sub_folders):
            self.exists = True
            ts = self._imagecache._get_timestamp('fake-ds-browser',
                                                 'fake-ds-path')
            self.assertEqual(self._file_name, ts)
            self.exists = False
            ts = self._imagecache._get_timestamp('fake-ds-browser',
                                                 'fake-ds-path')
            self.assertIsNone(ts)

    def test_get_timestamp_filename(self):
        timeutils.set_time_override(override_time=self._time)
        fn = self._imagecache._get_timestamp_filename()
        self.assertEqual(self._file_name, fn)

    def test_get_datetime_from_filename(self):
        t = self._imagecache._get_datetime_from_filename(self._file_name)
        self.assertEqual(self._time, t)

    def test_get_ds_browser(self):
        def fake_get_dynamic_property(vim, mobj, type, property_name):
            self.assertEqual('Datastore', type)
            self.assertEqual('browser', property_name)
            self.fake_called += 1
            return 'fake-ds-browser'

        with contextlib.nested(
            mock.patch.object(vim_util, 'get_dynamic_property',
                              fake_get_dynamic_property)
        ) as _get_dynamic:
            self.fake_called = 0
            self.assertEqual({}, self._imagecache._ds_browser)
            browser = self._imagecache._get_ds_browser('fake-ds-ref')
            self.assertEqual('fake-ds-browser', browser)
            self.assertEqual({'fake-ds-ref': 'fake-ds-browser'},
                             self._imagecache._ds_browser)
            self.assertEqual(1, self.fake_called)
            browser = self._imagecache._get_ds_browser('fake-ds-ref')
            self.assertEqual('fake-ds-browser', browser)
            self.assertEqual(1, self.fake_called)

    def test_list_base_images(self):
        def fake_get_dynamic_property(vim, mobj, type, property_name):
            return 'fake-ds-browser'

        def fake_get_sub_folders(session, ds_browser, ds_path):
            files = set()
            files.add('image-ref-uuid')
            return files

        with contextlib.nested(
            mock.patch.object(vim_util, 'get_dynamic_property',
                              fake_get_dynamic_property),
            mock.patch.object(ds_util, 'get_sub_folders',
                              fake_get_sub_folders)
        ) as (_get_dynamic, _get_sub_folders):
            datastore = {'name': 'ds', 'ref': 'fake-ds-ref'}
            ds_path = ds_util.build_datastore_path(datastore['name'],
                                                   'base_folder')
            images = self._imagecache._list_datastore_images(
                    ds_path, datastore)
            originals = set()
            originals.add('image-ref-uuid')
            self.assertEqual({'originals': originals,
                              'unexplained_images': []},
                             images)

    def test_age_cached_images(self):
        def fake_get_ds_browser(ds_ref):
            return 'fake-ds-browser'

        def fake_get_timestamp(ds_browser, path):
            self._get_timestamp_called += 1
            if path == 'fake-ds-path/fake-image-1':
                # No time stamp exists
                return
            if path == 'fake-ds-path/fake-image-2':
                # Timestamp that will be valid => no deletion
                return 'ts-2012-11-22-10-00-00'
            if path == 'fake-ds-path/fake-image-3':
                # Timestamp that will be invalid => deletion
                return 'ts-2012-11-20-12-00-00'
            self.fail()

        def fake_mkdir(session, ts_path, dc_ref):
            self.assertEqual(
                    'fake-ds-path/fake-image-1/ts-2012-11-22-12-00-00',
                    ts_path)

        def fake_file_delete(session, path, dc_ref):
            self.assertEqual('fake-ds-path/fake-image-3', path)

        def fake_timestamp_cleanup(dc_ref, ds_browser,
                                   ds_ref, ds_name, path):
            self.assertEqual('fake-ds-path/fake-image-4', path)

        with contextlib.nested(
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
            timeutils.set_time_override(override_time=self._time)
            datastore = {'name': 'ds', 'ref': 'fake-ds-ref'}
            dc_info = vmops.DcInfo(ref='dc_ref', name='name',
                                   vmFolder='vmFolder')
            self._get_timestamp_called = 0
            self._imagecache.originals = set(['fake-image-1', 'fake-image-2',
                                              'fake-image-3', 'fake-image-4'])
            self._imagecache.used_images = set(['fake-image-4'])
            self._imagecache._age_cached_images('fake-context',
                    datastore, dc_info, 'fake-ds-path')
            self.assertEqual(3, self._get_timestamp_called)

    def test_update(self):
        def fake_list_datastore_images(ds_path, datastore):
            return {'unexplained_images': [],
                    'originals': self.images}

        def fake_age_cached_images(context, datastore,
                                   dc_info, ds_path):
            self.assertEqual('[ds] fake-base-folder', ds_path)
            self.assertEqual(self.images,
                             self._imagecache.used_images)
            self.assertEqual(self.images,
                             self._imagecache.originals)

        with contextlib.nested(
            mock.patch.object(self._imagecache, '_list_datastore_images',
                              fake_list_datastore_images),
            mock.patch.object(self._imagecache,
                              '_age_cached_images',
                              fake_age_cached_images)
        ) as (_list_base, _age_and_verify):
            instances = [{'image_ref': '1',
                          'host': CONF.host,
                          'name': 'inst-1',
                          'uuid': '123',
                          'vm_state': '',
                          'task_state': ''},
                         {'image_ref': '2',
                          'host': CONF.host,
                          'name': 'inst-2',
                          'uuid': '456',
                          'vm_state': '',
                          'task_state': ''}]
            self.images = set(['1', '2'])
            datastore = {'name': 'ds', 'ref': 'fake-ds-ref'}
            dc_info = vmops.DcInfo(ref='dc_ref', name='name',
                                   vmFolder='vmFolder')
            datastores_info = [(datastore, dc_info)]
            self._imagecache.update('context', instances, datastores_info)
