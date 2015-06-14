# Copyright 2014 Hewlett-Packard Development Company, L.P.
#
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Unit tests for the API Request internals."""

import copy

from oslo_utils import timeutils

from nova.api.ec2 import apirequest
from nova import test


class APIRequestTestCase(test.NoDBTestCase):

    def setUp(self):
        super(APIRequestTestCase, self).setUp()
        self.req = apirequest.APIRequest("FakeController", "FakeAction",
                                         "FakeVersion", {})
        self.resp = {
            'string': 'foo',
            'int': 1,
            'long': long(1),
            'bool': False,
            'dict': {
                'string': 'foo',
                'int': 1,
            }
        }

        # The previous will produce an output that looks like the
        # following (excusing line wrap for 80 cols):
        #
        # <FakeActionResponse xmlns="http://ec2.amazonaws.com/doc/\
        #          FakeVersion/">
        #   <requestId>uuid</requestId>
        #   <int>1</int>
        #   <dict>
        #     <int>1</int>
        #     <string>foo</string>
        #   </dict>
        #   <bool>false</bool>
        #   <string>foo</string>
        # </FakeActionResponse>
        #
        # We don't attempt to ever test for the full document because
        # hash seed order might impact it's rendering order. The fact
        # that running the function doesn't explode is a big part of
        # the win.

    def test_render_response_ascii(self):
        data = self.req._render_response(self.resp, 'uuid')
        self.assertIn('<FakeActionResponse xmlns="http://ec2.amazonaws.com/'
                      'doc/FakeVersion/', data)
        self.assertIn('<int>1</int>', data)
        self.assertIn('<string>foo</string>', data)

    def test_render_response_utf8(self):
        resp = copy.deepcopy(self.resp)
        resp['utf8'] = unichr(40960) + u'abcd' + unichr(1972)
        data = self.req._render_response(resp, 'uuid')
        self.assertIn('<utf8>&#40960;abcd&#1972;</utf8>', data)

    # Tests for individual data element format functions

    def test_return_valid_isoformat(self):
        """Ensure that the ec2 api returns datetime in xs:dateTime
           (which apparently isn't datetime.isoformat())
           NOTE(ken-pepple): https://bugs.launchpad.net/nova/+bug/721297
        """
        conv = apirequest._database_to_isoformat
        # sqlite database representation with microseconds
        time_to_convert = timeutils.parse_strtime("2011-02-21 20:14:10.634276",
                                                  "%Y-%m-%d %H:%M:%S.%f")
        self.assertEqual(conv(time_to_convert), '2011-02-21T20:14:10.634Z')
        # mysqlite database representation
        time_to_convert = timeutils.parse_strtime("2011-02-21 19:56:18",
                                                  "%Y-%m-%d %H:%M:%S")
        self.assertEqual(conv(time_to_convert), '2011-02-21T19:56:18.000Z')
