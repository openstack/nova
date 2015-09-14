# Copyright (c) 2013 VMware, Inc.
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
from nova.tests.unit.virt.vmwareapi import fake
from nova.virt.vmwareapi import vim_util


class VMwareVIMUtilTestCase(test.NoDBTestCase):

    def setUp(self):
        super(VMwareVIMUtilTestCase, self).setUp()
        fake.reset()
        self.vim = fake.FakeVim()
        self.vim._login()

    def test_get_inner_objects(self):
        property = ['summary.name']
        # Get the fake datastores directly from the cluster
        cluster_refs = fake._get_object_refs('ClusterComputeResource')
        cluster = fake._get_object(cluster_refs[0])
        expected_ds = cluster.datastore.ManagedObjectReference
        # Get the fake datastores using inner objects utility method
        result = vim_util.get_inner_objects(
            self.vim, cluster_refs[0], 'datastore', 'Datastore', property)
        datastores = [oc.obj for oc in result.objects]
        self.assertEqual(expected_ds, datastores)
