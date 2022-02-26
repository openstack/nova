# Copyright 2022 StackHPC
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

import copy

import mock

from oslo_config import cfg
from oslo_limit import exception as limit_exceptions
from oslo_limit import fixture as limit_fixture
from oslo_utils.fixture import uuidsentinel as uuids

from nova import context
from nova import exception
from nova.limit import local as local_limit
from nova.limit import utils as limit_utils
from nova import objects
from nova import test

CONF = cfg.CONF


class TestLocalLimits(test.NoDBTestCase):
    def setUp(self):
        super(TestLocalLimits, self).setUp()
        self.flags(driver=limit_utils.UNIFIED_LIMITS_DRIVER, group="quota")
        self.context = context.RequestContext()

    def test_enforce_api_limit_metadata(self):
        # default max is 128
        self.useFixture(limit_fixture.LimitFixture(
            {local_limit.SERVER_METADATA_ITEMS: 128}, {}))
        local_limit.enforce_api_limit(local_limit.SERVER_METADATA_ITEMS, 128)

        e = self.assertRaises(exception.MetadataLimitExceeded,
                              local_limit.enforce_api_limit,
                              local_limit.SERVER_METADATA_ITEMS, 129)
        msg = ("Resource %s is over limit" % local_limit.SERVER_METADATA_ITEMS)
        self.assertIn(msg, str(e))

    def test_enforce_api_limit_skip(self):
        self.flags(driver="nova.quota.NoopQuotaDriver", group="quota")
        local_limit.enforce_api_limit(local_limit.SERVER_METADATA_ITEMS, 200)

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_api_limit_session_init_error(self, mock_util):
        mock_util.side_effect = limit_exceptions.SessionInitError('error')

        e = self.assertRaises(exception.KeystoneConnectionFailed,
                              local_limit.enforce_api_limit,
                              local_limit.SERVER_METADATA_ITEMS, 42)
        expected = ('Failed to connect to keystone while enforcing '
                    'server_metadata_items quota limit.')
        self.assertIn(expected, str(e))

    def test_enforce_api_limit_raises_for_invalid_entity(self):
        e = self.assertRaises(ValueError,
                              local_limit.enforce_api_limit,
                              local_limit.KEY_PAIRS, 42)
        expected = '%s is not a valid API limit: %s' % (
            local_limit.KEY_PAIRS, local_limit.API_LIMITS)
        self.assertEqual(expected, str(e))

    def test_enforce_api_limit_no_registered_limit_found(self):
        self.useFixture(limit_fixture.LimitFixture({}, {}))
        e = self.assertRaises(exception.MetadataLimitExceeded,
                              local_limit.enforce_api_limit,
                              local_limit.SERVER_METADATA_ITEMS, 42)
        msg = ("Resource %s is over limit" % local_limit.SERVER_METADATA_ITEMS)
        self.assertIn(msg, str(e))

    def test_enforce_injected_files(self):
        reglimits = {local_limit.INJECTED_FILES: 5,
                     local_limit.INJECTED_FILES_CONTENT: 10 * 1024,
                     local_limit.INJECTED_FILES_PATH: 255}
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))

        local_limit.enforce_api_limit(local_limit.INJECTED_FILES, 5)
        local_limit.enforce_api_limit(local_limit.INJECTED_FILES_CONTENT,
                                      10 * 1024)
        local_limit.enforce_api_limit(local_limit.INJECTED_FILES_PATH, 255)

        e = self.assertRaises(exception.OnsetFileLimitExceeded,
                              local_limit.enforce_api_limit,
                              local_limit.INJECTED_FILES, 6)
        msg = ("Resource %s is over limit" % local_limit.INJECTED_FILES)
        self.assertIn(msg, str(e))
        e = self.assertRaises(exception.OnsetFileContentLimitExceeded,
                              local_limit.enforce_api_limit,
                              local_limit.INJECTED_FILES_CONTENT,
                              10 * 1024 + 1)
        msg = (
            "Resource %s is over limit" % local_limit.INJECTED_FILES_CONTENT)
        self.assertIn(msg, str(e))
        e = self.assertRaises(exception.OnsetFilePathLimitExceeded,
                              local_limit.enforce_api_limit,
                              local_limit.INJECTED_FILES_PATH, 256)
        msg = ("Resource %s is over limit" % local_limit.INJECTED_FILES_PATH)
        self.assertIn(msg, str(e))

    @mock.patch.object(objects.KeyPairList, "get_count_by_user")
    def test_enforce_db_limit_keypairs(self, mock_count):
        self.useFixture(limit_fixture.LimitFixture(
            {local_limit.KEY_PAIRS: 100}, {}))

        mock_count.return_value = 99
        local_limit.enforce_db_limit(self.context, local_limit.KEY_PAIRS,
                                     uuids.user_id, 1)
        mock_count.assert_called_once_with(self.context, uuids.user_id)

        self.assertRaises(exception.KeypairLimitExceeded,
                          local_limit.enforce_db_limit,
                          self.context, local_limit.KEY_PAIRS,
                          uuids.user_id, 2)

        mock_count.return_value = 100
        local_limit.enforce_db_limit(self.context, local_limit.KEY_PAIRS,
                                     uuids.user_id, 0)
        mock_count.return_value = 101
        self.assertRaises(exception.KeypairLimitExceeded,
                          local_limit.enforce_db_limit,
                          self.context, local_limit.KEY_PAIRS,
                          uuids.user_id, 0)

    def test_enforce_db_limit_skip(self):
        self.flags(driver="nova.quota.NoopQuotaDriver", group="quota")
        local_limit.enforce_db_limit(self.context, local_limit.KEY_PAIRS,
                                     uuids.user_id, 1)

    @mock.patch('oslo_limit.limit.Enforcer')
    def test_enforce_db_limit_session_init_error(self, mock_util):
        mock_util.side_effect = limit_exceptions.SessionInitError(
            test.TestingException())

        e = self.assertRaises(exception.KeystoneConnectionFailed,
                              local_limit.enforce_db_limit, self.context,
                              local_limit.KEY_PAIRS, uuids.user_id, 42)
        expected = ('Failed to connect to keystone while enforcing '
                    'server_key_pairs quota limit.')
        self.assertEqual(expected, str(e))

    def test_enforce_db_limit_raise_on_invalid(self):
        e = self.assertRaises(ValueError, local_limit.enforce_db_limit,
                              self.context, local_limit.INJECTED_FILES,
                              uuids.user_id, 1)
        fmt = '%s does not have a DB count function defined: %s'
        expected = fmt % (
            local_limit.INJECTED_FILES, local_limit.DB_COUNT_FUNCTION.keys())
        self.assertEqual(expected, str(e))

    @mock.patch.object(objects.KeyPairList, "get_count_by_user")
    def test_enforce_db_limit_no_registered_limit_found(self, mock_count):
        self.useFixture(limit_fixture.LimitFixture({}, {}))
        mock_count.return_value = 5
        e = self.assertRaises(exception.KeypairLimitExceeded,
                              local_limit.enforce_db_limit, self.context,
                              local_limit.KEY_PAIRS, uuids.user_id, 42)
        msg = ("Resource %s is over limit" % local_limit.KEY_PAIRS)
        self.assertIn(msg, str(e))

    def test_enforce_db_limit_raise_bad_delta(self):
        e = self.assertRaises(ValueError, local_limit.enforce_db_limit,
                              self.context, local_limit.KEY_PAIRS,
                              uuids.user_id, -1)
        self.assertEqual("delta must be a positive integer", str(e))

    @mock.patch.object(objects.InstanceGroupList, "get_counts")
    def test_enforce_db_limit_server_groups(self, mock_count):
        self.useFixture(limit_fixture.LimitFixture(
            {local_limit.SERVER_GROUPS: 10}, {}))

        mock_count.return_value = {'project': {'server_groups': 9}}
        local_limit.enforce_db_limit(self.context, local_limit.SERVER_GROUPS,
                                     uuids.project_id, 1)
        mock_count.assert_called_once_with(self.context, uuids.project_id)

        self.assertRaises(exception.ServerGroupLimitExceeded,
                          local_limit.enforce_db_limit,
                          self.context, local_limit.SERVER_GROUPS,
                          uuids.project_id, 2)

    @mock.patch.object(objects.InstanceGroup, "get_by_uuid")
    def test_enforce_db_limit_server_group_members(self, mock_get):
        self.useFixture(limit_fixture.LimitFixture(
            {local_limit.SERVER_GROUP_MEMBERS: 10}, {}))

        mock_get.return_value = objects.InstanceGroup(members=[])
        local_limit.enforce_db_limit(self.context,
                                     local_limit.SERVER_GROUP_MEMBERS,
                                     uuids.server_group, 10)
        mock_get.assert_called_once_with(self.context, uuids.server_group)

        self.assertRaises(exception.GroupMemberLimitExceeded,
                          local_limit.enforce_db_limit,
                          self.context, local_limit.SERVER_GROUP_MEMBERS,
                          uuids.server_group, 11)

    @mock.patch.object(objects.InstanceGroupList, "get_counts")
    def test_get_in_use(self, mock_count):
        mock_count.return_value = {'project': {'server_groups': 9}}
        usages = local_limit.get_in_use(self.context, uuids.project_id)
        expected_usages = {
            'injected_file_content_bytes': 0,
            'injected_file_path_bytes': 0,
            'injected_files': 0,
            'key_pairs': 0,
            'metadata_items': 0,
            'server_group_members': 0,
            'server_groups': 9
        }
        self.assertEqual(expected_usages, usages)


