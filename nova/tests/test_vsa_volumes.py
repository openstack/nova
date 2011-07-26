# Copyright 2011 OpenStack LLC.
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

import stubout

from nova import exception
from nova import flags
from nova import vsa
from nova import volume
from nova import db
from nova import context
from nova import test
from nova import log as logging
import nova.image.fake

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.vsa.volumes')


def _default_volume_param():
    return {
        'size': 1,
        'snapshot_id': None,
        'name': 'Test volume name',
        'description': 'Test volume desc name'
        }


class VsaVolumesTestCase(test.TestCase):

    def setUp(self):
        super(VsaVolumesTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.vsa_api = vsa.API()
        self.volume_api = volume.API()

        self.context_non_admin = context.RequestContext(None, None)
        self.context = context.get_admin_context()

        def fake_show_by_name(meh, context, name):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.image.fake._FakeImageService,
                        'show_by_name',
                        fake_show_by_name)

        param = {'display_name': 'VSA name test'}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.vsa_id = vsa_ref['id']

    def tearDown(self):
        self.vsa_api.delete(self.context, self.vsa_id)
        self.stubs.UnsetAll()
        super(VsaVolumesTestCase, self).tearDown()

    def test_vsa_volume_create_delete(self):
        """ Check if volume properly created and deleted. """
        vols1 = self.volume_api.get_all_by_vsa(self.context, 
                                                self.vsa_id, "from")
        volume_param = _default_volume_param()
        volume_param['from_vsa_id'] = self.vsa_id
        volume_ref = self.volume_api.create(self.context, **volume_param)

        self.assertEqual(volume_ref['display_name'],
                         volume_param['name'])
        self.assertEqual(volume_ref['display_description'],
                         volume_param['description'])
        self.assertEqual(volume_ref['size'],
                         volume_param['size'])
        self.assertEqual(volume_ref['status'],
                         'available')

        vols2 = self.volume_api.get_all_by_vsa(self.context, 
                                                self.vsa_id, "from")
        self.assertEqual(len(vols1) + 1, len(vols2))

        self.volume_api.delete(self.context, volume_ref['id'])
        vols3 = self.volume_api.get_all_by_vsa(self.context,
                                                self.vsa_id, "from")
        self.assertEqual(len(vols3) + 1, len(vols2))
        
    def test_vsa_volume_delete_nonavail_volume(self):
        """ Check volume deleton in different states. """
        volume_param = _default_volume_param()
        volume_param['from_vsa_id'] = self.vsa_id
        volume_ref = self.volume_api.create(self.context, **volume_param)

        self.volume_api.update(self.context,
                            volume_ref['id'], {'status': 'in-use'})
        self.assertRaises(exception.ApiError,
                            self.volume_api.delete,
                            self.context, volume_ref['id'])

        self.volume_api.update(self.context,
                            volume_ref['id'], {'status': 'error'})
        self.volume_api.delete(self.context, volume_ref['id'])
