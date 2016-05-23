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

import functools

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova import objects
from nova.objects import build_request
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_build_request
from nova.tests.unit.objects import test_objects


class BuildRequestTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(BuildRequestTestCase, self).setUp()
        # NOTE: This means that we're using a database for this test suite
        # despite inheriting from NoDBTestCase
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.build_req_obj = build_request.BuildRequest()
        self.instance_uuid = uuidutils.generate_uuid()
        self.project_id = 'fake-project'

    def _create_req(self):
        args = fake_build_request.fake_db_req()
        args.pop('id', None)
        args['instance_uuid'] = self.instance_uuid
        args['project_id'] = self.project_id
        return build_request.BuildRequest._from_db_object(self.context,
                self.build_req_obj,
                self.build_req_obj._create_in_db(self.context, args))

    def test_get_by_instance_uuid_not_found(self):
        self.assertRaises(exception.BuildRequestNotFound,
                self.build_req_obj._get_by_instance_uuid_from_db, self.context,
                self.instance_uuid)

    def test_get_by_uuid(self):
        req = self._create_req()
        db_req = self.build_req_obj._get_by_instance_uuid_from_db(self.context,
                self.instance_uuid)

        obj_comp = functools.partial(objects.base.obj_equal_prims,
                ignore=['deleted', 'deleted_at', 'created_at',
                    'updated_at'])

        def date_comp(db_val, obj_val):
            # We have this separate comparison method because compare_obj below
            # assumes that db datetimes are tz unaware. That's normally true
            # but not when they're part of a serialized object and not a
            # dedicated datetime column.
            self.assertEqual(db_val.replace(tzinfo=None),
                             obj_val.replace(tzinfo=None))

        for key in self.build_req_obj.fields.keys():
            expected = getattr(req, key)
            db_value = db_req[key]
            if key in ['created_at', 'updated_at']:
                # Objects store tz aware datetimes but the db does not.
                expected = expected.replace(tzinfo=None)
            elif key == 'instance':
                db_instance = objects.Instance.obj_from_primitive(
                        jsonutils.loads(db_value))
                test_objects.compare_obj(self, expected, db_instance,
                        # These objects are not loaded in the test instance
                        allow_missing=['pci_requests', 'numa_topology',
                            'pci_devices', 'security_groups', 'info_cache',
                            'ec2_ids', 'migration_context', 'metadata',
                            'vcpu_model', 'services', 'system_metadata',
                            'tags', 'fault'],
                        comparators={'flavor': obj_comp,
                                     'created_at': date_comp,
                                     'keypairs': obj_comp})
                continue
            self.assertEqual(expected, db_value)
