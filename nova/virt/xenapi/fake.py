# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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
A fake XenAPI SDK.

Allows for xenapi helper classes testing.
"""


class Failure(Exception):
    def __init__(self, message=None):
        super(Failure, self).__init__(message)
        self.details = []

    def __str__(self):
        return 'Fake XenAPI Exception'


class FakeSession(object):
    """
    The session to invoke XenAPI SDK calls.
    FIXME(armando): this is a placeholder
    for the xenapi unittests branch.
    """
    def __init__(self, url):
        pass

    def get_xenapi(self):
        """ Return the xenapi object """
        raise NotImplementedError()

    def get_xenapi_host(self):
        """ Return the xenapi host """
        raise NotImplementedError()

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread.  Returns
        a Deferred for the result."""
        raise NotImplementedError()

    def async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread.  Returns a
        Deferred with the task reference."""
        raise NotImplementedError()

    def wait_for_task(self, task):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes."""
        raise NotImplementedError()

    def __getattr__(self, name):
        raise NotImplementedError()
