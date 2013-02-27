# Copyright 2012 OpenStack Foundation
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

import pkg_resources

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class PluginManager(object):
    """Manages plugin entrypoints and loading.

    For a service to implement this plugin interface for callback purposes:

      - Make use of the openstack-common notifier system
      - Instantiate this manager in each process (passing in
        project and service name)

    For an API service to extend itself using this plugin interface,
    it needs to query the plugin_extension_factory provided by
    the already-instantiated PluginManager.
    """

    def __init__(self, project_name, service_name):
        """ Construct Plugin Manager; load and initialize plugins.

        project_name (e.g. 'nova' or 'glance') is used
        to construct the entry point that identifies plugins.

        The service_name (e.g. 'compute') is passed on to
        each plugin as a raw string for it to do what it will.
        """
        self._project_name = project_name
        self._service_name = service_name
        self.plugins = []

    def load_plugins(self):
        self.plugins = []

        for entrypoint in pkg_resources.iter_entry_points('%s.plugin' %
                                                          self._project_name):
            try:
                pluginclass = entrypoint.load()
                plugin = pluginclass(self._service_name)
                self.plugins.append(plugin)
            except Exception, exc:
                LOG.error(_("Failed to load plugin %(plug)s: %(exc)s") %
                          {'plug': entrypoint, 'exc': exc})

        # Register individual notifiers.
        for plugin in self.plugins:
            for notifier in plugin.notifiers:
                notifier_api.add_driver(notifier)

    def plugin_extension_factory(self, ext_mgr):
        for plugin in self.plugins:
            descriptors = plugin.api_extension_descriptors
            for descriptor in descriptors:
                ext_mgr.load_extension(descriptor)
