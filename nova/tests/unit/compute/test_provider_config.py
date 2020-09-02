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
import ddt
import fixtures
import microversion_parse
import os

from unittest import mock

from oslo_utils.fixture import uuidsentinel
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


@ddt.ddt
class ValidateProviderConfigTestCases(base.BaseTestCase):
    @ddt.unpack
    @ddt.file_data('provider_config_data/validate_provider_good_config.yaml')
    def test__validate_provider_good_config(self, sample):
        provider_config._validate_provider_config(sample, "fake_path")

    @ddt.unpack
    @ddt.file_data('provider_config_data/validate_provider_bad_config.yaml')
    def test__validate_provider_bad_config(self, sample, expected_messages):
        actual_msg = self.assertRaises(
            nova_exc.ProviderConfigException,
            provider_config._validate_provider_config,
            sample, 'fake_path').message

        self.assertIn(actual_msg, expected_messages)

    @mock.patch.object(provider_config, 'LOG')
    def test__validate_provider_config_one_noop_provider(self, mock_log):
        expected = {
            "providers": [
                {
                    "identification": {"name": "NAME1"},
                    "inventories": {
                        "additional": [
                            {"CUSTOM_RESOURCE_CLASS": {}}
                        ]
                    }
                },
                {
                    "identification": {"name": "NAME_453764"},
                    "inventories": {
                        "additional": []
                    },
                    "traits": {
                        "additional": []
                    }
                }
            ]
        }
        data = copy.deepcopy(expected)

        valid = provider_config._validate_provider_config(data, "fake_path")

        mock_log.warning.assert_called_once_with(
            "Provider NAME_453764 defined in "
            "fake_path has no additional "
            "inventories or traits and will be ignored."
        )
        # assert that _validate_provider_config does not mutate inputs
        self.assertEqual(expected, data)
        # assert that the first entry in the returned tuple is the full set
        # of providers not a copy and is equal to the expected providers.
        self.assertIs(data['providers'][0], valid[0])
        self.assertEqual(expected['providers'][0], valid[0])


