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

from oslo_utils import units
from oslo_vmware.objects import datastore as ds_obj

from nova import test
from nova.virt.vmwareapi import ds_util

ResultSet = collections.namedtuple('ResultSet', ['objects'])
ObjectContent = collections.namedtuple('ObjectContent', ['obj', 'propSet'])
DynamicProperty = collections.namedtuple('Property', ['name', 'val'])
MoRef = collections.namedtuple('ManagedObjectReference', ['value'])


class VMwareDSUtilDatastoreSelectionTestCase(test.NoDBTestCase):

    def setUp(self):
        super(VMwareDSUtilDatastoreSelectionTestCase, self).setUp()
        self.data = [
            ['VMFS', 'os-some-name', True, 'normal', 987654321, 12346789],
            ['NFS', 'another-name', True, 'normal', 9876543210, 123467890],
            ['BAD', 'some-name-bad', True, 'normal', 98765432100, 1234678900],
            ['VMFS', 'some-name-good', False, 'normal', 987654321, 12346789],
            ['VMFS', 'new-name', True, 'inMaintenance', 987654321, 12346789]
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
                'summary.maintenanceMode', 'summary.capacity',
                'summary.freeSpace']

    def test_filter_datastores_simple(self):
        datastores = self.build_result_set(self.data)
        best_match = ds_obj.Datastore(ref='fake_ref', name='ds',
                              capacity=0, freespace=0)
        rec = ds_util._select_datastore(None, datastores, best_match)

        self.assertIsNotNone(rec.ref, "could not find datastore!")
        self.assertEqual('ds-001', rec.ref.value,
                         "didn't find the right datastore!")
        self.assertEqual(123467890, rec.freespace,
                         "did not obtain correct freespace!")

    def test_filter_datastores_empty(self):
        data = []
        datastores = self.build_result_set(data)

        best_match = ds_obj.Datastore(ref='fake_ref', name='ds',
                              capacity=0, freespace=0)
        rec = ds_util._select_datastore(None, datastores, best_match)

        self.assertEqual(best_match, rec)

    def test_filter_datastores_no_match(self):
        datastores = self.build_result_set(self.data)
        datastore_regex = re.compile('no_match.*')

        best_match = ds_obj.Datastore(ref='fake_ref', name='ds',
                              capacity=0, freespace=0)
        rec = ds_util._select_datastore(None, datastores,
                                        best_match,
                                        datastore_regex)

        self.assertEqual(best_match, rec, "did not match datastore properly")

    def test_filter_datastores_specific_match(self):

        data = [
            ['VMFS', 'os-some-name', True, 'normal', 987654321, 1234678],
            ['NFS', 'another-name', True, 'normal', 9876543210, 123467890],
            ['BAD', 'some-name-bad', True, 'normal', 98765432100, 1234678900],
            ['VMFS', 'some-name-good', True, 'normal', 987654321, 12346789],
            ['VMFS', 'some-other-good', False, 'normal', 987654321000,
             12346789000],
            ['VMFS', 'new-name', True, 'inMaintenance', 987654321000,
             12346789000]
        ]
        # only the DS some-name-good is accessible and matches the regex
        datastores = self.build_result_set(data)
        datastore_regex = re.compile('.*-good$')

        best_match = ds_obj.Datastore(ref='fake_ref', name='ds',
                              capacity=0, freespace=0)
        rec = ds_util._select_datastore(None, datastores,
                                        best_match,
                                        datastore_regex)

        self.assertIsNotNone(rec, "could not find datastore!")
        self.assertEqual('ds-003', rec.ref.value,
                         "didn't find the right datastore!")
        self.assertNotEqual('ds-004', rec.ref.value,
                            "accepted an unreachable datastore!")
        self.assertEqual('some-name-good', rec.name)
        self.assertEqual(12346789, rec.freespace,
                         "did not obtain correct freespace!")
        self.assertEqual(987654321, rec.capacity,
                         "did not obtain correct capacity!")

    def test_filter_datastores_missing_props(self):
        data = [
            ['VMFS', 'os-some-name', 987654321, 1234678],
            ['NFS', 'another-name', 9876543210, 123467890],
        ]
        # no matches are expected when 'summary.accessible' is missing
        prop_names = ['summary.type', 'summary.name',
                      'summary.capacity', 'summary.freeSpace']
        datastores = self.build_result_set(data, prop_names)
        best_match = ds_obj.Datastore(ref='fake_ref', name='ds',
                              capacity=0, freespace=0)

        rec = ds_util._select_datastore(None, datastores, best_match)
        self.assertEqual(best_match, rec, "no matches were expected")

    def test_filter_datastores_best_match(self):
        data = [
            ['VMFS', 'spam-good', True, 20 * units.Gi, 10 * units.Gi],
            ['NFS', 'eggs-good', True, 40 * units.Gi, 15 * units.Gi],
            ['NFS41', 'nfs41-is-good', True, 35 * units.Gi, 12 * units.Gi],
            ['BAD', 'some-name-bad', True, 30 * units.Gi, 20 * units.Gi],
            ['VMFS', 'some-name-good', True, 50 * units.Gi, 5 * units.Gi],
            ['VMFS', 'some-other-good', True, 10 * units.Gi, 10 * units.Gi],
        ]

        datastores = self.build_result_set(data)
        datastore_regex = re.compile('.*-good$')

        # the current best match is better than all candidates
        best_match = ds_obj.Datastore(ref='ds-100', name='best-ds-good',
                              capacity=20 * units.Gi, freespace=19 * units.Gi)
        rec = ds_util._select_datastore(None,
                                        datastores,
                                        best_match,
                                        datastore_regex)
        self.assertEqual(best_match, rec, "did not match datastore properly")
