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


import json
import operator

import nova.scheduler
from nova.scheduler.filters import abstract_filter


class JsonFilter(abstract_filter.AbstractHostFilter):
    """Host Filter to allow simple JSON-based grammar for
    selecting hosts.
    """
    def _op_compare(self, args, op):
        """Returns True if the specified operator can successfully
        compare the first item in the args with all the rest. Will
        return False if only one item is in the list.
        """
        if len(args) < 2:
            return False
        if op is operator.contains:
            bad = not args[0] in args[1:]
        else:
            bad = [arg for arg in args[1:]
                    if not op(args[0], arg)]
        return not bool(bad)

    def _equals(self, args):
        """First term is == all the other terms."""
        return self._op_compare(args, operator.eq)

    def _less_than(self, args):
        """First term is < all the other terms."""
        return self._op_compare(args, operator.lt)

    def _greater_than(self, args):
        """First term is > all the other terms."""
        return self._op_compare(args, operator.gt)

    def _in(self, args):
        """First term is in set of remaining terms"""
        return self._op_compare(args, operator.contains)

    def _less_than_equal(self, args):
        """First term is <= all the other terms."""
        return self._op_compare(args, operator.le)

    def _greater_than_equal(self, args):
        """First term is >= all the other terms."""
        return self._op_compare(args, operator.ge)

    def _not(self, args):
        """Flip each of the arguments."""
        return [not arg for arg in args]

    def _or(self, args):
        """True if any arg is True."""
        return any(args)

    def _and(self, args):
        """True if all args are True."""
        return all(args)

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
        form '$service.capability[.subcap*]'.
        """
        if not string:
            return None
        if not string.startswith("$"):
            return string

        path = string[1:].split(".")
        for item in path:
            services = services.get(item, None)
            if not services:
                return None
        return services

    def _process_filter(self, zone_manager, query, host, services):
        """Recursively parse the query structure."""
        if not query:
            return True
        cmd = query[0]
        method = self.commands[cmd]
        cooked_args = []
        for arg in query[1:]:
            if isinstance(arg, list):
                arg = self._process_filter(zone_manager, arg, host, services)
            elif isinstance(arg, basestring):
                arg = self._parse_string(arg, host, services)
            if arg is not None:
                cooked_args.append(arg)
        result = method(self, cooked_args)
        return result

    def filter_hosts(self, zone_manager, query):
        """Return a list of hosts that can fulfill the requirements
        specified in the query.
        """
        expanded = json.loads(query)
        filtered_hosts = []
        for host, services in zone_manager.service_states.iteritems():
            result = self._process_filter(zone_manager, expanded, host,
                    services)
            if isinstance(result, list):
                # If any succeeded, include the host
                result = any(result)
            if result:
                filtered_hosts.append((host, services))
        return filtered_hosts
