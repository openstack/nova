# Copyright 2012 Nebula, Inc.
# Copyright 2014 IBM Corp.
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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack import fakes


class SnapshotsSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "os-snapshots"

    create_subs = {
        'snapshot_name': 'snap-001',
        'description': 'Daily backup',
        'volume_id': '521752a6-acf6-4b2d-bc7a-119f9148cd8c'
    }

    def setUp(self):
        super().setUp()

        self.stub_out(
            "nova.volume.cinder.API.create_snapshot",
            fakes.stub_snapshot_create)
        self.stub_out(
            "nova.volume.cinder.API.delete_snapshot",
            fakes.stub_snapshot_delete)
        self.stub_out(
            "nova.volume.cinder.API.get_all_snapshots",
            fakes.stub_snapshot_get_all)
        self.stub_out(
            "nova.volume.cinder.API.get_snapshot",
            fakes.stub_snapshot_get)

    def _create_snapshot(self):
        response = self._do_post(
            "os-snapshots", "snapshot-create-req", self.create_subs)
        return response

    def test_snapshots_create(self):
        response = self._create_snapshot()
        self._verify_response(
            "snapshot-create-resp", self.create_subs, response, 200)

    def test_snapshots_delete(self):
        self._create_snapshot()
        response = self._do_delete(f'os-snapshots/{uuids.snapshot}')
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    def test_snapshots_detail(self):
        response = self._do_get('os-snapshots/detail')
        self._verify_response('snapshots-detail-resp', {}, response, 200)

    def test_snapshots_list(self):
        response = self._do_get('os-snapshots')
        self._verify_response('snapshots-list-resp', {}, response, 200)

    def test_snapshots_show(self):
        response = self._do_get(f'os-snapshots/{uuids.snapshot}')
        subs = {
            'snapshot_name': 'Default name',
            'description': 'Default description'
        }
        self._verify_response('snapshots-show-resp', subs, response, 200)
