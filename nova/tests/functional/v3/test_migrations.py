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

import datetime

from nova.compute import api as compute_api
from nova.tests.functional.v3 import api_sample_base


class MigrationsSamplesJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-migrations"

    def _stub_migrations(self, context, filters):
        fake_migrations = [
            {
                'id': 1234,
                'source_node': 'node1',
                'dest_node': 'node2',
                'source_compute': 'compute1',
                'dest_compute': 'compute2',
                'dest_host': '1.2.3.4',
                'status': 'Done',
                'instance_uuid': 'instance_id_123',
                'old_instance_type_id': 1,
                'new_instance_type_id': 2,
                'created_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                'updated_at': datetime.datetime(2012, 10, 29, 13, 42, 2),
                'deleted_at': None,
                'deleted': False
            },
            {
                'id': 5678,
                'source_node': 'node10',
                'dest_node': 'node20',
                'source_compute': 'compute10',
                'dest_compute': 'compute20',
                'dest_host': '5.6.7.8',
                'status': 'Done',
                'instance_uuid': 'instance_id_456',
                'old_instance_type_id': 5,
                'new_instance_type_id': 6,
                'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
                'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
                'deleted_at': None,
                'deleted': False
            }
        ]
        return fake_migrations

    def setUp(self):
        super(MigrationsSamplesJsonTest, self).setUp()
        self.stubs.Set(compute_api.API, 'get_migrations',
                       self._stub_migrations)

    def test_get_migrations(self):
        response = self._do_get('os-migrations')
        subs = self._get_regexes()

        self.assertEqual(response.status_code, 200)
        self._verify_response('migrations-get', subs, response, 200)
