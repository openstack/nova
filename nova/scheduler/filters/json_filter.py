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


import operator

from oslo_serialization import jsonutils
import six

from nova.scheduler import filters


class JsonFilter(filters.BaseHostFilter):
    """Host Filter to allow simple JSON-based grammar for
    selecting hosts.
    """

    RUN_ON_REBUILD = False

    def _op_compare(self, args, op):
        """Returns True if the specified operator can successfully
        compare the first item in the args with all the rest. Will
        return False if only one item is in the list.
        """
        if len(args) < 2:
            return False
        if op is operator.contains:
            bad = args[0] not in args[1:]
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
        """First term is in set of remaining terms."""
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

    def _parse_string(self, string, host_state):
        """Strings prefixed with $ are capability lookups in the
        form '$variable' where 'variable' is an attribute in the
        HostState class.  If $variable is a dictionary, you may
        use: $variable.dictkey
        """
        if not string:
            return None
        if not string.startswith("$"):
            return string

        path = string[1:].split(".")
        obj = getattr(host_state, path[0], None)
        if obj is None:
            return None
        for item in path[1:]:
            obj = obj.get(item, None)
            if obj is None:
                return None
        return obj

    def _process_filter(self, query, host_state):
        """Recursively parse the query structure."""
        if not query:
            return True
        cmd = query[0]
        method = self.commands[cmd]
        cooked_args = []
        for arg in query[1:]:
            if isinstance(arg, list):
                arg = self._process_filter(arg, host_state)
            elif isinstance(arg, six.string_types):
                arg = self._parse_string(arg, host_state)
            if arg is not None:
                cooked_args.append(arg)
        result = method(self, cooked_args)
        return result

    def host_passes(self, host_state, spec_obj):
        """Return a list of hosts that can fulfill the requirements
        specified in the query.
        """
        query = spec_obj.get_scheduler_hint('query')
        if not query:
            return True

        # NOTE(comstud): Not checking capabilities or service for
        # enabled/disabled so that a provided json filter can decide

        result = self._process_filter(jsonutils.loads(query), host_state)
        if isinstance(result, list):
            # If any succeeded, include the host
            result = any(result)
        if result:
            # Filter it out.
            return True
        return False
