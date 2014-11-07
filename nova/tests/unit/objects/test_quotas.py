#    Copyright 2013 Rackspace Hosting.
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

from nova import context
from nova.objects import quotas as quotas_obj
from nova import quota
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_objects


QUOTAS = quota.QUOTAS


class TestQuotasModule(test.NoDBTestCase):
    def setUp(self):
        super(TestQuotasModule, self).setUp()
        self.context = context.RequestContext('fake_user1', 'fake_proj1')
        self.instance = fake_instance.fake_db_instance(
                project_id='fake_proj2', user_id='fake_user2')

    def test_ids_from_instance_non_admin(self):
        project_id, user_id = quotas_obj.ids_from_instance(
                self.context, self.instance)
        self.assertEqual('fake_user2', user_id)
        self.assertEqual('fake_proj1', project_id)

    def test_ids_from_instance_admin(self):
        project_id, user_id = quotas_obj.ids_from_instance(
                self.context.elevated(), self.instance)
        self.assertEqual('fake_user2', user_id)
        self.assertEqual('fake_proj2', project_id)


class _TestQuotasObject(object):
    def setUp(self):
        super(_TestQuotasObject, self).setUp()
        self.context = context.RequestContext('fake_user1', 'fake_proj1')
        self.instance = fake_instance.fake_db_instance(
                project_id='fake_proj2', user_id='fake_user2')

    def test_from_reservations(self):
        fake_reservations = ['1', '2']
        quotas = quotas_obj.Quotas.from_reservations(
                self.context, fake_reservations)
        self.assertEqual(self.context, quotas._context)
        self.assertEqual(fake_reservations, quotas.reservations)
        self.assertIsNone(quotas.project_id)
        self.assertIsNone(quotas.user_id)

    def test_from_reservations_bogus(self):
        fake_reservations = [_TestQuotasObject, _TestQuotasObject]
        self.assertRaises(ValueError,
                          quotas_obj.Quotas.from_reservations,
                          self.context, fake_reservations)

    def test_from_reservations_instance(self):
        fake_reservations = ['1', '2']
        quotas = quotas_obj.Quotas.from_reservations(
                self.context, fake_reservations,
                instance=self.instance)
        self.assertEqual(self.context, quotas._context)
        self.assertEqual(fake_reservations, quotas.reservations)
        self.assertEqual('fake_proj1', quotas.project_id)
        self.assertEqual('fake_user2', quotas.user_id)

    def test_from_reservations_instance_admin(self):
        fake_reservations = ['1', '2']
        elevated = self.context.elevated()
        quotas = quotas_obj.Quotas.from_reservations(
                elevated, fake_reservations,
                instance=self.instance)
        self.assertEqual(elevated, quotas._context)
        self.assertEqual(fake_reservations, quotas.reservations)
        self.assertEqual('fake_proj2', quotas.project_id)
        self.assertEqual('fake_user2', quotas.user_id)

    def test_reserve(self):
        fake_reservations = ['1', '2']
        quotas = quotas_obj.Quotas()

        self.mox.StubOutWithMock(QUOTAS, 'reserve')
        QUOTAS.reserve(self.context, expire='expire',
                       project_id='project_id', user_id='user_id',
                       moo='cow').AndReturn(fake_reservations)

        self.mox.ReplayAll()
        quotas.reserve(self.context, expire='expire',
                       project_id='project_id', user_id='user_id',
                       moo='cow')
        self.assertEqual(self.context, quotas._context)
        self.assertEqual(fake_reservations, quotas.reservations)
        self.assertEqual('project_id', quotas.project_id)
        self.assertEqual('user_id', quotas.user_id)

    def test_commit(self):
        fake_reservations = ['1', '2']
        quotas = quotas_obj.Quotas.from_reservations(
                self.context, fake_reservations)

        self.mox.StubOutWithMock(QUOTAS, 'commit')
        QUOTAS.commit(self.context, fake_reservations,
                      project_id=None, user_id=None)

        self.mox.ReplayAll()
        quotas.commit()
        self.assertIsNone(quotas.reservations)

    def test_commit_none_reservations(self):
        quotas = quotas_obj.Quotas.from_reservations(self.context, None)
        self.mox.StubOutWithMock(QUOTAS, 'commit')
        self.mox.ReplayAll()
        quotas.commit()

    def test_rollback(self):
        fake_reservations = ['1', '2']
        quotas = quotas_obj.Quotas.from_reservations(
                self.context, fake_reservations)

        self.mox.StubOutWithMock(QUOTAS, 'rollback')
        QUOTAS.rollback(self.context, fake_reservations,
                        project_id=None, user_id=None)

        self.mox.ReplayAll()
        quotas.rollback()
        self.assertIsNone(quotas.reservations)

    def test_rollback_none_reservations(self):
        quotas = quotas_obj.Quotas.from_reservations(self.context, None)
        self.mox.StubOutWithMock(QUOTAS, 'rollback')
        self.mox.ReplayAll()
        quotas.rollback()

    @mock.patch('nova.db.quota_create')
    def test_create_limit(self, mock_create):
        quotas_obj.Quotas.create_limit(self.context, 'fake-project',
                                       'foo', 10, user_id='user')
        mock_create.assert_called_once_with(self.context, 'fake-project',
                                            'foo', 10, user_id='user')

    @mock.patch('nova.db.quota_update')
    def test_update_limit(self, mock_update):
        quotas_obj.Quotas.update_limit(self.context, 'fake-project',
                                       'foo', 10, user_id='user')
        mock_update.assert_called_once_with(self.context, 'fake-project',
                                            'foo', 10, user_id='user')


class TestQuotasObject(_TestQuotasObject, test_objects._LocalTest):
    pass


class TestRemoteQuotasObject(_TestQuotasObject, test_objects._RemoteTest):
    pass
