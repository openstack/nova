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

from nova.tests.functional.api_sample_tests import test_servers


class AvailabilityZoneJsonTest(test_servers.ServersSampleBase):
    ADMIN_API = True
    sample_dir = "os-availability-zone"

    # Do not use the AvailabilityZoneFixture in the base class.
    # TODO(mriedem): Make this more realistic by creating a "us-west" zone
    # and putting the "compute" service host in it.
    availability_zones = []

    def test_availability_zone_list(self):
        response = self._do_get('os-availability-zone')
        self._verify_response('availability-zone-list-resp', {}, response, 200)

    def test_availability_zone_detail(self):
        response = self._do_get('os-availability-zone/detail')
        self._verify_response('availability-zone-detail-resp', {}, response,
                              200)
