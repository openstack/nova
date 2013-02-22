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
from nova.openstack.common.plugin import plugin


LOG = logging.getLogger(__name__)


class _CallbackNotifier(object):
    """Manages plugin-defined notification callbacks.

    For each Plugin, a CallbackNotifier will be added to the
    notification driver list.  Calls to notify() with appropriate
    messages will be hooked and prompt callbacks.

    A callback should look like this:
      def callback(context, message, user_data)
    """

    def __init__(self):
        self._callback_dict = {}

    def _add_callback(self, event_type, callback, user_data):
        callback_list = self._callback_dict.get(event_type, [])
        callback_list.append({'function': callback,
                              'user_data': user_data})
        self._callback_dict[event_type] = callback_list

    def _remove_callback(self, callback):
        for callback_list in self._callback_dict.values():
            for entry in callback_list:
                if entry['function'] == callback:
                    callback_list.remove(entry)

    def notify(self, context, message):
        if message.get('event_type') not in self._callback_dict:
            return

        for entry in self._callback_dict[message.get('event_type')]:
            entry['function'](context, message, entry.get('user_data'))

    def callbacks(self):
        return self._callback_dict


class CallbackPlugin(plugin.Plugin):
    """ Plugin with a simple callback interface.

    This class is provided as a convenience for producing a simple
    plugin that only watches a couple of events.  For example, here's
    a subclass which prints a line the first time an instance is created.

    class HookInstanceCreation(CallbackPlugin):

        def __init__(self, _service_name):
            super(HookInstanceCreation, self).__init__()
            self._add_callback(self.magic, 'compute.instance.create.start')

        def magic(self):
            print "An instance was created!"
            self._remove_callback(self, self.magic)
    """

    def __init__(self, service_name):
        super(CallbackPlugin, self).__init__(service_name)
        self._callback_notifier = _CallbackNotifier()
        self._add_notifier(self._callback_notifier)

    def _add_callback(self, callback, event_type, user_data=None):
        """Add callback for a given event notification.

        Subclasses can call this as an alternative to implementing
        a fullblown notify notifier.
        """
        self._callback_notifier._add_callback(event_type, callback, user_data)

    def _remove_callback(self, callback):
        """Remove all notification callbacks to specified function."""
        self._callback_notifier._remove_callback(callback)
