# All Rights Reserved.
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

import os

from oslo_serialization import jsonutils

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import fake_notifier


class NotificationSampleTestBase(test.TestCase):
    """Base class for notification sample testing.

    To add tests for a versioned notification you have to store a sample file
    under doc/notification_sample directory. In the test method in the subclass
    trigger a change in the system that expected to generate the notification
    then use the _verify_notification function to assert if the stored sample
    matches with the generated one.

    If the notification has different payload content depending on the state
    change you triggered then the replacements parameter of the
    _verify_notification function can be used to override values coming from
    the sample file.

    Check nova.functional.notification_sample_tests.test_service_update as an
    example.
    """

    def setUp(self):
        super(NotificationSampleTestBase, self).setUp()

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
                api_version='v2.1'))

        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

    def _get_notification_sample(self, sample):
        sample_dir = os.path.dirname(os.path.abspath(__file__))
        sample_dir = os.path.normpath(os.path.join(
            sample_dir,
            "../../../../doc/notification_samples"))
        return sample_dir + '/' + sample + '.json'

    def _apply_replacements(self, replacements, sample_obj):
        replacements = replacements or {}
        for key, value in replacements.items():
            obj = sample_obj['payload']
            for sub_key in key.split('.')[:-1]:
                obj = obj['nova_object.data'][sub_key]
            obj['nova_object.data'][key.split('.')[-1]] = value

    def _verify_notification(self, sample_file_name, replacements=None):
        """Assert if the generated notification matches with the stored sample

        :param sample_file_name: The name of the sample file to match relative
                                 to doc/notification_samples
        :param replacements: A dict of key value pairs that is used to update
                             the payload field of the sample data before it is
                             matched against the generated notification.
                             The 'x.y':'new-value' key-value pair selects the
                             ["payload"]["nova_object.data"]["x"]
                             ["nova_object.data"]["y"] value from the sample
                             data and overrides it with 'new-value'.
        """

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        notification = fake_notifier.VERSIONED_NOTIFICATIONS[0]

        with open(self._get_notification_sample(sample_file_name)) as sample:
            sample_data = sample.read()

        sample_obj = jsonutils.loads(sample_data)
        self._apply_replacements(replacements, sample_obj)

        self.assertJsonEqual(sample_obj, notification)