class GetProviderConfigsTestCases(base.BaseTestCase):
    @mock.patch.object(provider_config, 'glob')
    def test_get_provider_configs_one_file(self, mock_glob):
        expected = {
            "$COMPUTE_NODE": {
                "__source_file": "example_provider.yaml",
                "identification": {
                    "name": "$COMPUTE_NODE"
                },
                "inventories": {
                    "additional": [
                        {
                            "CUSTOM_EXAMPLE_RESOURCE_CLASS": {
                                "total": 100,
                                "reserved": 0,
                                "min_unit": 1,
                                "max_unit": 10,
                                "step_size": 1,
                                "allocation_ratio": 1.0
                            }
                        }
                    ]
                },
                "traits": {
                    "additional": [
                        "CUSTOM_TRAIT_ONE",
                        "CUSTOM_TRAIT2"
                    ]
                }
            }
        }

        example_file = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            'provider_config_data/v1/example_provider.yaml')
        mock_glob.glob.return_value = [example_file]

        actual = provider_config.get_provider_configs('path')

        self.assertEqual(expected, actual)
        mock_glob.glob.assert_called_with('path/*.yaml')

    @mock.patch.object(provider_config, 'glob')
    @mock.patch.object(provider_config, '_parse_provider_yaml')
    def test_get_provider_configs_one_file_uuid_conflict(
            self, mock_parser, mock_glob):
        # one config file with conflicting identification
        providers = [
            {"__source_file": "file1.yaml",
             "identification": {
                 "uuid": uuidsentinel.uuid1
             },
             "inventories": {
                 "additional": [
                     {
                         "CUSTOM_EXAMPLE_RESOURCE_CLASS1": {
                             "total": 100,
                             "reserved": 0,
                             "min_unit": 1,
                             "max_unit": 10,
                             "step_size": 1,
                             "allocation_ratio": 1
                         }
                     }
                 ]
             },
             "traits": {
                 "additional": [
                     "CUSTOM_TRAIT1"
                 ]
             }
             },
            {"__source_file": "file1.yaml",
             "identification": {
                 "uuid": uuidsentinel.uuid1
             },
             "inventories": {
                 "additional": [
                     {
                         "CUSTOM_EXAMPLE_RESOURCE_CLASS2": {
                             "total": 100,
                             "reserved": 0,
                             "min_unit": 1,
                             "max_unit": 10,
                             "step_size": 1,
                             "allocation_ratio": 1
                         }
                     }
                 ]
             },
             "traits": {
                 "additional": [
                     "CUSTOM_TRAIT2"
                 ]
             }
             }
        ]
        mock_parser.side_effect = [{"providers": providers}]
        mock_glob.glob.return_value = ['file1.yaml']

        # test that correct error is raised and message matches
        error = self.assertRaises(nova_exc.ProviderConfigException,
                                  provider_config.get_provider_configs,
                                  'dummy_path').kwargs['error']
        self.assertEqual("Provider %s has multiple definitions in source "
                         "file(s): ['file1.yaml']." % uuidsentinel.uuid1,
                         error)

    @mock.patch.object(provider_config, 'glob')
    @mock.patch.object(provider_config, '_parse_provider_yaml')
    def test_get_provider_configs_two_files(self, mock_parser, mock_glob):
        expected = {
            "EXAMPLE_RESOURCE_PROVIDER1": {
                "__source_file": "file1.yaml",
                "identification": {
                    "name": "EXAMPLE_RESOURCE_PROVIDER1"
                },
                "inventories": {
                    "additional": [
                        {
                            "CUSTOM_EXAMPLE_RESOURCE_CLASS1": {
                                "total": 100,
                                "reserved": 0,
                                "min_unit": 1,
                                "max_unit": 10,
                                "step_size": 1,
                                "allocation_ratio": 1
                            }
                        }
                    ]
                },
                "traits": {
                    "additional": [
                        "CUSTOM_TRAIT1"
                    ]
                }
            },
            "EXAMPLE_RESOURCE_PROVIDER2": {
                "__source_file": "file2.yaml",
                "identification": {
                    "name": "EXAMPLE_RESOURCE_PROVIDER2"
                },
                "inventories": {
                    "additional": [
                        {
                            "CUSTOM_EXAMPLE_RESOURCE_CLASS2": {
                                "total": 100,
                                "reserved": 0,
                                "min_unit": 1,
                                "max_unit": 10,
                                "step_size": 1,
                                "allocation_ratio": 1
                            }
                        }
                    ]
                },
                "traits": {
                    "additional": [
                        "CUSTOM_TRAIT2"
                    ]
                }
            }
        }
        mock_parser.side_effect = [
            {"providers": [provider]} for provider in expected.values()]
        mock_glob_return = ['file1.yaml', 'file2.yaml']
        mock_glob.glob.return_value = mock_glob_return
        dummy_path = 'dummy_path'

        actual = provider_config.get_provider_configs(dummy_path)

        mock_glob.glob.assert_called_once_with(os.path.join(dummy_path,
                                                            '*.yaml'))
        mock_parser.assert_has_calls([mock.call(param)
                                      for param in mock_glob_return])
        self.assertEqual(expected, actual)

    @mock.patch.object(provider_config, 'glob')
    @mock.patch.object(provider_config, '_parse_provider_yaml')
    def test_get_provider_configs_two_files_name_conflict(self, mock_parser,
                                                          mock_glob):
        # two config files with conflicting identification
        configs = {
            "EXAMPLE_RESOURCE_PROVIDER1": {
                "__source_file": "file1.yaml",
                "identification": {
                    "name": "EXAMPLE_RESOURCE_PROVIDER1"
                },
                "inventories": {
                    "additional": [
                        {
                            "CUSTOM_EXAMPLE_RESOURCE_CLASS1": {
                                "total": 100,
                                "reserved": 0,
                                "min_unit": 1,
                                "max_unit": 10,
                                "step_size": 1,
                                "allocation_ratio": 1
                            }
                        }
                    ]
                },
                "traits": {
                    "additional": [
                        "CUSTOM_TRAIT1"
                    ]
                }
            },
            "EXAMPLE_RESOURCE_PROVIDER2": {
                "__source_file": "file2.yaml",
                "identification": {
                    "name": "EXAMPLE_RESOURCE_PROVIDER1"
                },
                "inventories": {
                    "additional": [
                        {
                            "CUSTOM_EXAMPLE_RESOURCE_CLASS1": {
                                "total": 100,
                                "reserved": 0,
                                "min_unit": 1,
                                "max_unit": 10,
                                "step_size": 1,
                                "allocation_ratio": 1
                            }
                        }
                    ]
                },
                "traits": {
                    "additional": [
                        "CUSTOM_TRAIT1"
                    ]
                }
            }
        }
        mock_parser.side_effect = [{"providers": [configs[provider]]}
                                   for provider in configs]
        mock_glob.glob.return_value = ['file1.yaml', 'file2.yaml']

        # test that correct error is raised and message matches
        error = self.assertRaises(nova_exc.ProviderConfigException,
                                  provider_config.get_provider_configs,
                                  'dummy_path').kwargs['error']
        self.assertEqual("Provider EXAMPLE_RESOURCE_PROVIDER1 has multiple "
                         "definitions in source file(s): "
                         "['file1.yaml', 'file2.yaml'].", error)

    @mock.patch.object(provider_config, 'LOG')
    def test_get_provider_configs_no_configs(self, mock_log):
        path = "invalid_path!@#"
        actual = provider_config.get_provider_configs(path)

        self.assertEqual({}, actual)
        mock_log.info.assert_called_once_with(
            "No provider configs found in %s. If files are present, "
            "ensure the Nova process has access.", path)
