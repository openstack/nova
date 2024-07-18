# Copyright (c) 2024 SAP
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
import nova.conf
from nova.scheduler.filters import utils as filter_utils
from nova.scheduler import utils
from nova.scheduler import weights


CONF = nova.conf.CONF


class AggregateMultiTenancyIsolation(weights.BaseHostWeigher):
    """Weigh hosts based on them being in a specific aggregate

    The AggregateMultiTenancyIsolation filter makes sure that VMs cannot land
    on hosts that are dedicated to specific projects via the `filter_tenant_id`
    aggregate property. This weigher uses the same information, but prioritizes
    hosts that belong to such a given aggregate. Use-case is to make sure users
    having dedicated hosts will use these hosts on priority and not use
    resources on hardware available for everyone.
    """

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return 1 * utils.get_weight_multiplier(
            host_state, 'aggregate_multi_tenancy_isolation_weight_multiplier',
            CONF.filter_scheduler
                .aggregate_multi_tenancy_isolation_weight_multiplier)

    def _weigh_object(self, host_state, spec_obj):
        """Prioritise hosts in aggregates with filter_tenant_id."""
        tenant_id = spec_obj.project_id

        metadata = filter_utils.aggregate_metadata_get_by_host(host_state,
                                                        key="filter_tenant_id")

        if not metadata:
            return 0.0

        configured_tenant_ids = metadata.get("filter_tenant_id")
        if not configured_tenant_ids:
            return 0.0

        if tenant_id not in configured_tenant_ids:
            return 0.0

        return 1.0
