# Copyright (c) 2011 OpenStack Foundation
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

"""
Scheduler host filters
"""
import functools

from nova import filters
from nova import objects


class BaseHostFilter(filters.BaseFilter):
    """Base class for host filters."""
    def _filter_one(self, obj, filter_properties):
        """Return True if the object passes the filter, otherwise False."""
        return self.host_passes(obj, filter_properties)

    def host_passes(self, host_state, filter_properties):
        """Return True if the HostState passes the filter, otherwise False.
        Override this in a subclass.
        """
        raise NotImplementedError()


class HostFilterHandler(filters.BaseFilterHandler):
    def __init__(self):
        super(HostFilterHandler, self).__init__(BaseHostFilter)


def all_filters():
    """Return a list of filter classes found in this directory.

    This method is used as the default for available scheduler filters
    and should return a list of all filter classes available.
    """
    return HostFilterHandler().get_all_classes()


# TODO(sbauza): Remove that decorator once all filters are using RequestSpec
# object directly.
def compat_legacy_props(function):
    """Decorator for returning a legacy filter_properties dictionary.

    This is used for keeping unchanged the existing filters without yet using
    the RequestSpec fields by returning a legacy dictionary.
    """

    @functools.wraps(function)
    def decorated_host_passes(self, host_state, filter_properties):
        if isinstance(filter_properties, objects.RequestSpec):
            legacy_props = filter_properties.to_legacy_filter_properties_dict()
            legacy_props.update({'request_spec': (
                filter_properties.to_legacy_request_spec_dict()),
                'instance_type': filter_properties.flavor})
            # TODO(sbauza): Adding two keys not used in-tree but which will be
            # provided as non-fields for the RequestSpec once we provide it to
            # the filters
            legacy_props.update(
                {'context': filter_properties._context,
                 'config_options': filter_properties.config_options})
            filter_properties = legacy_props
        return function(self, host_state, filter_properties)

    return decorated_host_passes
