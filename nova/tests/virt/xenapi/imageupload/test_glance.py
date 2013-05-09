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
from nova import test
from nova.virt.xenapi.imageupload import glance
from nova.virt.xenapi import vm_utils


class TestGlanceStore(test.TestCase):
    def setUp(self):
        super(TestGlanceStore, self).setUp()
        self.store = glance.GlanceStore()
        self.mox = mox.Mox()

    def test_upload_image(self):
        glance_host = '0.1.2.3'
        glance_port = 8143
        glance_use_ssl = False
        sr_path = '/fake/sr/path'
        self.flags(glance_host=glance_host)
        self.flags(glance_port=glance_port)
        self.flags(glance_api_insecure=glance_use_ssl)

        def fake_get_sr_path(*_args, **_kwargs):
            return sr_path

        self.stubs.Set(vm_utils, 'get_sr_path', fake_get_sr_path)

        ctx = context.RequestContext('user', 'project', auth_token='foobar')
        properties = {
            'auto_disk_config': True,
            'os_type': 'default',
            'xenapi_use_agent': 'true',
        }
        image_id = 'fake_image_uuid'
        vdi_uuids = ['fake_vdi_uuid']
        instance = {'uuid': 'blah',
                    'system_metadata': {'image_xenapi_use_agent': 'true'}}
        instance.update(properties)

        params = {'vdi_uuids': vdi_uuids,
                  'image_id': image_id,
                  'glance_host': glance_host,
                  'glance_port': glance_port,
                  'glance_use_ssl': glance_use_ssl,
                  'sr_path': sr_path,
                  'auth_token': 'foobar',
                  'properties': properties}
        session = self.mox.CreateMockAnything()
        session.call_plugin_serialized('glance', 'upload_vhd', **params)
        self.mox.ReplayAll()

        self.store.upload_image(ctx, session, instance, vdi_uuids, image_id)

        self.mox.VerifyAll()
