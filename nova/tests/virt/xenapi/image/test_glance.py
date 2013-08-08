# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


import mox

from nova import context
from nova import exception
from nova.tests.virt.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi.image import glance
from nova.virt.xenapi import vm_utils


class TestGlanceStore(stubs.XenAPITestBase):
    def setUp(self):
        super(TestGlanceStore, self).setUp()
        self.store = glance.GlanceStore()
        self.mox = mox.Mox()

        self.flags(glance_host='1.1.1.1',
                   glance_port=123,
                   glance_api_insecure=False,
                   xenapi_connection_url='test_url',
                   xenapi_connection_password='test_pass')

        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')

        fake.reset()
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session

        self.stubs.Set(
                vm_utils, 'get_sr_path', lambda *a, **kw: '/fake/sr/path')

        self.instance = {'uuid': 'blah',
                         'system_metadata': [],
                         'auto_disk_config': True,
                         'os_type': 'default',
                         'xenapi_use_agent': 'true'}

    def test_download_image(self):
        params = {'image_id': 'fake_image_uuid',
                  'glance_host': '1.1.1.1',
                  'glance_port': 123,
                  'glance_use_ssl': False,
                  'sr_path': '/fake/sr/path',
                  'auth_token': 'foobar',
                  'uuid_stack': ['uuid1']}

        self.stubs.Set(vm_utils, '_make_uuid_stack',
                       lambda *a, **kw: ['uuid1'])

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'download_vhd', **params)
        self.mox.ReplayAll()

        vdis = self.store.download_image(
                self.context, self.session, self.instance, 'fake_image_uuid')

        self.mox.VerifyAll()

    def _get_upload_params(self):
        params = {'vdi_uuids': ['fake_vdi_uuid'],
                  'image_id': 'fake_image_uuid',
                  'glance_host': '1.1.1.1',
                  'glance_port': 123,
                  'glance_use_ssl': False,
                  'sr_path': '/fake/sr/path',
                  'auth_token': 'foobar',
                  'properties': {'auto_disk_config': True,
                                 'os_type': 'default'}}
        return params

    def test_upload_image(self):
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'upload_vhd', **params)

        self.mox.ReplayAll()
        self.store.upload_image(self.context, self.session, self.instance,
                                ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image_raises_exception(self):
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(Exception)
        self.mox.ReplayAll()

        self.assertRaises(Exception, self.store.upload_image,
                          self.context, self.session, self.instance,
                          ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image_retries_then_raises_exception(self):
        self.flags(glance_num_retries=2)
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        error_details = ["", "", "RetryableError", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        self.mox.ReplayAll()

        self.assertRaises(exception.CouldNotUploadImage,
                          self.store.upload_image,
                          self.context, self.session, self.instance,
                          ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image_retries_on_signal_exception(self):
        self.flags(glance_num_retries=2)
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        error_details = ["", "task signaled", "", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        # Note(johngarbutt) XenServer 6.1 and later has this error
        error_details = ["", "signal: SIGTERM", "", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params)
        self.mox.ReplayAll()

        self.store.upload_image(self.context, self.session, self.instance,
                                ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()
