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

"""
Resource monitor API specification.

ResourceMonitorBase provides the definition of minimum set of methods
that needs to be implemented by Resource Monitor.
"""

import functools
import types

from oslo.config import cfg
from oslo.utils import timeutils
import six

from nova.i18n import _, _LW
from nova import loadables
from nova.openstack.common import log as logging

compute_monitors_opts = [
    cfg.MultiStrOpt('compute_available_monitors',
                    default=['nova.compute.monitors.all_monitors'],
                    help='Monitor classes available to the compute which may '
                         'be specified more than once.'),
    cfg.ListOpt('compute_monitors',
                default=[],
                help='A list of monitors that can be used for getting '
                     'compute metrics.'),
    ]

CONF = cfg.CONF
CONF.register_opts(compute_monitors_opts)
LOG = logging.getLogger(__name__)


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
        self._data = {}

    @classmethod
    def add_timestamp(cls, func):
        """Decorator to indicate that a method needs to add a timestamp.

        When a function returning a value is decorated by the decorator,
        which means a timestamp should be added into the returned value.
        That is, a tuple (value, timestamp) is returned.

        The timestamp is the time when we update the value in the _data.

        If users hope to define how the timestamp is got by themselves,
        they should not use this decorator in their own classes.
        """
        @functools.wraps(func)
        def wrapper(self, **kwargs):
            return func(self, **kwargs), self._data.get("timestamp", None)
        return wrapper

    def _update_data(self):
        """Method to update the metrics data.

        Each subclass can implement this method to update metrics
        into _data. It will be called in get_metrics.
        """
        pass

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
        self._update_data()
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

    def choose_monitors(self, manager):
        """This function checks the monitor names and metrics names against a
        predefined set of acceptable monitors.
        """
        monitor_classes = self.get_matching_classes(
             CONF.compute_available_monitors)
        monitor_class_map = dict((cls.__name__, cls)
                                 for cls in monitor_classes)
        monitor_cls_names = CONF.compute_monitors
        good_monitors = []
        bad_monitors = []
        metric_names = set()
        for monitor_name in monitor_cls_names:
            if monitor_name not in monitor_class_map:
                bad_monitors.append(monitor_name)
                continue

            try:
                # make sure different monitors do not have the same
                # metric name
                monitor = monitor_class_map[monitor_name](manager)
                metric_names_tmp = set(monitor.get_metric_names())
                overlap = metric_names & metric_names_tmp
                if not overlap:
                    metric_names = metric_names | metric_names_tmp
                    good_monitors.append(monitor)
                else:
                    msg = (_("Excluding monitor %(monitor_name)s due to "
                             "metric name overlap; overlapping "
                             "metrics: %(overlap)s") %
                             {'monitor_name': monitor_name,
                              'overlap': ', '.join(overlap)})
                    LOG.warn(msg)
                    bad_monitors.append(monitor_name)
            except Exception as ex:
                msg = (_("Monitor %(monitor_name)s cannot be used: %(ex)s") %
                         {'monitor_name': monitor_name, 'ex': ex})
                LOG.warn(msg)
                bad_monitors.append(monitor_name)

        if bad_monitors:
            LOG.warning(_LW("The following monitors have been disabled: %s"),
                        ', '.join(bad_monitors))

        return good_monitors


def all_monitors():
    """Return a list of monitor classes found in this directory.

    This method is used as the default for available monitors
    and should return a list of all monitor classes available.
    """
    return ResourceMonitorHandler().get_all_classes()
