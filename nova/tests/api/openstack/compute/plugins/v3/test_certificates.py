# Copyright (c) 2012 OpenStack Foundation
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

from lxml import etree
from webob import exc

from nova.api.openstack.compute.plugins.v3 import certificates
from nova import context
from nova import exception
from nova.openstack.common import rpc
from nova import test
from nova.tests.api.openstack import fakes


def fake_get_root_cert_not_found(context, *args, **kwargs):
    raise exception.CryptoCAFileNotFound(project='')


def fake_get_root_cert(context, *args, **kwargs):
    return 'fakeroot'


def fake_create_cert(context, *args, **kwargs):
    return 'fakepk', 'fakecert'


class CertificatesTest(test.NoDBTestCase):
    def setUp(self):
        super(CertificatesTest, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.controller = certificates.CertificatesController()

    def test_translate_certificate_view(self):
        pk, cert = fake_create_cert(self.context)
        view = certificates._translate_certificate_view(cert, pk)
        self.assertEqual(view['data'], cert)
        self.assertEqual(view['private_key'], pk)

    def test_certificates_show_root(self):
        self.stubs.Set(rpc, 'call', fake_get_root_cert)
        req = fakes.HTTPRequestV3.blank('/os-certificates/root')
        res_dict = self.controller.show(req, 'root')

        cert = fake_get_root_cert(self.context)
        response = {'certificate': {'data': cert, 'private_key': None}}
        self.assertEqual(res_dict, response)

    def test_certificates_show_not_found(self):
        self.stubs.Set(rpc, 'call', fake_get_root_cert_not_found)
        req = fakes.HTTPRequestV3.blank('/os-certificates/root')
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, 'root')

    def test_certificates_create_certificate(self):
        self.stubs.Set(rpc, 'call', fake_create_cert)
        req = fakes.HTTPRequestV3.blank('/os-certificates/')
        res_dict = self.controller.create(req)

        pk, cert = fake_create_cert(self.context)
        response = {'certificate': {'data': cert, 'private_key': pk}}
        self.assertEqual(res_dict, response)
        self.assertEqual(self.controller.create.wsgi_code, 201)


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
