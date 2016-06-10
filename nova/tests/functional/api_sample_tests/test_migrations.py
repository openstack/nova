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

from nova import context
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base


# NOTE(ShaoHe Feng) here I can not use uuidsentinel, it generate a random
# UUID. The uuid in doc/api_samples files is fixed.
INSTANCE_UUID_1 = "8600d31b-d1a1-4632-b2ff-45c2be1a70ff"
INSTANCE_UUID_2 = "9128d044-7b61-403e-b766-7547076ff6c1"


def _stub_migrations(stub_self, context, filters):
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
            'migration_type': 'resize',
            'hidden': False,
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
            'migration_type': 'resize',
            'hidden': False,
            'created_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
            'updated_at': datetime.datetime(2013, 10, 22, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        }
    ]
    return fake_migrations


class MigrationsSamplesJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-migrations"

    def setUp(self):
        super(MigrationsSamplesJsonTest, self).setUp()
        self.stub_out('nova.compute.api.API.get_migrations',
                      _stub_migrations)

    def test_get_migrations(self):
        response = self._do_get('os-migrations')

        self.assertEqual(200, response.status_code)
        self._verify_response('migrations-get', {}, response, 200)


class MigrationsSamplesJsonTestV2_23(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-migrations"
    microversion = '2.23'
    scenarios = [('v2_23', {'api_major_version': 'v2.1'})]

    fake_migrations = [
        # in-progress live-migration.
        {
            'source_node': 'node1',
            'dest_node': 'node2',
            'source_compute': 'compute1',
            'dest_compute': 'compute2',
            'dest_host': '1.2.3.4',
            'status': 'running',
            'instance_uuid': INSTANCE_UUID_1,
            'old_instance_type_id': 1,
            'new_instance_type_id': 2,
            'migration_type': 'live-migration',
            'hidden': False,
            'created_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        },
        # non in-progress live-migration.
        {
            'source_node': 'node1',
            'dest_node': 'node2',
            'source_compute': 'compute1',
            'dest_compute': 'compute2',
            'dest_host': '1.2.3.4',
            'status': 'error',
            'instance_uuid': INSTANCE_UUID_1,
            'old_instance_type_id': 1,
            'new_instance_type_id': 2,
            'migration_type': 'live-migration',
            'hidden': False,
            'created_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 29, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        },
        # non in-progress resize.
        {
            'source_node': 'node10',
            'dest_node': 'node20',
            'source_compute': 'compute10',
            'dest_compute': 'compute20',
            'dest_host': '5.6.7.8',
            'status': 'error',
            'instance_uuid': INSTANCE_UUID_2,
            'old_instance_type_id': 5,
            'new_instance_type_id': 6,
            'migration_type': 'resize',
            'hidden': False,
            'created_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        },
        # in-progress resize.
        {
            'source_node': 'node10',
            'dest_node': 'node20',
            'source_compute': 'compute10',
            'dest_compute': 'compute20',
            'dest_host': '5.6.7.8',
            'status': 'migrating',
            'instance_uuid': INSTANCE_UUID_2,
            'old_instance_type_id': 5,
            'new_instance_type_id': 6,
            'migration_type': 'resize',
            'hidden': False,
            'created_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'updated_at': datetime.datetime(2016, 0o1, 22, 13, 42, 2),
            'deleted_at': None,
            'deleted': False
        }
    ]

    def setUp(self):
        super(MigrationsSamplesJsonTestV2_23, self).setUp()
        self.api.microversion = self.microversion
        fake_context = context.RequestContext('fake', 'fake')

        for mig in self.fake_migrations:
            mig_obj = objects.Migration(context=fake_context, **mig)
            mig_obj.create()

    def test_get_migrations_v2_23(self):
        response = self._do_get('os-migrations')
        self.assertEqual(200, response.status_code)
        self._verify_response(
            'migrations-get',
            {"instance_1": INSTANCE_UUID_1, "instance_2": INSTANCE_UUID_2},
            response, 200)
