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

from nova import context
from nova import db
from nova import exception as ex
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers as helper


def rand_flavor():
    flav = {
        'name': 'name-%s' % helper.generate_random_alphanumeric(10),
        'id': helper.generate_random_alphanumeric(10),
        'ram': int(helper.generate_random_numeric(2)),
        'disk': int(helper.generate_random_numeric(3)),
        'vcpus': int(helper.generate_random_numeric(1)) + 1,
    }
    return flav


class FlavorManageFullstack(test.TestCase):
    """Tests for flavors manage administrative command.

    Extention: os-flavors-manage

    os-flavors-manage adds a set of admin functions to the flavors
    resource for create and delete of flavors.

    POST /v2/flavors:

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


    Functional Test Scope::

    This test starts the wsgi stack for the nova api services, uses an
    in memory database to ensure the path through the wsgi layer to
    the database.

    """
    def setUp(self):
        super(FlavorManageFullstack, self).setUp()
        self.api = self.useFixture(nova_fixtures.OSAPIFixture()).api

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
        for k, v in mapping.iteritems():
            if k in flav:
                self.assertEqual(flav[k], flavdb[v],
                                 "%s != %s" % (flav, flavdb))

    def test_flavor_manage_func_negative(self):
        # Test for various API failure conditions
        # bad body is 400
        resp = self.api.api_request('flavors', method='POST')
        self.assertEqual(400, resp.status_code)

        # get unknown flavor is 404
        resp = self.api.api_request('flavors/foo')
        self.assertEqual(404, resp.status_code)

        # delete unknown flavor is 404
        resp = self.api.api_request('flavors/foo', method='DELETE')
        self.assertEqual(404, resp.status_code)

    def test_flavor_manage_func(self):
        ctx = context.get_admin_context()
        flav1 = {
            'flavor': rand_flavor(),
         }

        # Create flavor and ensure it made it to the database
        resp = self.api.api_post('flavors', flav1)

        flav1db = db.flavor_get_by_flavor_id(ctx, flav1['flavor']['id'])
        self.assertFlavorDbEqual(flav1['flavor'], flav1db)

        # Delete flavor and ensure it was removed from the database
        resp = self.api.api_request('flavors/%s' % flav1['flavor']['id'],
                                    method='DELETE')
        self.assertRaises(ex.FlavorNotFound,
                          db.flavor_get_by_flavor_id,
                          ctx, flav1['flavor']['id'])

        resp = self.api.api_request('flavors/%s' % flav1['flavor']['id'],
                                    method='DELETE')
        self.assertEqual(404, resp.status_code)
