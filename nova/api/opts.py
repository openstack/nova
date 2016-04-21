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

import nova.api.openstack.compute.legacy_v2.contrib
import nova.api.openstack.compute.legacy_v2.extensions


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             nova.api.openstack.compute.legacy_v2.contrib.ext_opts,
             nova.api.openstack.compute.legacy_v2.extensions.ext_opts,
         )),
    ]
