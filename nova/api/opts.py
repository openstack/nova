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

import nova.api.openstack.compute
import nova.api.openstack.compute.hide_server_addresses
import nova.api.openstack.compute.legacy_v2.contrib
import nova.api.openstack.compute.legacy_v2.contrib.fping
import nova.api.openstack.compute.legacy_v2.contrib.os_tenant_networks
import nova.api.openstack.compute.legacy_v2.extensions
import nova.api.openstack.compute.legacy_v2.servers


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.api.openstack.compute.allow_instance_snapshots_opt],
             nova.api.openstack.compute.legacy_v2.contrib.ext_opts,
             nova.api.openstack.compute.legacy_v2.contrib.fping.fping_opts,
             nova.api.openstack.compute.legacy_v2.contrib.os_tenant_networks.
                 os_network_opts,
             nova.api.openstack.compute.legacy_v2.extensions.ext_opts,
             nova.api.openstack.compute.hide_server_addresses.opts,
             nova.api.openstack.compute.legacy_v2.servers.server_opts,
         )),
    ]
