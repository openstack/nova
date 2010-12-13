# vim: tabstop=4 shiftwidth=4 softtabstop=4
from twisted.web.domhelpers import _get
from aptdaemon.defer import defer

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


class FakeXenAPISession(object):
    """ The session to invoke XenAPI SDK calls """
    def __init__(self):
        self.fail_next_call = False

    def get_xenapi(self):
        """ Return the xenapi object """
        return self

    def get_xenapi_host(self):
        """ Return the xenapi host """
        return 'FAKE_XENAPI_HOST'

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
        return FakeXenAPIObject(name, self)


class FakeXenAPIObject(object):
    def __init__(self, name, session):
        self.name = name
        self.session = session
        self.FAKE_REF = 'FAKE_REFERENCE_%s' % name

    def get_by_name_label(self, label):
        if label is None:
            return ''   # 'No object found'
        else:
            return 'FAKE_OBJECT_%s_%s' % (self.name, label)

    def getter(self, *args):
        self._check_fail()
        return self.FAKE_REF

    def ref_list(self, *args):
        self._check_fail()
        return [FakeXenAPIRecord()]

    def __getattr__(self, name):
        if name == 'create':
            return self._create
        elif name == 'get_record':
            return self._record
        elif name == 'introduce':
            return self._introduce
        elif name.startswith('get_'):
            getter = 'get_%s' % self.name
            if name == getter:
                return self.getter
            else:
                child = name[name.find('_') + 1:]
                if child.endswith('s'):
                    return FakeXenAPIObject(child[:-1], self.session).ref_list
                else:
                    return FakeXenAPIObject(child, self.session).getter

    def _create(self, *args):
        self._check_fail()
        return self.FAKE_REF

    def _record(self, *args):
        self._check_fail()
        return FakeXenAPIRecord()

    def _introduce(self, *args):
        self._check_fail()
        pass

    def _check_fail(self):
        if self.session.fail_next_call:
            self.session.fail_next_call = False   # Reset!
            raise Failure('Unable to create %s' % self.name)


class FakeXenAPIRecord(dict):
    def __init__(self):
        pass

    def __getitem__(self, attr):
        return ''
