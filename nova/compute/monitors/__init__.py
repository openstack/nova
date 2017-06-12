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

from oslo_log import log as logging
from stevedore import enabled

import nova.conf

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class MonitorHandler(object):

    NAMESPACES = [
        'nova.compute.monitors.cpu',
    ]

    def __init__(self, resource_tracker):
        # Dictionary keyed by the monitor type namespace. Value is the
        # first loaded monitor of that namespace or False.
        self.type_monitor_loaded = {ns: False for ns in self.NAMESPACES}

        self.monitors = []
        for ns in self.NAMESPACES:
            plugin_mgr = enabled.EnabledExtensionManager(
                    namespace=ns,
                    invoke_on_load=True,
                    check_func=self.check_enabled_monitor,
                    invoke_args=(resource_tracker,)
            )
            self.monitors += [ext.obj for ext in plugin_mgr]

    def check_enabled_monitor(self, ext):
        """Ensures that only one monitor is specified of any type."""
        # The extension does not have a namespace attribute, unfortunately,
        # but we can get the namespace by examining the first part of the
        # entry_point_target attribute, which looks like this:
        # 'nova.compute.monitors.cpu.virt_driver:Monitor'
        ept = ext.entry_point_target
        ept_parts = ept.split(':')
        namespace_parts = ept_parts[0].split('.')
        namespace = '.'.join(namespace_parts[0:-1])
        if self.type_monitor_loaded[namespace] is not False:
            LOG.warning("Excluding %(namespace)s monitor "
                        "%(monitor_name)s. Already loaded "
                        "%(loaded_monitor)s.",
                        {'namespace': namespace,
                         'monitor_name': ext.name,
                         'loaded_monitor': self.type_monitor_loaded[namespace]
                        })
            return False

        # NOTE(jaypipes): We used to only have CPU monitors, so
        # CONF.compute_monitors could contain "virt_driver" without any monitor
        # type namespace. So, to maintain backwards-compatibility with that
        # older way of specifying monitors, we first loop through any values in
        # CONF.compute_monitors and put any non-namespace'd values into the
        # 'cpu' namespace.
        cfg_monitors = ['cpu.' + cfg if '.' not in cfg else cfg
                        for cfg in CONF.compute_monitors]
        # NOTE(jaypipes): Append 'nova.compute.monitors.' to any monitor value
        # that doesn't have it to allow CONF.compute_monitors to use shortened
        # namespaces (like 'cpu.' instead of 'nova.compute.monitors.cpu.')
        cfg_monitors = ['nova.compute.monitors.' + cfg
                        if 'nova.compute.monitors.' not in cfg else cfg
                        for cfg in cfg_monitors]
        if namespace + '.' + ext.name in cfg_monitors:
            self.type_monitor_loaded[namespace] = ext.name
            return True
        LOG.warning("Excluding %(namespace)s monitor %(monitor_name)s. "
                    "Not in the list of enabled monitors "
                    "(CONF.compute_monitors).",
                    {'namespace': namespace, 'monitor_name': ext.name})
        return False
