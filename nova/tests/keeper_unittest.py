# vim: tabstop=4 shiftwidth=4 softtabstop=4
import random

from nova import datastore
from nova import test

class KeeperTestCase(test.TrialTestCase):
    """
    Basic persistence tests for Keeper datastore.
    Generalize, then use these to support
    migration to redis / cassandra / multiple stores.
    """

    def setUp(self):
        super(KeeperTestCase, self).setUp()
        self.keeper = datastore.Keeper('test')

    def tearDown(self):
        super(KeeperTestCase, self).tearDown()
        self.keeper.clear()

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

