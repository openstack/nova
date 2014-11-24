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

from oslo.config import cfg

from nova.tests.functional.v3 import test_servers

CONF = cfg.CONF
CONF.import_opt('manager', 'nova.cells.opts', group='cells')


class AvailabilityZoneJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-availability-zone"

    def _setup_services(self):
        self.conductor = self.start_service('conductor',
            host='conductor', manager=CONF.conductor.manager)
        self.compute = self.start_service('compute', host='compute')
        self.cert = self.start_service('cert', host='cert')
        self.consoleauth = self.start_service('consoleauth',
                                              host='consoleauth')
        self.network = self.start_service('network', host='network')
        self.scheduler = self.start_service('scheduler', host='scheduler')
        self.cells = self.start_service('cells', host='cells',
                                        manager=CONF.cells.manager)

    def test_availability_zone_list(self):
        response = self._do_get('os-availability-zone')
        self._verify_response('availability-zone-list-resp', {}, response, 200)

    def test_availability_zone_detail(self):
        response = self._do_get('os-availability-zone/detail')
        subs = self._get_regexes()
        self._verify_response('availability-zone-detail-resp', subs, response,
                              200)

    def test_availability_zone_post(self):
        self._post_server()
