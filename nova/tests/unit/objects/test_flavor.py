#    Copyright 2013 Red Hat, Inc.
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

import mock
from oslo_db import exception as db_exc
from oslo_utils import uuidutils

from nova import context as nova_context
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import flavor as flavor_obj
from nova.tests.unit.objects import test_objects


fake_flavor = {
    'created_at': None,
    'updated_at': None,
    'id': 1,
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
    'description': None
    }


# We mock out _get_projects_from_db globally since it raises FlavorNotFound if
# the flavor is not found in the database, which is going to happen in a lot of
# tests when the flavor isn't actually created. Individual tests can override
# this mock as necessary.
@mock.patch('nova.objects.Flavor._get_projects_from_db', lambda *a, **kw: [])
class _TestFlavor(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            # NOTE(danms): The datetimes on SQLA models are tz-unaware,
            # but the object has tz-aware datetimes. If we're comparing
            # a model to an object (as opposed to a fake dict), just
            # ignore the datetimes in the comparison.
            if (isinstance(db, api_models.API_BASE) and
                  isinstance(value, datetime.datetime)):
                continue
            test.assertEqual(db[field], obj[field])

    @mock.patch('nova.objects.Flavor._flavor_get_from_db')
    def test_api_get_by_id_from_api(self, mock_get):
        mock_get.return_value = fake_flavor
        flavor = flavor_obj.Flavor.get_by_id(self.context, 1)
        self._compare(self, fake_flavor, flavor)
        mock_get.assert_called_once_with(self.context, 1)

    @mock.patch('nova.objects.Flavor._flavor_get_by_name_from_db')
    def test_get_by_name_from_api(self, mock_get):
        mock_get.return_value = fake_flavor
        flavor = flavor_obj.Flavor.get_by_name(self.context, 'm1.foo')
        self._compare(self, fake_flavor, flavor)
        mock_get.assert_called_once_with(self.context, 'm1.foo')

    @mock.patch('nova.objects.Flavor._flavor_get_by_flavor_id_from_db')
    def test_get_by_flavor_id_from_api(self, mock_get):
        mock_get.return_value = fake_flavor
        flavor = flavor_obj.Flavor.get_by_flavor_id(self.context, 'm1.foo')
        self._compare(self, fake_flavor, flavor)
        mock_get.assert_called_once_with(self.context, 'm1.foo')

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_api_flavor(context, altid=None):
        fake_db_flavor = dict(fake_flavor)
        del fake_db_flavor['extra_specs']
        del fake_db_flavor['id']
        flavor = api_models.Flavors()
        flavor.update(fake_db_flavor)
        if altid:
            flavor.update({'flavorid': altid,
                           'name': altid})
        flavor.save(context.session)

        fake_db_extra_spec = {'flavor_id': flavor['id'],
                              'key': 'foo', 'value': 'bar'}
        flavor_es = api_models.FlavorExtraSpecs()
        flavor_es.update(fake_db_extra_spec)
        flavor_es.save(context.session)

        return flavor

    def test_get_by_id_from_db(self):
        db_flavor = self._create_api_flavor(self.context)
        flavor = objects.Flavor.get_by_id(self.context, db_flavor['id'])
        self._compare(self, db_flavor, flavor)

    def test_get_by_name_from_db(self):
        db_flavor = self._create_api_flavor(self.context)
        flavor = objects.Flavor.get_by_name(self.context, db_flavor['name'])
        self._compare(self, db_flavor, flavor)

    def test_get_by_flavor_id_from_db(self):
        db_flavor = self._create_api_flavor(self.context)
        flavor = objects.Flavor.get_by_flavor_id(self.context,
                                                 db_flavor['flavorid'])
        self._compare(self, db_flavor, flavor)

    @mock.patch('nova.objects.Flavor._send_notification')
    @mock.patch('nova.objects.Flavor._flavor_add_project')
    def test_add_access_api(self, mock_api_add, mock_notify):
        elevated = self.context.elevated()
        flavor = flavor_obj.Flavor(context=elevated, id=12345, flavorid='123')
        flavor.add_access('456')
        mock_api_add.assert_called_once_with(elevated, 12345, '456')

    def test_add_access_with_dirty_projects(self):
        flavor = flavor_obj.Flavor(context=self.context, projects=['1'])
        self.assertRaises(exception.ObjectActionError,
                          flavor.add_access, '2')

    @mock.patch('nova.objects.Flavor._send_notification')
    @mock.patch('nova.objects.Flavor._flavor_del_project')
    def test_remove_access_api(self, mock_api_del, mock_notify):
        elevated = self.context.elevated()
        flavor = flavor_obj.Flavor(context=elevated, id=12345, flavorid='123')
        flavor.remove_access('456')
        mock_api_del.assert_called_once_with(elevated, 12345, '456')

    @mock.patch('nova.objects.Flavor._flavor_create')
    def test_create(self, mock_create):
        mock_create.return_value = fake_flavor

        flavor = flavor_obj.Flavor(context=self.context)
        flavor.name = 'm1.foo'
        flavor.extra_specs = fake_flavor['extra_specs']
        flavor.create()

        self.assertEqual(self.context, flavor._context)
        # NOTE(danms): Orphan this to avoid lazy-loads
        flavor._context = None
        self._compare(self, fake_flavor, flavor)

    @mock.patch('nova.objects.Flavor._flavor_create')
    def test_create_with_projects(self, mock_create):
        context = self.context.elevated()
        flavor = flavor_obj.Flavor(context=context)
        flavor.name = 'm1.foo'
        flavor.extra_specs = fake_flavor['extra_specs']
        flavor.projects = ['project-1', 'project-2']

        db_flavor = dict(fake_flavor,
                         projects=[{'project_id': pid}
                                   for pid in flavor.projects])
        mock_create.return_value = db_flavor
        flavor.create()

        mock_create.assert_called_once_with(
            context, {'name': 'm1.foo',
                      'extra_specs': fake_flavor['extra_specs'],
                      'projects': ['project-1', 'project-2']})

        self.assertEqual(context, flavor._context)
        # NOTE(danms): Orphan this to avoid lazy-loads
        flavor._context = None
        self._compare(self, fake_flavor, flavor)
        self.assertEqual(['project-1', 'project-2'], flavor.projects)

    def test_create_with_id(self):
        flavor = flavor_obj.Flavor(context=self.context, id=123)
        self.assertRaises(exception.ObjectActionError, flavor.create)

    @mock.patch('nova.db.sqlalchemy.api_models.Flavors')
    def test_create_duplicate(self, mock_flavors):
        mock_flavors.return_value.save.side_effect = db_exc.DBDuplicateEntry
        fields = dict(fake_flavor)
        del fields['id']
        flavor = objects.Flavor(self.context, **fields)
        self.assertRaises(exception.FlavorExists, flavor.create)

    @mock.patch('nova.objects.Flavor._send_notification')
    @mock.patch('nova.objects.Flavor._flavor_add_project')
    @mock.patch('nova.objects.Flavor._flavor_del_project')
    @mock.patch('nova.objects.Flavor._flavor_extra_specs_del')
    @mock.patch('nova.objects.Flavor._flavor_extra_specs_add')
    def test_save_api(self, mock_update, mock_delete, mock_remove, mock_add,
                      mock_notify):
        extra_specs = {'key1': 'value1', 'key2': 'value2'}
        projects = ['project-1', 'project-2']
        flavor = flavor_obj.Flavor(context=self.context, flavorid='foo',
                                   id=123, extra_specs=extra_specs,
                                   projects=projects)
        flavor.obj_reset_changes()

        # Test deleting an extra_specs key and project
        del flavor.extra_specs['key1']
        del flavor.projects[-1]
        self.assertEqual(set(['extra_specs', 'projects']),
                         flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'value2'}, flavor.extra_specs)
        mock_delete.assert_called_once_with(self.context, 123, 'key1')
        self.assertEqual(['project-1'], flavor.projects)
        mock_remove.assert_called_once_with(self.context, 123, 'project-2')

        # Test updating an extra_specs key value
        flavor.extra_specs['key2'] = 'foobar'
        self.assertEqual(set(['extra_specs']), flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'foobar'}, flavor.extra_specs)
        mock_update.assert_called_with(self.context, 123, {'key2': 'foobar'})

        # Test adding an extra_specs and project
        flavor.extra_specs['key3'] = 'value3'
        flavor.projects.append('project-3')
        self.assertEqual(set(['extra_specs', 'projects']),
                         flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'foobar', 'key3': 'value3'},
                         flavor.extra_specs)
        mock_update.assert_called_with(self.context, 123, {'key2': 'foobar',
                                                   'key3': 'value3'})
        self.assertEqual(['project-1', 'project-3'], flavor.projects)
        mock_add.assert_called_once_with(self.context, 123, 'project-3')

    @mock.patch('nova.objects.Flavor._flavor_create')
    @mock.patch('nova.objects.Flavor._flavor_extra_specs_del')
    @mock.patch('nova.objects.Flavor._flavor_extra_specs_add')
    def test_save_deleted_extra_specs(self, mock_add, mock_delete,
                                      mock_create):
        mock_create.return_value = dict(fake_flavor,
                                        extra_specs={'key1': 'value1'})
        flavor = flavor_obj.Flavor(context=self.context)
        flavor.flavorid = 'test'
        flavor.extra_specs = {'key1': 'value1'}
        flavor.create()
        flavor.extra_specs = {}
        flavor.save()
        mock_delete.assert_called_once_with(self.context, flavor.id, 'key1')
        self.assertFalse(mock_add.called)

    def test_save_invalid_fields(self):
        flavor = flavor_obj.Flavor(id=123)
        self.assertRaises(exception.ObjectActionError, flavor.save)

    @mock.patch('nova.objects.Flavor._flavor_destroy')
    def test_destroy_api_by_id(self, mock_destroy):
        mock_destroy.return_value = dict(fake_flavor, id=123)
        flavor = flavor_obj.Flavor(context=self.context, id=123)
        flavor.destroy()
        mock_destroy.assert_called_once_with(self.context, flavor_id=flavor.id)

    @mock.patch('nova.objects.Flavor._flavor_destroy')
    def test_destroy_api_by_flavorid(self, mock_destroy):
        mock_destroy.return_value = dict(fake_flavor, flavorid='foo')
        flavor = flavor_obj.Flavor(context=self.context, flavorid='foo')
        flavor.destroy()
        mock_destroy.assert_called_once_with(self.context,
                                             flavorid=flavor.flavorid)

    def test_load_projects_from_api(self):
        mock_get_projects = mock.Mock(return_value=['a', 'b'])
        objects.Flavor._get_projects_from_db = mock_get_projects
        flavor = objects.Flavor(context=self.context, flavorid='m1.foo')
        self.assertEqual(['a', 'b'], flavor.projects)
        mock_get_projects.assert_called_once_with(self.context, 'm1.foo')
        self.assertNotIn('projects', flavor.obj_what_changed())

    def test_from_db_loads_projects(self):
        fake = dict(fake_flavor, projects=[{'project_id': 'foo'}])
        obj = objects.Flavor._from_db_object(self.context, objects.Flavor(),
                                             fake, expected_attrs=['projects'])
        self.assertIn('projects', obj)
        self.assertEqual(['foo'], obj.projects)

    def test_load_anything_else(self):
        flavor = flavor_obj.Flavor()
        self.assertRaises(exception.ObjectActionError,
                          getattr, flavor, 'name')


