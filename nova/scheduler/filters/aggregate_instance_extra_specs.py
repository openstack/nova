# Copyright (c) 2012 OpenStack, LLC.
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

from nova import db
from nova import exception
from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova import utils


LOG = logging.getLogger(__name__)


class AggregateInstanceExtraSpecsFilter(filters.BaseHostFilter):
    """AggregateInstanceExtraSpecsFilter works with InstanceType records."""

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type

        Check that the extra specs associated with the instance type match
        the metadata provided by aggregates.  If not present return False.
        """
        instance_type = filter_properties.get('instance_type')
        if 'extra_specs' not in instance_type:
            return True

        context = filter_properties['context'].elevated()
        metadata = db.aggregate_metadata_get_by_host(context, host_state.host)

        for key, value in instance_type['extra_specs'].iteritems():
            aggregate_value = metadata.get(key, None)
            if not aggregate_value or value not in aggregate_value:
                LOG.debug(_("%(host_state)s fails "
                        "AggregateInstanceExtraSpecsFilter requirements, "
                        "missing %(key)s,'%(value)s'="
                        "'%(aggregate_value)s'"), locals())
                return False
        return True
