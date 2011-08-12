# Copyright (c) 2011 Openstack, LLC.
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
The Host Filter classes are a way to ensure that only hosts that are
appropriate are considered when creating a new instance. Hosts that are
either incompatible or insufficient to accept a newly-requested instance
are removed by Host Filter classes from consideration. Those that pass
the filter are then passed on for weighting or other process for ordering.

Three filters are included: AllHosts, Flavor & JSON. AllHosts just
returns the full, unfiltered list of hosts. Flavor is a hard coded
matching mechanism based on flavor criteria and JSON is an ad-hoc
filter grammar.

Why JSON? The requests for instances may come in through the
REST interface from a user or a parent Zone.
Currently Flavors and/or InstanceTypes are used for
specifing the type of instance desired. Specific Nova users have
noted a need for a more expressive way of specifying instances.
Since we don't want to get into building full DSL this is a simple
form as an example of how this could be done. In reality, most
consumers will use the more rigid filters such as FlavorFilter.
"""

import json

from nova import exception
from nova import flags
from nova import log as logging

import nova.scheduler


LOG = logging.getLogger('nova.scheduler.host_filter')
FLAGS = flags.FLAGS
flags.DEFINE_string('default_host_filter',
        'nova.scheduler.host_filter.AllHostsFilter',
        'Which filter to use for filtering hosts')


class AbstractHostFilter(object):
    """Base class for host filters."""
    def instance_type_to_filter(self, instance_type):
        """Convert instance_type into a filter for most common use-case."""
        raise NotImplementedError()

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that fulfill the filter."""
        raise NotImplementedError()

    def _full_name(self):
        """module.classname of the filter."""
        return "%s.%s" % (self.__module__, self.__class__.__name__)


def _get_filters():
    from nova.scheduler import filters
    return [itm for itm in dir(filters)
            if issubclass(itm, AbstractHostFilter)]


def choose_host_filter(filter_name=None):
    """Since the caller may specify which filter to use we need
    to have an authoritative list of what is permissible. This
    function checks the filter name against a predefined set
    of acceptable filters.
    """
    if not filter_name:
        filter_name = FLAGS.default_host_filter
    for filter_class in _get_filters():
        host_match = "%s.%s" % (filter_class.__module__, filter_class.__name__)
        if host_match == filter_name:
            return filter_class()
    raise exception.SchedulerHostFilterNotFound(filter_name=filter_name)
