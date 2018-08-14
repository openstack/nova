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
_UUID_CHAR = "[0-9a-fA-F-]"
# TODO(efried): Use this stricter pattern, and replace string/uuid with it:
# UUID_PATTERN = "^%s{8}-%s{4}-%s{4}-%s{4}-%s{12}$" % ((_UUID_CHAR,) * 5)
UUID_PATTERN = "^%s{36}$" % _UUID_CHAR

_RC_TRAIT_CHAR = "[A-Z0-9_]"
_RC_TRAIT_PATTERN = "^%s+$" % _RC_TRAIT_CHAR
RC_PATTERN = _RC_TRAIT_PATTERN
_CUSTOM_RC_TRAIT_PATTERN = "^CUSTOM_%s+$" % _RC_TRAIT_CHAR
CUSTOM_RC_PATTERN = _CUSTOM_RC_TRAIT_PATTERN
CUSTOM_TRAIT_PATTERN = _CUSTOM_RC_TRAIT_PATTERN
