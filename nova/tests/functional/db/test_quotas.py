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

    def test_migrate_quota_limits(self):
        # Create a limit in api db
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'instances', 5, user_id='fake-user')
        # Create 4 limits in main db
        db_api.quota_create(self.context, 'fake-project', 'cores', 10,
                            user_id='fake-user')
        db_api.quota_create(self.context, 'fake-project', 'ram', 8192,
                            user_id='fake-user')
        db_api.quota_create(self.context, 'fake-project', 'fixed_ips', 10)
        db_api.quota_create(self.context, 'fake-project', 'floating_ips', 10)

        # Migrate with a count/limit of 3
        total, done = quotas.migrate_quota_limits_to_api_db(self.context, 3)
        self.assertEqual(3, total)
        self.assertEqual(3, done)

        # This only fetches from the api db. There should now be 4 limits.
        api_user_limits = quotas.Quotas._get_all_from_db(self.context,
                                                         'fake-project')
        api_proj_limits_dict = quotas.Quotas._get_all_from_db_by_project(
                self.context, 'fake-project')
        api_proj_limits_dict.pop('project_id', None)
        self.assertEqual(4,
                         len(api_user_limits) + len(api_proj_limits_dict))

        # This only fetches from the main db. There should be one left.
        main_user_limits = db_api.quota_get_all(self.context, 'fake-project')
        main_proj_limits_dict = db_api.quota_get_all_by_project(self.context,
                                                                'fake-project')
        main_proj_limits_dict.pop('project_id', None)
        self.assertEqual(1, len(main_user_limits) + len(main_proj_limits_dict))

        self.assertEqual((1, 1),
                         quotas.migrate_quota_limits_to_api_db(
                                self.context, 100))
        self.assertEqual((0, 0),
                         quotas.migrate_quota_limits_to_api_db(
                                self.context, 100))

    def test_migrate_quota_limits_skips_existing(self):
        quotas.Quotas._create_limit_in_db(self.context, 'fake-project',
                                          'instances', 5, user_id='fake-user')
        db_api.quota_create(self.context, 'fake-project', 'instances', 5,
                            user_id='fake-user')
        total, done = quotas.migrate_quota_limits_to_api_db(
                        self.context, 100)
        self.assertEqual(1, total)
        self.assertEqual(1, done)
        total, done = quotas.migrate_quota_limits_to_api_db(
                        self.context, 100)
        self.assertEqual(0, total)
        self.assertEqual(0, done)
        self.assertEqual(1, len(quotas.Quotas._get_all_from_db(
                        self.context, 'fake-project')))

    def test_migrate_quota_classes(self):
        # Create a class in api db
        quotas.Quotas._create_class_in_db(self.context, 'foo', 'instances', 5)
        # Create 3 classes in main db
        db_api.quota_class_create(self.context, 'foo', 'cores', 10)
        db_api.quota_class_create(self.context, db_api._DEFAULT_QUOTA_NAME,
                                  'instances', 10)
        db_api.quota_class_create(self.context, 'foo', 'ram', 8192)

        total, done = quotas.migrate_quota_classes_to_api_db(self.context, 2)
        self.assertEqual(2, total)
        self.assertEqual(2, done)

        # This only fetches from the api db
        api_foo_dict = quotas.Quotas._get_all_class_from_db_by_name(
                self.context, 'foo')
        api_foo_dict.pop('class_name', None)
        api_default_dict = quotas.Quotas._get_all_class_from_db_by_name(
                self.context, db_api._DEFAULT_QUOTA_NAME)
        api_default_dict.pop('class_name', None)
        self.assertEqual(3,
                         len(api_foo_dict) + len(api_default_dict))

        # This only fetches from the main db
        main_foo_dict = db_api.quota_class_get_all_by_name(self.context, 'foo')
        main_foo_dict.pop('class_name', None)
        main_default_dict = db_api.quota_class_get_default(self.context)
        main_default_dict.pop('class_name', None)
        self.assertEqual(1, len(main_foo_dict) + len(main_default_dict))

        self.assertEqual((1, 1),
                         quotas.migrate_quota_classes_to_api_db(
                                self.context, 100))
        self.assertEqual((0, 0),
                         quotas.migrate_quota_classes_to_api_db(
                                self.context, 100))

    def test_migrate_quota_classes_skips_existing(self):
        quotas.Quotas._create_class_in_db(self.context, 'foo-class',
                                          'instances', 5)
        db_api.quota_class_create(self.context, 'foo-class', 'instances', 7)
        total, done = quotas.migrate_quota_classes_to_api_db(
                        self.context, 100)
        self.assertEqual(1, total)
        self.assertEqual(1, done)
        total, done = quotas.migrate_quota_classes_to_api_db(
                        self.context, 100)
        self.assertEqual(0, total)
        self.assertEqual(0, done)
        # Existing class should not be overwritten in the result
        db_class = quotas.Quotas._get_all_class_from_db_by_name(
                        self.context, 'foo-class')
        self.assertEqual(5, db_class['instances'])
