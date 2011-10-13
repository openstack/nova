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

Filters are in the 'filters' directory that is off the 'scheduler'
directory of nova. Additional filters can be created and added to that
directory; be sure to add them to the filters/__init__.py file so that
they are part of the nova.schedulers.filters namespace.
"""

import types

from nova import exception
from nova import flags
import nova.scheduler

from nova.scheduler import filters


FLAGS = flags.FLAGS
flags.DEFINE_list('default_host_filters', ['AllHostsFilter'],
        'Which filters to use for filtering hosts when not specified '
        'in the request.')


def _get_filter_classes():
    # Imported here to avoid circular imports
    from nova.scheduler import filters

    def get_itm(nm):
        return getattr(filters, nm)

    return [get_itm(itm) for itm in dir(filters)
            if (type(get_itm(itm)) is types.TypeType)
            and issubclass(get_itm(itm), filters.AbstractHostFilter)
            and get_itm(itm) is not filters.AbstractHostFilter]


def choose_host_filters(filters=None):
    """Since the caller may specify which filters to use we need
    to have an authoritative list of what is permissible. This
    function checks the filter names against a predefined set
    of acceptable filters.
    """
    if not filters:
        filters = FLAGS.default_host_filters
    if not isinstance(filters, (list, tuple)):
        filters = [filters]
    good_filters = []
    bad_filters = []
    filter_classes = _get_filter_classes()
    for filter_name in filters:
        found_class = False
        for cls in filter_classes:
            if cls.__name__ == filter_name:
                good_filters.append(cls())
                found_class = True
                break
        if not found_class:
            bad_filters.append(filter_name)
    if bad_filters:
        msg = ", ".join(bad_filters)
        raise exception.SchedulerHostFilterNotFound(filter_name=msg)
    return good_filters
