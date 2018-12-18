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

from nova import context
from nova import exception
from nova.objects import base as obj_base
from nova.objects import request_spec
from nova import test
from nova.tests import fixtures
from nova.tests.unit import fake_request_spec


class RequestSpecTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(RequestSpecTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        # NOTE(danms): Only needed for the fallback legacy main db loading
        # code in InstanceGroup.
        self.useFixture(fixtures.Database(database='main'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.spec_obj = request_spec.RequestSpec()
        self.instance_uuid = None

    def _create_spec(self):
        args = fake_request_spec.fake_db_spec()
        args.pop('id', None)
        self.instance_uuid = args['instance_uuid']
        request_spec.RequestSpec._from_db_object(self.context, self.spec_obj,
                self.spec_obj._create_in_db(self.context, args))
        return self.spec_obj

    def test_get_by_instance_uuid_not_found(self):
        self.assertRaises(exception.RequestSpecNotFound,
                self.spec_obj._get_by_instance_uuid_from_db, self.context,
                self.instance_uuid)

    def test_get_by_uuid(self):
        spec = self._create_spec()
        db_spec = self.spec_obj.get_by_instance_uuid(self.context,
                self.instance_uuid)
        self.assertTrue(obj_base.obj_equal_prims(spec, db_spec))

    def test_save_in_db(self):
        spec = self._create_spec()

        old_az = spec.availability_zone
        spec.availability_zone = '%s-new' % old_az
        spec.save()
        db_spec = self.spec_obj.get_by_instance_uuid(self.context,
                spec.instance_uuid)
        self.assertTrue(obj_base.obj_equal_prims(spec, db_spec))
        self.assertNotEqual(old_az, db_spec.availability_zone)

    def test_double_create(self):
        spec = self._create_spec()
        self.assertRaises(exception.ObjectActionError, spec.create)

    def test_destroy(self):
        spec = self._create_spec()
        spec.destroy()
        self.assertRaises(
            exception.RequestSpecNotFound,
            self.spec_obj._get_by_instance_uuid_from_db, self.context,
            self.instance_uuid)

    def test_destroy_not_found(self):
        spec = self._create_spec()
        spec.destroy()
        self.assertRaises(exception.RequestSpecNotFound, spec.destroy)
