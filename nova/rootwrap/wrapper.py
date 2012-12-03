# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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


import ConfigParser
import os
import string

from nova.rootwrap import filters


class NoFilterMatched(Exception):
    """This exception is raised when no filter matched."""
    pass


class FilterMatchNotExecutable(Exception):
    """
    This exception is raised when a filter matched but no executable was
    found.
    """
    def __init__(self, match=None, **kwargs):
        self.match = match


def build_filter(class_name, *args):
    """Returns a filter object of class class_name"""
    if not hasattr(filters, class_name):
        # TODO(ttx): Log the error (whenever nova-rootwrap has a log file)
        return None
    filterclass = getattr(filters, class_name)
    return filterclass(*args)


def load_filters(filters_path):
    """Load filters from a list of directories"""
    filterlist = []
    for filterdir in filters_path:
        if not os.path.isdir(filterdir):
            continue
        for filterfile in os.listdir(filterdir):
            filterconfig = ConfigParser.RawConfigParser()
            filterconfig.read(os.path.join(filterdir, filterfile))
            for (name, value) in filterconfig.items("Filters"):
                filterdefinition = [string.strip(s) for s in value.split(',')]
                newfilter = build_filter(*filterdefinition)
                if newfilter is None:
                    continue
                filterlist.append(newfilter)
    return filterlist


def match_filter(filters, userargs, exec_dirs=[]):
    """
    Checks user command and arguments through command filters and
    returns the first matching filter.
    Raises NoFilterMatched if no filter matched.
    Raises FilterMatchNotExecutable if no executable was found for the
    best filter match.
    """
    first_not_executable_filter = None

    for f in filters:
        if f.match(userargs):
            # Try other filters if executable is absent
            if not f.get_exec(exec_dirs=exec_dirs):
                if not first_not_executable_filter:
                    first_not_executable_filter = f
                continue
            # Otherwise return matching filter for execution
            return f

    if first_not_executable_filter:
        # A filter matched, but no executable was found for it
        raise FilterMatchNotExecutable(match=first_not_executable_filter)

    # No filter matched
    raise NoFilterMatched()
