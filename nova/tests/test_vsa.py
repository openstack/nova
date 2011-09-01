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

import base64
import stubout

from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import vsa
from nova import volume
from nova.volume import volume_types
from nova.vsa import utils as vsa_utils

import nova.image.fake

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.vsa')


class VsaTestCase(test.TestCase):

    def setUp(self):
        super(VsaTestCase, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        self.vsa_api = vsa.API()
        self.volume_api = volume.API()

        FLAGS.quota_volumes = 100
        FLAGS.quota_gigabytes = 10000

        self.context = context.get_admin_context()

        volume_types.create(self.context,
                            'SATA_500_7200',
                            extra_specs={'type': 'vsa_drive',
                                         'drive_name': 'SATA_500_7200',
                                         'drive_type': 'SATA',
                                         'drive_size': '500',
                                         'drive_rpm': '7200'})

        def fake_show_by_name(meh, context, name):
            if name == 'wrong_image_name':
                LOG.debug(_("Test: Emulate wrong VSA name. Raise"))
                raise exception.ImageNotFound
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.image.fake._FakeImageService,
                        'show_by_name',
                        fake_show_by_name)

    def tearDown(self):
        self.stubs.UnsetAll()
        super(VsaTestCase, self).tearDown()

    def test_vsa_create_delete_defaults(self):
        param = {'display_name': 'VSA name test'}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.assertEqual(vsa_ref['display_name'], param['display_name'])
        self.vsa_api.delete(self.context, vsa_ref['id'])

    def test_vsa_create_delete_check_in_db(self):
        vsa_list1 = self.vsa_api.get_all(self.context)
        vsa_ref = self.vsa_api.create(self.context)
        vsa_list2 = self.vsa_api.get_all(self.context)
        self.assertEqual(len(vsa_list2), len(vsa_list1) + 1)

        self.vsa_api.delete(self.context, vsa_ref['id'])
        vsa_list3 = self.vsa_api.get_all(self.context)
        self.assertEqual(len(vsa_list3), len(vsa_list2) - 1)

    def test_vsa_create_delete_high_vc_count(self):
        param = {'vc_count': FLAGS.max_vcs_in_vsa + 1}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.assertEqual(vsa_ref['vc_count'], FLAGS.max_vcs_in_vsa)
        self.vsa_api.delete(self.context, vsa_ref['id'])

    def test_vsa_create_wrong_image_name(self):
        param = {'image_name': 'wrong_image_name'}
        self.assertRaises(exception.ApiError,
                          self.vsa_api.create, self.context, **param)

    def test_vsa_create_db_error(self):

        def fake_vsa_create(context, options):
            LOG.debug(_("Test: Emulate DB error. Raise"))
            raise exception.Error

        self.stubs.Set(nova.db.api, 'vsa_create', fake_vsa_create)
        self.assertRaises(exception.ApiError,
                          self.vsa_api.create, self.context)

    def test_vsa_create_wrong_storage_params(self):
        vsa_list1 = self.vsa_api.get_all(self.context)
        param = {'storage': [{'stub': 1}]}
        self.assertRaises(exception.ApiError,
                          self.vsa_api.create, self.context, **param)
        vsa_list2 = self.vsa_api.get_all(self.context)
        self.assertEqual(len(vsa_list2), len(vsa_list1))

        param = {'storage': [{'drive_name': 'wrong name'}]}
        self.assertRaises(exception.ApiError,
                          self.vsa_api.create, self.context, **param)

    def test_vsa_create_with_storage(self, multi_vol_creation=True):
        """Test creation of VSA with BE storage"""

        FLAGS.vsa_multi_vol_creation = multi_vol_creation

        param = {'storage': [{'drive_name': 'SATA_500_7200',
                              'num_drives': 3}]}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.assertEqual(vsa_ref['vol_count'], 3)
        self.vsa_api.delete(self.context, vsa_ref['id'])

        param = {'storage': [{'drive_name': 'SATA_500_7200',
                              'num_drives': 3}],
                 'shared': True}
        vsa_ref = self.vsa_api.create(self.context, **param)
        self.assertEqual(vsa_ref['vol_count'], 15)
        self.vsa_api.delete(self.context, vsa_ref['id'])

    def test_vsa_create_with_storage_single_volumes(self):
        self.test_vsa_create_with_storage(multi_vol_creation=False)

    def test_vsa_update(self):
        vsa_ref = self.vsa_api.create(self.context)

        param = {'vc_count': FLAGS.max_vcs_in_vsa + 1}
        vsa_ref = self.vsa_api.update(self.context, vsa_ref['id'], **param)
        self.assertEqual(vsa_ref['vc_count'], FLAGS.max_vcs_in_vsa)

        param = {'vc_count': 2}
        vsa_ref = self.vsa_api.update(self.context, vsa_ref['id'], **param)
        self.assertEqual(vsa_ref['vc_count'], 2)

        self.vsa_api.delete(self.context, vsa_ref['id'])

    def test_vsa_generate_user_data(self):

        FLAGS.vsa_multi_vol_creation = False
        param = {'display_name': 'VSA name test',
                 'display_description': 'VSA desc test',
                 'vc_count': 2,
                 'storage': [{'drive_name': 'SATA_500_7200',
                              'num_drives': 3}]}
        vsa_ref = self.vsa_api.create(self.context, **param)
        volumes = self.vsa_api.get_all_vsa_drives(self.context,
                                                  vsa_ref['id'])

        user_data = vsa_utils.generate_user_data(vsa_ref, volumes)
        user_data = base64.b64decode(user_data)

        LOG.debug(_("Test: user_data = %s"), user_data)

        elem = ElementTree.fromstring(user_data)
        self.assertEqual(elem.findtext('name'),
                         param['display_name'])
        self.assertEqual(elem.findtext('description'),
                         param['display_description'])
        self.assertEqual(elem.findtext('vc_count'),
                         str(param['vc_count']))

        self.vsa_api.delete(self.context, vsa_ref['id'])