class TestFlavor(test_objects._LocalTest, _TestFlavor):
    # NOTE(danms): Run this test local-only because we would otherwise
    # have to do a bunch of change-resetting to handle the way we do
    # our change tracking for special attributes like projects. There is
    # nothing remotely-concerning (see what I did there?) so this is fine.
    def test_projects_in_db(self):
        db_flavor = self._create_api_flavor(self.context)
        flavor = objects.Flavor.get_by_id(self.context, db_flavor['id'])
        flavor.add_access('project1')
        flavor.add_access('project2')
        flavor.add_access('project3')
        flavor.remove_access('project2')
        flavor = flavor.get_by_id(self.context, db_flavor['id'])
        self.assertEqual(['project1', 'project3'], flavor.projects)
        self.assertRaises(exception.FlavorAccessExists,
                          flavor.add_access, 'project1')
        self.assertRaises(exception.FlavorAccessNotFound,
                          flavor.remove_access, 'project2')

    def test_extra_specs_in_db(self):
        db_flavor = self._create_api_flavor(self.context)
        flavor = objects.Flavor.get_by_id(self.context, db_flavor['id'])
        flavor.extra_specs['marty'] = 'mcfly'
        del flavor.extra_specs['foo']
        flavor.save()
        flavor = objects.Flavor.get_by_id(self.context, db_flavor['id'])
        self.assertEqual({'marty': 'mcfly'}, flavor.extra_specs)

    # NOTE(mriedem): There is no remotable method for updating the description
    # in a flavor so we test this local-only.
    @mock.patch('nova.objects.Flavor._send_notification')
    def test_description(self, mock_notify):
        # Create a flavor with a description.
        ctxt = nova_context.get_admin_context()
        flavorid = uuidutils.generate_uuid()
        dict_flavor = dict(fake_flavor, name=flavorid, flavorid=flavorid)
        del dict_flavor['id']
        flavor = flavor_obj.Flavor(ctxt, **dict_flavor)
        flavor.description = 'rainbows and unicorns'
        flavor.create()
        mock_notify.assert_called_once_with('create')
        # Lookup the flavor to make sure the description is set.
        flavor = flavor_obj.Flavor.get_by_flavor_id(ctxt, flavorid)
        self.assertEqual('rainbows and unicorns', flavor.description)

        # Now reset the flavor.description since it's nullable=True.
        mock_notify.reset_mock()
        self.assertEqual(0, len(flavor.obj_what_changed()),
                         flavor.obj_what_changed())
        flavor.description = None
        self.assertEqual(['description'], list(flavor.obj_what_changed()),
                         flavor.obj_what_changed())
        old_updated_at = flavor.updated_at
        flavor.save()
        # Make sure we reloaded the flavor from the database.
        self.assertNotEqual(old_updated_at, flavor.updated_at)
        mock_notify.assert_called_once_with('update')
        self.assertEqual(0, len(flavor.obj_what_changed()),
                         flavor.obj_what_changed())
        # Lookup the flavor to make sure the description is gone.
        flavor = flavor_obj.Flavor.get_by_flavor_id(ctxt, flavorid)
        self.assertIsNone(flavor.description)

        # Test compatibility.
        flavor.description = 'flavor descriptions are not backward compatible'
        data = lambda x: x['nova_object.data']
        flavor_primitive = data(flavor.obj_to_primitive())
        self.assertIn('description', flavor_primitive)
        flavor.obj_make_compatible(flavor_primitive, '1.1')
        self.assertIn('name', flavor_primitive)
        self.assertNotIn('description', flavor_primitive)


