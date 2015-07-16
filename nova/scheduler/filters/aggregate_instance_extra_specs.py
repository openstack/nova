# Copyright (c) 2012 OpenStack Foundation
# Copyright (c) 2012 Cloudscaling
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
import six

from nova.scheduler import filters
from nova.scheduler.filters import extra_specs_ops
from nova.scheduler.filters import utils


LOG = logging.getLogger(__name__)

_SCOPE = 'aggregate_instance_extra_specs'


class AggregateInstanceExtraSpecsFilter(filters.BaseHostFilter):
    """AggregateInstanceExtraSpecsFilter works with InstanceType records."""

    # Aggregate data and instance type does not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, spec_obj):
        """Return a list of hosts that can create instance_type

        Check that the extra specs associated with the instance type match
        the metadata provided by aggregates.  If not present return False.
        """
        instance_type = spec_obj.flavor
        # If 'extra_specs' is not present or extra_specs are empty then we
        # need not proceed further
        if (not instance_type.obj_attr_is_set('extra_specs')
                or not instance_type.extra_specs):
            return True

        metadata = utils.aggregate_metadata_get_by_host(host_state)

        for key, req in six.iteritems(instance_type.extra_specs):
            # Either not scope format, or aggregate_instance_extra_specs scope
            scope = key.split(':', 1)
            if len(scope) > 1:
                if scope[0] != _SCOPE:
                    continue
                else:
                    del scope[0]
            key = scope[0]
            aggregate_vals = metadata.get(key, None)
            if not aggregate_vals:
                LOG.debug("%(host_state)s fails instance_type extra_specs "
                    "requirements. Extra_spec %(key)s is not in aggregate.",
                    {'host_state': host_state, 'key': key})
                return False
            for aggregate_val in aggregate_vals:
                if extra_specs_ops.match(aggregate_val, req):
                    break
            else:
                LOG.debug("%(host_state)s fails instance_type extra_specs "
                            "requirements. '%(aggregate_vals)s' do not "
                            "match '%(req)s'",
                          {'host_state': host_state, 'req': req,
                           'aggregate_vals': aggregate_vals})
                return False
        return True
