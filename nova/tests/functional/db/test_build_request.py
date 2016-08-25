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

from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova import objects
from nova.objects import build_request
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_build_request


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
        expected_req = self._create_req()
        req_obj = self.build_req_obj.get_by_instance_uuid(self.context,
                                                          self.instance_uuid)

        for key in self.build_req_obj.fields.keys():
            expected = getattr(expected_req, key)
            db_value = getattr(req_obj, key)
            if key == 'instance':
                objects.base.obj_equal_prims(expected, db_value)
                continue
            elif key == 'block_device_mappings':
                self.assertEqual(1, len(db_value))
                # Can't compare list objects directly, just compare the single
                # item they contain.
                objects.base.obj_equal_prims(expected[0], db_value[0])
                continue
            self.assertEqual(expected, db_value)

    def test_destroy(self):
        self._create_req()
        db_req = self.build_req_obj.get_by_instance_uuid(self.context,
                                                         self.instance_uuid)
        db_req.destroy()
        self.assertRaises(exception.BuildRequestNotFound,
                self.build_req_obj._get_by_instance_uuid_from_db, self.context,
                self.instance_uuid)

    def test_destroy_twice_raises(self):
        self._create_req()
        db_req = self.build_req_obj.get_by_instance_uuid(self.context,
                                                         self.instance_uuid)
        db_req.destroy()
        self.assertRaises(exception.BuildRequestNotFound, db_req.destroy)
