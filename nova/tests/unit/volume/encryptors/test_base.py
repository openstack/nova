# Copyright (c) 2013 The Johns Hopkins University/Applied Physics Laboratory
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

from nova.i18n import _LE
from nova import keymgr
from nova import test
from nova.tests.unit.keymgr import fake
from nova.volume import encryptors


class VolumeEncryptorTestCase(test.TestCase):
    def _create(self, device_path):
        pass

    def setUp(self):
        super(VolumeEncryptorTestCase, self).setUp()

        self.stubs.Set(keymgr, 'API', fake.fake_api)

        self.connection_info = {
            "data": {
                "device_path": "/dev/disk/by-path/"
                    "ip-192.0.2.0:3260-iscsi-iqn.2010-10.org.openstack"
                    ":volume-fake_uuid-lun-1",
            },
        }
        self.encryptor = self._create(self.connection_info)

    @mock.patch('nova.volume.encryptors.LOG')
    def test_error_log(self, log):
        encryption = {'control_location': 'front-end',
                      'provider': 'TestEncryptor'}
        provider = 'TestEncryptor'
        try:
            encryptors.get_volume_encryptor(self.connection_info, **encryption)
        except Exception as e:
            log.error.assert_called_once_with(_LE("Error instantiating "
                                                  "%(provider)s: "
                                                  "%(exception)s"),
                      {'provider': provider, 'exception': e})
