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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class AssistedVolumeSnapshotsJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-assisted-volume-snapshots"

    def _get_flags(self):
        f = super(AssistedVolumeSnapshotsJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.'
            'assisted_volume_snapshots.Assisted_volume_snapshots')
        return f

    def test_create(self):
        """Create a volume snapshots."""
        self.stub_out('nova.compute.api.API.volume_snapshot_create',
                      fakes.stub_compute_volume_snapshot_create)

        subs = {
            'volume_id': '521752a6-acf6-4b2d-bc7a-119f9148cd8c',
            'snapshot_id': '421752a6-acf6-4b2d-bc7a-119f9148cd8c',
            'type': 'qcow2',
            'new_file': 'new_file_name'
        }

        response = self._do_post("os-assisted-volume-snapshots",
                                 "snapshot-create-assisted-req",
                                 subs)
        self._verify_response("snapshot-create-assisted-resp",
                              subs, response, 200)

    def test_snapshots_delete_assisted(self):
        self.stub_out('nova.compute.api.API.volume_snapshot_delete',
                      fakes.stub_compute_volume_snapshot_delete)

        snapshot_id = '100'
        response = self._do_delete(
                'os-assisted-volume-snapshots/%s?delete_info='
                '{"volume_id":"521752a6-acf6-4b2d-bc7a-119f9148cd8c"}'
                % snapshot_id)
        self.assertEqual(204, response.status_code)
        self.assertEqual('', response.content)
