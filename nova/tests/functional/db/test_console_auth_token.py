#    Copyright 2016 Hewlett Packard Enterprise Development Company LP
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

from oslo_utils.fixture import uuidsentinel
from oslo_versionedobjects import fixture as ovo_fixture

from nova import context
from nova import exception
from nova import objects
from nova import test


class ConsoleAuthTokenTestCase(test.TestCase):
    def setUp(self):
        super(ConsoleAuthTokenTestCase, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        instance = objects.Instance(
            context=self.context,
            project_id=self.context.project_id,
            uuid=uuidsentinel.fake_instance)
        instance.create()
        self.console = objects.ConsoleAuthToken(
            context=self.context,
            instance_uuid=uuidsentinel.fake_instance,
            console_type='fake-type',
            host='fake-host',
            port=1000,
            internal_access_path='fake-internal_access_path',
            access_url_base='fake-external_access_path'
        )
        self.token = self.console.authorize(100)

    def test_validate(self):
        connection_info = objects.ConsoleAuthToken.validate(
            self.context, self.token)
        expected = self.console.obj_to_primitive()['nova_object.data']
        del expected['created_at']
        ovo_fixture.compare_obj(self, connection_info, expected,
                                allow_missing=['created_at'])

    def test_validate_invalid(self):
        unauthorized_token = uuidsentinel.token
        self.assertRaises(
            exception.InvalidToken,
            objects.ConsoleAuthToken.validate,
            self.context, unauthorized_token)
