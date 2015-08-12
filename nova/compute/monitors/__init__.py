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
from stevedore import enabled

from nova.i18n import _LW

compute_monitors_opts = [
    cfg.MultiStrOpt('compute_available_monitors',
                    deprecated_for_removal=True,
                    default=None,
                    help='Monitor classes available to the compute which may '
                         'be specified more than once. This option is '
                         'DEPRECATED and no longer used. Use setuptools entry '
                         'points to list available monitor plugins.'),
    cfg.ListOpt('compute_monitors',
                default=[],
                help='A list of monitors that can be used for getting '
                     'compute metrics. You can use the alias/name from '
                     'the setuptools entry points for nova.compute.monitors.* '
                     'namespaces.'),
    ]

CONF = cfg.CONF
CONF.register_opts(compute_monitors_opts)
LOG = logging.getLogger(__name__)


class MonitorHandler(object):

    def __init__(self, resource_tracker):
        self.cpu_monitor_loaded = False

        ns = 'nova.compute.monitors.cpu'
        cpu_plugin_mgr = enabled.EnabledExtensionManager(
                namespace=ns,
                invoke_on_load=True,
                check_func=self.check_enabled_cpu_monitor,
                invoke_args=(resource_tracker,)
        )
        self.monitors = [obj.obj for obj in cpu_plugin_mgr]

    def check_enabled_cpu_monitor(self, ext):
        if self.cpu_monitor_loaded is not False:
            msg = _LW("Excluding CPU monitor %(monitor_name)s. Already "
                      "loaded %(loaded_cpu_monitor)s.")
            msg = msg % {
                'monitor_name': ext.name,
                'loaded_cpu_monitor': self.cpu_monitor_loaded
            }
            LOG.warn(msg)
            return False
        # TODO(jaypipes): Right now, we only have CPU monitors, so we don't
        # need to check if the plugin is a CPU monitor or not. Once non-CPU
        # monitors are added, change this to check either the base class or
        # the set of metric names returned to ensure only a single CPU
        # monitor is loaded at any one time.
        if ext.name in CONF.compute_monitors:
            self.cpu_monitor_loaded = ext.name
            return True
        msg = _LW("Excluding CPU monitor %(monitor_name)s. Not in the "
                  "list of enabled monitors (CONF.compute_monitors).")
        msg = msg % {
            'monitor_name': ext.name,
        }
        LOG.warn(msg)
        return False
