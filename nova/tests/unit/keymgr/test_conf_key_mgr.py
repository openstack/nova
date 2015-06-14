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

"""
Test cases for the conf key manager.
"""

import array

from oslo_config import cfg

from nova.keymgr import conf_key_mgr
from nova.keymgr import key
from nova.tests.unit.keymgr import test_single_key_mgr


CONF = cfg.CONF
CONF.import_opt('fixed_key', 'nova.keymgr.conf_key_mgr', group='keymgr')


class ConfKeyManagerTestCase(test_single_key_mgr.SingleKeyManagerTestCase):
    def __init__(self, *args, **kwargs):
        super(ConfKeyManagerTestCase, self).__init__(*args, **kwargs)

        self._hex_key = '0' * 64

    def _create_key_manager(self):
        CONF.set_default('fixed_key', default=self._hex_key, group='keymgr')
        return conf_key_mgr.ConfKeyManager()

    def setUp(self):
        super(ConfKeyManagerTestCase, self).setUp()

        encoded_key = array.array('B', self._hex_key.decode('hex')).tolist()
        self.key = key.SymmetricKey('AES', encoded_key)

    def test_init(self):
        key_manager = self._create_key_manager()
        self.assertEqual(self._hex_key, key_manager._hex_key)

    def test_init_value_error(self):
        CONF.set_default('fixed_key', default=None, group='keymgr')
        self.assertRaises(ValueError, conf_key_mgr.ConfKeyManager)

    def test_generate_hex_key(self):
        key_manager = self._create_key_manager()
        self.assertEqual(self._hex_key, key_manager._generate_hex_key())
