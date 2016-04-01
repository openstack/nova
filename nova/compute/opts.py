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

import itertools

import nova.compute.flavors
import nova.compute.manager
import nova.compute.monitors
import nova.compute.rpcapi
import nova.conf


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             nova.compute.flavors.flavor_opts,
             nova.compute.manager.compute_opts,
             nova.compute.manager.instance_cleaning_opts,
             nova.compute.manager.interval_opts,
             nova.compute.manager.running_deleted_opts,
             nova.compute.manager.timeout_opts,
             nova.compute.rpcapi.rpcapi_opts,
         )),
        ('upgrade_levels',
         itertools.chain(
             [nova.compute.rpcapi.rpcapi_cap_opt],
         )),
    ]
