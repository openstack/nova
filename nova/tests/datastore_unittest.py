# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
from nova import datastore
import random

class KeeperTestCase(test.BaseTestCase):
    """
    Basic persistence tests for Keeper datastore.
    Generalize, then use these to support
    migration to redis / cassandra / multiple stores.
    """

    def __init__(self, *args, **kwargs):
        """
        Create a new keeper instance for test keys.
        """
        super(KeeperTestCase, self).__init__(*args, **kwargs)
        self.keeper = datastore.Keeper('test-')

    def tear_down(self):
        """
        Scrub out test keeper data.
        """
        pass

    def test_store_strings(self):
        """
        Confirm that simple strings go in and come out safely.
        Should also test unicode strings.
        """
        randomstring = ''.join(
                [random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890-')
                 for _x in xrange(20)]
                )
        self.keeper['test_string'] = randomstring
        self.assertEqual(randomstring, self.keeper['test_string'])

    def test_store_dicts(self):
        """
        Arbitrary dictionaries should be storable.
        """
        test_dict = {'key_one': 'value_one'}
        self.keeper['test_dict'] = test_dict
        self.assertEqual(test_dict['key_one'],
            self.keeper['test_dict']['key_one'])

    def test_sets(self):
        """
        A keeper dict should be self-serializing.
        """
        self.keeper.set_add('test_set', 'foo')
        test_dict = {'arbitrary': 'dict of stuff'}
        self.keeper.set_add('test_set', test_dict)
        self.assertTrue(self.keeper.set_is_member('test_set', 'foo'))
        self.assertFalse(self.keeper.set_is_member('test_set', 'bar'))
        self.keeper.set_remove('test_set', 'foo')
        self.assertFalse(self.keeper.set_is_member('test_set', 'foo'))
        rv = self.keeper.set_fetch('test_set')
        self.assertEqual(test_dict, rv.next())
        self.keeper.set_remove('test_set', test_dict)

