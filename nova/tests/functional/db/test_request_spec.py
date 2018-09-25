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
from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import request_spec
from nova import test
from nova.tests import fixtures
from nova.tests.functional import integrated_helpers
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


@db.api_context_manager.writer
def _delete_request_spec(context, instance_uuid):
    """Deletes a RequestSpec by the instance_uuid."""
    context.session.query(api_models.RequestSpec).filter_by(
        instance_uuid=instance_uuid).delete()


class RequestSpecInstanceMigrationTestCase(
        integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2.1'
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    USE_NEUTRON = True

    def setUp(self):
        super(RequestSpecInstanceMigrationTestCase, self).setUp()
        self.context = context.get_admin_context()

    def _create_instances(self, old=2, total=5):
        request = self._build_minimal_create_server_request()
        # Create all instances that would set a RequestSpec object
        request.update({'max_count': total})
        self.api.post_server({'server': request})

        self.instances = objects.InstanceList.get_all(self.context)
        # Make sure that we have all the needed instances
        self.assertEqual(total, len(self.instances))

        # Fake the legacy behaviour by removing the RequestSpec for some old.
        for i in range(0, old):
            _delete_request_spec(self.context, self.instances[i].uuid)

        # Just add a deleted instance to make sure we don't create
        # a RequestSpec object for it.
        del request['max_count']
        server = self.api.post_server({'server': request})
        self.api.delete_server(server['id'])
        # Make sure we have the deleted instance only soft-deleted in DB
        deleted_instances = objects.InstanceList.get_by_filters(
            self.context, filters={'deleted': True})
        self.assertEqual(1, len(deleted_instances))

    def test_migration(self):
        self._create_instances(old=2, total=5)

        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 2)
        self.assertEqual(2, match)
        self.assertEqual(2, done)

        # Run again the migration call for making sure that we don't check
        # again the same instances
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 3)
        self.assertEqual(3, match)
        self.assertEqual(0, done)

        # Make sure we ran over all the instances
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 50)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

        # Make sure all instances have now a related RequestSpec
        for instance in self.instances:
            uuid = instance.uuid
            try:
                spec = objects.RequestSpec.get_by_instance_uuid(
                    self.context, uuid)
                self.assertEqual(instance.project_id, spec.project_id)
            except exception.RequestSpecNotFound:
                self.fail("RequestSpec not found for instance UUID :%s ", uuid)

    def test_migration_with_none_old(self):
        self._create_instances(old=0, total=5)

        # Make sure no migrations can be found
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 50)
        self.assertEqual(5, match)
        self.assertEqual(0, done)

    def test_migration_with_missing_marker(self):
        self._create_instances(old=2, total=5)

        # Start with 2 old (without request_spec) and 3 new instances:
        # [old, old, new, new, new]
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 2)
        # Instance list after session 1:
        # [upgraded, upgraded<MARKER>, new, new, new]
        self.assertEqual(2, match)
        self.assertEqual(2, done)

        # Delete and remove the marker instance from api table while leaving
        # the spec in request_specs table. This triggers MarkerNotFound
        # exception in the latter session.
        self.api.delete_server(self.instances[1].uuid)
        db.archive_deleted_rows(max_rows=100)
        # Instance list after deletion: [upgraded, new, new, new]

        # This session of migration hits MarkerNotFound exception and then
        # starts from the beginning of the list
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 50)
        self.assertEqual(4, match)
        self.assertEqual(0, done)

        # Make sure we ran over all the instances
        match, done = request_spec.migrate_instances_add_request_spec(
            self.context, 50)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

        # Make sure all instances have now a related RequestSpec
        for instance in self.instances:
            uuid = instance.uuid
            try:
                spec = objects.RequestSpec.get_by_instance_uuid(
                    self.context, uuid)
                self.assertEqual(instance.project_id, spec.project_id)
            except exception.RequestSpecNotFound:
                self.fail("RequestSpec not found for instance UUID :%s ", uuid)