class TestFlavorRemote(test_objects._RemoteTest, _TestFlavor):
    pass


class _TestFlavorList(object):
    def test_get_all_from_db(self):
        # Get a list of the actual flavors in the API DB
        api_flavors = flavor_obj._flavor_get_all_from_db(self.context,
                                                         False, None,
                                                         'flavorid', 'asc',
                                                         None, None)

        flavors = objects.FlavorList.get_all(self.context)
        # Make sure we're getting all flavors from the api
        self.assertEqual(len(api_flavors), len(flavors))

    def test_get_all_from_db_with_limit(self):
        flavors = objects.FlavorList.get_all(self.context,
                                             limit=1)
        self.assertEqual(1, len(flavors))

    @mock.patch('nova.objects.flavor._flavor_get_all_from_db')
    def test_get_all(self, mock_api_get):
        _fake_flavor = dict(fake_flavor,
                            id=2, name='m1.bar', flavorid='m1.bar')

        mock_api_get.return_value = [_fake_flavor]
        filters = {'min_memory_mb': 4096}
        flavors = flavor_obj.FlavorList.get_all(self.context,
                                                inactive=False,
                                                filters=filters,
                                                sort_key='id',
                                                sort_dir='asc')
        self.assertEqual(1, len(flavors))
        _TestFlavor._compare(self, _fake_flavor, flavors[0])
        mock_api_get.assert_called_once_with(self.context, inactive=False,
                                             filters=filters, sort_key='id',
                                             sort_dir='asc', limit=None,
                                             marker=None)

    @mock.patch('nova.objects.flavor._flavor_get_all_from_db')
    def test_get_all_limit_applied_to_api(self, mock_api_get):
        _fake_flavor = dict(fake_flavor,
                            id=2, name='m1.bar', flavorid='m1.bar')

        mock_api_get.return_value = [_fake_flavor]
        filters = {'min_memory_mb': 4096}
        flavors = flavor_obj.FlavorList.get_all(self.context,
                                                inactive=False,
                                                filters=filters,
                                                limit=1,
                                                sort_key='id',
                                                sort_dir='asc')
        self.assertEqual(1, len(flavors))
        _TestFlavor._compare(self, _fake_flavor, flavors[0])
        mock_api_get.assert_called_once_with(self.context, inactive=False,
                                             filters=filters, sort_key='id',
                                             sort_dir='asc', limit=1,
                                             marker=None)

    def test_get_no_marker_in_api(self):
        self.assertRaises(exception.MarkerNotFound,
                          flavor_obj.FlavorList.get_all,
                          self.context,
                          inactive=False,
                          filters=None,
                          limit=1,
                          marker='foo',
                          sort_key='id',
                          sort_dir='asc')


class TestFlavorList(test_objects._LocalTest, _TestFlavorList):
    pass


class TestFlavorListRemote(test_objects._RemoteTest, _TestFlavorList):
    pass
