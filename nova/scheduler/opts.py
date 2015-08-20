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


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.scheduler.filters.disk_filter.disk_allocation_ratio_opt],
             [nova.scheduler.filters.io_ops_filter.max_io_ops_per_host_opt],
             [nova.scheduler.filters.num_instances_filter.
                  max_instances_per_host_opt],
             [nova.scheduler.scheduler_options.
                  scheduler_json_config_location_opt],
             nova.scheduler.driver.scheduler_driver_opts,
             nova.scheduler.filter_scheduler.filter_scheduler_opts,
             nova.scheduler.filters.aggregate_image_properties_isolation.opts,
             nova.scheduler.filters.isolated_hosts_filter.isolated_opts,
             nova.scheduler.host_manager.host_manager_opts,
             nova.scheduler.ironic_host_manager.host_manager_opts,
             nova.scheduler.manager.scheduler_driver_opts,
             nova.scheduler.rpcapi.rpcapi_opts,
             nova.scheduler.utils.scheduler_opts,
             nova.scheduler.weights.io_ops.io_ops_weight_opts,
             nova.scheduler.weights.ram.ram_weight_opts,
         )),
        ('metrics', nova.scheduler.weights.metrics.metrics_weight_opts),
        ('trusted_computing',
         nova.scheduler.filters.trusted_filter.trusted_opts),
        ('upgrade_levels',
         itertools.chain(
             [nova.scheduler.rpcapi.rpcapi_cap_opt],
         )),
    ]
