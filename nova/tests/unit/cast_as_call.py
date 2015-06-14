# Copyright 2013 Red Hat, Inc.
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

import fixtures
import oslo_messaging as messaging


class CastAsCall(fixtures.Fixture):

    """Make RPC 'cast' behave like a 'call'.

    This is a little hack for tests that need to know when a cast
    operation has completed. The idea is that we wait for the RPC
    endpoint method to complete and return before continuing on the
    caller.

    See Ia7f40718533e450f00cd3e7d753ac65755c70588 for more background.
    """

    def __init__(self, stubs):
        super(CastAsCall, self).__init__()
        self.stubs = stubs

    @staticmethod
    def _stub_out(stubs, obj):
        orig_prepare = obj.prepare

        def prepare(self, *args, **kwargs):
            # Casts with fanout=True would throw errors if its monkeypatched to
            # the call method, so we must override fanout to False
            if 'fanout' in kwargs:
                kwargs['fanout'] = False
            cctxt = orig_prepare(self, *args, **kwargs)
            CastAsCall._stub_out(stubs, cctxt)  # woo, recurse!
            return cctxt

        stubs.Set(obj, 'prepare', prepare)
        stubs.Set(obj, 'cast', obj.call)

    def setUp(self):
        super(CastAsCall, self).setUp()
        self._stub_out(self.stubs, messaging.RPCClient)
