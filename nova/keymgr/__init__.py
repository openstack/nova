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


from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova.i18n import _LW

LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

# NOTE(kfarr): For backwards compatibility, everything below this comment
# is deprecated for removal
api_class = None
try:
    api_class = CONF.key_manager.api_class
except cfg.NoSuchOptError:
    LOG.warning(_LW("key_manager.api_class is not set, will use deprecated "
                    "option keymgr.api_class if set"))
    try:
        api_class = CONF.keymgr.api_class
    except cfg.NoSuchOptError:
        LOG.warning(_LW("keymgr.api_class is not set"))

deprecated_barbican = 'nova.keymgr.barbican.BarbicanKeyManager'
barbican = 'castellan.key_manager.barbican_key_manager.BarbicanKeyManager'
deprecated_mock = 'nova.tests.unit.keymgr.mock_key_mgr.MockKeyManager'
castellan_mock = ('castellan.tests.unit.key_manager.mock_key_manager.'
                  'MockKeyManager')


def log_deprecated_warning(deprecated, castellan):
    LOG.warning(_LW("key manager api_class set to use deprecated option "
                    "%(deprecated)s, using %(castellan)s instead"),
                {'deprecated': deprecated, 'castellan': castellan})

if api_class == deprecated_barbican:
    log_deprecated_warning(deprecated_barbican, barbican)
    api_class = barbican
elif api_class == deprecated_mock:
    log_deprecated_warning(deprecated_mock, castellan_mock)
    api_class = castellan_mock
elif api_class is None:
    # TODO(kfarr): key_manager.api_class should be set in DevStack, and this
    # block can be removed
    LOG.warning(_LW("key manager not set, using insecure default %s"),
                castellan_mock)
    api_class = castellan_mock

CONF.set_override('api_class', api_class, 'key_manager')


def API(conf=CONF):
    cls = importutils.import_class(CONF.key_manager.api_class)
    return cls(conf)
