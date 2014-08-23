# Copyright (c) 2012 The Cloudscaling Group, Inc.
#
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

from nova import db
from nova.scheduler import filters
from nova.scheduler.filters import utils


class TypeAffinityFilter(filters.BaseHostFilter):
    """TypeAffinityFilter doesn't allow more than one VM type per host.

    Note: this works best with ram_weight_multiplier
    (spread) set to 1 (default).
    """

    def host_passes(self, host_state, filter_properties):
        """Dynamically limits hosts to one instance type

        Return False if host has any instance types other than the requested
        type. Return True if all instance types match or if host is empty.
        """

        instance_type = filter_properties.get('instance_type')
        context = filter_properties['context'].elevated()
        instances_other_type = db.instance_get_all_by_host_and_not_type(
                     context, host_state.host, instance_type['id'])
        return len(instances_other_type) == 0


class AggregateTypeAffinityFilter(filters.BaseHostFilter):
    """AggregateTypeAffinityFilter limits instance_type by aggregate

    return True if no instance_type key is set or if the aggregate metadata
    key 'instance_type' has the instance_type name as a value
    """

    # Aggregate data does not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        instance_type = filter_properties.get('instance_type')

        # TODO(uni): DB query in filter is a performance hit, especially for
        # system with lots of hosts. Will need a general solution here to fix
        # all filters with aggregate DB call things.
        aggregate_vals = utils.aggregate_values_from_db(
            filter_properties['context'], host_state.host, 'instance_type')

        if not aggregate_vals:
            return True
        return instance_type['name'] in aggregate_vals
