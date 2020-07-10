# Copyright 2013 OpenStack Foundation
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

import random
import time

import mock
from os_xenapi.client import exception as xenapi_exception
from os_xenapi.client import host_glance
from os_xenapi.client import XenAPI

from nova.compute import utils as compute_utils
from nova import context
from nova import exception
from nova.image import glance as common_glance
from nova.tests.unit.virt.xenapi import stubs
from nova import utils
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi.image import glance
from nova.virt.xenapi import vm_utils


class TestGlanceStore(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(TestGlanceStore, self).setUp()
        self.store = glance.GlanceStore()

        self.flags(api_servers=['http://localhost:9292'], group='glance')
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')

        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')

        fake.reset()
        stubs.stubout_session(self, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session

        self.stub_out('nova.virt.xenapi.vm_utils.get_sr_path',
                      lambda *a, **kw: '/fake/sr/path')

        self.instance = {'uuid': 'blah',
                         'system_metadata': [],
                         'auto_disk_config': True,
                         'os_type': 'default',
                         'xenapi_use_agent': 'true'}

    def _get_params(self):
        return {'image_id': 'fake_image_uuid',
                'endpoint': 'http://localhost:9292',
                'sr_path': '/fake/sr/path',
                'api_version': 2,
                'extra_headers': {'X-Auth-Token': 'foobar',
                                  'X-Roles': '',
                                  'X-Tenant-Id': 'project',
                                  'X-User-Id': 'user',
                                  'X-Identity-Status': 'Confirmed'}}

    def _get_download_params(self):
        params = self._get_params()
        params['uuid_stack'] = ['uuid1']
        return params

    @mock.patch.object(vm_utils, '_make_uuid_stack', return_value=['uuid1'])
    def test_download_image(self, mock_make_uuid_stack):
        params = self._get_download_params()
        with mock.patch.object(self.session, 'call_plugin_serialized'
                               ) as mock_call_plugin:
            self.store.download_image(self.context, self.session,
                                      self.instance, 'fake_image_uuid')

            mock_call_plugin.assert_called_once_with('glance.py',
                                                     'download_vhd2',
                                                     **params)
            mock_make_uuid_stack.assert_called_once_with()

    @mock.patch.object(vm_utils, '_make_uuid_stack', return_value=['uuid1'])
    @mock.patch.object(random, 'shuffle')
    @mock.patch.object(time, 'sleep')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_download_image_retry(self, mock_fault, mock_sleep,
                                  mock_shuffle, mock_make_uuid_stack):
        params = self._get_download_params()
        self.flags(num_retries=2, group='glance')

        params.pop("endpoint")
        calls = [mock.call('glance.py', 'download_vhd2',
                           endpoint='http://10.0.1.1:9292',
                           **params),
                 mock.call('glance.py', 'download_vhd2',
                           endpoint='http://10.0.0.1:9293',
                           **params)]

        glance_api_servers = ['http://10.0.1.1:9292',
                              'http://10.0.0.1:9293']
        self.flags(api_servers=glance_api_servers, group='glance')

        with (mock.patch.object(self.session, 'call_plugin_serialized')
          ) as mock_call_plugin_serialized:
            error_details = ["", "", "RetryableError", ""]
            error = self.session.XenAPI.Failure(details=error_details)
            mock_call_plugin_serialized.side_effect = [error, "success"]

            self.store.download_image(self.context, self.session,
                                      self.instance, 'fake_image_uuid')

            mock_call_plugin_serialized.assert_has_calls(calls)

            self.assertEqual(1, mock_fault.call_count)

    def _get_upload_params(self, auto_disk_config=True,
                           expected_os_type='default'):
        params = {}
        params['vdi_uuids'] = ['fake_vdi_uuid']
        params['properties'] = {'auto_disk_config': auto_disk_config,
                                'os_type': expected_os_type}
        return params

    @mock.patch.object(utils, 'get_auto_disk_config_from_instance')
    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image(self, mock_upload, mock_sr_path, mock_extra_header,
                          mock_disk_config):
        params = self._get_upload_params()
        mock_upload.return_value = 'fake_upload'
        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_disk_config.return_value = 'true'
        self.store.upload_image(self.context, self.session, self.instance,
                                'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)

    @mock.patch.object(utils, 'get_auto_disk_config_from_instance')
    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image_None_os_type(self, mock_upload, mock_sr_path,
                                       mock_extra_header, mock_disk_config):
        self.instance['os_type'] = None
        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_upload.return_value = 'fake_upload'
        mock_disk_config.return_value = 'true'
        params = self._get_upload_params(True, 'linux')
        self.store.upload_image(self.context, self.session, self.instance,
                                'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)
        mock_disk_config.assert_called_once_with(self.instance)

    @mock.patch.object(utils, 'get_auto_disk_config_from_instance')
    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image_no_os_type(self, mock_upload, mock_sr_path,
                                     mock_extra_header, mock_disk_config):
        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_upload.return_value = 'fake_upload'
        del self.instance['os_type']
        params = self._get_upload_params(True, 'linux')
        self.store.upload_image(self.context, self.session, self.instance,
                                'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)
        mock_disk_config.assert_called_once_with(self.instance)

    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image_auto_config_disk_disabled(
            self, mock_upload, mock_sr_path, mock_extra_header):
        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_upload.return_value = 'fake_upload'
        sys_meta = [{"key": "image_auto_disk_config", "value": "Disabled"}]
        self.instance["system_metadata"] = sys_meta
        params = self._get_upload_params("disabled")
        self.store.upload_image(self.context, self.session, self.instance,
                                'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)

    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image_raises_exception(self, mock_upload, mock_sr_path,
                                           mock_extra_header):

        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_upload.side_effect = RuntimeError
        params = self._get_upload_params()
        self.assertRaises(RuntimeError, self.store.upload_image,
                          self.context, self.session, self.instance,
                          'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_upload_image_retries_then_raises_exception(self,
                                                        mock_add_inst,
                                                        mock_time_sleep):
        self.flags(num_retries=2, group='glance')
        params = self._get_params()
        params.update(self._get_upload_params())

        error_details = ["", "", "RetryableError", ""]
        error = XenAPI.Failure(details=error_details)

        with mock.patch.object(self.session, 'call_plugin_serialized',
                               side_effect=error) as mock_call_plugin:
            self.assertRaises(exception.CouldNotUploadImage,
                              self.store.upload_image,
                              self.context, self.session, self.instance,
                              'fake_image_uuid', ['fake_vdi_uuid'])

            time_sleep_args = [mock.call(0.5), mock.call(1)]
            call_plugin_args = [
                mock.call('glance.py', 'upload_vhd2', **params),
                mock.call('glance.py', 'upload_vhd2', **params),
                mock.call('glance.py', 'upload_vhd2', **params)]
            add_inst_args = [
                mock.call(self.context, self.instance, error,
                          (XenAPI.Failure, error, mock.ANY)),
                mock.call(self.context, self.instance, error,
                          (XenAPI.Failure, error, mock.ANY)),
                mock.call(self.context, self.instance, error,
                          (XenAPI.Failure, error, mock.ANY))]
            mock_time_sleep.assert_has_calls(time_sleep_args)
            mock_call_plugin.assert_has_calls(call_plugin_args)
            mock_add_inst.assert_has_calls(add_inst_args)

    @mock.patch.object(time, 'sleep')
    @mock.patch.object(compute_utils, 'add_instance_fault_from_exc')
    def test_upload_image_retries_on_signal_exception(self,
                                                      mock_add_inst,
                                                      mock_time_sleep):
        self.flags(num_retries=2, group='glance')
        params = self._get_params()
        params.update(self._get_upload_params())

        error_details = ["", "task signaled", "", ""]
        error = XenAPI.Failure(details=error_details)

        # Note(johngarbutt) XenServer 6.1 and later has this error
        error_details_v61 = ["", "signal: SIGTERM", "", ""]
        error_v61 = self.session.XenAPI.Failure(details=error_details_v61)

        with mock.patch.object(self.session, 'call_plugin_serialized',
                               side_effect=[error, error_v61, None]
                               ) as mock_call_plugin:
            self.store.upload_image(self.context, self.session, self.instance,
                                    'fake_image_uuid', ['fake_vdi_uuid'])

            time_sleep_args = [mock.call(0.5), mock.call(1)]
            call_plugin_args = [
                mock.call('glance.py', 'upload_vhd2', **params),
                mock.call('glance.py', 'upload_vhd2', **params),
                mock.call('glance.py', 'upload_vhd2', **params)]
            add_inst_args = [
                mock.call(self.context, self.instance, error,
                          (XenAPI.Failure, error, mock.ANY)),
                mock.call(self.context, self.instance, error_v61,
                          (XenAPI.Failure, error_v61, mock.ANY))]
            mock_time_sleep.assert_has_calls(time_sleep_args)
            mock_call_plugin.assert_has_calls(call_plugin_args)
            mock_add_inst.assert_has_calls(add_inst_args)

    @mock.patch.object(utils, 'get_auto_disk_config_from_instance')
    @mock.patch.object(common_glance, 'generate_identity_headers')
    @mock.patch.object(vm_utils, 'get_sr_path')
    @mock.patch.object(host_glance, 'upload_vhd')
    def test_upload_image_raises_exception_image_not_found(self,
                                                           mock_upload,
                                                           mock_sr_path,
                                                           mock_extra_header,
                                                           mock_disk_config):
        params = self._get_upload_params()
        mock_upload.return_value = 'fake_upload'
        mock_sr_path.return_value = 'fake_sr_path'
        mock_extra_header.return_value = 'fake_extra_header'
        mock_disk_config.return_value = 'true'
        image_id = 'fake_image_id'
        mock_upload.side_effect = xenapi_exception.PluginImageNotFound(
            image_id=image_id
        )
        self.assertRaises(exception.ImageNotFound, self.store.upload_image,
                          self.context, self.session, self.instance,
                          'fake_image_uuid', ['fake_vdi_uuid'])

        mock_sr_path.assert_called_once_with(self.session)
        mock_extra_header.assert_called_once_with(self.context)
        mock_upload.assert_called_once_with(
            self.session, 3, mock.ANY, mock.ANY, 'fake_image_uuid',
            'fake_sr_path', 'fake_extra_header', **params)
