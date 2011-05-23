# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2011 Citrix Systems, Inc.
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

"""
Unit tests for the Dns Manager.
"""


import unittest
from nova.dns.driver import DnsEntry
from nova.dns.driver import DnsEntryNotFound
from nova.dns.manager import DnsManager
from nova.tests.dns.fake import FakeDnsDriver


class FakeEntryFactory(object):

    def __init__(self):
        self.make_entry = True

    def create_entry(self, instance):
        name = instance["name"]
        if self.make_entry:
            return DnsEntry(name=name, content=None, type="CNAME")
        else:
            return None


class BaseCase(unittest.TestCase):

    def setUp(self):
        self.driver = FakeDnsDriver()
        self.entry_factory = FakeEntryFactory()
        self.manager = DnsManager()
        self.manager.driver = self.driver
        self.manager.entry_factory = self.entry_factory


class TestWhenEntryCreatorReturnsEntryForInstance(BaseCase):

    def setUp(self):
        super(TestWhenEntryCreatorReturnsEntryForInstance, self).setUp()
        self.instance = {'name': 'my-instance'}
        self.content = "255.1.1.1"
        initial_entries = self.driver.get_entries_by_content(self.content)
        self.assertEquals(0, len(list(initial_entries)))
        self.manager.create_instance_entry(self.instance, self.content)
        self.entries = list(self.driver.get_entries_by_content(self.content))

    def test_new_entry_should_exist(self):
        self.assertEqual(1, len(self.entries))

    def test_new_entry_should_have_correct_name(self):
        expected_name = self.entry_factory.create_entry(self.instance).name
        actual_name = self.entries[0].name
        self.assertEquals(expected_name, actual_name)

    def test_on_delete_should_remove_entry(self):
        self.manager.delete_instance_entry(self.instance, self.content)
        final_entries = list(self.driver.get_entries_by_content(self.content))
        self.assertEquals(0, len(final_entries))

    def test_on_delete_should_not_remove_entry_if_none(self):
        expected_name = self.entry_factory.create_entry(self.instance).name

        self.entry_factory.make_entry = False
        self.manager.delete_instance_entry(self.instance, self.content)

        final_entries = list(self.driver.get_entries_by_content(self.content))
        self.assertEqual(1, len(final_entries))
        actual_name = final_entries[0].name
        self.assertEquals(expected_name, actual_name)


class TestWhenEntryCreatorReturnsNoneForInstance(BaseCase):

    def setUp(self):
        super(TestWhenEntryCreatorReturnsNoneForInstance, self).setUp()
        self.entry_factory.make_entry = False
        self.instance = {'name': 'my-instance'}
        self.content = "255.1.1.1"
        initial_entries = self.driver.get_entries_by_content(self.content)
        self.assertEquals(0, len(list(initial_entries)))
        self.manager.create_instance_entry(self.instance, self.content)
        self.entries = list(self.driver.get_entries_by_content(self.content))

    def test_no_entry_is_added(self):
        self.assertEqual(0, len(self.entries))

    def test_on_delete_should_do_nothing(self):
        self.manager.delete_instance_entry(self.instance, self.content)
        final_entries = list(self.driver.get_entries_by_content(self.content))
        self.assertEquals(0, len(final_entries))

    def test_on_delete_should_fail_if_entry_returned(self):
        self.entry_factory.make_entry = True
        self.assertRaises(DnsEntryNotFound, self.manager.delete_instance_entry,
                          self.instance, self.content)
