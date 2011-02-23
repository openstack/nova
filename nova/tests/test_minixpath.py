# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 Justin Santa Barbara
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

from nova import test
from nova import utils
from nova import exception


class MiniXPathTestCase(test.TestCase):
    def test_tolerates_nones(self):
        xp = utils.minixpath_select

        input = []
        self.assertEquals([], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [None]
        self.assertEquals([], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': None}]
        self.assertEquals([], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': None}}]
        self.assertEquals([{'b': None}], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}]
        self.assertEquals([{'b': {'c': None}}], xp(input, "a"))
        self.assertEquals([{'c': None}], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': None}]
        self.assertEquals([{'b': {'c': None}}], xp(input, "a"))
        self.assertEquals([{'c': None}], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': None}}}, {'a': {'b': None}}]
        self.assertEquals([{'b': {'c': None}}, {'b': None}], xp(input, "a"))
        self.assertEquals([{'c': None}], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

    def test_does_select(self):
        xp = utils.minixpath_select

        input = [{'a': 'a_1'}]
        self.assertEquals(['a_1'], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': 'b_1'}}]
        self.assertEquals([{'b': 'b_1'}], xp(input, "a"))
        self.assertEquals(['b_1'], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}]
        self.assertEquals([{'b': {'c': 'c_1'}}], xp(input, "a"))
        self.assertEquals([{'c': 'c_1'}], xp(input, "a/b"))
        self.assertEquals(['c_1'], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}}, {'a': None}]
        self.assertEquals([{'b': {'c': 'c_1'}}],
                          xp(input, "a"))
        self.assertEquals([{'c': 'c_1'}], xp(input, "a/b"))
        self.assertEquals(['c_1'], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': None}}]
        self.assertEquals([{'b': {'c': 'c_1'}}, {'b': None}],
                          xp(input, "a"))
        self.assertEquals([{'c': 'c_1'}], xp(input, "a/b"))
        self.assertEquals(['c_1'], xp(input, "a/b/c"))

        input = [{'a': {'b': {'c': 'c_1'}}},
                 {'a': {'b': {'c': 'c_2'}}}]
        self.assertEquals([{'b': {'c': 'c_1'}}, {'b': {'c': 'c_2'}}],
                          xp(input, "a"))
        self.assertEquals([{'c': 'c_1'}, {'c': 'c_2'}],
                          xp(input, "a/b"))
        self.assertEquals(['c_1', 'c_2'], xp(input, "a/b/c"))

        self.assertEquals([], xp(input, "a/b/c/d"))
        self.assertEquals([], xp(input, "c/a/b/d"))
        self.assertEquals([], xp(input, "i/r/t"))

    def test_flattens_lists(self):
        xp = utils.minixpath_select

        input = [{'a': [1, 2, 3]}]
        self.assertEquals([1, 2, 3], xp(input, "a"))
        self.assertEquals([], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}]
        self.assertEquals([{'b': [1, 2, 3]}], xp(input, "a"))
        self.assertEquals([1, 2, 3], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': {'b': [1, 2, 3]}}, {'a': {'b': [4, 5, 6]}}]
        self.assertEquals([1, 2, 3, 4, 5, 6], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': [{'b': [1, 2, 3]}, {'b': [4, 5, 6]}]}]
        self.assertEquals([1, 2, 3, 4, 5, 6], xp(input, "a/b"))
        self.assertEquals([], xp(input, "a/b/c"))

        input = [{'a': [1, 2, {'b': 'b_1'}]}]
        self.assertEquals([1, 2, {'b': 'b_1'}], xp(input, "a"))
        self.assertEquals(['b_1'], xp(input, "a/b"))

    def test_bad_xpath(self):
        xp = utils.minixpath_select

        self.assertRaises(exception.Error, xp, [], None)
        self.assertRaises(exception.Error, xp, [], "")
        self.assertRaises(exception.Error, xp, [], "/")
        self.assertRaises(exception.Error, xp, [], "/a")
        self.assertRaises(exception.Error, xp, [], "/a/")
        self.assertRaises(exception.Error, xp, [], "//")
        self.assertRaises(exception.Error, xp, [], "//a")
        self.assertRaises(exception.Error, xp, [], "a//a")
        self.assertRaises(exception.Error, xp, [], "a//a/")
        self.assertRaises(exception.Error, xp, [], "a/a/")
