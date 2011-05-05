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
Query is a plug-in mechanism for requesting instance resources.
Three plug-ins are included: AllHosts, Flavor & JSON. AllHosts just
returns the full, unfiltered list of hosts. Flavor is a hard coded
matching mechanism based on flavor criteria and JSON is an ad-hoc
query grammar.

Note: These are hard filters. All capabilities used  must be present
or the host will excluded. If you want soft filters use the weighting
mechanism which is intended for the more touchy-feely capabilities.
"""

import json

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils

LOG = logging.getLogger('nova.scheduler.query')

FLAGS = flags.FLAGS
flags.DEFINE_string('default_query_engine',
                    'nova.scheduler.query.AllHostsQuery',
                    'Which query engine to use for filtering hosts.')


class Query:
    """Base class for query plug-ins."""

    def instance_type_to_query(self, instance_type):
        """Convert instance_type into a query for most common use-case."""
        raise exception.BadSchedulerQueryDriver()

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that fulfill the query."""
        raise exception.BadSchedulerQueryDriver()


class AllHostsQuery:
    """NOP query plug-in. Returns all hosts in ZoneManager.
    This essentially does what the old Scheduler+Chance used
    to give us."""

    def instance_type_to_query(self, instance_type):
        """Return anything to prevent base-class from raising
        exception."""
        return (str(self.__class__), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts from ZoneManager list."""
        return [(host, services)
               for host, services in zone_manager.service_states.iteritems()]


class FlavorQuery:
    """Query plug-in hard-coded to work with flavors."""

    def instance_type_to_query(self, instance_type):
        """Use instance_type to filter hosts."""
        return (str(self.__class__), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can create instance_type."""
        instance_type = query
        selected_hosts = []
        for host, services in zone_manager.service_states.iteritems():
            capabilities = services.get('compute', {})
            host_ram_mb = capabilities['host_memory']['free']
            disk_bytes = capabilities['disk']['available']
            if host_ram_mb >= instance_type['memory_mb'] and \
                disk_bytes >= instance_type['local_gb']:
                    selected_hosts.append((host, capabilities))
        return selected_hosts

#host entries (currently) are like:
#    {'host_name-description': 'Default install of XenServer',
#    'host_hostname': 'xs-mini',
#    'host_memory': {'total': 8244539392,
#        'overhead': 184225792,
#        'free': 3868327936,
#        'free-computed': 3840843776},
#    'host_other-config': {},
#    'host_ip_address': '192.168.1.109',
#    'host_cpu_info': {},
#    'disk': {'available': 32954957824,
#        'total': 50394562560,
#        'used': 17439604736},
#    'host_uuid': 'cedb9b39-9388-41df-8891-c5c9a0c0fe5f',
#    'host_name-label': 'xs-mini'}

# instance_type table has:
#name = Column(String(255), unique=True)
#memory_mb = Column(Integer)
#vcpus = Column(Integer)
#local_gb = Column(Integer)
#flavorid = Column(Integer, unique=True)
#swap = Column(Integer, nullable=False, default=0)
#rxtx_quota = Column(Integer, nullable=False, default=0)
#rxtx_cap = Column(Integer, nullable=False, default=0)


class JsonQuery:
    """Query plug-in to allow simple JSON-based grammar for selecting hosts."""

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
        if len(args) == 0:
            return False
        return [not arg for arg in args]

    def _or(self, args):
        return True in args

    def _and(self, args):
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

    def instance_type_to_query(self, instance_type):
        """Convert instance_type into JSON query object."""
        required_ram = instance_type['memory_mb']
        required_disk = instance_type['local_gb']
        query = ['and',
                    ['>=', '$compute.host_memory.free', required_ram],
                    ['>=', '$compute.disk.available', required_disk]
                ]
        return (str(self.__class__), json.dumps(query))

    def _parse_string(self, string, host, services):
        """Strings prefixed with $ are capability lookups in the
        form '$service.capability[.subcap*]'"""
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

    def _process_query(self, zone_manager, query, host, services):
        if len(query) == 0:
            return True
        cmd = query[0]
        method = self.commands[cmd]  # Let exception fly.
        cooked_args = []
        for arg in query[1:]:
            if isinstance(arg, list):
                arg = self._process_query(zone_manager, arg, host, services)
            elif isinstance(arg, basestring):
                arg = self._parse_string(arg, host, services)
            if arg != None:
                cooked_args.append(arg)
        result = method(self, cooked_args)
        print "*** %s %s = %s" % (cmd, cooked_args, result)
        return result

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can fulfill query."""
        expanded = json.loads(query)
        hosts = []
        for host, services in zone_manager.service_states.iteritems():
            print "-----"
            r = self._process_query(zone_manager, expanded, host, services)
            if isinstance(r, list):
                r = True in r
            if r:
                hosts.append((host, services))
        return hosts


# Since the caller may specify which driver to use we need
# to have an authoritative list of what is permissible.
DRIVERS = [AllHostsQuery, FlavorQuery, JsonQuery]


def choose_driver(driver_name=None):
    if not driver_name:
        driver_name = FLAGS.default_query_engine
    for driver in DRIVERS:
        if str(driver) == driver_name:
            return driver
    raise exception.SchedulerQueryDriverNotFound(driver_name=driver_name)
