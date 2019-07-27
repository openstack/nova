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

import ddt
import fixtures
import microversion_parse

from oslotest import base

from nova.compute import provider_config
from nova import exception as nova_exc


class SchemaValidationMixin(base.BaseTestCase):
    """This class provides the basic methods for running schema validation test
    cases. It can be used along with ddt.file_data to test a specific schema
    version using tests defined in yaml files. See SchemaValidationTestCasesV1
    for an example of how this was done for schema version 1.

    Because decorators can only access class properties of the class they are
    defined in (even when overriding values in the subclass), the decorators
    need to be placed in the subclass. This is why there are test_ functions in
    the subclass that call the run_test_ methods in this class. This should
    keep things simple as more schema versions are added.
    """
    def setUp(self):
        super(SchemaValidationMixin, self).setUp()
        self.mock_load_yaml = self.useFixture(
            fixtures.MockPatchObject(
                provider_config, '_load_yaml_file')).mock
        self.mock_LOG = self.useFixture(
            fixtures.MockPatchObject(
                provider_config, 'LOG')).mock

    def set_config(self, config=None):
        data = config or {}
        self.mock_load_yaml.return_value = data
        return data

    def run_test_validation_errors(self, config, expected_messages):
        self.set_config(config=config)

        actual_msg = self.assertRaises(
            nova_exc.ProviderConfigException,
            provider_config._parse_provider_yaml, 'test_path').message

        for msg in expected_messages:
            self.assertIn(msg, actual_msg)

    def run_test_validation_success(self, config):
        reference = self.set_config(config=config)

        actual = provider_config._parse_provider_yaml('test_path')

        self.assertEqual(reference, actual)

    def run_schema_version_matching(
            self, min_schema_version, max_schema_version):
        # note _load_yaml_file is mocked so the value is not important
        # however it may appear in logs messages so changing it could
        # result in tests failing unless the expected_messages field
        # is updated in the test data.
        path = 'test_path'

        # test exactly min and max versions are supported
        self.set_config(config={
            'meta': {'schema_version': str(min_schema_version)}})
        provider_config._parse_provider_yaml(path)
        self.set_config(config={
            'meta': {'schema_version': str(max_schema_version)}})
        provider_config._parse_provider_yaml(path)

        self.mock_LOG.warning.assert_not_called()

        # test max major+1 raises
        higher_major = microversion_parse.Version(
            major=max_schema_version.major + 1, minor=max_schema_version.minor)
        self.set_config(config={'meta': {'schema_version': str(higher_major)}})

        self.assertRaises(nova_exc.ProviderConfigException,
                          provider_config._parse_provider_yaml, path)

        # test max major with max minor+1 is logged
        higher_minor = microversion_parse.Version(
            major=max_schema_version.major, minor=max_schema_version.minor + 1)
        expected_log_call = (
            "Provider config file [%(path)s] is at schema version "
            "%(schema_version)s. Nova supports the major version, but "
            "not the minor. Some fields may be ignored." % {
            "path": path, "schema_version": higher_minor})
        self.set_config(config={'meta': {'schema_version': str(higher_minor)}})

        provider_config._parse_provider_yaml(path)

        self.mock_LOG.warning.assert_called_once_with(expected_log_call)


@ddt.ddt
class SchemaValidationTestCasesV1(SchemaValidationMixin):
    MIN_SCHEMA_VERSION = microversion_parse.Version(1, 0)
    MAX_SCHEMA_VERSION = microversion_parse.Version(1, 0)

    @ddt.unpack
    @ddt.file_data('provider_config_data/v1/validation_error_test_data.yaml')
    def test_validation_errors(self, config, expected_messages):
        self.run_test_validation_errors(config, expected_messages)

    @ddt.unpack
    @ddt.file_data('provider_config_data/v1/validation_success_test_data.yaml')
    def test_validation_success(self, config):
        self.run_test_validation_success(config)

    def test_schema_version_matching(self):
        self.run_schema_version_matching(self.MIN_SCHEMA_VERSION,
                                         self.MAX_SCHEMA_VERSION)
