# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import testtools
from testtools.tests.matchers import helpers

from nova.tests import matchers


class TestDictMatches(testtools.TestCase, helpers.TestMatchersInterface):

    matches_matcher = matchers.DictMatches(
        {'foo': 'bar', 'baz': 'DONTCARE',
         'cat': {'tabby': True, 'fluffy': False}}
        )

    matches_matches = [
        {'foo': 'bar', 'baz': 'noox', 'cat': {'tabby': True, 'fluffy': False}},
        {'foo': 'bar', 'baz': 'quux', 'cat': {'tabby': True, 'fluffy': False}},
        ]

    matches_mismatches = [
        {},
        {'foo': 'bar', 'baz': 'qux'},
        {'foo': 'bop', 'baz': 'qux',
         'cat': {'tabby': True, 'fluffy': False}},
        {'foo': 'bar', 'baz': 'quux',
         'cat': {'tabby': True, 'fluffy': True}},
        {'foo': 'bar', 'cat': {'tabby': True, 'fluffy': False}},
        ]

    str_examples = [
        ("DictMatches({'baz': 'DONTCARE', 'cat':"
         " {'fluffy': False, 'tabby': True}, 'foo': 'bar'})",
         matches_matcher),
        ]

    describe_examples = [
        ("Keys in d1 and not d2: set(['foo', 'baz', 'cat'])."
         " Keys in d2 and not d1: set([])", {}, matches_matcher),
        ("Dictionaries do not match at fluffy. d1: False d2: True",
         {'foo': 'bar', 'baz': 'quux',
          'cat': {'tabby': True, 'fluffy': True}}, matches_matcher),
        ("Dictionaries do not match at foo. d1: bar d2: bop",
         {'foo': 'bop', 'baz': 'quux',
          'cat': {'tabby': True, 'fluffy': False}}, matches_matcher),
         ]


class TestDictListMatches(testtools.TestCase, helpers.TestMatchersInterface):

    matches_matcher = matchers.DictListMatches(
        [{'foo': 'bar', 'baz': 'DONTCARE',
         'cat': {'tabby': True, 'fluffy': False}},
         {'dog': 'yorkie'},
         ])

    matches_matches = [
        [{'foo': 'bar', 'baz': 'qoox',
         'cat': {'tabby': True, 'fluffy': False}},
         {'dog': 'yorkie'}],
        [{'foo': 'bar', 'baz': False,
         'cat': {'tabby': True, 'fluffy': False}},
         {'dog': 'yorkie'}],
        ]

    matches_mismatches = [
        [],
        {},
        [{'foo': 'bar', 'baz': 'qoox',
         'cat': {'tabby': True, 'fluffy': True}},
         {'dog': 'yorkie'}],
        [{'foo': 'bar', 'baz': False,
         'cat': {'tabby': True, 'fluffy': False}},
         {'cat': 'yorkie'}],
        [{'foo': 'bop', 'baz': False,
         'cat': {'tabby': True, 'fluffy': False}},
         {'dog': 'yorkie'}],
        ]

    str_examples = [
        ("DictListMatches([{'baz': 'DONTCARE', 'cat':"
         " {'fluffy': False, 'tabby': True}, 'foo': 'bar'},\n"
         " {'dog': 'yorkie'}])",
         matches_matcher),
        ]

    describe_examples = [
        ("Length mismatch: len(L1)=2 != len(L2)=0", {}, matches_matcher),
        ("Dictionaries do not match at fluffy. d1: True d2: False",
         [{'foo': 'bar', 'baz': 'qoox',
           'cat': {'tabby': True, 'fluffy': True}},
          {'dog': 'yorkie'}],
         matches_matcher),
         ]


class TestDictMatches(testtools.TestCase, helpers.TestMatchersInterface):

    matches_matcher = matchers.IsSubDictOf(
        {'foo': 'bar', 'baz': 'DONTCARE',
         'cat': {'tabby': True, 'fluffy': False}}
        )

    matches_matches = [
        {'foo': 'bar', 'baz': 'noox', 'cat': {'tabby': True, 'fluffy': False}},
        {'foo': 'bar', 'baz': 'quux'}
        ]

    matches_mismatches = [
        {'foo': 'bop', 'baz': 'qux',
         'cat': {'tabby': True, 'fluffy': False}},
        {'foo': 'bar', 'baz': 'quux',
         'cat': {'tabby': True, 'fluffy': True}},
        {'foo': 'bar', 'cat': {'tabby': True, 'fluffy': False}, 'dog': None},
        ]

    str_examples = [
        ("IsSubDictOf({'foo': 'bar', 'baz': 'DONTCARE',"
         " 'cat': {'fluffy': False, 'tabby': True}})",
         matches_matcher),
        ]

    describe_examples = [
        ("Dictionaries do not match at fluffy. d1: False d2: True",
         {'foo': 'bar', 'baz': 'quux',
          'cat': {'tabby': True, 'fluffy': True}}, matches_matcher),
        ("Dictionaries do not match at foo. d1: bar d2: bop",
         {'foo': 'bop', 'baz': 'quux',
          'cat': {'tabby': True, 'fluffy': False}}, matches_matcher),
         ]
