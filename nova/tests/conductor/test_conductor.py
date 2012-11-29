#    Copyright 2012 IBM Corp.
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

"""Tests for the conductor service"""

from nova.compute import instance_types
from nova.compute import vm_states
from nova import conductor
from nova.conductor import api as conductor_api
from nova.conductor import manager as conductor_manager
from nova.conductor import rpcapi as conductor_rpcapi
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import notifications
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import test


FAKE_IMAGE_REF = 'fake-image-ref'


class BaseTestCase(test.TestCase):
    def setUp(self):
        super(BaseTestCase, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def _create_fake_instance(self, params=None, type_name='m1.tiny'):
        if not params:
            params = {}

        inst = {}
        inst['vm_state'] = vm_states.ACTIVE
        inst['image_ref'] = FAKE_IMAGE_REF
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['host'] = 'fake_host'
        type_id = instance_types.get_instance_type_by_name(type_name)['id']
        inst['instance_type_id'] = type_id
        inst['ami_launch_index'] = 0
        inst['memory_mb'] = 0
        inst['vcpus'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['architecture'] = 'x86_64'
        inst['os_type'] = 'Linux'
        inst.update(params)
        return db.instance_create(self.context, inst)


class ConductorTestCase(BaseTestCase):
    """Conductor Manager Tests"""
    def setUp(self):
        super(ConductorTestCase, self).setUp()
        self.conductor = conductor_manager.ConductorManager()
        self.db = None

    def _do_update(self, instance_uuid, **updates):
        return self.conductor.instance_update(self.context, instance_uuid,
                                              updates)

    def test_instance_update(self):
        instance = self._create_fake_instance()
        new_inst = self._do_update(instance['uuid'],
                                   vm_state=vm_states.STOPPED)
        instance = db.instance_get_by_uuid(self.context, instance['uuid'])
        self.assertEqual(instance['vm_state'], vm_states.STOPPED)
        self.assertEqual(new_inst['vm_state'], instance['vm_state'])

    def test_instance_update_invalid_key(self):
        # NOTE(danms): the real DB API call ignores invalid keys
        if self.db == None:
            self.assertRaises(KeyError,
                              self._do_update, 'any-uuid', foobar=1)

    def test_migration_update(self):
        migration = db.migration_create(self.context.elevated(),
                {'instance_uuid': 'fake-uuid',
                 'status': 'migrating'})
        migration_p = jsonutils.to_primitive(migration)
        migration = self.conductor.migration_update(self.context, migration_p,
                                                    'finished')
        self.assertEqual(migration['status'], 'finished')


class ConductorRPCAPITestCase(ConductorTestCase):
    """Conductor RPC API Tests"""
    def setUp(self):
        super(ConductorRPCAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_rpcapi.ConductorAPI()


class ConductorLocalAPITestCase(ConductorTestCase):
    """Conductor LocalAPI Tests"""
    def setUp(self):
        super(ConductorLocalAPITestCase, self).setUp()
        self.conductor = conductor_api.LocalAPI()
        self.db = db

    def _do_update(self, instance_uuid, **updates):
        # NOTE(danms): the public API takes actual keyword arguments,
        # so override the base class here to make the call correctly
        return self.conductor.instance_update(self.context, instance_uuid,
                                              **updates)


class ConductorAPITestCase(ConductorLocalAPITestCase):
    """Conductor API Tests"""
    def setUp(self):
        super(ConductorAPITestCase, self).setUp()
        self.conductor_service = self.start_service(
            'conductor', manager='nova.conductor.manager.ConductorManager')
        self.conductor = conductor_api.API()
        self.db = None


class ConductorImportTest(test.TestCase):
    def test_import_conductor_local(self):
        self.flags(use_local=True, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.LocalAPI))

    def test_import_conductor_rpc(self):
        self.flags(use_local=False, group='conductor')
        self.assertTrue(isinstance(conductor.API(),
                                   conductor_api.API))


class ConductorPolicyTest(test.TestCase):
    def test_all_allowed_keys(self):

        def fake_db_instance_update(self, *args, **kwargs):
            return None, None
        self.stubs.Set(db, 'instance_update_and_get_original',
                       fake_db_instance_update)

        ctxt = context.RequestContext('fake-user', 'fake-project')
        conductor = conductor_api.LocalAPI()
        updates = {}
        for key in conductor_manager.allowed_updates:
            if key in conductor_manager.datetime_fields:
                updates[key] = timeutils.utcnow()
            else:
                updates[key] = 'foo'
        conductor.instance_update(ctxt, 'fake-instance', **updates)

    def test_allowed_keys_are_real(self):
        instance = models.Instance()
        keys = list(conductor_manager.allowed_updates)

        # NOTE(danms): expected_task_state is a parameter that gets
        # passed to the db layer, but is not actually an instance attribute
        del keys[keys.index('expected_task_state')]

        for key in keys:
            self.assertTrue(hasattr(instance, key))
