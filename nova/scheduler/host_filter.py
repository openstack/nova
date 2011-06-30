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
Host Filter is a mechanism for requesting instance resources.
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

Note: These are "required" capability filters. These capabilities
used must be present or the host will be excluded. The hosts
returned are then weighed by the Weighted Scheduler. Weights
can take the more esoteric factors into consideration (such as
server affinity and customer separation).
"""

import json

from nova import exception
from nova import flags
from nova import log as logging
from nova.scheduler import zone_aware_scheduler
from nova import utils
from nova.scheduler import zone_aware_scheduler

LOG = logging.getLogger('nova.scheduler.host_filter')

FLAGS = flags.FLAGS
flags.DEFINE_string('default_host_filter',
                    'nova.scheduler.host_filter.AllHostsFilter',
                    'Which filter to use for filtering hosts.')


class HostFilter(object):
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


class AllHostsFilter(HostFilter):
    """ NOP host filter. Returns all hosts in ZoneManager.
    This essentially does what the old Scheduler+Chance used
    to give us.
    """

    def instance_type_to_filter(self, instance_type):
        """Return anything to prevent base-class from raising
        exception."""
        return (self._full_name(), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts from ZoneManager list."""
        return [(host, services)
               for host, services in zone_manager.service_states.iteritems()]


class InstanceTypeFilter(HostFilter):
    """HostFilter hard-coded to work with InstanceType records."""

    def instance_type_to_filter(self, instance_type):
        """Use instance_type to filter hosts."""
        return (self._full_name(), instance_type)

    def _satisfies_extra_specs(self, capabilities, instance_type):
        """Check that the capabilities provided by the compute service
        satisfy the extra specs associated with the instance type"""

        if 'extra_specs' not in instance_type:
            return True

        # Note(lorinh): For now, we are just checking exact matching on the
        # values. Later on, we  want to handle numerical
        # values so we can represent things like number of GPU cards

        try:
            for key, value in instance_type['extra_specs'].iteritems():
                if capabilities[key] != value:
                    return False
        except KeyError:
            return False

        return True

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can create instance_type."""
        instance_type = query
        selected_hosts = []
        for host, services in zone_manager.service_states.iteritems():
            capabilities = services.get('compute', {})
            host_ram_mb = capabilities['host_memory_free']
            disk_bytes = capabilities['disk_available']
            spec_ram = instance_type['memory_mb']
            spec_disk = instance_type['local_gb']
            extra_specs = instance_type['extra_specs']

            if host_ram_mb >= spec_ram and \
               disk_bytes >= spec_disk and \
               self._satisfies_extra_specs(capabilities, instance_type):
                selected_hosts.append((host, capabilities))
        return selected_hosts

#host entries (currently) are like:
#    {'host_name-description': 'Default install of XenServer',
#    'host_hostname': 'xs-mini',
#    'host_memory_total': 8244539392,
#    'host_memory_overhead': 184225792,
#    'host_memory_free': 3868327936,
#    'host_memory_free_computed': 3840843776,
#    'host_other_config': {},
#    'host_ip_address': '192.168.1.109',
#    'host_cpu_info': {},
#    'disk_available': 32954957824,
#    'disk_total': 50394562560,
#    'disk_used': 17439604736,
#    'host_uuid': 'cedb9b39-9388-41df-8891-c5c9a0c0fe5f',
#    'host_name_label': 'xs-mini'}

# instance_type table has:
#name = Column(String(255), unique=True)
#memory_mb = Column(Integer)
#vcpus = Column(Integer)
#local_gb = Column(Integer)
#flavorid = Column(Integer, unique=True)
#swap = Column(Integer, nullable=False, default=0)
#rxtx_quota = Column(Integer, nullable=False, default=0)
#rxtx_cap = Column(Integer, nullable=False, default=0)


class JsonFilter(HostFilter):
    """Host Filter to allow simple JSON-based grammar for
    selecting hosts.
    """

    def _equals(self, args):
        """First term is == all the other terms."""
        if len(args) < 2:
            return False
        lhs = args[0]
        for rhs in args[1:]:
            if lhs != rhs:
                return False
        return True

    def _less_than(self, args):
        """First term is < all the other terms."""
        if len(args) < 2:
            return False
        lhs = args[0]
        for rhs in args[1:]:
            if lhs >= rhs:
                return False
        return True

    def _greater_than(self, args):
        """First term is > all the other terms."""
        if len(args) < 2:
            return False
        lhs = args[0]
        for rhs in args[1:]:
            if lhs <= rhs:
                return False
        return True

    def _in(self, args):
        """First term is in set of remaining terms"""
        if len(args) < 2:
            return False
        return args[0] in args[1:]

    def _less_than_equal(self, args):
        """First term is <= all the other terms."""
        if len(args) < 2:
            return False
        lhs = args[0]
        for rhs in args[1:]:
            if lhs > rhs:
                return False
        return True

    def _greater_than_equal(self, args):
        """First term is >= all the other terms."""
        if len(args) < 2:
            return False
        lhs = args[0]
        for rhs in args[1:]:
            if lhs < rhs:
                return False
        return True

    def _not(self, args):
        """Flip each of the arguments."""
        if len(args) == 0:
            return False
        return [not arg for arg in args]

    def _or(self, args):
        """True if any arg is True."""
        return True in args

    def _and(self, args):
        """True if all args are True."""
        return False not in args

    commands = {
        '=': _equals,
        '<': _less_than,
        '>': _greater_than,
        'in': _in,
        '<=': _less_than_equal,
        '>=': _greater_than_equal,
        'not': _not,
        'or': _or,
        'and': _and,
    }

    def instance_type_to_filter(self, instance_type):
        """Convert instance_type into JSON filter object."""
        required_ram = instance_type['memory_mb']
        required_disk = instance_type['local_gb']
        query = ['and',
                    ['>=', '$compute.host_memory_free', required_ram],
                    ['>=', '$compute.disk_available', required_disk]]
        return (self._full_name(), json.dumps(query))

    def _parse_string(self, string, host, services):
        """Strings prefixed with $ are capability lookups in the
        form '$service.capability[.subcap*]'
        """
        if not string:
            return None
        if string[0] != '$':
            return string

        path = string[1:].split('.')
        for item in path:
            services = services.get(item, None)
            if not services:
                return None
        return services

    def _process_filter(self, zone_manager, query, host, services):
        """Recursively parse the query structure."""
        if len(query) == 0:
            return True
        cmd = query[0]
        method = self.commands[cmd]  # Let exception fly.
        cooked_args = []
        for arg in query[1:]:
            if isinstance(arg, list):
                arg = self._process_filter(zone_manager, arg, host, services)
            elif isinstance(arg, basestring):
                arg = self._parse_string(arg, host, services)
            if arg != None:
                cooked_args.append(arg)
        result = method(self, cooked_args)
        return result

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can fulfill filter."""
        expanded = json.loads(query)
        hosts = []
        for host, services in zone_manager.service_states.iteritems():
            r = self._process_filter(zone_manager, expanded, host, services)
            if isinstance(r, list):
                r = True in r
            if r:
                hosts.append((host, services))
        return hosts