class GetLegacyLimitsTest(test.NoDBTestCase):
    def setUp(self):
        super(GetLegacyLimitsTest, self).setUp()
        self.new = {"server_metadata_items": 1,
                    "server_injected_files": 2,
                    "server_injected_file_content_bytes": 3,
                    "server_injected_file_path_bytes": 4,
                    "server_key_pairs": 5,
                    "server_groups": 6,
                    "server_group_members": 7}
        self.legacy = {"metadata_items": 1,
                       "injected_files": 2,
                       "injected_file_content_bytes": 3,
                       "injected_file_path_bytes": 4,
                       "key_pairs": 5,
                       "server_groups": 6,
                       "server_group_members": 7}
        self.resources = list(local_limit.API_LIMITS | local_limit.DB_LIMITS)
        self.resources.sort()
        self.flags(driver=limit_utils.UNIFIED_LIMITS_DRIVER, group="quota")

    def test_convert_keys_to_legacy_name(self):
        limits = local_limit._convert_keys_to_legacy_name(self.new)
        self.assertEqual(self.legacy, limits)

    def test_get_legacy_default_limits(self):
        reglimits = copy.deepcopy(self.new)
        reglimits.pop('server_key_pairs')
        self.useFixture(limit_fixture.LimitFixture(reglimits, {}))
        limits = local_limit.get_legacy_default_limits()
        expected = copy.deepcopy(self.legacy)
        expected['key_pairs'] = 0
        self.assertEqual(expected, limits)
