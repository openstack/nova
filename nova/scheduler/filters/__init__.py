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
from nova import filters


class BaseHostFilter(filters.BaseFilter):
    """Base class for host filters."""

    # This is set to True if this filter should be run for rebuild.
    # For example, with rebuild, we need to ask the scheduler if the
    # existing host is still legit for a rebuild with the new image and
    # other parameters. We care about running policy filters (i.e.
    # ImagePropertiesFilter) but not things that check usage on the
    # existing compute node, etc.
    RUN_ON_REBUILD = False

    def _filter_one(self, obj, spec):
        """Return True if the object passes the filter, otherwise False."""
        # Do this here so we don't get scheduler.filters.utils
        from nova.scheduler import utils
        if not self.RUN_ON_REBUILD and utils.request_is_rebuild(spec):
            # If we don't filter, default to passing the host.
            return True
        else:
            # We are either a rebuild filter, in which case we always run,
            # or this request is not rebuild in which case all filters
            # should run.
            return self.host_passes(obj, spec)

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
