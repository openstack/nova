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

from nova import test
from nova.tests.unit.keymgr import fake
from nova.volume import encryptors
from nova.volume.encryptors import cryptsetup
from nova.volume.encryptors import luks
from nova.volume.encryptors import nop


class VolumeEncryptorTestCase(test.NoDBTestCase):
    def _create(self, device_path):
        pass

    def setUp(self):
        super(VolumeEncryptorTestCase, self).setUp()

        self.stub_out('nova.keymgr.API', fake.fake_api)

        self.connection_info = {
            "data": {
                "device_path": "/dev/disk/by-path/"
                    "ip-192.0.2.0:3260-iscsi-iqn.2010-10.org.openstack"
                    ":volume-fake_uuid-lun-1",
            },
        }
        self.encryptor = self._create(self.connection_info)


class VolumeEncryptorInitTestCase(VolumeEncryptorTestCase):

    def setUp(self):
        super(VolumeEncryptorInitTestCase, self).setUp()

    def _test_get_encryptor(self, provider, expected_provider_class):
        encryption = {'control_location': 'front-end',
                      'provider': provider}
        encryptor = encryptors.get_volume_encryptor(self.connection_info,
                                                    **encryption)
        self.assertIsInstance(encryptor, expected_provider_class)

    def test_get_encryptors(self):

        self._test_get_encryptor('luks',
                                 luks.LuksEncryptor)
        # TODO(lyarwood): Remove the following in 16.0.0 Pike
        self._test_get_encryptor('LuksEncryptor',
                                 luks.LuksEncryptor)
        self._test_get_encryptor('nova.volume.encryptors.luks.LuksEncryptor',
                                 luks.LuksEncryptor)

        self._test_get_encryptor('plain',
                                 cryptsetup.CryptsetupEncryptor)
        # TODO(lyarwood): Remove the following in 16.0.0 Pike
        self._test_get_encryptor('CryptsetupEncryptor',
                                 cryptsetup.CryptsetupEncryptor)
        self._test_get_encryptor(
            'nova.volume.encryptors.cryptsetup.CryptsetupEncryptor',
             cryptsetup.CryptsetupEncryptor)

        self._test_get_encryptor(None,
                                 nop.NoOpEncryptor)
        # TODO(lyarwood): Remove the following in 16.0.0 Pike
        self._test_get_encryptor('NoOpEncryptor',
                                 nop.NoOpEncryptor)
        self._test_get_encryptor('nova.volume.encryptors.nop.NoOpEncryptor',
                                 nop.NoOpEncryptor)

    def test_get_missing_encryptor_error(self):
        encryption = {'control_location': 'front-end',
                      'provider': 'ErrorEncryptor'}
        self.assertRaises(ValueError, encryptors.get_volume_encryptor,
                          self.connection_info, **encryption)

    @mock.patch('nova.volume.encryptors.LOG')
    def test_get_missing_out_of_tree_encryptor_log(self, log):
        provider = 'TestEncryptor'
        encryption = {'control_location': 'front-end',
                      'provider': provider}
        try:
            encryptors.get_volume_encryptor(self.connection_info, **encryption)
        except Exception as e:
            log.error.assert_called_once_with("Error instantiating "
                                              "%(provider)s: "
                                              "%(exception)s",
                                              {'provider': provider,
                                               'exception': e})
            log.warning.assert_called_once_with("Use of the out of tree "
                                                "encryptor class %(provider)s "
                                                "will be blocked with the "
                                                "16.0.0 Pike release of Nova.",
                                                {'provider': provider})

    @mock.patch('nova.volume.encryptors.LOG')
    def test_get_direct_encryptor_log(self, log):
        encryption = {'control_location': 'front-end',
                      'provider': 'LuksEncryptor'}
        encryptors.get_volume_encryptor(self.connection_info, **encryption)

        encryption = {'control_location': 'front-end',
                      'provider': 'nova.volume.encryptors.luks.LuksEncryptor'}
        encryptors.get_volume_encryptor(self.connection_info, **encryption)

        log.warning.assert_has_calls([
            mock.call("Use of the in tree encryptor class %(provider)s by "
                      "directly referencing the implementation class will be "
                      "blocked in the 16.0.0 Pike release of Nova.",
                      {'provider': 'LuksEncryptor'}),
            mock.call("Use of the in tree encryptor class %(provider)s by "
                      "directly referencing the implementation class will be "
                      "blocked in the 16.0.0 Pike release of Nova.",
                      {'provider':
                           'nova.volume.encryptors.luks.LuksEncryptor'})])
