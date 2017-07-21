# Copyright (c) 2014-2016 Red Hat, Inc
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

import mock

from nova.console.rfb import auth
from nova.console.rfb import authnone
from nova import test


class RFBAuthSchemeNoneTestCase(test.NoDBTestCase):

    def test_handshake(self):
        scheme = authnone.RFBAuthSchemeNone()

        sock = mock.MagicMock()
        ret = scheme.security_handshake(sock)

        self.assertEqual(sock, ret)

    def test_types(self):
        scheme = authnone.RFBAuthSchemeNone()

        self.assertEqual(auth.AuthType.NONE, scheme.security_type())
