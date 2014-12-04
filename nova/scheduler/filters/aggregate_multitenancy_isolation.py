# Copyright (c) 2011-2013 OpenStack Foundation
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

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler.filters import utils


LOG = logging.getLogger(__name__)


class AggregateMultiTenancyIsolation(filters.BaseHostFilter):
    """Isolate tenants in specific aggregates."""

    # Aggregate data and tenant do not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        """If a host is in an aggregate that has the metadata key
        "filter_tenant_id" it can only create instances from that tenant(s).
        A host can be in different aggregates.

        If a host doesn't belong to an aggregate with the metadata key
        "filter_tenant_id" it can create instances from all tenants.
        """
        spec = filter_properties.get('request_spec', {})
        props = spec.get('instance_properties', {})
        tenant_id = props.get('project_id')

        context = filter_properties['context']
        metadata = utils.aggregate_metadata_get_by_host(context,
                                                        host_state.host,
                                                        key="filter_tenant_id")

        if metadata != {}:
            if tenant_id not in metadata["filter_tenant_id"]:
                LOG.debug("%s fails tenant id on aggregate", host_state)
                return False
        return True
