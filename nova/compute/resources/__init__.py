# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

from oslo_log import log as logging
import stevedore

from nova.i18n import _LW

LOG = logging.getLogger(__name__)

RESOURCE_NAMESPACE = 'nova.compute.resources'


class ResourceHandler(object):

    def _log_missing_plugins(self, names):
        for name in names:
            if name not in self._mgr.names():
                LOG.warning(_LW('Compute resource plugin %s was not loaded'),
                            name)

    def __init__(self, names, propagate_map_exceptions=False):
        """Initialise the resource handler by loading the plugins.

        The ResourceHandler uses stevedore to load the resource plugins.
        The handler can handle and report exceptions raised in the plugins
        depending on the value of the propagate_map_exceptions parameter.
        It is useful in testing to propagate exceptions so they are exposed
        as part of the test. If exceptions are not propagated they are
        logged at error level.

        Any named plugins that are not located are logged.

        :param names: the list of plugins to load by name
        :param propagate_map_exceptions: True indicates exceptions in the
        plugins should be raised, False indicates they should be handled and
        logged.
        """
        self._mgr = stevedore.NamedExtensionManager(
            namespace=RESOURCE_NAMESPACE,
            names=names,
            propagate_map_exceptions=propagate_map_exceptions,
            invoke_on_load=True)
        if self._mgr.names():
            LOG.warning(_LW(
                'The Extensible Resource Tracker is deprecated and will '
                'be removed in the 14.0.0 release. If you '
                'use this functionality and have custom resources that '
                'are managed by the Extensible Resource Tracker, please '
                'contact the Nova development team by posting to the '
                'openstack-dev mailing list. There is no future planned '
                'support for the tracking of custom resources.'))
        self._log_missing_plugins(names)

    def reset_resources(self, resources, driver):
        """Reset the resources to their initial state.

        Each plugin is called to reset its state. The resources data provided
        is initial state gathered from the hypervisor. The driver is also
        provided in case the plugin needs to obtain additional information
        from the driver, for example, the memory calculation obtains
        the memory overhead from the driver.

        :param resources: the resources reported by the hypervisor
        :param driver: the driver for the hypervisor

        :returns: None
        """
        if self._mgr.extensions:
            self._mgr.map_method('reset', resources, driver)

    def test_resources(self, usage, limits):
        """Test the ability to support the given instance.

        Each resource plugin is called to determine if it's resource is able
        to support the additional requirements of a new instance. The
        plugins either return None to indicate they have sufficient resource
        available or a human readable string to indicate why they can not.

        :param usage: the additional resource usage
        :param limits: limits used for the calculation

        :returns: a list or return values from the plugins
        """
        if not self._mgr.extensions:
            return []

        reasons = self._mgr.map_method('test', usage, limits)
        return reasons

    def update_from_instance(self, usage, sign=1):
        """Update the resource information to reflect the allocation for
        an instance with the given resource usage.

        :param usage: the resource usage of the instance
        :param sign: has value 1 or -1. 1 indicates the instance is being
        added to the current usage, -1 indicates the instance is being removed.

        :returns: None
        """
        if not self._mgr.extensions:
            return

        if sign == 1:
            self._mgr.map_method('add_instance', usage)
        else:
            self._mgr.map_method('remove_instance', usage)

    def write_resources(self, resources):
        """Write the resource data to populate the resources.

        Each resource plugin is called to write its resource data to
        resources.

        :param resources: the compute node resources

        :returns: None
        """
        if self._mgr.extensions:
            self._mgr.map_method('write', resources)

    def report_free_resources(self):
        """Each resource plugin is called to log free resource information.

        :returns: None
        """
        if not self._mgr.extensions:
            return

        self._mgr.map_method('report_free')
