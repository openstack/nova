# Copyright 2020 Red Hat, Inc.  All rights reserved.
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

# NOTE(artom) This file exists to test eventlet monkeypatching. How and what
# eventlet monkeypatches can be controlled by environment variables that
# are processed by eventlet at import-time (for exmaple, EVENTLET_NO_GREENDNS).
# Nova manages all of this in nova.monkey_patch. Therefore, nova.monkey_patch
# must be the first thing to import eventlet. As nova.tests.functional.__init__
# imports nova.monkey_patch, we're OK here.

import socket
import traceback

from nova import test


class TestMonkeyPatch(test.TestCase):

    def test_greendns_is_disabled(self):
        """Try to resolve a fake fqdn. If we see greendns mentioned in the
        traceback of the raised exception, it means we've not actually disabled
        greendns. See the TODO and NOTE in nova.monkey_patch to understand why
        greendns needs to be disabled.
        """
        raised = False
        try:
            socket.gethostbyname('goat.fake')
        except Exception:
            tb = traceback.format_exc()
            # NOTE(artom) If we've correctly disabled greendns, we expect the
            # traceback to not contain any reference to it.
            self.assertNotIn('greendns.py', tb)
            raised = True
        self.assertTrue(raised)
