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
from nova.objects import quotas
from nova import test
from nova.tests.unit.db import test_db_api


class QuotasObjectTestCase(test.TestCase,
                           test_db_api.ModelsObjectComparatorMixin):
    def setUp(self):
        super(QuotasObjectTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def test_create_class(self):
        created = quotas.Quotas._create_class_in_db(self.context, 'foo',
                                                    'cores', 10)
        db_class = quotas.Quotas._get_class_from_db(self.context, 'foo',
                                                    'cores')
        self._assertEqualObjects(created, db_class)

    def test_create_class_exists(self):
        quotas.Quotas._create_class_in_db(self.context, 'foo', 'cores', 10)
        self.assertRaises(exception.QuotaClassExists,
                          quotas.Quotas._create_class_in_db, self.context,
                          'foo', 'cores', 10)

    def test_update_class(self):
        created = quotas.Quotas._create_class_in_db(self.context, 'foo',
                                                    'cores', 10)
        quotas.Quotas._update_class_in_db(self.context, 'foo', 'cores', 20)
        db_class = quotas.Quotas._get_class_from_db(self.context, 'foo',
                                                    'cores')
        # Should have a limit of 20 now
        created['hard_limit'] = 20
        self._assertEqualObjects(created, db_class, ignored_keys='updated_at')

    def test_update_class_not_found(self):
        self.assertRaises(exception.QuotaClassNotFound,
                          quotas.Quotas._update_class_in_db, self.context,
                          'foo', 'cores', 20)

    def test_create_per_project_limit(self):
        created = quotas.Quotas._create_limit_in_db(self.context,
                                                    'fake-project',
                                                    'fixed_ips', 10)
        db_limit = quotas.Quotas._get_from_db(self.context, 'fake-project',
                                              'fixed_ips')
        self._assertEqualObjects(created, db_limit)

    def test_create_per_user_limit(self):
        created = quotas.Quotas._create_limit_in_db(self.context,
                                                    'fake-project', 'cores',
                                                    10, user_id='fake-user')
        db_limit = quotas.Quotas._get_from_db(self.context, 'fake-project',
                                              'cores', user_id='fake-user')
        self._assertEqualObjects(created, db_limit)

    def test_create_limit_duplicate(self):
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'cores', 10)
        self.assertRaises(exception.QuotaExists,
                          quotas.Quotas._create_limit_in_db, self.context,
                          'fake-project', 'cores', 20)

    def test_update_per_project_limit(self):
        created = quotas.Quotas._create_limit_in_db(self.context,
                                                    'fake-project',
                                                    'fixed_ips', 10)
        quotas.Quotas._update_limit_in_db(self.context, 'fake-project',
                                          'fixed_ips', 20)
        db_limit = quotas.Quotas._get_from_db(self.context, 'fake-project',
                                              'fixed_ips')
        # Should have a limit of 20 now
        created['hard_limit'] = 20
        self._assertEqualObjects(created, db_limit, ignored_keys='updated_at')

    def test_update_per_project_limit_not_found(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          quotas.Quotas._update_limit_in_db, self.context,
                          'fake-project', 'fixed_ips', 20)

    def test_update_per_user_limit(self):
        created = quotas.Quotas._create_limit_in_db(self.context,
                                                    'fake-project', 'cores',
                                                    10, user_id='fake-user')
        quotas.Quotas._update_limit_in_db(self.context, 'fake-project',
                                          'cores', 20, user_id='fake-user')
        db_limit = quotas.Quotas._get_from_db(self.context, 'fake-project',
                                              'cores', user_id='fake-user')
        # Should have a limit of 20 now
        created['hard_limit'] = 20
        self._assertEqualObjects(created, db_limit, ignored_keys='updated_at')

    def test_update_per_user_limit_not_found(self):
        self.assertRaises(exception.ProjectUserQuotaNotFound,
                          quotas.Quotas._update_limit_in_db, self.context,
                          'fake-project', 'cores', 20, user_id='fake-user')

    def test_get_per_project_limit_not_found(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          quotas.Quotas._get_from_db, self.context,
                          'fake-project', 'fixed_ips')

    def test_get_per_user_limit_not_found(self):
        self.assertRaises(exception.ProjectUserQuotaNotFound,
                          quotas.Quotas._get_from_db, self.context,
                          'fake-project', 'cores', user_id='fake-user')

    def test_get_all_per_user_limits(self):
        created = []
        created.append(quotas.Quotas._create_limit_in_db(self.context,
                                                         'fake-project',
                                                         'cores', 10,
                                                         user_id='fake-user'))
        created.append(quotas.Quotas._create_limit_in_db(self.context,
                                                         'fake-project', 'ram',
                                                         8192,
                                                         user_id='fake-user'))
        db_limits = quotas.Quotas._get_all_from_db(self.context,
                                                   'fake-project')
        for i, db_limit in enumerate(db_limits):
            self._assertEqualObjects(created[i], db_limit)

    def test_get_all_per_project_limits_by_project(self):
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'fixed_ips', 20)
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'floating_ips', 10)
        limits_dict = quotas.Quotas._get_all_from_db_by_project(self.context,
                                                                'fake-project')
        self.assertEqual('fake-project', limits_dict['project_id'])
        self.assertEqual(20, limits_dict['fixed_ips'])
        self.assertEqual(10, limits_dict['floating_ips'])

    def test_get_all_per_user_limits_by_project_and_user(self):
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'instances', 5, user_id='fake-user')
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'cores', 10, user_id='fake-user')
        limits_dict = quotas.Quotas._get_all_from_db_by_project_and_user(
                self.context, 'fake-project', 'fake-user')
        self.assertEqual('fake-project', limits_dict['project_id'])
        self.assertEqual('fake-user', limits_dict['user_id'])
        self.assertEqual(5, limits_dict['instances'])
        self.assertEqual(10, limits_dict['cores'])

    def test_destroy_per_project_and_per_user_limits(self):
        # per user limit
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'instances', 5, user_id='fake-user')
        # per project limit
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'fixed_ips', 10)
        quotas.Quotas._destroy_all_in_db_by_project(self.context,
                                                    'fake-project')
        self.assertRaises(exception.ProjectUserQuotaNotFound,
                          quotas.Quotas._get_from_db, self.context,
                          'fake-project', 'instances', user_id='fake-user')
        self.assertRaises(exception.ProjectQuotaNotFound,
                          quotas.Quotas._get_from_db, self.context,
                          'fake-project', 'fixed_ips')

    def test_destroy_per_project_and_per_user_limits_not_found(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          quotas.Quotas._destroy_all_in_db_by_project,
                          self.context, 'fake-project')

    def test_destroy_per_user_limits(self):
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'instances', 5, user_id='fake-user')
        quotas.Quotas._destroy_all_in_db_by_project_and_user(self.context,
                                                             'fake-project',
                                                             'fake-user')
        self.assertRaises(exception.ProjectUserQuotaNotFound,
                          quotas.Quotas._get_from_db, self.context,
                          'fake-project', 'instances', user_id='fake-user')

    def test_destroy_per_user_limits_not_found(self):
        self.assertRaises(
            exception.ProjectUserQuotaNotFound,
            quotas.Quotas._destroy_all_in_db_by_project_and_user,
            self.context, 'fake-project', 'fake-user')

    def test_get_class_not_found(self):
        self.assertRaises(exception.QuotaClassNotFound,
                          quotas.Quotas._get_class_from_db, self.context,
                          'foo', 'cores')

    def test_get_all_class_by_name(self):
        quotas.Quotas._create_class_in_db(self.context, 'foo', 'instances', 5)
        quotas.Quotas._create_class_in_db(self.context, 'foo', 'cores', 10)
        limits_dict = quotas.Quotas._get_all_class_from_db_by_name(
                self.context, 'foo')
        self.assertEqual('foo', limits_dict['class_name'])
        self.assertEqual(5, limits_dict['instances'])
        self.assertEqual(10, limits_dict['cores'])
