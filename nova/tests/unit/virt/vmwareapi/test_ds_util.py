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

import re

import mock
from oslo_utils import units
from oslo_vmware import exceptions as vexc
from oslo_vmware.objects import datastore as ds_obj

from nova import exception
from nova import test
from nova.tests.unit.virt.vmwareapi import fake
from nova.virt.vmwareapi import ds_util


class DsUtilTestCase(test.NoDBTestCase):
    def setUp(self):
        super(DsUtilTestCase, self).setUp()
        self.session = fake.FakeSession()
        self.flags(api_retry_count=1, group='vmware')
        fake.reset()

    def tearDown(self):
        super(DsUtilTestCase, self).tearDown()
        fake.reset()

    def test_get_datacenter_ref(self):
        with mock.patch.object(self.session, '_call_method') as call_method:
            ds_util.get_datacenter_ref(self.session, "datacenter")
            call_method.assert_called_once_with(
                self.session.vim,
                "FindByInventoryPath",
                self.session.vim.service_content.searchIndex,
                inventoryPath="datacenter")

    def test_file_delete(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('DeleteDatastoreFile_Task', method)
            name = kwargs.get('name')
            self.assertEqual('[ds] fake/path', name)
            datacenter = kwargs.get('datacenter')
            self.assertEqual('fake-dc-ref', datacenter)
            return 'fake_delete_task'

        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            ds_path = ds_obj.DatastorePath('ds', 'fake/path')
            ds_util.file_delete(self.session,
                                ds_path, 'fake-dc-ref')
            _wait_for_task.assert_has_calls([
                   mock.call('fake_delete_task')])

    def test_file_copy(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('CopyDatastoreFile_Task', method)
            src_name = kwargs.get('sourceName')
            self.assertEqual('[ds] fake/path/src_file', src_name)
            src_dc_ref = kwargs.get('sourceDatacenter')
            self.assertEqual('fake-src-dc-ref', src_dc_ref)
            dst_name = kwargs.get('destinationName')
            self.assertEqual('[ds] fake/path/dst_file', dst_name)
            dst_dc_ref = kwargs.get('destinationDatacenter')
            self.assertEqual('fake-dst-dc-ref', dst_dc_ref)
            return 'fake_copy_task'

        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            src_ds_path = ds_obj.DatastorePath('ds', 'fake/path', 'src_file')
            dst_ds_path = ds_obj.DatastorePath('ds', 'fake/path', 'dst_file')
            ds_util.file_copy(self.session,
                              str(src_ds_path), 'fake-src-dc-ref',
                              str(dst_ds_path), 'fake-dst-dc-ref')
            _wait_for_task.assert_has_calls([
                   mock.call('fake_copy_task')])

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

        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            src_ds_path = ds_obj.DatastorePath('ds', 'tmp/src')
            dst_ds_path = ds_obj.DatastorePath('ds', 'base/dst')
            ds_util.file_move(self.session,
                              'fake-dc-ref', src_ds_path, dst_ds_path)
            _wait_for_task.assert_has_calls([
                   mock.call('fake_move_task')])

    def test_disk_move(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('MoveVirtualDisk_Task', method)
            src_name = kwargs.get('sourceName')
            self.assertEqual('[ds] tmp/src', src_name)
            dest_name = kwargs.get('destName')
            self.assertEqual('[ds] base/dst', dest_name)
            src_datacenter = kwargs.get('sourceDatacenter')
            self.assertEqual('fake-dc-ref', src_datacenter)
            dest_datacenter = kwargs.get('destDatacenter')
            self.assertEqual('fake-dc-ref', dest_datacenter)
            return 'fake_move_task'

        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              fake_call_method)
        ) as (_wait_for_task, _call_method):
            ds_util.disk_move(self.session,
                              'fake-dc-ref', '[ds] tmp/src', '[ds] base/dst')
            _wait_for_task.assert_has_calls([
                   mock.call('fake_move_task')])

    def test_disk_copy(self):
        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              return_value=mock.sentinel.cm)
        ) as (_wait_for_task, _call_method):
            ds_util.disk_copy(self.session, mock.sentinel.dc_ref,
                              mock.sentinel.source_ds, mock.sentinel.dest_ds)
            _wait_for_task.assert_called_once_with(mock.sentinel.cm)
            _call_method.assert_called_once_with(
                    mock.ANY, 'CopyVirtualDisk_Task', 'VirtualDiskManager',
                    sourceName='sentinel.source_ds',
                    destDatacenter=mock.sentinel.dc_ref,
                    sourceDatacenter=mock.sentinel.dc_ref, force=False,
                    destName='sentinel.dest_ds')

    def test_disk_delete(self):
        with test.nested(
            mock.patch.object(self.session, '_wait_for_task'),
            mock.patch.object(self.session, '_call_method',
                              return_value=mock.sentinel.cm)
        ) as (_wait_for_task, _call_method):
            ds_util.disk_delete(self.session,
                                'fake-dc-ref', '[ds] tmp/disk.vmdk')
            _wait_for_task.assert_called_once_with(mock.sentinel.cm)
            _call_method.assert_called_once_with(
                    mock.ANY, 'DeleteVirtualDisk_Task', 'VirtualDiskManager',
                    datacenter='fake-dc-ref', name='[ds] tmp/disk.vmdk')

    def test_mkdir(self):
        def fake_call_method(module, method, *args, **kwargs):
            self.assertEqual('MakeDirectory', method)
            name = kwargs.get('name')
            self.assertEqual('[ds] fake/path', name)
            datacenter = kwargs.get('datacenter')
            self.assertEqual('fake-dc-ref', datacenter)
            createParentDirectories = kwargs.get('createParentDirectories')
            self.assertTrue(createParentDirectories)

        with mock.patch.object(self.session, '_call_method',
                               fake_call_method):
            ds_path = ds_obj.DatastorePath('ds', 'fake/path')
            ds_util.mkdir(self.session, ds_path, 'fake-dc-ref')

    def test_file_exists(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'SearchDatastore_Task':
                ds_browser = args[0]
                self.assertEqual('fake-browser', ds_browser)
                datastorePath = kwargs.get('datastorePath')
                self.assertEqual('[ds] fake/path', datastorePath)
                return 'fake_exists_task'

            # Should never get here
            self.fail()

        def fake_wait_for_task(task_ref):
            if task_ref == 'fake_exists_task':
                result_file = fake.DataObject()
                result_file.path = 'fake-file'

                result = fake.DataObject()
                result.file = [result_file]
                result.path = '[ds] fake/path'

                task_info = fake.DataObject()
                task_info.result = result

                return task_info

            # Should never get here
            self.fail()

        with test.nested(
                mock.patch.object(self.session, '_call_method',
                                  fake_call_method),
                mock.patch.object(self.session, '_wait_for_task',
                                  fake_wait_for_task)):
            ds_path = ds_obj.DatastorePath('ds', 'fake/path')
            file_exists = ds_util.file_exists(self.session,
                    'fake-browser', ds_path, 'fake-file')
            self.assertTrue(file_exists)

    def test_file_exists_fails(self):
        def fake_call_method(module, method, *args, **kwargs):
            if method == 'SearchDatastore_Task':
                return 'fake_exists_task'

            # Should never get here
            self.fail()

        def fake_wait_for_task(task_ref):
            if task_ref == 'fake_exists_task':
                raise vexc.FileNotFoundException()

            # Should never get here
            self.fail()

        with test.nested(
                mock.patch.object(self.session, '_call_method',
                                  fake_call_method),
                mock.patch.object(self.session, '_wait_for_task',
                                  fake_wait_for_task)):
            ds_path = ds_obj.DatastorePath('ds', 'fake/path')
            file_exists = ds_util.file_exists(self.session,
                    'fake-browser', ds_path, 'fake-file')
            self.assertFalse(file_exists)

    def _mock_get_datastore_calls(self, *datastores):
        """Mock vim_util calls made by get_datastore."""

        datastores_i = [None]

        # For the moment, at least, this list of datastores is simply passed to
        # get_properties_for_a_collection_of_objects, which we mock below. We
        # don't need to over-complicate the fake function by worrying about its
        # contents.
        fake_ds_list = ['fake-ds']

        def fake_call_method(module, method, *args, **kwargs):
            # Mock the call which returns a list of datastores for the cluster
            if (module == ds_util.vutil and
                    method == 'get_object_property' and
                    args == ('fake-cluster', 'datastore')):
                fake_ds_mor = fake.DataObject()
                fake_ds_mor.ManagedObjectReference = fake_ds_list
                return fake_ds_mor

            # Return the datastore result sets we were passed in, in the order
            # given
            if (module == ds_util.vim_util and
                    method == 'get_properties_for_a_collection_of_objects' and
                    args[0] == 'Datastore' and
                    args[1] == fake_ds_list):
                # Start a new iterator over given datastores
                datastores_i[0] = iter(datastores)
                return next(datastores_i[0])

            # Continue returning results from the current iterator.
            if (module == ds_util.vutil and
                    method == 'continue_retrieval'):
                try:
                    return next(datastores_i[0])
                except StopIteration:
                    return None

            if (method == 'continue_retrieval' or
                method == 'cancel_retrieval'):
                return

            # Sentinel that get_datastore's use of vim has changed
            self.fail('Unexpected vim call in get_datastore: %s' % method)

        return mock.patch.object(self.session, '_call_method',
                                 side_effect=fake_call_method)

    def test_get_datastore(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore())
        fake_objects.add_object(fake.Datastore("fake-ds-2", 2048, 1000,
                                               False, "normal"))
        fake_objects.add_object(fake.Datastore("fake-ds-3", 4096, 2000,
                                               True, "inMaintenance"))

        with self._mock_get_datastore_calls(fake_objects):
            result = ds_util.get_datastore(self.session, 'fake-cluster')
        self.assertEqual("fake-ds", result.name)
        self.assertEqual(units.Ti, result.capacity)
        self.assertEqual(500 * units.Gi, result.freespace)

    def test_get_datastore_with_regex(self):
        # Test with a regex that matches with a datastore
        datastore_valid_regex = re.compile(r"^openstack.*\d$")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))

        with self._mock_get_datastore_calls(fake_objects):
            result = ds_util.get_datastore(self.session, 'fake-cluster',
                                           datastore_valid_regex)
        self.assertEqual("openstack-ds0", result.name)

    def test_get_datastore_with_token(self):
        regex = re.compile(r"^ds.*\d$")
        fake0 = fake.FakeRetrieveResult()
        fake0.add_object(fake.Datastore("ds0", 10 * units.Gi, 5 * units.Gi))
        fake0.add_object(fake.Datastore("foo", 10 * units.Gi, 9 * units.Gi))
        setattr(fake0, 'token', 'token-0')
        fake1 = fake.FakeRetrieveResult()
        fake1.add_object(fake.Datastore("ds2", 10 * units.Gi, 8 * units.Gi))
        fake1.add_object(fake.Datastore("ds3", 10 * units.Gi, 1 * units.Gi))

        with self._mock_get_datastore_calls(fake0, fake1):
            result = ds_util.get_datastore(self.session, 'fake-cluster', regex)
        self.assertEqual("ds2", result.name)

    def test_get_datastore_with_list(self):
        # Test with a regex containing whitelist of datastores
        datastore_valid_regex = re.compile("(openstack-ds0|openstack-ds2)")
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("openstack-ds0"))
        fake_objects.add_object(fake.Datastore("openstack-ds1"))
        fake_objects.add_object(fake.Datastore("openstack-ds2"))

        with self._mock_get_datastore_calls(fake_objects):
            result = ds_util.get_datastore(self.session, 'fake-cluster',
                                           datastore_valid_regex)
        self.assertNotEqual("openstack-ds1", result.name)

    def test_get_datastore_with_regex_error(self):
        # Test with a regex that has no match
        # Checks if code raises DatastoreNotFound with a specific message
        datastore_invalid_regex = re.compile("unknown-ds")
        exp_message = ("Datastore regex %s did not match any datastores"
                       % datastore_invalid_regex.pattern)
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.Datastore("fake-ds0"))
        fake_objects.add_object(fake.Datastore("fake-ds1"))
        # assertRaisesRegExp would have been a good choice instead of
        # try/catch block, but it's available only from Py 2.7.
        try:
            with self._mock_get_datastore_calls(fake_objects):
                ds_util.get_datastore(self.session, 'fake-cluster',
                                      datastore_invalid_regex)
        except exception.DatastoreNotFound as e:
            self.assertEqual(exp_message, e.args[0])
        else:
            self.fail("DatastoreNotFound Exception was not raised with "
                      "message: %s" % exp_message)

    def test_get_datastore_without_datastore(self):
        self.assertRaises(exception.DatastoreNotFound,
                ds_util.get_datastore,
                fake.FakeObjectRetrievalSession(None), cluster="fake-cluster")

    def test_get_datastore_inaccessible_ds(self):
        data_store = fake.Datastore()
        data_store.set("summary.accessible", False)

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(data_store)

        with self._mock_get_datastore_calls(fake_objects):
            self.assertRaises(exception.DatastoreNotFound,
                              ds_util.get_datastore,
                              self.session, 'fake-cluster')

    def test_get_datastore_ds_in_maintenance(self):
        data_store = fake.Datastore()
        data_store.set("summary.maintenanceMode", "inMaintenance")

        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(data_store)

        with self._mock_get_datastore_calls(fake_objects):
            self.assertRaises(exception.DatastoreNotFound,
                              ds_util.get_datastore,
                              self.session, 'fake-cluster')

    def test_get_datastore_no_host_in_cluster(self):
        def fake_call_method(module, method, *args, **kwargs):
            return ''

        with mock.patch.object(self.session, '_call_method',
                               fake_call_method):
            self.assertRaises(exception.DatastoreNotFound,
                              ds_util.get_datastore,
                              self.session, 'fake-cluster')

    def _test_is_datastore_valid(self, accessible=True,
                                 maintenance_mode="normal",
                                 type="VMFS",
                                 datastore_regex=None,
                                 ds_types=ds_util.ALL_SUPPORTED_DS_TYPES):
        propdict = {}
        propdict["summary.accessible"] = accessible
        propdict["summary.maintenanceMode"] = maintenance_mode
        propdict["summary.type"] = type
        propdict["summary.name"] = "ds-1"

        return ds_util._is_datastore_valid(propdict, datastore_regex, ds_types)

    def test_is_datastore_valid(self):
        for ds_type in ds_util.ALL_SUPPORTED_DS_TYPES:
            self.assertTrue(self._test_is_datastore_valid(True,
                                                          "normal",
                                                          ds_type))

    def test_is_datastore_valid_inaccessible_ds(self):
        self.assertFalse(self._test_is_datastore_valid(False,
                                                      "normal",
                                                      "VMFS"))

    def test_is_datastore_valid_ds_in_maintenance(self):
        self.assertFalse(self._test_is_datastore_valid(True,
                                                      "inMaintenance",
                                                      "VMFS"))

    def test_is_datastore_valid_ds_type_invalid(self):
        self.assertFalse(self._test_is_datastore_valid(True,
                                                      "normal",
                                                      "vfat"))

    def test_is_datastore_valid_not_matching_regex(self):
        datastore_regex = re.compile("ds-2")
        self.assertFalse(self._test_is_datastore_valid(True,
                                                      "normal",
                                                      "VMFS",
                                                      datastore_regex))

    def test_is_datastore_valid_matching_regex(self):
        datastore_regex = re.compile("ds-1")
        self.assertTrue(self._test_is_datastore_valid(True,
                                                      "normal",
                                                      "VMFS",
                                                      datastore_regex))

    def test_get_connected_hosts_none(self):
        with mock.patch.object(self.session,
                               '_call_method') as _call_method:
            hosts = ds_util.get_connected_hosts(self.session,
                                                'fake_datastore')
            self.assertEqual([], hosts)
            _call_method.assert_called_once_with(
                    mock.ANY, 'get_object_property',
                    'fake_datastore', 'host')

    def test_get_connected_hosts(self):
        host = mock.Mock(spec=object)
        host.value = 'fake-host'
        host_mount = mock.Mock(spec=object)
        host_mount.key = host
        host_mounts = mock.Mock(spec=object)
        host_mounts.DatastoreHostMount = [host_mount]

        with mock.patch.object(self.session, '_call_method',
                               return_value=host_mounts) as _call_method:
            hosts = ds_util.get_connected_hosts(self.session,
                                                'fake_datastore')
            self.assertEqual(['fake-host'], hosts)
            _call_method.assert_called_once_with(
                    mock.ANY, 'get_object_property',
                    'fake_datastore', 'host')
