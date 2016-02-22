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

import nova.api.auth
import nova.api.metadata.base
import nova.api.metadata.handler
import nova.api.metadata.vendordata_json
import nova.api.openstack
import nova.api.openstack.common
import nova.api.openstack.compute
import nova.api.openstack.compute.hide_server_addresses
import nova.api.openstack.compute.legacy_v2.contrib
import nova.api.openstack.compute.legacy_v2.contrib.fping
import nova.api.openstack.compute.legacy_v2.contrib.os_tenant_networks
import nova.api.openstack.compute.legacy_v2.extensions
import nova.api.openstack.compute.legacy_v2.servers
import nova.availability_zones
import nova.baserpc
import nova.cells.manager
import nova.cells.messaging
import nova.cells.opts
import nova.cells.rpc_driver
import nova.cells.rpcapi
import nova.cells.scheduler
import nova.cells.state
import nova.cells.weights.mute_child
import nova.cells.weights.ram_by_instance_type
import nova.cells.weights.weight_offset
import nova.cert.rpcapi
import nova.cloudpipe.pipelib
import nova.cmd.novnc
import nova.cmd.novncproxy
import nova.cmd.serialproxy
import nova.cmd.spicehtml5proxy
import nova.compute.api
import nova.compute.flavors
import nova.compute.manager
import nova.compute.monitors
import nova.compute.resource_tracker
import nova.compute.rpcapi
import nova.conductor.api
import nova.conductor.rpcapi
import nova.conductor.tasks.live_migrate
import nova.console.manager
import nova.console.rpcapi
import nova.console.serial
import nova.console.xvp
import nova.consoleauth
import nova.consoleauth.manager
import nova.consoleauth.rpcapi
import nova.crypto
import nova.db.api
import nova.db.base
import nova.db.sqlalchemy.api
import nova.exception
import nova.image.download.file
import nova.image.glance
import nova.ipv6.api
import nova.keymgr
import nova.keymgr.barbican
import nova.keymgr.conf_key_mgr
import nova.netconf
import nova.network
import nova.network.driver
import nova.network.floating_ips
import nova.network.ldapdns
import nova.network.linux_net
import nova.network.manager
import nova.network.neutronv2.api
import nova.network.rpcapi
import nova.network.security_group.openstack_driver
import nova.notifications
import nova.objects.network
import nova.paths
import nova.pci.request
import nova.pci.whitelist
import nova.quota
import nova.rdp
import nova.scheduler.driver
import nova.scheduler.filter_scheduler
import nova.scheduler.filters.aggregate_image_properties_isolation
import nova.scheduler.filters.core_filter
import nova.scheduler.filters.disk_filter
import nova.scheduler.filters.io_ops_filter
import nova.scheduler.filters.isolated_hosts_filter
import nova.scheduler.filters.num_instances_filter
import nova.scheduler.filters.ram_filter
import nova.scheduler.filters.trusted_filter
import nova.scheduler.host_manager
import nova.scheduler.ironic_host_manager
import nova.scheduler.manager
import nova.scheduler.rpcapi
import nova.scheduler.scheduler_options
import nova.scheduler.utils
import nova.scheduler.weights.io_ops
import nova.scheduler.weights.metrics
import nova.scheduler.weights.ram
import nova.service
import nova.servicegroup.api
import nova.spice
import nova.utils
import nova.vnc
import nova.vnc.xvp_proxy
import nova.volume
import nova.volume.cinder
import nova.wsgi


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.api.metadata.vendordata_json.file_opt],
             [nova.api.openstack.compute.allow_instance_snapshots_opt],
             nova.api.auth.auth_opts,
             nova.api.metadata.base.metadata_opts,
             nova.api.metadata.handler.metadata_opts,
             nova.api.openstack.common.osapi_opts,
             nova.api.openstack.compute.legacy_v2.contrib.ext_opts,
             nova.api.openstack.compute.legacy_v2.contrib.fping.fping_opts,
             nova.api.openstack.compute.legacy_v2.contrib.os_tenant_networks.
                 os_network_opts,
             nova.api.openstack.compute.legacy_v2.extensions.ext_opts,
             nova.api.openstack.compute.hide_server_addresses.opts,
             nova.api.openstack.compute.legacy_v2.servers.server_opts,
         )),
        ('neutron', nova.api.metadata.handler.metadata_proxy_opts),
        ('osapi_v21', nova.api.openstack.api_opts),
    ]
