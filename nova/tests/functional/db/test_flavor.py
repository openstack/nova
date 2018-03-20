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
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
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
    'description': None
    }


class FlavorObjectTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(FlavorObjectTestCase, self).setUp()
        self.useFixture(fixtures.Database())
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_create(self):
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self.assertIn('id', flavor)

        # Make sure we find this in the API database
        flavor2 = objects.Flavor._flavor_get_from_db(self.context, flavor.id)
        self.assertEqual(flavor.id, flavor2['id'])

    def test_get_with_no_projects(self):
        fields = dict(fake_api_flavor, projects=[])
        flavor = objects.Flavor(context=self.context, **fields)
        flavor.create()
        flavor = objects.Flavor.get_by_flavor_id(self.context, flavor.flavorid)
        self.assertEqual([], flavor.projects)

    def test_get_with_projects_and_specs(self):
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
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
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
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_destroy(flavor)
        self.assertEqual(
            0, self._collect_flavor_residue_api(self.context, flavor))

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

    def test_get_all_with_all_api_flavors(self):
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        self._test_get_all(1)

    def test_get_all_with_marker_in_api(self):
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        fake_flavor2 = dict(fake_api_flavor, name='m1.zoo', flavorid='m1.zoo')
        flavor = objects.Flavor(context=self.context, **fake_flavor2)
        flavor.create()
        result = self._test_get_all(1, marker='m1.foo', limit=1)
        result_flavorids = [x.flavorid for x in result]
        self.assertEqual(['m1.zoo'], result_flavorids)

    def test_get_all_with_marker_not_found(self):
        flavor = objects.Flavor(context=self.context, **fake_api_flavor)
        flavor.create()
        fake_flavor2 = dict(fake_api_flavor, name='m1.zoo', flavorid='m1.zoo')
        flavor = objects.Flavor(context=self.context, **fake_flavor2)
        flavor.create()
        self.assertRaises(exception.MarkerNotFound,
                          self._test_get_all, 2, marker='noflavoratall')
