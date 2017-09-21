# Copyright 2015 Hewlett-Packard Development Company, L.P.
#
# All Rights Reserved.
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

import testscenarios

from nova import context
from nova import exception as ex
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers as helper
from nova.tests.unit import policy_fixture


def rand_flavor(**kwargs):
    flav = {
        'name': 'name-%s' % helper.generate_random_alphanumeric(10),
        'id': helper.generate_random_alphanumeric(10),
        'ram': int(helper.generate_random_numeric(2)) + 1,
        'disk': int(helper.generate_random_numeric(3)),
        'vcpus': int(helper.generate_random_numeric(1)) + 1,
    }
    flav.update(kwargs)
    return flav


class FlavorManageFullstack(testscenarios.WithScenarios, test.TestCase):
    """Tests for flavors manage administrative command.

    Extension: os-flavors-manage

    os-flavors-manage adds a set of admin functions to the flavors
    resource for the creation and deletion of flavors.

    POST /v2/flavors:

    ::

        {
            'name': NAME, # string, required unique
            'id': ID, # string, required unique
            'ram': RAM, # in MB, required
            'vcpus': VCPUS, # int value, required
            'disk': DISK, # in GB, required
            'OS-FLV-EXT-DATA:ephemeral', # in GB, ephemeral disk size
            'is_public': IS_PUBLIC, # boolean
            'swap': SWAP, # in GB?
            'rxtx_factor': RXTX, # ???
        }

    Returns Flavor

    DELETE /v2/flavors/ID


    Functional Test Scope:

    This test starts the wsgi stack for the nova api services, uses an
    in memory database to ensure the path through the wsgi layer to
    the database.

    """

    _additional_fixtures = []

    scenarios = [
        # test v2.1 base microversion
        ('v2_1', {
            'api_major_version': 'v2.1'}),
    ]

    def setUp(self):
        super(FlavorManageFullstack, self).setUp()

        # load any additional fixtures specified by the scenario
        for fix in self._additional_fixtures:
            self.useFixture(fix())

        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(
            nova_fixtures.OSAPIFixture(
                api_version=self.api_major_version))

        # NOTE(sdague): because this test is primarily an admin API
        # test default self.api to the admin api.
        self.api = api_fixture.admin_api
        self.user_api = api_fixture.api

    def assertFlavorDbEqual(self, flav, flavdb):
        # a mapping of the REST params to the db fields
        mapping = {
            'name': 'name',
            'disk': 'root_gb',
            'ram': 'memory_mb',
            'vcpus': 'vcpus',
            'id': 'flavorid',
            'swap': 'swap'
        }
        for k, v in mapping.items():
            if k in flav:
                self.assertEqual(flav[k], flavdb[v],
                                 "%s != %s" % (flav, flavdb))

    def assertFlavorAPIEqual(self, flav, flavapi):
        # for all keys in the flavor, ensure they are correctly set in
        # flavapi response.
        for k in flav:
            if k in flavapi:
                self.assertEqual(flav[k], flavapi[k],
                                 "%s != %s" % (flav, flavapi))
            else:
                self.fail("Missing key: %s in flavor: %s" % (k, flavapi))

    def assertFlavorInList(self, flav, flavlist):
        for item in flavlist['flavors']:
            if flav['id'] == item['id']:
                self.assertEqual(flav['name'], item['name'])
                return
        self.fail("%s not found in %s" % (flav, flavlist))

    def assertFlavorNotInList(self, flav, flavlist):
        for item in flavlist['flavors']:
            if flav['id'] == item['id']:
                self.fail("%s found in %s" % (flav, flavlist))

    def test_flavor_manage_func_negative(self):
        """Test flavor manage edge conditions.

        - Bogus body is a 400
        - Unknown flavor is a 404
        - Deleting unknown flavor is a 404
        """
        # Test for various API failure conditions
        # bad body is 400
        resp = self.api.api_post('flavors', '', check_response_status=False)
        self.assertEqual(400, resp.status)

        # get unknown flavor is 404
        resp = self.api.api_delete('flavors/foo', check_response_status=False)
        self.assertEqual(404, resp.status)

        # delete unknown flavor is 404
        resp = self.api.api_delete('flavors/foo', check_response_status=False)
        self.assertEqual(404, resp.status)

        ctx = context.get_admin_context()
        # bounds conditions - invalid vcpus
        flav = {'flavor': rand_flavor(vcpus=0)}
        resp = self.api.api_post('flavors', flav, check_response_status=False)
        self.assertEqual(400, resp.status, resp)
        # ... and ensure that we didn't leak it into the db
        self.assertRaises(ex.FlavorNotFound,
                          objects.Flavor.get_by_flavor_id,
                          ctx, flav['flavor']['id'])

        # bounds conditions - invalid ram
        flav = {'flavor': rand_flavor(ram=0)}

        resp = self.api.api_post('flavors', flav, check_response_status=False)
        self.assertEqual(400, resp.status)
        # ... and ensure that we didn't leak it into the db
        self.assertRaises(ex.FlavorNotFound,
                          objects.Flavor.get_by_flavor_id,
                          ctx, flav['flavor']['id'])

        # NOTE(sdague): if there are other bounds conditions that
        # should be checked, stack them up here.

    def test_flavor_manage_deleted(self):
        """Ensure the behavior around a deleted flavor is stable.

        - Fetching a deleted flavor works, and returns the flavor info.
        - Listings should not contain deleted flavors

        """
        # create a deleted flavor
        new_flav = {'flavor': rand_flavor()}
        self.api.api_post('flavors', new_flav)
        self.api.api_delete('flavors/%s' % new_flav['flavor']['id'])

        # deleted flavor should not show up in a list
        resp = self.api.api_get('flavors')
        self.assertFlavorNotInList(new_flav['flavor'], resp.body)

    def test_flavor_manage_func(self):
        """Basic flavor creation lifecycle testing.

        - Creating a flavor
        - Ensure it's in the database
        - Ensure it's in the listing
        - Delete it
        - Ensure it's hidden in the database
        """

        ctx = context.get_admin_context()
        flav1 = {
            'flavor': rand_flavor(),
         }

        # Create flavor and ensure it made it to the database
        self.api.api_post('flavors', flav1)

        flav1db = objects.Flavor.get_by_flavor_id(ctx, flav1['flavor']['id'])
        self.assertFlavorDbEqual(flav1['flavor'], flav1db)

        # Ensure new flavor is seen in the listing
        resp = self.api.api_get('flavors')
        self.assertFlavorInList(flav1['flavor'], resp.body)

        # Delete flavor and ensure it was removed from the database
        self.api.api_delete('flavors/%s' % flav1['flavor']['id'])
        self.assertRaises(ex.FlavorNotFound,
                          objects.Flavor.get_by_flavor_id,
                          ctx, flav1['flavor']['id'])

        resp = self.api.api_delete('flavors/%s' % flav1['flavor']['id'],
                                   check_response_status=False)
        self.assertEqual(404, resp.status)

    def test_flavor_manage_permissions(self):
        """Ensure that regular users can't create or delete flavors.

        """
        ctx = context.get_admin_context()
        flav1 = {'flavor': rand_flavor()}

        # Ensure user can't create flavor
        resp = self.user_api.api_post('flavors', flav1,
                                      check_response_status=False)
        self.assertEqual(403, resp.status)
        # ... and that it didn't leak through
        self.assertRaises(ex.FlavorNotFound,
                        objects.Flavor.get_by_flavor_id,
                        ctx, flav1['flavor']['id'])

        # Create the flavor as the admin user
        self.api.api_post('flavors', flav1)

        # Ensure user can't delete flavors from our cloud
        resp = self.user_api.api_delete('flavors/%s' % flav1['flavor']['id'],
                                        check_response_status=False)
        self.assertEqual(403, resp.status)
        # ... and ensure that we didn't actually delete the flavor,
        # this will throw an exception if we did.
        objects.Flavor.get_by_flavor_id(ctx, flav1['flavor']['id'])
