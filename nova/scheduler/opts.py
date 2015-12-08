# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import nova.conf.scheduler


def list_opts():
    return [
        ('DEFAULT',
         nova.conf.scheduler.SIMPLE_OPTS),
        ('metrics', nova.conf.scheduler.metrics_weight_opts),
        ('trusted_computing',
         nova.conf.scheduler.trusted_opts),
        ('upgrade_levels',
         [nova.conf.scheduler.rpcapi_cap_opt]),
    ]
