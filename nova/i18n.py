# Copyright 2014 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""oslo.i18n integration module.

See http://docs.openstack.org/developer/oslo.i18n/usage.html .

"""

from oslo import i18n

from nova.openstack.common import gettextutils

DOMAIN = 'nova'

_translators = i18n.TranslatorFactory(domain=DOMAIN)

# The primary translation function using the well-known name "_"
_ = _translators.primary

# Translators for log levels.
#
# The abbreviated names are meant to reflect the usual use of a short
# name like '_'. The "L" is for "log" and the other letter comes from
# the level.
_LI = _translators.log_info
_LW = _translators.log_warning
_LE = _translators.log_error
_LC = _translators.log_critical


def translate(value, user_locale):
    return i18n.translate(value, user_locale)


def get_available_languages():
    return i18n.get_available_languages(DOMAIN)


# Parts in oslo-incubator are still using gettextutils._(), _LI(), etc., from
# oslo-incubator. Until these parts are changed to use oslo.i18n, Keystone
# needs to do something to allow them to work. One option is to continue to
# initialize gettextutils, but with the way that Nova has initialization
# spread out over mutltiple entry points, we'll monkey-patch
# gettextutils._(), _LI(), etc., to use our oslo.i18n versions.

# FIXME(dims): Remove the monkey-patching and update openstack-common.conf and
# do a sync with oslo-incubator to remove gettextutils once oslo-incubator
# isn't using oslo-incubator gettextutils any more.

gettextutils._ = _
gettextutils._LI = _LI
gettextutils._LW = _LW
gettextutils._LE = _LE
gettextutils._LC = _LC
