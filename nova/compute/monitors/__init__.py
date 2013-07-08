# Copyright 2013 Intel Corporation.
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
# @author: Shane Wang, Intel Corporation.

"""
Resource monitor API specification.

ResourceMonitorBase provides the definition of minimum set of methods
that needs to be implemented by Resource Monitor.
"""

import types

import six

from nova import loadables
from nova.openstack.common import timeutils


class ResourceMonitorMeta(type):
    def __init__(cls, names, bases, dict_):
        """Metaclass that allows us to create a function map and call it later
        to get the metric names and their values.
        """
        super(ResourceMonitorMeta, cls).__init__(names, bases, dict_)

        prefix = '_get_'
        prefix_len = len(prefix)
        cls.metric_map = {}
        for name, value in cls.__dict__.iteritems():
            if (len(name) > prefix_len
               and name[:prefix_len] == prefix
               and isinstance(value, types.FunctionType)):
                metric_name = name[prefix_len:].replace('_', '.')
                cls.metric_map[metric_name] = value


@six.add_metaclass(ResourceMonitorMeta)
class ResourceMonitorBase(object):
    """Base class for resource monitors
    """

    def __init__(self, parent):
        self.compute_manager = parent
        self.source = None

    def get_metric_names(self):
        """Get available metric names.

        Get available metric names, which are represented by a set of keys
        that can be used to check conflicts and duplications
        :returns: a set of keys representing metrics names
        """
        return self.metric_map.keys()

    def get_metrics(self, **kwargs):
        """Get metrics.

        Get metrics, which are represented by a list of dictionaries
        [{'name': metric name,
          'value': metric value,
          'timestamp': the time when the value is retrieved,
          'source': what the value is got by}, ...]
        :param kwargs: extra arguments that might be present
        :returns: a list to tell the current metrics
        """
        data = []
        for name, func in self.metric_map.iteritems():
            ret = func(self, **kwargs)
            data.append(self._populate(name, ret[0], ret[1]))
        return data

    def _populate(self, metric_name, metric_value, timestamp=None):
        """Populate the format what we want from metric name and metric value
        """
        result = {}
        result['name'] = metric_name
        result['value'] = metric_value
        result['timestamp'] = timestamp or timeutils.utcnow()
        result['source'] = self.source

        return result


class ResourceMonitorHandler(loadables.BaseLoader):
    """Base class to handle loading monitor classes.
    """
    def __init__(self):
        super(ResourceMonitorHandler, self).__init__(ResourceMonitorBase)


def all_monitors():
    """Return a list of monitor classes found in this directory.

    This method is used as the default for available monitors
    and should return a list of all monitor classes avaiable.
    """
    return ResourceMonitorHandler().get_all_classes()
