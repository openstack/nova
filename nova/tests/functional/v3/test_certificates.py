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

from nova.tests.functional.v3 import api_sample_base


class CertificatesSamplesJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-certificates"

    def test_create_certificates(self):
        response = self._do_post('os-certificates',
                                 'certificate-create-req', {})
        subs = self._get_regexes()
        self._verify_response('certificate-create-resp', subs, response, 200)

    def test_get_root_certificate(self):
        response = self._do_get('os-certificates/root')
        subs = self._get_regexes()
        self._verify_response('certificate-get-root-resp', subs, response, 200)
