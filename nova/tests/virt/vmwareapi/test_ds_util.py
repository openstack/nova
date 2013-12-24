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

import contextlib
import mock

from nova import test
from nova.virt.vmwareapi import ds_util
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake


class fake_session(object):
    def __init__(self, ret=None):
        self.ret = ret

    def _get_vim(self):
        return fake.FakeVim()

    def _call_method(self, module, method, *args, **kwargs):
        return self.ret

    def _wait_for_task(self, task_ref):
        task_info = self._call_method('module', "get_dynamic_property",
                        task_ref, "Task", "info")
        task_name = task_info.name
        if task_info.state == 'success':
            return task_info
        else:
            error_info = 'fake error'
            error = task_info.error
            name = error.fault.__class__.__name__
            raise error_util.get_fault_class(name)(error_info)


class DsUtilTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DsUtilTestCase, self).setUp()
        self.session = fake_session()
        self.flags(api_retry_count=1, group='vmware')
        fake.reset()

    def tearDown(self):
        super(DsUtilTestCase, self).tearDown()
        fake.reset()

    def test_build_datastore_path(self):
        path = ds_util.build_datastore_path('ds', 'folder')
        self.assertEqual('[ds] folder', path)
        path = ds_util.build_datastore_path('ds', 'folder/file')
        self.assertEqual('[ds] folder/file', path)

    def test_split_datastore_path(self):
        ds, path = ds_util.split_datastore_path('[ds]')
        self.assertEqual('ds', ds)
        self.assertEqual('', path)
        ds, path = ds_util.split_datastore_path('[ds] folder')
        self.assertEqual('ds', ds)
        self.assertEqual('folder', path)
        ds, path = ds_util.split_datastore_path('[ds] folder/file')
        self.assertEqual('ds', ds)
        self.assertEqual('folder/file', path)
        self.assertRaises(IndexError,
                          ds_util.split_datastore_path,
                          'split bad path')

    def test_file_delete(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('DeleteDatastoreFile_Task', method)
            name = kwargs.get('name')
            self.assertEqual('fake-datastore-path', name)
            datacenter = kwargs.get('datacenter')
            self.assertEqual('fake-dc-ref', datacenter)
            return 'fake_delete_task'

        with contextlib.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            ds_util.file_delete(self.session,
                                'fake-datastore-path', 'fake-dc-ref')
            _wait_for_task.assert_has_calls([
                   mock.call('fake_delete_task')])

    def test_file_move(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('MoveDatastoreFile_Task', method)
            sourceName = kwargs.get('sourceName')
            self.assertEqual('[ds] tmp/src', sourceName)
            destinationName = kwargs.get('destinationName')
            self.assertEqual('[ds] base/dst', destinationName)
            sourceDatacenter = kwargs.get('sourceDatacenter')
            self.assertEqual('fake-dc-ref', sourceDatacenter)
            destinationDatacenter = kwargs.get('destinationDatacenter')
            self.assertEqual('fake-dc-ref', destinationDatacenter)
            return 'fake_move_task'

        with contextlib.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            ds_util.file_move(self.session,
                              'fake-dc-ref', '[ds] tmp/src', '[ds] base/dst')
            _wait_for_task.assert_has_calls([
                   mock.call('fake_move_task')])

    def test_mkdir(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('MakeDirectory', method)
            name = kwargs.get('name')
            self.assertEqual('fake-path', name)
            datacenter = kwargs.get('datacenter')
            self.assertEqual('fake-dc-ref', datacenter)
            createParentDirectories = kwargs.get('createParentDirectories')
            self.assertTrue(createParentDirectories)

        with mock.patch.object(self.session, '_call_method',
                               fake_call_method):
            ds_util.mkdir(self.session, 'fake-path', 'fake-dc-ref')

    def test_file_exists(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'SearchDatastore_Task':
                ds_browser = args[0]
                self.assertEqual('fake-browser', ds_browser)
                datastorePath = kwargs.get('datastorePath')
                self.assertEqual('fake-path', datastorePath)
                return 'fake_exists_task'
            elif method == 'get_dynamic_property':
                info = fake.DataObject()
                info.name = 'search_task'
                info.state = 'success'
                result = fake.DataObject()
                result.path = 'fake-path'
                matched = fake.DataObject()
                matched.path = 'fake-file'
                result.file = [matched]
                info.result = result
                return info
            # Should never get here
            self.fail()

        with mock.patch.object(self.session, '_call_method',
                               fake_call_method):
            file_exists = ds_util.file_exists(self.session,
                    'fake-browser', 'fake-path', 'fake-file')
            self.assertTrue(file_exists)

    def test_file_exists_fails(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'SearchDatastore_Task':
                return 'fake_exists_task'
            elif method == 'get_dynamic_property':
                info = fake.DataObject()
                info.name = 'search_task'
                info.state = 'error'
                error = fake.DataObject()
                error.localizedMessage = "Error message"
                error.fault = fake.FileNotFound()
                info.error = error
                return info
            # Should never get here
            self.fail()

        with mock.patch.object(self.session, '_call_method',
                               fake_call_method):
            file_exists = ds_util.file_exists(self.session,
                    'fake-browser', 'fake-path', 'fake-file')
            self.assertFalse(file_exists)
