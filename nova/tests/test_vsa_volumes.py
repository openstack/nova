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


class VsaVolumesTestCase(test.TestCase):

    def setUp(self):
        super(VsaVolumesTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.vsa_api = vsa.API()
        self.volume_api = volume.API()
        self.context = context.get_admin_context()

        self.default_vol_type = self.vsa_api.get_vsa_volume_type(self.context)

        def fake_show_by_name(meh, context, name):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.image.fake._FakeImageService,
                        'show_by_name',
                        fake_show_by_name)

        param = {'display_name': 'VSA name test'}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.vsa_id = vsa_ref['id']

    def tearDown(self):
        if self.vsa_id:
            self.vsa_api.delete(self.context, self.vsa_id)
        self.stubs.UnsetAll()
        super(VsaVolumesTestCase, self).tearDown()

    def _default_volume_param(self):
        return {
            'size': 1,
            'snapshot_id': None,
            'name': 'Test volume name',
            'description': 'Test volume desc name',
            'volume_type': self.default_vol_type,
            'metadata': {'from_vsa_id': self.vsa_id}
            }

    def _get_all_volumes_by_vsa(self):
        return self.volume_api.get_all(self.context,
                search_opts={'metadata': {"from_vsa_id": str(self.vsa_id)}})

    def test_vsa_volume_create_delete(self):
        """ Check if volume properly created and deleted. """
        volume_param = self._default_volume_param()
        volume_ref = self.volume_api.create(self.context, **volume_param)

        self.assertEqual(volume_ref['display_name'],
                         volume_param['name'])
        self.assertEqual(volume_ref['display_description'],
                         volume_param['description'])
        self.assertEqual(volume_ref['size'],
                         volume_param['size'])
        self.assertEqual(volume_ref['status'],
                         'creating')

        vols2 = self._get_all_volumes_by_vsa()
        self.assertEqual(1, len(vols2))
        volume_ref = vols2[0]

        self.assertEqual(volume_ref['display_name'],
                         volume_param['name'])
        self.assertEqual(volume_ref['display_description'],
                         volume_param['description'])
        self.assertEqual(volume_ref['size'],
                         volume_param['size'])
        self.assertEqual(volume_ref['status'],
                         'creating')

        self.volume_api.update(self.context,
                    volume_ref['id'], {'status': 'available'})
        self.volume_api.delete(self.context, volume_ref['id'])

        vols3 = self._get_all_volumes_by_vsa()
        self.assertEqual(1, len(vols2))
        volume_ref = vols3[0]
        self.assertEqual(volume_ref['status'],
                         'deleting')

    def test_vsa_volume_delete_nonavail_volume(self):
        """ Check volume deleton in different states. """
        volume_param = self._default_volume_param()
        volume_ref = self.volume_api.create(self.context, **volume_param)

        self.volume_api.update(self.context,
                            volume_ref['id'], {'status': 'in-use'})
        self.assertRaises(exception.ApiError,
                            self.volume_api.delete,
                            self.context, volume_ref['id'])

    def test_vsa_volume_delete_vsa_with_volumes(self):
        """ Check volume deleton in different states. """

        vols1 = self._get_all_volumes_by_vsa()
        for i in range(3):
            volume_param = self._default_volume_param()
            volume_ref = self.volume_api.create(self.context, **volume_param)

        vols2 = self._get_all_volumes_by_vsa()
        self.assertEqual(len(vols1) + 3, len(vols2))

        self.vsa_api.delete(self.context, self.vsa_id)

        vols3 = self._get_all_volumes_by_vsa()
        self.assertEqual(len(vols1), len(vols3))
