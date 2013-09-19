# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import collections
import re

from nova import test
from nova.virt.vmwareapi import vm_util

ResultSet = collections.namedtuple('ResultSet', ['objects'])
ResultSetToken = collections.namedtuple('ResultSet', ['objects', 'token'])
ObjectContent = collections.namedtuple('ObjectContent', ['obj', 'propSet'])
DynamicProperty = collections.namedtuple('Property', ['name', 'val'])
MoRef = collections.namedtuple('ManagedObjectReference', ['value'])


class VMwareVMUtilDatastoreSelectionTestCase(test.NoDBTestCase):

    def setUp(self):
        super(VMwareVMUtilDatastoreSelectionTestCase, self).setUp()
        self.data = [
            ['VMFS', 'os-some-name', True, 987654321, 12346789],
            ['NFS', 'another-name', True, 9876543210, 123467890],
            ['BAD', 'some-name-bad', True, 98765432100, 1234678900],
            ['VMFS', 'some-name-good', False, 987654321, 12346789],
        ]

    def build_result_set(self, mock_data, name_list=None):
        # datastores will have a moref_id of ds-000 and
        # so on based on their index in the mock_data list
        if name_list is None:
            name_list = self.propset_name_list

        objects = []
        for id, row in enumerate(mock_data):
            obj = ObjectContent(
                obj=MoRef(value="ds-%03d" % id),
                propSet=[])
            for index, value in enumerate(row):
                obj.propSet.append(
                    DynamicProperty(name=name_list[index], val=row[index]))
            objects.append(obj)
        return ResultSet(objects=objects)

    @property
    def propset_name_list(self):
        return ['summary.type', 'summary.name', 'summary.accessible',
                'summary.capacity', 'summary.freeSpace']

    def test_filter_datastores_simple(self):
        datastores = self.build_result_set(self.data)
        rec = vm_util._get_datastore_ref_and_name(datastores)

        self.assertIsNotNone(rec[0], "could not find datastore!")
        self.assertEqual('ds-001', rec[0].value,
                         "didn't find the right datastore!")
        self.assertEqual(123467890, rec[3],
                         "did not obtain correct freespace!")

    def test_filter_datastores_empty(self):
        data = []
        datastores = self.build_result_set(data)

        rec = vm_util._get_datastore_ref_and_name(datastores)

        self.assertIsNone(rec)

    def test_filter_datastores_no_match(self):
        datastores = self.build_result_set(self.data)
        datastore_regex = re.compile('no_match.*')

        rec = vm_util._get_datastore_ref_and_name(datastores,
                                                  datastore_regex)

        self.assertIsNone(rec, "did not fail to match datastore properly")

    def test_filter_datastores_specific_match(self):

        data = [
            ['VMFS', 'os-some-name', True, 987654321, 1234678],
            ['NFS', 'another-name', True, 9876543210, 123467890],
            ['BAD', 'some-name-bad', True, 98765432100, 1234678900],
            ['VMFS', 'some-name-good', True, 987654321, 12346789],
            ['VMFS', 'some-other-good', False, 987654321000, 12346789000],
        ]
        # only the DS some-name-good is accessible and matches the regex
        datastores = self.build_result_set(data)
        datastore_regex = re.compile('.*-good$')

        rec = vm_util._get_datastore_ref_and_name(datastores,
                                                  datastore_regex)

        self.assertIsNotNone(rec, "could not find datastore!")
        self.assertEqual('ds-003', rec[0].value,
                         "didn't find the right datastore!")
        self.assertNotEqual('ds-004', rec[0].value,
                            "accepted an unreachable datastore!")
        self.assertEqual('some-name-good', rec[1])
        self.assertEqual(12346789, rec[3],
                         "did not obtain correct freespace!")
        self.assertEqual(987654321, rec[2],
                         "did not obtain correct capacity!")
