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

"""Bench of utility methods used by filters."""

import collections

from nova.i18n import _LI
from nova import objects
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def aggregate_values_from_db(context, host, key_name):
    """Returns a set of values based on a metadata key for a specific host."""
    # TODO(sahid): DB query in filter is a performance hit, especially for
    # system with lots of hosts. Will need a general solution here to fix
    # all filters with aggregate DB call things.
    aggrlist = objects.AggregateList.get_by_host(
        context.elevated(), host, key=key_name)
    aggregate_vals = set(aggr.metadata[key_name] for aggr in aggrlist)
    return aggregate_vals


def aggregate_metadata_get_by_host(context, host, key=None):
    """Returns a dict of all metadata for a specific host."""
    # TODO(pmurray): DB query in filter is a performance hit. Will need a
    # general solution here.
    aggrlist = objects.AggregateList.get_by_host(
        context.elevated(), host, key=key)

    metadata = collections.defaultdict(set)
    for aggr in aggrlist:
        for k, v in aggr.metadata.iteritems():
            metadata[k].add(v)
    return metadata


def validate_num_values(vals, default=None, cast_to=int, based_on=min):
    """Returns a corretly casted value based on a set of values.

    This method is useful to work with per-aggregate filters, It takes
    a set of values then return the 'based_on'{min/max} converted to
    'cast_to' of the set or the default value.

    Note: The cast implies a possible ValueError
    """
    num_values = len(vals)
    if num_values == 0:
        return default

    if num_values > 1:
        LOG.info(_LI("%(num_values)d values found, "
                     "of which the minimum value will be used."),
                 {'num_values': num_values})

    return cast_to(based_on(vals))
