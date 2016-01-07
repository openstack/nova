# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit import fake_crypto

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class CertificatesSamplesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    extension_name = "os-certificates"

    def _get_flags(self):
        f = super(CertificatesSamplesJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.certificates.Certificates')
        return f

    def setUp(self):
        super(CertificatesSamplesJsonTest, self).setUp()
        self.stub_out('nova.crypto.ensure_ca_filesystem',
                      fake_crypto.ensure_ca_filesystem)
        self.stub_out('nova.crypto.fetch_ca', fake_crypto.fetch_ca)
        self.stub_out('nova.crypto.generate_x509_cert',
                      fake_crypto.generate_x509_cert)
        self.cert = self.start_service('cert')

    def test_create_certificates(self):
        response = self._do_post('os-certificates',
                                 'certificate-create-req', {})
        self._verify_response('certificate-create-resp', {}, response, 200)

    def test_get_root_certificate(self):
        response = self._do_get('os-certificates/root')
        self._verify_response('certificate-get-root-resp', {}, response, 200)
