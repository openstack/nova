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

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class Plugin(object):
    """Defines an interface for adding functionality to an OpenStack service.

    A plugin interacts with a service via the following pathways:

    - An optional set of notifiers, managed by calling add_notifier()
      or by overriding _notifiers()

    - A set of api extensions, managed via add_api_extension_descriptor()

    - Direct calls to service functions.

    - Whatever else the plugin wants to do on its own.

    This is the reference implementation.
    """

    # The following functions are provided as convenience methods
    # for subclasses.  Subclasses should call them but probably not
    # override them.
    def _add_api_extension_descriptor(self, descriptor):
        """Subclass convenience method which adds an extension descriptor.

           Subclass constructors should call this method when
           extending a project's REST interface.

           Note that once the api service has loaded, the
           API extension set is more-or-less fixed, so
           this should mainly be called by subclass constructors.
        """
        self._api_extension_descriptors.append(descriptor)

    def _add_notifier(self, notifier):
        """Subclass convenience method which adds a notifier.

           Notifier objects should implement the function notify(message).
           Each notifier receives a notify() call whenever an openstack
           service broadcasts a notification.

           Best to call this during construction.  Notifiers are enumerated
           and registered by the pluginmanager at plugin load time.
        """
        self._notifiers.append(notifier)

    # The following methods are called by OpenStack services to query
    #  plugin features.  Subclasses should probably not override these.
    def _notifiers(self):
        """Returns list of notifiers for this plugin."""
        return self._notifiers

    notifiers = property(_notifiers)

    def _api_extension_descriptors(self):
        """Return a list of API extension descriptors.

           Called by a project API during its load sequence.
        """
        return self._api_extension_descriptors

    api_extension_descriptors = property(_api_extension_descriptors)

    # Most plugins will override this:
    def __init__(self, service_name):
        self._notifiers = []
        self._api_extension_descriptors = []
