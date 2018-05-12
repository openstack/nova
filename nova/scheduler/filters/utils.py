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

from oslo_log import log as logging
import six

LOG = logging.getLogger(__name__)


def aggregate_values_from_key(host_state, key_name):
    """Returns a set of values based on a metadata key for a specific host."""
    aggrlist = host_state.aggregates
    return {aggr.metadata[key_name]
              for aggr in aggrlist
              if key_name in aggr.metadata
              }


def aggregate_metadata_get_by_host(host_state, key=None):
    """Returns a dict of all metadata based on a metadata key for a specific
    host. If the key is not provided, returns a dict of all metadata.
    """
    aggrlist = host_state.aggregates
    metadata = collections.defaultdict(set)
    for aggr in aggrlist:
        if key is None or key in aggr.metadata:
            for k, v in aggr.metadata.items():
                metadata[k].update(x.strip() for x in v.split(','))
    return metadata


def validate_num_values(vals, default=None, cast_to=int, based_on=min):
    """Returns a correctly casted value based on a set of values.

    This method is useful to work with per-aggregate filters, It takes
    a set of values then return the 'based_on'{min/max} converted to
    'cast_to' of the set or the default value.

    Note: The cast implies a possible ValueError
    """
    num_values = len(vals)
    if num_values == 0:
        return default

    if num_values > 1:
        if based_on == min:
            LOG.info("%(num_values)d values found, "
                     "of which the minimum value will be used.",
                     {'num_values': num_values})
        else:
            LOG.info("%(num_values)d values found, "
                     "of which the maximum value will be used.",
                     {'num_values': num_values})
    return based_on([cast_to(val) for val in vals])


def instance_uuids_overlap(host_state, uuids):
    """Tests for overlap between a host_state and a list of uuids.

    Returns True if any of the supplied uuids match any of the instance.uuid
    values in the host_state.
    """
    if isinstance(uuids, six.string_types):
        uuids = [uuids]
    set_uuids = set(uuids)
    # host_state.instances is a dict whose keys are the instance uuids
    host_uuids = set(host_state.instances.keys())
    return bool(host_uuids.intersection(set_uuids))