FILTERS = [AllHostsFilter, InstanceTypeFilter, JsonFilter]


def choose_host_filter(filter_name=None):
    """Since the caller may specify which filter to use we need
    to have an authoritative list of what is permissible. This
    function checks the filter name against a predefined set
    of acceptable filters.
    """

    if not filter_name:
        filter_name = FLAGS.default_host_filter
    for filter_class in FILTERS:
        host_match = "%s.%s" % (filter_class.__module__, filter_class.__name__)
        if host_match == filter_name:
            return filter_class()
    raise exception.SchedulerHostFilterNotFound(filter_name=filter_name)


class HostFilterScheduler(zone_aware_scheduler.ZoneAwareScheduler):
    """The HostFilterScheduler uses the HostFilter to filter
    hosts for weighing. The particular filter used may be passed in
    as an argument or the default will be used.

    request_spec = {'filter': <Filter name>,
                    'instance_type': <InstanceType dict>}
    """

    def filter_hosts(self, topic, request_spec, hosts=None):
        """Filter the full host list (from the ZoneManager)"""

        filter_name = request_spec.get('filter', None)
        host_filter = choose_host_filter(filter_name)

        # TODO(sandy): We're only using InstanceType-based specs
        # currently. Later we'll need to snoop for more detailed
        # host filter requests.
        instance_type = request_spec['instance_type']
        name, query = host_filter.instance_type_to_filter(instance_type)
        return host_filter.filter_hosts(self.zone_manager, query)

    def weigh_hosts(self, topic, request_spec, hosts):
        """Derived classes must override this method and return
        a lists of hosts in [{weight, hostname}] format.
        """
        return [dict(weight=1, hostname=hostname, capabilities=caps)
                for hostname, caps in hosts]
