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
An implementation of a key manager that reads its key from the project's
configuration options.

This key manager implementation provides limited security, assuming that the
key remains secret. Using the volume encryption feature as an example,
encryption provides protection against a lost or stolen disk, assuming that
the configuration file that contains the key is not stored on the disk.
Encryption also protects the confidentiality of data as it is transmitted via
iSCSI from the compute host to the storage host (again assuming that an
attacker who intercepts the data does not know the secret key).

Because this implementation uses a single, fixed key, it proffers no
protection once that key is compromised. In particular, different volumes
encrypted with a key provided by this key manager actually share the same
encryption key so *any* volume can be decrypted once the fixed key is known.
"""

from oslo_config import cfg

from nova.i18n import _
from nova.keymgr import single_key_mgr

key_mgr_opts = [
    cfg.StrOpt('fixed_key',
            help='Fixed key returned by key manager, specified in hex'),
]

CONF = cfg.CONF
CONF.register_opts(key_mgr_opts, group='keymgr')


class ConfKeyManager(single_key_mgr.SingleKeyManager):
    """This key manager implementation supports all the methods specified by
    the key manager interface. This implementation creates a single key in
    response to all invocations of create_key. Side effects
    (e.g., raising exceptions) for each method are handled
    as specified by the key manager interface.
    """

    def __init__(self):
        if CONF.keymgr.fixed_key is None:
            raise ValueError(_('keymgr.fixed_key not defined'))
        self._hex_key = CONF.keymgr.fixed_key
        super(ConfKeyManager, self).__init__()

    def _generate_hex_key(self, **kwargs):
        return self._hex_key
