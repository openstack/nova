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

import mock

from eventlet import greenthread

from nova.tests.virt.xenapi import stubs
from nova.virt.xenapi import volume_utils


class SROps(stubs.XenAPITestBaseNoDB):
    def test_find_sr_valid_uuid(self):
        self.session = mock.Mock()
        self.session.call_xenapi.return_value = 'sr_ref'
        self.assertEqual(volume_utils.find_sr_by_uuid(self.session,
                                                      'sr_uuid'),
                         'sr_ref')

    def test_find_sr_invalid_uuid(self):
        class UUIDException(Exception):
            details = ["UUID_INVALID", "", "", ""]

        self.session = mock.Mock()
        self.session.XenAPI.Failure = UUIDException
        self.session.call_xenapi.side_effect = UUIDException
        self.assertEqual(volume_utils.find_sr_by_uuid(self.session,
                                                      'sr_uuid'),
                         None)


class ISCSIParametersTestCase(stubs.XenAPITestBaseNoDB):
    def test_target_host(self):
        self.assertEqual(volume_utils._get_target_host('host:port'),
                         'host')

        self.assertEqual(volume_utils._get_target_host('host'),
                         'host')

        # There is no default value
        self.assertEqual(volume_utils._get_target_host(':port'),
                         None)

        self.assertEqual(volume_utils._get_target_host(None),
                         None)

    def test_target_port(self):
        self.assertEqual(volume_utils._get_target_port('host:port'),
                         'port')

        self.assertEqual(volume_utils._get_target_port('host'),
                         '3260')


class IntroduceTestCase(stubs.XenAPITestBaseNoDB):

    @mock.patch.object(volume_utils, '_get_vdi_ref')
    @mock.patch.object(greenthread, 'sleep')
    def test_introduce_vdi_retry(self, mock_sleep, mock_get_vdi_ref):
        def fake_get_vdi_ref(session, sr_ref, vdi_uuid, target_lun):
            fake_get_vdi_ref.call_count += 1
            if fake_get_vdi_ref.call_count == 2:
                return 'vdi_ref'

        def fake_call_xenapi(method, *args):
            if method == 'SR.scan':
                return
            elif method == 'VDI.get_record':
                return {'managed': 'true'}

        session = mock.Mock()
        session.call_xenapi.side_effect = fake_call_xenapi

        mock_get_vdi_ref.side_effect = fake_get_vdi_ref
        fake_get_vdi_ref.call_count = 0

        self.assertEqual(volume_utils.introduce_vdi(session, 'sr_ref'),
                         'vdi_ref')
        mock_sleep.assert_called_once_with(20)

    @mock.patch.object(volume_utils, '_get_vdi_ref')
    @mock.patch.object(greenthread, 'sleep')
    def test_introduce_vdi_exception(self, mock_sleep, mock_get_vdi_ref):
        def fake_call_xenapi(method, *args):
            if method == 'SR.scan':
                return
            elif method == 'VDI.get_record':
                return {'managed': 'true'}

        session = mock.Mock()
        session.call_xenapi.side_effect = fake_call_xenapi
        mock_get_vdi_ref.return_value = None

        self.assertRaises(volume_utils.StorageError,
                          volume_utils.introduce_vdi, session, 'sr_ref')
        mock_sleep.assert_called_once_with(20)
