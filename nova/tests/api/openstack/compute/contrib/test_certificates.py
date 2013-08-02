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

from lxml import etree
import mox

from nova.api.openstack.compute.contrib import certificates
from nova import context
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

        req = fakes.HTTPRequest.blank('/v2/fake/os-certificates/root')
        res_dict = self.controller.show(req, 'root')

        response = {'certificate': {'data': 'fakeroot', 'private_key': None}}
        self.assertEqual(res_dict, response)

    def test_certificates_create_certificate(self):
        self.mox.StubOutWithMock(self.controller.cert_rpcapi,
                                 'generate_x509_cert')

        self.controller.cert_rpcapi.generate_x509_cert(
            mox.IgnoreArg(),
            user_id='fake_user',
            project_id='fake').AndReturn(('fakepk', 'fakecert'))

        self.mox.ReplayAll()

        req = fakes.HTTPRequest.blank('/v2/fake/os-certificates/')
        res_dict = self.controller.create(req)

        response = {
            'certificate': {'data': 'fakecert',
                            'private_key': 'fakepk'}
        }
        self.assertEqual(res_dict, response)


class CertificatesSerializerTest(test.NoDBTestCase):
    def test_index_serializer(self):
        serializer = certificates.CertificateTemplate()
        text = serializer.serialize(dict(
                certificate=dict(
                    data='fakecert',
                    private_key='fakepk'),
                ))

        tree = etree.fromstring(text)

        self.assertEqual('certificate', tree.tag)
        self.assertEqual('fakepk', tree.get('private_key'))
        self.assertEqual('fakecert', tree.get('data'))
