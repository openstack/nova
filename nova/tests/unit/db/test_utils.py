# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.db import utils
from nova import exception
from nova import test


class ProcessSortParamTestCase(test.TestCase):

    def test_process_sort_params_defaults(self):
        """Verifies default sort parameters."""
        sort_keys, sort_dirs = utils.process_sort_params([], [])
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

        sort_keys, sort_dirs = utils.process_sort_params(None, None)
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_keys(self):
        """Verifies that the default keys can be overridden."""
        sort_keys, sort_dirs = utils.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'])
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_override_default_dir(self):
        """Verifies that the default direction can be overridden."""
        sort_keys, sort_dirs = utils.process_sort_params(
            [], [], default_dir='dir1')
        self.assertEqual(['created_at', 'id'], sort_keys)
        self.assertEqual(['dir1', 'dir1'], sort_dirs)

    def test_process_sort_params_override_default_key_and_dir(self):
        """Verifies that the default key and dir can be overridden."""
        sort_keys, sort_dirs = utils.process_sort_params(
            [], [], default_keys=['key1', 'key2', 'key3'],
            default_dir='dir1')
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir1', 'dir1'], sort_dirs)

        sort_keys, sort_dirs = utils.process_sort_params(
            [], [], default_keys=[], default_dir='dir1')
        self.assertEqual([], sort_keys)
        self.assertEqual([], sort_dirs)

    def test_process_sort_params_non_default(self):
        """Verifies that non-default keys are added correctly."""
        sort_keys, sort_dirs = utils.process_sort_params(
            ['key1', 'key2'], ['asc', 'desc'])
        self.assertEqual(['key1', 'key2', 'created_at', 'id'], sort_keys)
        # First sort_dir in list is used when adding the default keys
        self.assertEqual(['asc', 'desc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default(self):
        """Verifies that default keys are added correctly."""
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2'], ['asc', 'desc'])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'desc', 'asc'], sort_dirs)

        # Include default key value, rely on default direction
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2'], [])
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['asc', 'asc', 'asc'], sort_dirs)

    def test_process_sort_params_default_dir(self):
        """Verifies that the default dir is applied to all keys."""
        # Direction is set, ignore default dir
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2'], ['desc'], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc'], sort_dirs)

        # But should be used if no direction is set
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2'], [], default_dir='dir')
        self.assertEqual(['id', 'key2', 'created_at'], sort_keys)
        self.assertEqual(['dir', 'dir', 'dir'], sort_dirs)

    def test_process_sort_params_unequal_length(self):
        """Verifies that a sort direction list is applied correctly."""
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2', 'key3'], ['desc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'desc', 'desc', 'desc'], sort_dirs)

        # Default direction is the first key in the list
        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'desc', 'desc'], sort_dirs)

        sort_keys, sort_dirs = utils.process_sort_params(
            ['id', 'key2', 'key3'], ['desc', 'asc', 'asc'])
        self.assertEqual(['id', 'key2', 'key3', 'created_at'], sort_keys)
        self.assertEqual(['desc', 'asc', 'asc', 'desc'], sort_dirs)

    def test_process_sort_params_extra_dirs_lengths(self):
        """InvalidInput raised if more directions are given."""
        self.assertRaises(
            exception.InvalidInput,
            utils.process_sort_params,
            ['key1', 'key2'],
            ['asc', 'desc', 'desc'])

    def test_process_sort_params_invalid_sort_dir(self):
        """InvalidInput raised if invalid directions are given."""
        for dirs in [['foo'], ['asc', 'foo'], ['asc', 'desc', 'foo']]:
            self.assertRaises(
                exception.InvalidInput,
                utils.process_sort_params, ['key'], dirs)
