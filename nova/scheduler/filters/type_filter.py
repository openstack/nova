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
import collections
import six

from nova.i18n import _LI
from nova.scheduler import filters
from nova.scheduler.filters import utils
from oslo_log import log as logging


LOG = logging.getLogger(__name__)


class TypeAffinityFilter(filters.BaseHostFilter):
    """TypeAffinityFilter doesn't allow more than one VM type per host.

    Note: this works best with ram_weight_multiplier
    (spread) set to 1 (default).
    """

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

    def host_passes(self, host_state, spec_obj):
        instance_type = spec_obj.flavor

        aggregate_vals = utils.aggregate_values_from_key(
            host_state, 'instance_type')

        for val in aggregate_vals:
            if (instance_type.name in
                    [x.strip() for x in val.split(',')]):
                return True
        return not aggregate_vals


class AggregateTypeExtraSpecsAffinityFilter(filters.BaseHostFilter):
    """AggregateTypeExtraSpecsAffinityFilter filters only hosts aggregated
    inside host aggregates containing "flavor_extra_spec" metadata. Keys inside
    this variable must match with the instance extra specs.

    To use this filter, the name of this class should be added to the variable
    ``scheduler_default_filters``, in ``nova.conf``:

    |   [DEFAULT]
    |   scheduler_default_filters=<list of other filters>, \
                                  AggregateTypeExtraSpecsAffinityFilter

    The content of the list will be formatted as follows. The entries in the
    list will be separated by commas without white space. Each entry will
    comprise of an instance type extra spec key followed by and equals "="
    followed by a value: <key>=<value>.

    Eg.
        Host Aggregate metadata:
            'flavor_extra_spec=hw:mem_page_size=any,hw:mem_page_size=~,' \
            'hw:mem_page_size=small'
        Flavor extra specs:
            'hw:mem_page_size=small'

    Valid sentinel values are:

    | * (asterisk): may be used to specify that any value is valid.
    | ~ (tilde): may be used to specify that a key may optionally be omitted.
    | ! (exclamation): may be used to specify that the key must not be present.
    """

    def _parse_extra_spec_key_pairs(self, aggregate_extra_spec):
        """Parse and group all key/data from aggregate_extra_spec.

        :param aggregate_extra_spec: string containing a list of required
                                     instance flavor extra specs, separated by
                                     commas, with format "key=value"
        :type aggregate_extra_spec: unicode.
        :return: dictionary with the values parsed and grouped by keys.
        :type: dict.
        """
        extra_specs = collections.defaultdict(set)
        kv_list = str(aggregate_extra_spec).split(',')

        # Create a new set entry in a dict for every new key, update the key
        # value (set object) for every other value.
        for kv_element in kv_list:
            key, value = kv_element.split('=', 1)
            extra_specs[key].add(value)
            if '=' in value:
                LOG.info(_LI("Value string has an '=' char: key = '%(key)s', "
                             "value = '%(value)s'. Check if it's malformed"),
                         {'value': value, 'key': key})
        return extra_specs

    def _instance_is_allowed_in_aggregate(self,
                                          aggregate_extra_spec,
                                          instance_extra_specs):
        """Loop over all aggregate_extra_spec elements parsed and execute the
        appropriate filter action.

        :param aggregate_extra_spec: dictionary with the values parsed and
                                     grouped by keys.
        :type aggregate_extra_spec: dict.
        :param instance_extra_specs: dictionary containing the extra specs of
                                     the instance to be filtered.
        :type instance_extra_specs: dict.
        :return: True if all parameters executed correctly; False is there
                 is any error.
        :type: boolean.
        """
        for key, value in six.iteritems(aggregate_extra_spec):
            if '*' in value:
                if key not in instance_extra_specs:
                    LOG.debug("'flavor_extra_spec' key: %(key)s "
                              "is not present", {'key': key})
                    return False
                else:
                    continue

            if '!' in value:
                if key in instance_extra_specs:
                    LOG.debug("'flavor_extra_spec' key: %(key)s "
                              "is present", {'key': key})
                    return False
                else:
                    continue

            if '~' in value:
                if key not in instance_extra_specs:
                    continue
                else:
                    value.discard('~')

            for element in value:
                match = [char for char in ["*", "!", "~"] if char in element]
                if match:
                    LOG.info(_LI("Value string has '%(chars)s' char(s): "
                                 "key = '%(key)s', value = '%(value)s'. "
                                 "Check if it's malformed"),
                             {'value': element, 'chars': match, 'key': key})
                if key not in instance_extra_specs:
                    LOG.debug("'flavor_extra_spec' key: %(key)s "
                              "is not present", {'key': key})
                    return False
                if instance_extra_specs[key] not in value:
                    LOG.debug("The following 'flavor_extra_spec' "
                              "key=value: %(key)s=%(value)s doesn't "
                              "match", {'key': key, 'value': value})
                    return False

        return True

    def host_passes(self, host_state, spec_obj):
        instance_type = spec_obj.flavor
        # If 'extra_specs' is not present or extra_specs are empty then we
        # need not proceed further
        if (not instance_type.obj_attr_is_set('extra_specs')
                or not instance_type.extra_specs):
            return True

        aggregate_extra_spec_list = utils.aggregate_values_from_key(host_state,
            'flavor_extra_spec')

        for aggregate_extra_spec in aggregate_extra_spec_list:
            aggregate_extra_spec = self._parse_extra_spec_key_pairs(
                aggregate_extra_spec)
            if not self._instance_is_allowed_in_aggregate(aggregate_extra_spec,
                    instance_type.extra_specs):
                return False
        return True
