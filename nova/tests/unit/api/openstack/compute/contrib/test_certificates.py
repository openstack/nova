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

import mock
from mox3 import mox
from webob import exc

from nova.api.openstack.compute.contrib import certificates as certificates_v2
from nova.api.openstack.compute.plugins.v3 import certificates \
    as certificates_v21
from nova.cert import rpcapi
from nova import context
from nova import exception
from nova.openstack.common import policy as common_policy
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes


class CertificatesTestV21(test.NoDBTestCase):
    certificates = certificates_v21
    url = '/v3/os-certificates'
    certificate_show_extension = 'compute_extension:v3:os-certificates:show'
    certificate_create_extension = \
        'compute_extension:v3:os-certificates:create'

    def setUp(self):
        super(CertificatesTestV21, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.controller = self.certificates.CertificatesController()

    def test_translate_certificate_view(self):
        pk, cert = 'fakepk', 'fakecert'
        view = self.certificates._translate_certificate_view(cert, pk)
        self.assertEqual(view['data'], cert)
        self.assertEqual(view['private_key'], pk)

    def test_certificates_show_root(self):
        self.mox.StubOutWithMock(self.controller.cert_rpcapi, 'fetch_ca')

        self.controller.cert_rpcapi.fetch_ca(
            mox.IgnoreArg(), project_id='fake').AndReturn('fakeroot')

        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank(self.url + '/root')
        res_dict = self.controller.show(req, 'root')

        response = {'certificate': {'data': 'fakeroot', 'private_key': None}}
        self.assertEqual(res_dict, response)

    def test_certificates_show_policy_failed(self):
        rules = {
            self.certificate_show_extension:
            common_policy.parse_rule("!")
        }
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank(self.url + '/root')
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.show, req, 'root')
        self.assertIn(self.certificate_show_extension,
                      exc.format_message())

    def test_certificates_create_certificate(self):
        self.mox.StubOutWithMock(self.controller.cert_rpcapi,
                                 'generate_x509_cert')

        self.controller.cert_rpcapi.generate_x509_cert(
            mox.IgnoreArg(),
            user_id='fake_user',
            project_id='fake').AndReturn(('fakepk', 'fakecert'))

        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank(self.url)
        res_dict = self.controller.create(req)

        response = {
            'certificate': {'data': 'fakecert',
                            'private_key': 'fakepk'}
        }
        self.assertEqual(res_dict, response)

    def test_certificates_create_policy_failed(self):
        rules = {
            self.certificate_create_extension:
            common_policy.parse_rule("!")
        }
        policy.set_rules(rules)
        req = fakes.HTTPRequest.blank(self.url)
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller.create, req)
        self.assertIn(self.certificate_create_extension,
                      exc.format_message())

    @mock.patch.object(rpcapi.CertAPI, 'fetch_ca',
                side_effect=exception.CryptoCAFileNotFound(project='fake'))
    def test_non_exist_certificates_show(self, mock_fetch_ca):
        req = fakes.HTTPRequest.blank(self.url + '/root')
        self.assertRaises(
            exc.HTTPNotFound,
            self.controller.show,
            req, 'root')


class CertificatesTestV2(CertificatesTestV21):
    certificates = certificates_v2
    url = '/v2/fake/os-certificates'
    certificate_show_extension = 'compute_extension:certificates'
    certificate_create_extension = 'compute_extension:certificates'
