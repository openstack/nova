# Copyright (c) 2011-2012 OpenStack Foundation
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
Filter support
"""

from oslo_log import log as logging

from nova.i18n import _LI
from nova import loadables

LOG = logging.getLogger(__name__)


class BaseFilter(object):
    """Base class for all filter classes."""
    def _filter_one(self, obj, spec_obj):
        """Return True if it passes the filter, False otherwise.
        Override this in a subclass.
        """
        return True

    def filter_all(self, filter_obj_list, spec_obj):
        """Yield objects that pass the filter.

        Can be overridden in a subclass, if you need to base filtering
        decisions on all objects.  Otherwise, one can just override
        _filter_one() to filter a single object.
        """
        for obj in filter_obj_list:
            if self._filter_one(obj, spec_obj):
                yield obj

    # Set to true in a subclass if a filter only needs to be run once
    # for each request rather than for each instance
    run_filter_once_per_request = False

    def run_filter_for_index(self, index):
        """Return True if the filter needs to be run for the "index-th"
        instance in a request.  Only need to override this if a filter
        needs anything other than "first only" or "all" behaviour.
        """
        if self.run_filter_once_per_request and index > 0:
            return False
        else:
            return True


class BaseFilterHandler(loadables.BaseLoader):
    """Base class to handle loading filter classes.

    This class should be subclassed where one needs to use filters.
    """

    def get_filtered_objects(self, filters, objs, spec_obj, index=0):
        list_objs = list(objs)
        LOG.debug("Starting with %d host(s)", len(list_objs))
        # Track the hosts as they are removed. The 'full_filter_results' list
        # contains the host/nodename info for every host that passes each
        # filter, while the 'part_filter_results' list just tracks the number
        # removed by each filter, unless the filter returns zero hosts, in
        # which case it records the host/nodename for the last batch that was
        # removed. Since the full_filter_results can be very large, it is only
        # recorded if the LOG level is set to debug.
        part_filter_results = []
        full_filter_results = []
        log_msg = "%(cls_name)s: (start: %(start)s, end: %(end)s)"
        for filter_ in filters:
            if filter_.run_filter_for_index(index):
                cls_name = filter_.__class__.__name__
                start_count = len(list_objs)
                objs = filter_.filter_all(list_objs, spec_obj)
                if objs is None:
                    LOG.debug("Filter %s says to stop filtering", cls_name)
                    return
                list_objs = list(objs)
                end_count = len(list_objs)
                part_filter_results.append(log_msg % {"cls_name": cls_name,
                        "start": start_count, "end": end_count})
                if list_objs:
                    remaining = [(getattr(obj, "host", obj),
                                  getattr(obj, "nodename", ""))
                                 for obj in list_objs]
                    full_filter_results.append((cls_name, remaining))
                else:
                    LOG.info(_LI("Filter %s returned 0 hosts"), cls_name)
                    full_filter_results.append((cls_name, None))
                    break
                LOG.debug("Filter %(cls_name)s returned "
                          "%(obj_len)d host(s)",
                          {'cls_name': cls_name, 'obj_len': len(list_objs)})
        if not list_objs:
            # Log the filtration history
            msg_dict = {
                "inst_uuid": spec_obj.instance_uuid,
                "str_results": str(full_filter_results),
            }
            full_msg = ("Filtering removed all hosts for the request with "
                        "instance ID "
                        "'%(inst_uuid)s'. Filter results: %(str_results)s"
                       ) % msg_dict
            LOG.debug(full_msg)

            msg_dict["str_results"] = str(part_filter_results)
            part_msg = ("Filtering removed all hosts for the request with "
                        "instance ID "
                        "'%(inst_uuid)s'. Filter results: %(str_results)s"
                       ) % msg_dict
            LOG.info(part_msg)
        return list_objs
