# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from nova import context as nova_context
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base


class FlavorsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = 'flavors'
    flavor_show_id = '1'
    subs = {}
    sort_keys = ['created_at', 'description', 'disabled', 'ephemeral_gb',
                 'flavorid', 'id', 'is_public', 'memory_mb', 'name',
                 'root_gb', 'rxtx_factor', 'swap', 'updated_at',
                 'vcpu_weight', 'vcpus']
    sort_dirs = ['asc', 'desc']

    def test_flavors_get(self):
        response = self._do_get('flavors/%s' % self.flavor_show_id)
        self._verify_response('flavor-get-resp', self.subs, response, 200)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        self._verify_response('flavors-list-resp', self.subs, response, 200)

    def test_flavors_list_with_sort_key(self):
        for sort_key in self.sort_keys:
            response = self._do_get('flavors?sort_key=%s' % sort_key)
            self._verify_response('flavors-list-resp', self.subs, response,
                                  200)

    def test_flavors_list_with_invalid_sort_key(self):
        response = self._do_get('flavors?sort_key=invalid')
        self.assertEqual(400, response.status_code)

    def test_flavors_list_with_sort_dir(self):
        for sort_dir in self.sort_dirs:
            response = self._do_get('flavors?sort_dir=%s' % sort_dir)
            self._verify_response('flavors-list-resp', self.subs, response,
                                  200)

    def test_flavors_list_with_invalid_sort_dir(self):
        response = self._do_get('flavors?sort_dir=invalid')
        self.assertEqual(400, response.status_code)

    def test_flavors_detail(self):
        response = self._do_get('flavors/detail')
        self._verify_response('flavors-detail-resp', self.subs, response,
                              200)

    def test_flavors_detail_with_sort_key(self):
        for sort_key in self.sort_keys:
            response = self._do_get('flavors/detail?sort_key=%s' % sort_key)
            self._verify_response('flavors-detail-resp', self.subs, response,
                                  200)

    def test_flavors_detail_with_invalid_sort_key(self):
        response = self._do_get('flavors/detail?sort_key=invalid')
        self.assertEqual(400, response.status_code)

    def test_flavors_detail_with_sort_dir(self):
        for sort_dir in self.sort_dirs:
            response = self._do_get('flavors/detail?sort_dir=%s' % sort_dir)
            self._verify_response('flavors-detail-resp', self.subs, response,
                                  200)

    def test_flavors_detail_with_invalid_sort_dir(self):
        response = self._do_get('flavors/detail?sort_dir=invalid')
        self.assertEqual(400, response.status_code)


class FlavorsSampleJsonTest2_55(FlavorsSampleJsonTest):
    microversion = '2.55'
    scenarios = [('v2_55', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(FlavorsSampleJsonTest2_55, self).setUp()
        # Get the existing flavors created by DefaultFlavorsFixture.
        ctxt = nova_context.get_admin_context()
        flavors = objects.FlavorList.get_all(ctxt)
        # Flavors are sorted by flavorid in ascending order by default, so
        # get the last flavor in the list and create a new flavor with an
        # incremental flavorid so we have a predictable sort order for the
        # sample response.
        new_flavor_id = int(flavors[-1].flavorid) + 1
        new_flavor = objects.Flavor(
            ctxt, memory_mb=2048, vcpus=1, root_gb=20, flavorid=new_flavor_id,
            name='m1.small.description', description='test description')
        new_flavor.create()
        self.flavor_show_id = new_flavor_id
        self.subs = {'flavorid': new_flavor_id}


class FlavorsSampleJsonTest2_61(FlavorsSampleJsonTest):
    microversion = '2.61'
    scenarios = [('v2_61', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(FlavorsSampleJsonTest2_61, self).setUp()
        # Get the existing flavors created by DefaultFlavorsFixture.
        ctxt = nova_context.get_admin_context()
        flavors = objects.FlavorList.get_all(ctxt)
        # Flavors are sorted by flavorid in ascending order by default, so
        # get the last flavor in the list and create a new flavor with an
        # incremental flavorid so we have a predictable sort order for the
        # sample response.
        new_flavor_id = int(flavors[-1].flavorid) + 1
        new_flavor = objects.Flavor(
            ctxt, memory_mb=2048, vcpus=1, root_gb=20, flavorid=new_flavor_id,
            name='m1.small.description', description='test description',
            extra_specs={
                'hw:numa_nodes': '1',
                'hw:cpu_policy': 'shared',
            })
        new_flavor.create()
        self.flavor_show_id = new_flavor_id
        self.subs = {'flavorid': new_flavor_id}


class FlavorsSampleJsonTest2_75(FlavorsSampleJsonTest2_61):
    microversion = '2.75'
    scenarios = [('v2_75', {'api_major_version': 'v2.1'})]

    def test_flavors_list(self):
        pass


class FlavorIdAliasTest(api_sample_base.ApiSampleTestBaseV21):
    alias_prefix = "x_test_alias_"

    def setUp(self):
        super(FlavorIdAliasTest, self).setUp()
        self.ctxt = nova_context.get_admin_context()
        self.flags(flavorid_alias_prefix=self.alias_prefix)

    def _create_aliased_flavor(self, alias):
        flavors = objects.FlavorList.get_all(self.ctxt)
        self.flavor_id = str(int(flavors[-1].flavorid) + 1)
        self.flavor_id_alias = self.alias_prefix + self.flavor_id + "_0"
        aliased_flavor = objects.Flavor(
            self.ctxt, memory_mb=2048, vcpus=1, root_gb=20,
            flavorid=self.flavor_id, name='my.flavor',
            extra_specs={'catalog:alias': alias})
        aliased_flavor.create()

    @staticmethod
    def _response_flavor_ids(response):
        return [f['id'] for f in response.json()['flavors']]

    def test_aliased_flavor_visible_in_list(self):
        self._create_aliased_flavor('my.flavor.old')
        response = self._do_get('flavors')
        self.assertIn(self.flavor_id_alias,
                      self._response_flavor_ids(response))

    def test_aliased_flavor_unaliased_name_in_show(self):
        self._create_aliased_flavor('my.flavor.old')
        response = self._do_get('flavors/%s' % self.flavor_id_alias)
        response_flavor = response.json()['flavor']
        response_id = response_flavor['id']
        response_name = response_flavor['name']
        self.assertEqual(response_id, self.flavor_id)
        self.assertEqual(response_name, 'my.flavor')

    def test_empty_catalog_alias_doesnt_create_alias(self):
        self._create_aliased_flavor('')
        response = self._do_get('flavors')
        self.assertNotIn(self.flavor_id_alias,
                         self._response_flavor_ids(response))

    def test_multiple_aliases_list(self):
        self._create_aliased_flavor('old1,old2, old3')
        response = self._do_get('flavors')
        self.assertIn(self.flavor_id_alias,
                      self._response_flavor_ids(response))
        self.assertIn(self.flavor_id_alias.replace("_0", "_1"),
                      self._response_flavor_ids(response))
        self.assertIn(self.flavor_id_alias.replace("_0", "_2"),
                      self._response_flavor_ids(response))
