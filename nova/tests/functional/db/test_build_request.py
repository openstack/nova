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

from oslo_serialization import jsonutils
from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova import objects
from nova.objects import build_request
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_build_request
from nova.tests.unit import fake_request_spec


class BuildRequestTestCase(test.NoDBTestCase):
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
        req_spec = fake_request_spec.fake_spec_obj(remove_id=True)
        req_spec.instance_uuid = self.instance_uuid
        req_spec.create()
        args = fake_build_request.fake_db_req(
                request_spec_id=req_spec.id)
        args.pop('id', None)
        args.pop('request_spec', None)
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
        for key in self.build_req_obj.fields.keys():
            expected = getattr(req, key)
            db_value = db_req[key]
            if key == 'request_spec':
                # NOTE: The object and db value can't be compared directly as
                # objects, so serialize them to a comparable form.
                db_value = jsonutils.dumps(objects.RequestSpec._from_db_object(
                    self.context, objects.RequestSpec(),
                    db_value).obj_to_primitive())
                expected = jsonutils.dumps(expected.obj_to_primitive())
            elif key in build_request.OBJECT_FIELDS:
                expected = jsonutils.dumps(expected.obj_to_primitive())
            elif key in build_request.JSON_FIELDS:
                expected = jsonutils.dumps(expected)
            elif key in build_request.IP_FIELDS:
                expected = str(expected)
            elif key in ['created_at', 'updated_at']:
                # Objects store tz aware datetimes but the db does not.
                expected = expected.replace(tzinfo=None)
            self.assertEqual(expected, db_value)
