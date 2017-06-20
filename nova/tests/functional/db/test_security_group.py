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
from nova import objects
from nova import test


class SecurityGroupObjectTestCase(test.TestCase):
    def setUp(self):
        super(SecurityGroupObjectTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')

    def _create_group(self, **values):
        defaults = {'project_id': self.context.project_id,
                    'user_id': self.context.user_id,
                    'name': 'foogroup',
                    'description': 'foodescription'}
        defaults.update(values)
        db_api.security_group_create(self.context, defaults)

    def test_get_counts(self):
        # _create_group() creates a group with project_id and user_id from
        # self.context by default
        self._create_group(name='a')
        self._create_group(name='b', project_id='foo')
        self._create_group(name='c', user_id='bar')

        # Count only across a project
        counts = objects.SecurityGroupList.get_counts(self.context, 'foo')
        self.assertEqual(1, counts['project']['security_groups'])
        self.assertNotIn('user', counts)

        # Count across a project and a user
        counts = objects.SecurityGroupList.get_counts(
            self.context, self.context.project_id,
            user_id=self.context.user_id)

        self.assertEqual(2, counts['project']['security_groups'])
        self.assertEqual(1, counts['user']['security_groups'])
