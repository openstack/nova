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
Three plug-ins are included: PassThru, Flavor & JSON. PassThru just
returns the full, unfiltered list of hosts. Flavor is a hard coded
matching mechanism based on flavor criteria and JSON is an ad-hoc
query grammar.
"""

from nova import exception
from nova import utils

class Query:
    """Base class for query plug-ins."""

    def instance_type_to_query(self, instance_type):
        """Convert instance_type into a query for most common use-case."""
        raise exception.Error(_("Query driver not specified."))

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that fulfill the query."""
        raise exception.Error(_("Query driver not specified."))


def load_driver(driver_name):
    resource = utils.import_class(driver_name)
    if type(resource) != types.ClassType:
        continue
    cls = resource
    if not issubclass(cls, Query):
        raise exception.Error(_("Query driver does not derive "
                "from nova.scheduler.query.Query."))
    return cls


class PassThruQuery:
    """NOP query plug-in. Returns all hosts in ZoneManager.
    This essentially does what the old Scheduler+Chance used
    to give us."""

    def instance_type_to_query(self, instance_type):
        """Return anything to prevent base-class from raising
        exception."""
        return (str(self.__class__), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts from ZoneManager list."""
        hosts = zone_manager.service_state.get('compute', {})
        return [(host, capabilities)
                for host, capabilities in hosts.iteritems()]


class FlavorQuery:
    """Query plug-in hard-coded to work with flavors."""

    def instance_type_to_query(self, instance_type):
        """Use instance_type to filter hosts."""
        return (str(self.__class__), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can create instance_type."""
        hosts = zone_manager.service_state.get('compute', {})
        selected_hosts = []
        instance_type = query
        for host, capabilities in hosts.iteritems():
            host_ram_mb = capabilities.get['host_memory']['free']
            disk_bytes = capabilities.get['disk']['available']
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
        pass

    def _less_than(self, args):
        pass

    def _greater_than(self, args):
        pass

    def _in(self, args):
        pass

    def _less_than_equal(self, args):
        pass
        
    def _greater_than_equal(self, args):
        pass

    def _not(self, args):
        pass

    def _must(self, args):
        pass

    def _or(self, args):
        pass
 
    commands = {
        '=': _equals,
        '<': _less_than,
        '>': _greater_than,
        'in': _in,
        '<=': _less_than_equal,
        '>=': _greater_than_equal,
        'not': _not,
        'must', _must,
        'or', _or,
    }

    def instance_type_to_query(self, instance_type):
        """Convert instance_type into JSON query object."""
        return (str(self.__class__), instance_type)

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can fulfill query."""
        return []


                              
