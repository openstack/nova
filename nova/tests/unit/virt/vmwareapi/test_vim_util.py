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

import collections

import fixtures
import mock

from nova import test
from nova.tests.unit.virt.vmwareapi import fake
from nova.tests.unit.virt.vmwareapi import stubs
from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import vim_util


def _fake_get_object_properties(vim, collector, mobj,
                                type, properties):
    fake_objects = fake.FakeRetrieveResult()
    fake_objects.add_object(fake.ObjectContent(None))
    return fake_objects


def _fake_get_object_properties_missing(vim, collector, mobj,
                                type, properties):
    fake_objects = fake.FakeRetrieveResult()
    ml = [fake.MissingProperty()]
    fake_objects.add_object(fake.ObjectContent(None, missing_list=ml))
    return fake_objects


class VMwareVIMUtilTestCase(test.NoDBTestCase):

    def setUp(self):
        super(VMwareVIMUtilTestCase, self).setUp()
        fake.reset()
        self.vim = fake.FakeVim()
        self.vim._login()

    def test_get_dynamic_properties_missing(self):
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.vmwareapi.vim_util.get_object_properties',
                _fake_get_object_properties))
        res = vim_util.get_dynamic_property('fake-vim', 'fake-obj',
                                            'fake-type', 'fake-property')
        self.assertIsNone(res)

    def test_get_dynamic_properties_missing_path_exists(self):
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.vmwareapi.vim_util.get_object_properties',
                _fake_get_object_properties_missing))
        res = vim_util.get_dynamic_property('fake-vim', 'fake-obj',
                                            'fake-type', 'fake-property')
        self.assertIsNone(res)

    def test_get_dynamic_properties_with_token(self):
        ObjectContent = collections.namedtuple('ObjectContent', ['propSet'])
        DynamicProperty = collections.namedtuple('Property', ['name', 'val'])

        # Add a token to our results, indicating that more are available
        result = fake.FakeRetrieveResult(token='fake_token')

        # We expect these properties to be returned
        result.add_object(ObjectContent(propSet=[
            DynamicProperty(name='name1', val='value1'),
            DynamicProperty(name='name2', val='value2')
        ]))

        # These properties should be ignored
        result.add_object(ObjectContent(propSet=[
            DynamicProperty(name='name3', val='value3')
        ]))

        retrievePropertiesEx = mock.MagicMock(name='RetrievePropertiesEx')
        retrievePropertiesEx.return_value = result

        calls = {'RetrievePropertiesEx': retrievePropertiesEx}
        with stubs.fake_suds_context(calls):
            session = driver.VMwareAPISession(host_ip='localhost')

            service_content = session.vim.service_content
            props = session._call_method(vim_util, "get_dynamic_properties",
                                         service_content.propertyCollector,
                                        'fake_type', None)

            self.assertEqual(props, {
                'name1': 'value1',
                'name2': 'value2'
            })

    @mock.patch.object(vim_util, 'get_object_properties', return_value=None)
    def test_get_dynamic_properties_no_objects(self, mock_get_object_props):
        res = vim_util.get_dynamic_properties('fake-vim', 'fake-obj',
                                              'fake-type', 'fake-property')
        self.assertEqual({}, res)

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
