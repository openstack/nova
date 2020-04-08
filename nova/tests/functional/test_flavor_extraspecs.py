# Copyright 2020, Red Hat, Inc. All Rights Reserved.
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

"""Tests for os-extra_specs API."""

from nova.tests.functional.api import client as api_client
from nova.tests.functional import integrated_helpers


class FlavorExtraSpecsTest(integrated_helpers._IntegratedTestBase):
    api_major_version = 'v2'

    def setUp(self):
        super(FlavorExtraSpecsTest, self).setUp()
        self.flavor_id = self._create_flavor()

    def test_create(self):
        """Test creating flavor extra specs with valid specs."""
        body = {
            'extra_specs': {'hw:numa_nodes': '1', 'hw:cpu_policy': 'shared'},
        }
        self.admin_api.post_extra_spec(self.flavor_id, body)
        self.assertEqual(
            body['extra_specs'], self.admin_api.get_extra_specs(self.flavor_id)
        )

    def test_create_invalid_spec(self):
        """Test creating flavor extra specs with invalid specs.

        This should pass because validation is not enabled in this API
        microversion.
        """
        body = {'extra_specs': {'hw:numa_nodes': 'foo', 'foo': 'bar'}}
        self.admin_api.post_extra_spec(self.flavor_id, body)
        self.assertEqual(
            body['extra_specs'], self.admin_api.get_extra_specs(self.flavor_id)
        )

    def test_update(self):
        """Test updating extra specs with valid specs."""
        spec_id = 'hw:numa_nodes'
        body = {'hw:numa_nodes': '1'}
        self.admin_api.put_extra_spec(self.flavor_id, spec_id, body)
        self.assertEqual(
            body, self.admin_api.get_extra_spec(self.flavor_id, spec_id)
        )

    def test_update_invalid_spec(self):
        """Test updating extra specs with invalid specs.

        This should pass because validation is not enabled in this API
        microversion.
        """
        spec_id = 'hw:foo'
        body = {'hw:foo': 'bar'}
        self.admin_api.put_extra_spec(self.flavor_id, spec_id, body)
        self.assertEqual(
            body, self.admin_api.get_extra_spec(self.flavor_id, spec_id)
        )


class FlavorExtraSpecsV286Test(FlavorExtraSpecsTest):
    api_major_version = 'v2.1'
    microversion = '2.86'

    def test_create_invalid_spec(self):
        """Test creating extra specs with invalid specs."""
        body = {'extra_specs': {'hw:numa_nodes': 'foo', 'foo': 'bar'}}

        # this should fail because 'foo' is not a suitable value for
        # 'hw:numa_nodes'
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.admin_api.post_extra_spec,
            self.flavor_id, body,
        )
        self.assertEqual(400, exc.response.status_code)

        # ...and the extra specs should not be saved
        self.assertEqual({}, self.admin_api.get_extra_specs(self.flavor_id))

    def test_create_unknown_spec(self):
        """Test creating extra specs with unknown specs."""
        body = {'extra_specs': {'hw:numa_nodes': '1', 'foo': 'bar'}}

        # this should pass because we don't recognize the extra spec but it's
        # not in a namespace we care about
        self.admin_api.post_extra_spec(self.flavor_id, body)

        body = {'extra_specs': {'hw:numa_nodes': '1', 'hw:foo': 'bar'}}

        # ...but this should fail because we do recognize the namespace
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.admin_api.post_extra_spec,
            self.flavor_id, body,
        )
        self.assertEqual(400, exc.response.status_code)

    def test_update_invalid_spec(self):
        """Test updating extra specs with invalid specs."""
        spec_id = 'hw:foo'
        body = {'hw:foo': 'bar'}

        # this should fail because we don't recognize the extra spec
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.admin_api.put_extra_spec,
            self.flavor_id, spec_id, body,
        )
        self.assertEqual(400, exc.response.status_code)

        spec_id = 'hw:numa_nodes'
        body = {'hw:numa_nodes': 'foo'}

        # ...while this should fail because the value is not valid
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.admin_api.put_extra_spec,
            self.flavor_id, spec_id, body,
        )
        self.assertEqual(400, exc.response.status_code)

        # ...and neither extra spec should be saved
        self.assertEqual({}, self.admin_api.get_extra_specs(self.flavor_id))

    def test_update_unknown_spec(self):
        """Test updating extra specs with unknown specs."""
        spec_id = 'foo:bar'
        body = {'foo:bar': 'baz'}

        # this should pass because we don't recognize the extra spec but it's
        # not in a namespace we care about
        self.admin_api.put_extra_spec(self.flavor_id, spec_id, body)
        self.assertEqual(body, self.admin_api.get_extra_specs(self.flavor_id))
