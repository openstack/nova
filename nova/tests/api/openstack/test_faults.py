# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import webob
import webob.dec
import webob.exc

from nova import test
from nova.api.openstack import common
from nova.api.openstack import faults


class TestFaults(test.TestCase):

    def test_fault_parts(self):
        req = webob.Request.blank('/.xml')
        f = faults.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
        resp = req.get_response(f)

        first_three_words = resp.body.strip().split()[:3]
        self.assertEqual(first_three_words,
                         ['<badRequest',
                          'code="400"',
                          'xmlns="%s">' % common.XML_NS_V10])
        body_without_spaces = ''.join(resp.body.split())
        self.assertTrue('<message>scram</message>' in body_without_spaces)

    def test_retry_header(self):
        req = webob.Request.blank('/.xml')
        exc = webob.exc.HTTPRequestEntityTooLarge(explanation='sorry',
                                                  headers={'Retry-After': 4})
        f = faults.Fault(exc)
        resp = req.get_response(f)
        first_three_words = resp.body.strip().split()[:3]
        self.assertEqual(first_three_words,
                         ['<overLimit',
                          'code="413"',
                          'xmlns="%s">' % common.XML_NS_V10])
        body_sans_spaces = ''.join(resp.body.split())
        self.assertTrue('<message>sorry</message>' in body_sans_spaces)
        self.assertTrue('<retryAfter>4</retryAfter>' in body_sans_spaces)
        self.assertEqual(resp.headers['Retry-After'], 4)

    def test_raise(self):
        @webob.dec.wsgify
        def raiser(req):
            raise faults.Fault(webob.exc.HTTPNotFound(explanation='whut?'))
        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.status_int, 404)
        self.assertTrue('whut?' in resp.body)
