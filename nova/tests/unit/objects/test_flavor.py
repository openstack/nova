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

import mock

from nova import db
from nova import exception
from nova.objects import flavor as flavor_obj
from nova.tests.unit.objects import test_objects


fake_flavor = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
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
    }


class _TestFlavor(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], obj[field])

    def test_get_by_id(self):
        with mock.patch.object(db, 'flavor_get') as get:
            get.return_value = fake_flavor
            flavor = flavor_obj.Flavor.get_by_id(self.context, 1)
            self._compare(self, fake_flavor, flavor)

    def test_get_by_name(self):
        with mock.patch.object(db, 'flavor_get_by_name') as get_by_name:
            get_by_name.return_value = fake_flavor
            flavor = flavor_obj.Flavor.get_by_name(self.context, 'm1.foo')
            self._compare(self, fake_flavor, flavor)

    def test_get_by_flavor_id(self):
        with mock.patch.object(db, 'flavor_get_by_flavor_id') as get_by_id:
            get_by_id.return_value = fake_flavor
            flavor = flavor_obj.Flavor.get_by_flavor_id(self.context,
                                                        'm1.foo')
            self._compare(self, fake_flavor, flavor)

    def test_add_access(self):
        elevated = self.context.elevated()
        flavor = flavor_obj.Flavor(context=elevated, flavorid='123')
        with mock.patch.object(db, 'flavor_access_add') as add:
            flavor.add_access('456')
            add.assert_called_once_with(elevated, '123', '456')

    def test_add_access_with_dirty_projects(self):
        flavor = flavor_obj.Flavor(context=self.context, projects=['1'])
        self.assertRaises(exception.ObjectActionError,
                          flavor.add_access, '2')

    def test_remove_access(self):
        elevated = self.context.elevated()
        flavor = flavor_obj.Flavor(context=elevated, flavorid='123')
        with mock.patch.object(db, 'flavor_access_remove') as remove:
            flavor.remove_access('456')
            remove.assert_called_once_with(elevated, '123', '456')

    def test_create(self):
        flavor = flavor_obj.Flavor(context=self.context)
        flavor.name = 'm1.foo'
        flavor.extra_specs = fake_flavor['extra_specs']

        with mock.patch.object(db, 'flavor_create') as create:
            create.return_value = fake_flavor
            flavor.create()

        self.assertEqual(self.context, flavor._context)
        # NOTE(danms): Orphan this to avoid lazy-loads
        flavor._context = None
        self._compare(self, fake_flavor, flavor)

    def test_create_with_projects(self):
        context = self.context.elevated()
        flavor = flavor_obj.Flavor(context=context)
        flavor.name = 'm1.foo'
        flavor.extra_specs = fake_flavor['extra_specs']
        flavor.projects = ['project-1', 'project-2']

        db_flavor = dict(fake_flavor, projects=list(flavor.projects))

        with mock.patch.multiple(db, flavor_create=mock.DEFAULT,
                                 flavor_access_get_by_flavor_id=mock.DEFAULT
                                 ) as methods:
            methods['flavor_create'].return_value = db_flavor
            methods['flavor_access_get_by_flavor_id'].return_value = [
                {'project_id': 'project-1'},
                {'project_id': 'project-2'}]
            flavor.create()
            methods['flavor_create'].assert_called_once_with(
                context,
                {'name': 'm1.foo',
                 'extra_specs': fake_flavor['extra_specs']},
                projects=['project-1', 'project-2'])

        self.assertEqual(context, flavor._context)
        # NOTE(danms): Orphan this to avoid lazy-loads
        flavor._context = None
        self._compare(self, fake_flavor, flavor)
        self.assertEqual(['project-1', 'project-2'], flavor.projects)

    def test_create_with_id(self):
        flavor = flavor_obj.Flavor(id=123)
        self.assertRaises(exception.ObjectActionError, flavor.create,
                          self.context)

    @mock.patch('nova.db.flavor_access_add')
    @mock.patch('nova.db.flavor_access_remove')
    @mock.patch('nova.db.flavor_extra_specs_delete')
    @mock.patch('nova.db.flavor_extra_specs_update_or_create')
    def test_save(self, mock_update, mock_delete, mock_remove, mock_add):
        ctxt = self.context.elevated()
        extra_specs = {'key1': 'value1', 'key2': 'value2'}
        projects = ['project-1', 'project-2']
        flavor = flavor_obj.Flavor(context=ctxt, flavorid='foo',
                                   extra_specs=extra_specs, projects=projects)
        flavor.obj_reset_changes()

        # Test deleting an extra_specs key and project
        del flavor.extra_specs['key1']
        del flavor.projects[-1]
        self.assertEqual(set(['extra_specs', 'projects']),
                         flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'value2'}, flavor.extra_specs)
        mock_delete.assert_called_once_with(ctxt, 'foo', 'key1')
        self.assertEqual(['project-1'], flavor.projects)
        mock_remove.assert_called_once_with(ctxt, 'foo', 'project-2')

        # Test updating an extra_specs key value
        flavor.extra_specs['key2'] = 'foobar'
        self.assertEqual(set(['extra_specs']), flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'foobar'}, flavor.extra_specs)
        mock_update.assert_called_with(ctxt, 'foo', {'key2': 'foobar'})

        # Test adding an extra_specs and project
        flavor.extra_specs['key3'] = 'value3'
        flavor.projects.append('project-3')
        self.assertEqual(set(['extra_specs', 'projects']),
                         flavor.obj_what_changed())
        flavor.save()
        self.assertEqual({'key2': 'foobar', 'key3': 'value3'},
                         flavor.extra_specs)
        mock_update.assert_called_with(ctxt, 'foo', {'key2': 'foobar',
                                                     'key3': 'value3'})
        self.assertEqual(['project-1', 'project-3'], flavor.projects)
        mock_add.assert_called_once_with(ctxt, 'foo', 'project-3')

    @mock.patch('nova.db.flavor_create')
    @mock.patch('nova.db.flavor_extra_specs_delete')
    @mock.patch('nova.db.flavor_extra_specs_update_or_create')
    def test_save_deleted_extra_specs(self, mock_update, mock_delete,
                                      mock_create):
        mock_create.return_value = dict(fake_flavor,
                                        extra_specs={'key1': 'value1'})
        ctxt = self.context.elevated()
        flavor = flavor_obj.Flavor(context=ctxt)
        flavor.flavorid = 'test'
        flavor.extra_specs = {'key1': 'value1'}
        flavor.create()
        flavor.extra_specs = {}
        flavor.save()
        mock_delete.assert_called_once_with(ctxt, flavor.flavorid,
                                            'key1')
        self.assertFalse(mock_update.called)

    def test_save_invalid_fields(self):
        flavor = flavor_obj.Flavor(id=123)
        self.assertRaises(exception.ObjectActionError, flavor.save)

    def test_destroy(self):
        flavor = flavor_obj.Flavor(context=self.context, id=123, name='foo')
        with mock.patch.object(db, 'flavor_destroy') as destroy:
            flavor.destroy()
            destroy.assert_called_once_with(self.context, flavor.name)

    def test_load_projects(self):
        flavor = flavor_obj.Flavor(context=self.context, flavorid='foo')
        with mock.patch.object(db, 'flavor_access_get_by_flavor_id') as get:
            get.return_value = [{'project_id': 'project-1'}]
            projects = flavor.projects

        self.assertEqual(['project-1'], projects)
        self.assertNotIn('projects', flavor.obj_what_changed())

    def test_load_anything_else(self):
        flavor = flavor_obj.Flavor()
        self.assertRaises(exception.ObjectActionError,
                          getattr, flavor, 'name')


class TestFlavor(test_objects._LocalTest, _TestFlavor):
    pass


class TestFlavorRemote(test_objects._RemoteTest, _TestFlavor):
    pass


class _TestFlavorList(object):
    def test_get_all(self):
        with mock.patch.object(db, 'flavor_get_all') as get_all:
            get_all.return_value = [fake_flavor]
            filters = {'min_memory_mb': 4096}
            flavors = flavor_obj.FlavorList.get_all(self.context,
                                                    inactive=False,
                                                    filters=filters,
                                                    sort_key='id',
                                                    sort_dir='asc')
            self.assertEqual(1, len(flavors))
            _TestFlavor._compare(self, fake_flavor, flavors[0])
            get_all.assert_called_once_with(self.context, inactive=False,
                                            filters=filters, sort_key='id',
                                            sort_dir='asc', limit=None,
                                            marker=None)


class TestFlavorList(test_objects._LocalTest, _TestFlavorList):
    pass


class TestFlavorListRemote(test_objects._RemoteTest, _TestFlavorList):
    pass
