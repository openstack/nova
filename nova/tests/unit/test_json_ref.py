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
import copy
import mock

from nova import test
from nova.tests import json_ref


class TestJsonRef(test.NoDBTestCase):

    def test_update_dict_recursively(self):
        input = {'foo': 1,
                 'bar': 13,
                 'a list': [],
                 'nesting': {
                     'baz': 42,
                     'foobar': 121
                 }}

        d = copy.deepcopy(input)
        json_ref._update_dict_recursively(d, {})
        self.assertDictEqual(input, d)

        d = copy.deepcopy(input)
        json_ref._update_dict_recursively(d, {'foo': 111,
                                              'new_key': 1,
                                              'nesting': {
                                                  'baz': 142,
                                                  'new_nested': 1
                                              }})
        expected = copy.deepcopy(input)
        expected['foo'] = 111
        expected['new_key'] = 1
        expected['nesting']['baz'] = 142
        expected['nesting']['new_nested'] = 1
        self.assertDictEqual(expected, d)

        d = copy.deepcopy(input)
        json_ref._update_dict_recursively(d, {'nesting': 1})
        expected = copy.deepcopy(input)
        expected['nesting'] = 1
        self.assertDictEqual(expected, d)
        d = copy.deepcopy(input)

    @mock.patch('oslo_serialization.jsonutils.load')
    @mock.patch('nova.tests.json_ref.open')
    def test_resolve_ref(self, mock_open, mock_json_load):
        mock_json_load.return_value = {'baz': 13}

        actual = json_ref.resolve_refs(
            {'foo': 1,
             'bar': {'$ref': 'another.json#'}},
            'some/base/path/')

        self.assertDictEqual({'foo': 1,
                              'bar': {'baz': 13}},
                             actual)
        mock_open.assert_called_once_with('some/base/path/another.json', 'r+b')

    @mock.patch('oslo_serialization.jsonutils.load')
    @mock.patch('nova.tests.json_ref.open')
    def test_resolve_ref_recursively(self, mock_open, mock_json_load):
        mock_json_load.side_effect = [
            # this is the content of direct_ref.json
            {'baz': 13,
             'nesting': {'$ref': 'subdir/nested_ref.json#'}},
            # this is the content of subdir/nested_ref.json
            {'a deep key': 'happiness'}]

        actual = json_ref.resolve_refs(
            {'foo': 1,
             'bar': {'$ref': 'direct_ref.json#'}},
            'some/base/path/')

        self.assertDictEqual({'foo': 1,
                              'bar': {'baz': 13,
                                      'nesting':
                                          {'a deep key': 'happiness'}}},
                             actual)
        mock_open.assert_any_call('some/base/path/direct_ref.json', 'r+b')
        mock_open.assert_any_call('some/base/path/subdir/nested_ref.json',
                                  'r+b')

    @mock.patch('oslo_serialization.jsonutils.load')
    @mock.patch('nova.tests.json_ref.open')
    def test_resolve_ref_with_override(self, mock_open, mock_json_load):
        mock_json_load.return_value = {'baz': 13,
                                       'boo': 42}

        actual = json_ref.resolve_refs(
            {'foo': 1,
             'bar': {'$ref': 'another.json#',
                     'boo': 0}},
            'some/base/path/')

        self.assertDictEqual({'foo': 1,
                              'bar': {'baz': 13,
                                      'boo': 0}},
                             actual)
        mock_open.assert_called_once_with('some/base/path/another.json', 'r+b')

    @mock.patch('oslo_serialization.jsonutils.load')
    @mock.patch('nova.tests.json_ref.open')
    def test_resolve_ref_with_nested_override(self, mock_open, mock_json_load):
        mock_json_load.return_value = {'baz': 13,
                                       'boo': {'a': 1,
                                               'b': 2}}

        actual = json_ref.resolve_refs(
            {'foo': 1,
             'bar': {'$ref': 'another.json#',
                     'boo': {'b': 3,
                             'c': 13}}},
            'some/base/path/')

        self.assertDictEqual({'foo': 1,
                              'bar': {'baz': 13,
                                      'boo': {'a': 1,
                                              'b': 3,
                                              'c': 13}}},
                             actual)
        mock_open.assert_called_once_with('some/base/path/another.json', 'r+b')

    @mock.patch('oslo_serialization.jsonutils.load')
    @mock.patch('nova.tests.json_ref.open')
    def test_resolve_ref_with_override_having_refs(self, mock_open,
                                                   mock_json_load):
        mock_json_load.side_effect = [
            {'baz': 13,
             'boo': 42},
            {'something': 0}]

        actual = json_ref.resolve_refs(
            {'foo': 1,
             'bar': {'$ref': 'another.json#',
                     'boo': {'$ref': 'override_ref.json#'}}},
            'some/base/path/')

        self.assertDictEqual({'foo': 1,
                              'bar': {'baz': 13,
                                      'boo': {'something': 0}}},
                             actual)
        self.assertEqual(2, mock_open.call_count)
        # any_order=True is needed as context manager calls also done on open
        mock_open.assert_has_calls(
            [mock.call('some/base/path/another.json', 'r+b'),
             mock.call('some/base/path/override_ref.json', 'r+b')],
            any_order=True)

    def test_ref_with_json_path_not_supported(self):

        self.assertRaises(
            NotImplementedError, json_ref.resolve_refs,
            {'foo': 1,
             'bar': {'$ref': 'another.json#/key-in-another',
                     'boo': {'b': 3,
                             'c': 13}}},
            'some/base/path/')
