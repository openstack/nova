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

POLICY_FORCE = 'force'
POLICY_REQUIRE = 'require'
POLICY_OPTIONAL = 'optional'
POLICY_DISABLE = 'disable'
POLICY_FORBID = 'forbid'

ALL_POLICIES = [
    POLICY_FORCE,
    POLICY_REQUIRE,
    POLICY_OPTIONAL,
    POLICY_DISABLE,
    POLICY_FORBID,
]

MODE_CUSTOM = 'custom'
MODE_HOST_MODEL = 'host-model'
MODE_HOST_PASSTHROUGH = 'host-passthrough'

ALL_CPUMODES = [
    MODE_CUSTOM,
    MODE_HOST_MODEL,
    MODE_HOST_PASSTHROUGH,
]

MATCH_MINIMUM = 'minimum'
MATCH_EXACT = 'exact'
MATCH_STRICT = 'strict'

ALL_MATCHES = [
    MATCH_MINIMUM,
    MATCH_EXACT,
    MATCH_STRICT,
]
