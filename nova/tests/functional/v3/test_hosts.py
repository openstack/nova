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


class HostsSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-hosts"

    def test_host_startup(self):
        response = self._do_get('os-hosts/%s/startup' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-startup', subs, response, 200)

    def test_host_reboot(self):
        response = self._do_get('os-hosts/%s/reboot' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-reboot', subs, response, 200)

    def test_host_shutdown(self):
        response = self._do_get('os-hosts/%s/shutdown' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-shutdown', subs, response, 200)

    def test_host_maintenance(self):
        response = self._do_put('os-hosts/%s' % self.compute.host,
                                'host-put-maintenance-req', {})
        subs = self._get_regexes()
        self._verify_response('host-put-maintenance-resp', subs, response, 200)

    def test_host_get(self):
        response = self._do_get('os-hosts/%s' % self.compute.host)
        subs = self._get_regexes()
        self._verify_response('host-get-resp', subs, response, 200)

    def test_hosts_list(self):
        response = self._do_get('os-hosts')
        subs = self._get_regexes()
        self._verify_response('hosts-list-resp', subs, response, 200)

    def test_hosts_list_compute_service(self):
        response = self._do_get('os-hosts?service=compute')
        subs = self._get_regexes()
        self._verify_response('hosts-list-compute-service-resp',
                               subs, response, 200)
