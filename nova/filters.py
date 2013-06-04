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

from nova import loadables
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class BaseFilter(object):
    """Base class for all filter classes."""
    def _filter_one(self, obj, filter_properties):
        """Return True if it passes the filter, False otherwise.
        Override this in a subclass.
        """
        return True

    def filter_all(self, filter_obj_list, filter_properties):
        """Yield objects that pass the filter.

        Can be overriden in a subclass, if you need to base filtering
        decisions on all objects.  Otherwise, one can just override
        _filter_one() to filter a single object.
        """
        for obj in filter_obj_list:
            if self._filter_one(obj, filter_properties):
                yield obj


class BaseFilterHandler(loadables.BaseLoader):
    """Base class to handle loading filter classes.

    This class should be subclassed where one needs to use filters.
    """

    def get_filtered_objects(self, filter_classes, objs,
            filter_properties):
        list_objs = list(objs)
        LOG.debug("Starting with %d host(s)", len(list_objs))
        for filter_cls in filter_classes:
            cls_name = filter_cls.__name__
            objs = filter_cls().filter_all(list_objs,
                                           filter_properties)
            if objs is None:
                LOG.debug("Filter %(cls_name)s says to stop filtering",
                          {'cls_name': cls_name})
                return
            list_objs = list(objs)
            LOG.debug("Filter %(cls_name)s returned %(obj_len)d host(s)",
                      {'cls_name': cls_name, 'obj_len': len(list_objs)})
            if len(list_objs) == 0:
                break
        return list_objs
