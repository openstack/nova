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
"""

from oslo_config import cfg
from oslo_log import log as logging

import nova.compute.monitors.base
from nova.i18n import _LW
from nova import loadables

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


# TODO(jaypipes): Replace the use of loadables with stevedore.
class ResourceMonitorHandler(loadables.BaseLoader):
    """Base class to handle loading monitor classes.
    """
    def __init__(self):
        super(ResourceMonitorHandler, self).__init__(
                nova.compute.monitors.base.MonitorBase)

    def choose_monitors(self, manager):
        """This function checks the monitor names and metrics names against a
        predefined set of acceptable monitors.
        """
        monitor_classes = self.get_matching_classes(
             CONF.compute_available_monitors)
        monitor_class_map = {cls.__name__: cls for cls in monitor_classes}
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
                metric_names_tmp = monitor.get_metric_names()
                overlap = metric_names & metric_names_tmp
                if not overlap:
                    metric_names = metric_names | metric_names_tmp
                    good_monitors.append(monitor)
                else:
                    msg = (_LW("Excluding monitor %(monitor_name)s due to "
                               "metric name overlap; overlapping "
                               "metrics: %(overlap)s") %
                               {'monitor_name': monitor_name,
                                'overlap': ', '.join(overlap)})
                    LOG.warn(msg)
                    bad_monitors.append(monitor_name)
            except Exception as ex:
                msg = (_LW("Monitor %(monitor_name)s cannot be used: %(ex)s") %
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
