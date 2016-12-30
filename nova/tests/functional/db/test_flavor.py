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

import mock

from nova import context
from nova import db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import flavor as flavor_obj
from nova import test
from nova.tests import fixtures

fake_api_flavor = {
    'created_at': None,
    'updated_at': None,
    'name': 'm1.foo',
    'memory_mb': 1024,
    'vcpus': 4,
    'root_gb': 20,
    'ephemeral_gb': 0,
    'flavorid': 'm1.foo',
    'swap': 0,
    'rxtx_factor': 1.0,
    'vcpu_weight': 1,
    'disabled': False,
    'is_public': True,
    'extra_specs': {'foo': 'bar'},
    'projects': ['project1', 'project2'],
    }


class ForcedFlavor(objects.Flavor):
    """A Flavor object that lets us create with things still in the main DB.

    This is required for us to be able to test mixed scenarios.
    """
    @staticmethod
    def _ensure_migrated(*args):
        return True


def _create_main_flavor(ctxt, **updates):
    values = dict(fake_api_flavor, flavorid='mainflavor')
    del values['projects']
    del values['extra_specs']
    values.update(updates)
    return db_api.flavor_create(ctxt, values)


class FlavorObjectTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(FlavorObjectTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _delete_main_flavors(self):
        flavors = db_api.flavor_get_all(self.context)
        for flavor in flavors:
            db_api.flavor_destroy(self.context, flavor['flavorid'])

    def test_create(self):
        self._delete_main_flavors()
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self.assertIn('id', flavor)

        # Make sure we find this in the API database
        flavor2 = objects.Flavor._flavor_get_from_db(self.context, flavor.id)
        self.assertEqual(flavor.id, flavor2['id'])

        # Make sure we don't find it in the main database
        self.assertRaises(exception.FlavorNotFoundByName,
                          db.flavor_get_by_name, self.context, flavor.name)
        self.assertRaises(exception.FlavorNotFound,
                          db.flavor_get_by_flavor_id, self.context,
                          flavor.flavorid)

    def test_get_with_no_projects(self):
        self._delete_main_flavors()
        fields = dict(fake_api_flavor, projects=[])
        flavor = objects.Flavor(context=self.context, **fields)
        flavor.create()
        flavor = objects.Flavor.get_by_flavor_id(self.context, flavor.flavorid)
        self.assertEqual([], flavor.projects)

    def test_get_with_projects_and_specs(self):
        self._delete_main_flavors()
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        flavor = objects.Flavor.get_by_id(self.context, flavor.id)
        self.assertEqual(fake_api_flavor['projects'], flavor.projects)
        self.assertEqual(fake_api_flavor['extra_specs'], flavor.extra_specs)

    def _test_query(self, flavor):
        flavor2 = objects.Flavor.get_by_id(self.context, flavor.id)
        self.assertEqual(flavor.id, flavor2.id)

        flavor2 = objects.Flavor.get_by_flavor_id(self.context,
                                                  flavor.flavorid)
        self.assertEqual(flavor.id, flavor2.id)

        flavor2 = objects.Flavor.get_by_name(self.context, flavor.name)
        self.assertEqual(flavor.id, flavor2.id)

    def test_query_api(self):
        self._delete_main_flavors()
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_query(flavor)

    def test_query_main(self):
        _create_main_flavor(self.context)
        flavor = objects.Flavor.get_by_flavor_id(self.context, 'mainflavor')
        self._test_query(flavor)

    def test_save(self):
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        flavor.extra_specs['marty'] = 'mcfly'
        flavor.extra_specs['foo'] = 'bart'
        projects = list(flavor.projects)
        flavor.projects.append('project3')
        flavor.save()

        flavor2 = objects.Flavor.get_by_flavor_id(self.context,
                                                  flavor.flavorid)
        self.assertEqual({'marty': 'mcfly', 'foo': 'bart'},
                         flavor2.extra_specs)
        self.assertEqual(set(projects + ['project3']), set(flavor.projects))

        del flavor.extra_specs['foo']
        del flavor.projects[-1]
        flavor.save()

        flavor2 = objects.Flavor.get_by_flavor_id(self.context,
                                                  flavor.flavorid)
        self.assertEqual({'marty': 'mcfly'}, flavor2.extra_specs)
        self.assertEqual(set(projects), set(flavor2.projects))

    @staticmethod
    @db_api.api_context_manager.reader
    def _collect_flavor_residue_api(context, flavor):
        flavors = context.session.query(api_models.Flavors).\
                  filter_by(id=flavor.id).all()
        specs = context.session.query(api_models.FlavorExtraSpecs).\
                filter_by(flavor_id=flavor.id).all()
        projects = context.session.query(api_models.FlavorProjects).\
                   filter_by(flavor_id=flavor.id).all()

        return len(flavors) + len(specs) + len(projects)

    def _test_destroy(self, flavor):
        flavor.destroy()

        self.assertRaises(exception.FlavorNotFound,
                          objects.Flavor.get_by_name, self.context,
                          flavor.name)

    def test_destroy_api(self):
        self._delete_main_flavors()
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_destroy(flavor)
        self.assertEqual(
            0, self._collect_flavor_residue_api(self.context, flavor))

    def test_destroy_main(self):
        _create_main_flavor(self.context)
        flavor = objects.Flavor.get_by_flavor_id(self.context, 'mainflavor')
        self._test_destroy(flavor)

    def test_destroy_missing_flavor_by_flavorid(self):
        flavor = objects.Flavor(context=self.context, flavorid='foo')
        self.assertRaises(exception.FlavorNotFound,
                          flavor.destroy)

    def test_destroy_missing_flavor_by_id(self):
        flavor = objects.Flavor(context=self.context, flavorid='foo', id=1234)
        self.assertRaises(exception.FlavorNotFound,
                          flavor.destroy)

    def _test_get_all(self, expect_len, marker=None, limit=None):
        flavors = objects.FlavorList.get_all(self.context, marker=marker,
                                             limit=limit)
        self.assertEqual(expect_len, len(flavors))
        return flavors

    def test_get_all(self):
        expect_len = len(db_api.flavor_get_all(self.context))
        self._test_get_all(expect_len)

    def test_get_all_with_some_api_flavors(self):
        expect_len = len(db_api.flavor_get_all(self.context))
        flavor = ForcedFlavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_get_all(expect_len + 1)

    def test_get_all_with_all_api_flavors(self):
        self._delete_main_flavors()
        flavor = ForcedFlavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_get_all(1)

    def test_get_all_with_marker_in_api(self):
        db_flavors = [_create_main_flavor(self.context),
                      _create_main_flavor(self.context,
                                          flavorid='mainflavor2',
                                          name='m1.foo2')]
        db_flavor_ids = [x['flavorid'] for x in db_flavors]
        flavor = ForcedFlavor(context=self.context, **fake_api_flavor)
        flavor.create()
        fake_flavor2 = dict(fake_api_flavor, name='m1.zoo', flavorid='m1.zoo')
        flavor = ForcedFlavor(context=self.context, **fake_flavor2)
        flavor.create()
        result = self._test_get_all(3, marker='m1.foo', limit=3)
        result_flavorids = [x.flavorid for x in result]
        self.assertEqual(['m1.zoo'] + db_flavor_ids[:2], result_flavorids)

    def test_get_all_with_marker_in_main(self):
        db_flavors = [_create_main_flavor(self.context,
                                          flavorid='mainflavor1',
                                          name='main1'),
                      _create_main_flavor(self.context,
                                          flavorid='mainflavor2',
                                          name='main2')]
        db_flavor_ids = [x['flavorid'] for x in db_flavors]
        flavor = ForcedFlavor(context=self.context, **fake_api_flavor)
        flavor.create()
        fake_flavor2 = dict(fake_api_flavor, name='m1.zoo', flavorid='m1.zoo')
        flavor = ForcedFlavor(context=self.context, **fake_flavor2)
        flavor.create()
        result = self._test_get_all(1, marker='mainflavor1', limit=3)
        result_flavorids = [x.flavorid for x in result]
        self.assertEqual(db_flavor_ids[1:], result_flavorids)

    def test_get_all_with_marker_in_neither(self):
        flavor = ForcedFlavor(context=self.context, **fake_api_flavor)
        flavor.create()
        fake_flavor2 = dict(fake_api_flavor, name='m1.zoo', flavorid='m1.zoo')
        flavor = ForcedFlavor(context=self.context, **fake_flavor2)
        flavor.create()
        self.assertRaises(exception.MarkerNotFound,
                          self._test_get_all, 2, marker='noflavoratall')

    def test_create_checks_main_flavors(self):
        _create_main_flavor(self.context)
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        self.assertRaises(exception.ObjectActionError, flavor.create)
        self._delete_main_flavors()
        flavor.create()


class FlavorMigrationTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(FlavorMigrationTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.get_admin_context()

    def test_migration(self):
        # create a flavor in the main database that will be migrated
        _create_main_flavor(self.context)
        main_flavors = len(db.flavor_get_all(self.context))
        self.assertEqual(1, main_flavors)
        match, done = flavor_obj.migrate_flavors(self.context, 50)
        self.assertEqual(main_flavors, match)
        self.assertEqual(main_flavors, done)
        self.assertEqual(0, len(db.flavor_get_all(self.context)))
        self.assertEqual(main_flavors,
                         len(objects.FlavorList.get_all(self.context)))

    def test_migrate_flavor_reset_autoincrement(self):
        # NOTE(danms): Not much we can do here other than just make
        # sure that the non-postgres case does not explode.
        match, done = flavor_obj.migrate_flavor_reset_autoincrement(
            self.context, 0)
        self.assertEqual(0, match)
        self.assertEqual(0, done)

    @mock.patch('nova.objects.flavor.LOG.error')
    def test_migrate_flavors_duplicate_unicode(self, mock_log_error):
        """Tests that we handle a duplicate flavor when migrating and that
        we handle when the exception message is in unicode.
        """
        # First create a flavor that will be migrated from main to API DB.
        main_flavor = _create_main_flavor(self.context)
        # Now create that same flavor in the API DB.
        del main_flavor['id']
        api_flavor = ForcedFlavor(self.context, **main_flavor)
        api_flavor.create()
        # Now let's run the online data migration which will fail to create
        # a duplicate flavor in the API database and will raise FlavorIdExists
        # or FlavorExists which we want to modify to have a unicode message.
        with mock.patch.object(exception.FlavorIdExists, 'msg_fmt',
                               u'\xF0\x9F\x92\xA9'):
            with mock.patch.object(exception.FlavorExists, 'msg_fmt',
                                   u'\xF0\x9F\x92\xA9'):
                match, done = flavor_obj.migrate_flavors(self.context, 50)
                # we found one
                self.assertEqual(1, match)
                # but we didn't migrate it
                self.assertEqual(0, done)
                # and we logged an error for the duplicate flavor
                mock_log_error.assert_called()
