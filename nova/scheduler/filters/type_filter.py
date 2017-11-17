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

from oslo_log import log as logging

from nova.scheduler import filters
from nova.scheduler.filters import utils

LOG = logging.getLogger(__name__)


class TypeAffinityFilter(filters.BaseHostFilter):
    """DEPRECATED: TypeAffinityFilter doesn't allow more than one VM type
    per host.

    Note: this works best with ram_weight_multiplier
    (spread) set to 1 (default).
    """

    RUN_ON_REBUILD = False

    def __init__(self):
        super(TypeAffinityFilter, self).__init__()
        LOG.warning('TypeAffinityFilter is deprecated for removal in the '
                    '17.0.0 Queens release. There is no replacement planned '
                    'for this filter. It is fundamentally flawed in that it '
                    'relies on the flavors.id primary key and if a flavor '
                    '\"changed\" (deleted and re-created with new values) '
                    'it will result in this filter thinking it is a '
                    'different flavor, thus breaking the usefulness of this '
                    'filter.')

    def host_passes(self, host_state, spec_obj):
        """Dynamically limits hosts to one instance type

        Return False if host has any instance types other than the requested
        type. Return True if all instance types match or if host is empty.
        """
        instance_type = spec_obj.flavor
        instance_type_id = instance_type.id
        other_types_on_host = utils.other_types_on_host(host_state,
                                                        instance_type_id)
        return not other_types_on_host


class AggregateTypeAffinityFilter(filters.BaseHostFilter):
    """AggregateTypeAffinityFilter limits instance_type by aggregate

    return True if no instance_type key is set or if the aggregate metadata
    key 'instance_type' has the instance_type name as a value
    """

    # Aggregate data does not change within a request
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        instance_type = spec_obj.flavor

        aggregate_vals = utils.aggregate_values_from_key(
            host_state, 'instance_type')

        for val in aggregate_vals:
            if (instance_type.name in
                    [x.strip() for x in val.split(',')]):
                return True
        return not aggregate_vals
