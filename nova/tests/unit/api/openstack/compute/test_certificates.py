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

import webob.exc

from nova.api.openstack.compute import certificates \
        as certificates_v21
from nova import context
from nova import test
from nova.tests.unit.api.openstack import fakes


class CertificatesTestV21(test.NoDBTestCase):
    certificates = certificates_v21
    url = '/v2/fake/os-certificates'
    certificate_show_extension = 'os_compute_api:os-certificates:show'
    certificate_create_extension = \
        'os_compute_api:os-certificates:create'

    def setUp(self):
        super(CertificatesTestV21, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.controller = self.certificates.CertificatesController()
        self.req = fakes.HTTPRequest.blank('')

    def test_certificates_show_root(self):
        self.assertRaises(webob.exc.HTTPGone, self.controller.show,
                          self.req, 'root')

    def test_certificates_create_certificate(self):
        self.assertRaises(webob.exc.HTTPGone, self.controller.create, self.req)
