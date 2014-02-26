# Copyright (c) 2012 OpenStack Foundation
# All Rights Reserved.
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

import mox

from nova.api.openstack.compute.plugins.v3 import certificates
from nova import context
from nova import exception
from nova.openstack.common import policy as common_policy
from nova import test
from nova.tests.api.openstack import fakes


class CertificatesTest(test.NoDBTestCase):
    def setUp(self):
        super(CertificatesTest, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.controller = certificates.CertificatesController()

    def test_translate_certificate_view(self):
        pk, cert = 'fakepk', 'fakecert'
        view = certificates._translate_certificate_view(cert, pk)
        self.assertEqual(view['data'], cert)
        self.assertEqual(view['private_key'], pk)

    def test_certificates_show_root(self):
        self.mox.StubOutWithMock(self.controller.cert_rpcapi, 'fetch_ca')

        self.controller.cert_rpcapi.fetch_ca(
            mox.IgnoreArg(), project_id='fake').AndReturn('fakeroot')

        self.mox.ReplayAll()

        req = fakes.HTTPRequestV3.blank('/os-certificates/root')
        res_dict = self.controller.show(req, 'root')

        response = {'certificate': {'data': 'fakeroot', 'private_key': None}}
        self.assertEqual(res_dict, response)

    def test_certificates_show_policy_failed(self):
        rules = {
            "compute_extension:v3:os-certificates:show":
            common_policy.parse_rule("!")
        }
        common_policy.set_rules(common_policy.Rules(rules))
        req = fakes.HTTPRequestV3.blank('/os-certificates/root')
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.show, req, 'root')
        self.assertIn("compute_extension:v3:os-certificates:show",
                      exc.format_message())

    def test_certificates_create_certificate(self):
        self.mox.StubOutWithMock(self.controller.cert_rpcapi,
                                 'generate_x509_cert')

        self.controller.cert_rpcapi.generate_x509_cert(
            mox.IgnoreArg(),
            user_id='fake_user',
            project_id='fake').AndReturn(('fakepk', 'fakecert'))
        self.mox.ReplayAll()

        req = fakes.HTTPRequestV3.blank('/os-certificates/')
        res_dict = self.controller.create(req)

        response = {
            'certificate': {'data': 'fakecert',
                            'private_key': 'fakepk'}
        }
        self.assertEqual(res_dict, response)
        self.assertEqual(self.controller.create.wsgi_code, 201)

    def test_certificates_create_policy_failed(self):
        rules = {
            "compute_extension:v3:os-certificates:create":
            common_policy.parse_rule("!")
        }
        common_policy.set_rules(common_policy.Rules(rules))
        req = fakes.HTTPRequestV3.blank('/os-certificates/')
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.create, req)
        self.assertIn("compute_extension:v3:os-certificates:create",
                      exc.format_message())
