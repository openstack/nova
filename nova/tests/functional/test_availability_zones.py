# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nova.api.openstack.compute import hosts
from nova.compute import instance_actions
from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack import fakes


class TestAvailabilityZoneScheduling(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):

    def setUp(self):
        super(TestAvailabilityZoneScheduling, self).setUp()

        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api
        self.api.microversion = 'latest'

        self.controller = hosts.HostController()
        self.req = fakes.HTTPRequest.blank('', use_admin_context=True)

        self.start_service('conductor')
        self.start_service('scheduler')

        # Start two compute services in separate zones.
        self._start_host_in_zone('host1', 'zone1')
        self._start_host_in_zone('host2', 'zone2')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]['id']
        self.flavor2 = flavors[1]['id']

    def _start_host_in_zone(self, host, zone):
        # Start the nova-compute service.
        self.start_service('compute', host=host)
        # Create a host aggregate with a zone in which to put this host.
        aggregate_body = {
            "aggregate": {
                "name": zone,
                "availability_zone": zone
            }
        }
        aggregate = self.api.api_post(
            '/os-aggregates', aggregate_body).body['aggregate']
        # Now add the compute host to the aggregate.
        add_host_body = {
            "add_host": {
                "host": host
            }
        }
        self.api.api_post(
            '/os-aggregates/%s/action' % aggregate['id'], add_host_body)

    def _create_server(self, name, zone=None):
        # Create a server, it doesn't matter which host it ends up in.
        server = super(TestAvailabilityZoneScheduling, self)._create_server(
            flavor_id=self.flavor1,
            networks='none',
            az=zone,
        )
        return server

    def _assert_instance_az_and_host(
            self, server, expected_zone, expected_host=None):
        # Check AZ
        # Check the API.
        self.assertEqual(expected_zone, server['OS-EXT-AZ:availability_zone'])
        # Check the DB.
        ctxt = context.get_admin_context()
        with context.target_cell(
                ctxt, self.cell_mappings[test.CELL1_NAME]) as cctxt:
            instance = objects.Instance.get_by_uuid(cctxt, server['id'])
            self.assertEqual(expected_zone, instance.availability_zone)
        # Check host
        if expected_host:
            self.assertEqual(expected_host, server['OS-EXT-SRV-ATTR:host'])

    def _assert_request_spec_az(self, ctxt, server, az):
        request_spec = objects.RequestSpec.get_by_instance_uuid(
            ctxt, server['id'])
        self.assertEqual(request_spec.availability_zone, az)

    def _assert_server_with_az_unshelved_to_specified_az(self, server, az):
        """Ensure a server with an az constraints is unshelved in the
        corresponding az.
        """
        host_to_disable = 'host1' if az == 'zone1' else 'host2'
        self._shelve_server(server, expected_state='SHELVED_OFFLOADED')
        compute_service_id = self.api.get_services(
            host=host_to_disable, binary='nova-compute')[0]['id']
        self.api.put_service(compute_service_id, {'status': 'disabled'})

        req = {
            'unshelve': None
        }

        self.api.post_server_action(server['id'], req)

        server = self._wait_for_action_fail_completion(
            server, instance_actions.UNSHELVE, 'schedule_instances')
        self.assertIn('Error', server['result'])
        self.assertIn('No valid host', server['details'])

    def _shelve_unshelve_server(self, ctxt, server, req):
        self._shelve_server(server, expected_state='SHELVED_OFFLOADED')

        self.api.post_server_action(server['id'], req)
        server = self._wait_for_server_parameter(
            server,
            {'status': 'ACTIVE', },
        )
        return self.api.get_server(server['id'])

    def other_az_than(self, az):
        return 'zone2' if az == 'zone1' else 'zone1'

    def other_host_than(self, host):
        return 'host2' if host == 'host1' else 'host1'

    def test_live_migrate_implicit_az(self):
        """Tests live migration of an instance with an implicit AZ.

        Before Pike, a server created without an explicit availability zone
        was assigned a default AZ based on the "default_schedule_zone" config
        option which defaults to None, which allows the instance to move
        freely between availability zones.

        With change I8d426f2635232ffc4b510548a905794ca88d7f99 in Pike, if the
        user does not request an availability zone, the
        instance.availability_zone field is set based on the host chosen by
        the scheduler. The default AZ for all nova-compute services is
        determined by the "default_availability_zone" config option which
        defaults to "nova".

        This test creates two nova-compute services in separate zones, creates
        a server without specifying an explicit zone, and then tries to live
        migrate the instance to the other compute which should succeed because
        the request spec does not include an explicit AZ, so the instance is
        still not restricted to its current zone even if it says it is in one.
        """
        server = self._create_server('test_live_migrate_implicit_az')
        original_az = server['OS-EXT-AZ:availability_zone']
        expected_zone = self.other_az_than(original_az)

        # Attempt to live migrate the instance; again, we don't specify a host
        # because there are only two hosts so the scheduler would only be able
        # to pick the second host which is in a different zone.
        live_migrate_req = {
            'os-migrateLive': {
                'block_migration': 'auto',
                'host': None
            }
        }
        self.api.post_server_action(server['id'], live_migrate_req)

        # Poll the migration until it is done.
        migration = self._wait_for_migration_status(server, ['completed'])
        self.assertEqual('live-migration', migration['migration_type'])

        # Assert that the server did move. Note that we check both the API and
        # the database because the API will return the AZ from the host
        # aggregate if instance.host is not None.
        server = self.api.get_server(server['id'])
        self._assert_instance_az_and_host(server, expected_zone)

    def test_create_server(self):
        """Create a server without an AZ constraint and make sure asking a new
        request spec will not have the request_spec.availability_zone set.
        """
        ctxt = context.get_admin_context()
        server = self._create_server('server01')
        self._assert_request_spec_az(ctxt, server, None)

    def test_create_server_to_zone(self):
        """Create a server with an AZ constraint and make sure asking a new
        request spec will have the request_spec.availability_zone to the
        required zone.
        """
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone2')

        server = self.api.get_server(server['id'])
        self._assert_instance_az_and_host(server, 'zone2')
        self._assert_request_spec_az(ctxt, server, 'zone2')

    def test_cold_migrate_cross_az(self):
        """Test a cold migration cross AZ.
        """
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        expected_host = self.other_host_than(original_host)
        expected_zone = self.other_az_than(original_az)

        self._migrate_server(server)
        self._confirm_resize(server)

        server = self.api.get_server(server['id'])
        self._assert_instance_az_and_host(server, expected_zone, expected_host)

# Next tests attempt to check the following behavior
# +----------+---------------------------+-------+----------------------------+
# | Boot     | Unshelve after offload AZ | Host  | Result                     |
# +==========+===========================+=======+============================+
# |  No AZ   | No AZ or AZ=null          | No    | Free scheduling,           |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | No AZ or AZ=null          | Host1 | Schedule to host1,         |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | AZ="AZ1"                  | No    | Schedule to AZ1,           |
# |          |                           |       | reqspec.AZ="AZ1"           |
# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | AZ="AZ1"                  | Host1 | Verify that host1 in AZ1,  |
# |          |                           |       | or (1). Schedule to        |
# |          |                           |       | host1, reqspec.AZ="AZ1"    |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | No AZ                     | No    | Schedule to AZ1,           |
# |          |                           |       | reqspec.AZ="AZ1"           |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ=null                   | No    | Free scheduling,           |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | No AZ                     | Host1 | If host1 is in AZ1,        |
# |          |                           |       | then schedule to host1,    |
# |          |                           |       | reqspec.AZ="AZ1", otherwise|
# |          |                           |       | reject the request (1)     |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ=null                   | Host1 | Schedule to host1,         |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ="AZ2"                  | No    | Schedule to AZ2,           |
# |          |                           |       | reqspec.AZ="AZ2"           |
# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ="AZ2"                  | Host1 | If host1 in AZ2 then       |
# |          |                           |       | schedule to host1,         |
# |          |                           |       | reqspec.AZ="AZ2",          |
# |          |                           |       | otherwise reject (1)       |
# +----------+---------------------------+-------+----------------------------+
#
# (1) Check at the api and return an error.
#
#
# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | No AZ or AZ=null          | No    | Free scheduling,           |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+

    def test_unshelve_server_without_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')

        req = {
            'unshelve': None
        }

        self._shelve_unshelve_server(ctxt, server, req)
        self._assert_request_spec_az(ctxt, server, None)

    def test_unshelve_unpin_az_server_without_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')

        req = {
            'unshelve': {'availability_zone': None}
        }

        self._shelve_unshelve_server(ctxt, server, req)
        self._assert_request_spec_az(ctxt, server, None)

# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | No AZ or AZ=null          | Host1 | Schedule to host1,         |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_host_server_without_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        dest_hostname = self.other_host_than(original_host)
        expected_zone = self.other_az_than(original_az)

        req = {
            'unshelve': {'host': dest_hostname}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, expected_zone, dest_hostname)
        self._assert_request_spec_az(ctxt, server, None)

    def test_unshelve_to_host_and_unpin_server_without_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        dest_hostname = self.other_host_than(original_host)
        expected_zone = self.other_az_than(original_az)

        req = {
            'unshelve': {
                'host': dest_hostname,
                'availability_zone': None,
            }
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, expected_zone, dest_hostname)
        self._assert_request_spec_az(ctxt, server, None)

# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | AZ="AZ1"                  | No    | Schedule to AZ1,           |
# |          |                           |       | reqspec.AZ="AZ1"           |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_az_server_without_az_constraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        dest_hostname = 'host2' if original_host == 'host1' else 'host1'
        dest_az = self.other_az_than(original_az)

        req = {
            'unshelve': {'availability_zone': dest_az}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, dest_az, dest_hostname)
        self._assert_request_spec_az(ctxt, server, dest_az)
        self._assert_server_with_az_unshelved_to_specified_az(
            server, dest_az)

# +----------+---------------------------+-------+----------------------------+
# |  No AZ   | AZ="AZ1"                  | Host1 | Verify that host1 in AZ1,  |
# |          |                           |       | or (3). Schedule to        |
# |          |                           |       | host1, reqspec.AZ="AZ1"    |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_az_and_host_server_without_az_constraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        dest_hostname = 'host2' if original_host == 'host1' else 'host1'
        dest_az = self.other_az_than(original_az)

        req = {
            'unshelve': {'host': dest_hostname, 'availability_zone': dest_az}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, dest_az, dest_hostname)
        self._assert_request_spec_az(ctxt, server, dest_az)
        self._assert_server_with_az_unshelved_to_specified_az(
            server, dest_az)

    def test_unshelve_to_wrong_az_and_host_server_without_az_constraint(self):
        server = self._create_server('server01')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = server['OS-EXT-AZ:availability_zone']
        dest_hostname = 'host2' if original_host == 'host1' else 'host1'

        req = {
            'unshelve': {'host': dest_hostname,
                         'availability_zone': original_az}
        }

        self._shelve_server(server, expected_state='SHELVED_OFFLOADED')
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.api.post_server_action,
            server['id'],
            req
        )

        self.assertEqual(409, exc.response.status_code)
        self.assertIn(
            'Host \\\"{}\\\" is not in the availability zone \\\"{}\\\".'
            .format(dest_hostname, original_az),
            exc.response.text
        )

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | No AZ                     | No    | Schedule to AZ1,           |
# |          |                           |       | reqspec.AZ="AZ1"           |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_a_server_with_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone2')

        req = {
            'unshelve': None
        }

        self._shelve_unshelve_server(ctxt, server, req)
        self._assert_request_spec_az(ctxt, server, 'zone2')
        self._assert_server_with_az_unshelved_to_specified_az(
            server, 'zone2')

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ=null                   | No    | Free scheduling,           |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_unpin_az_a_server_with_az_constraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone2')

        req = {
            'unshelve': {'availability_zone': None}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_request_spec_az(ctxt, server, None)

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | No AZ                     | Host1 | If host1 is in AZ1,        |
# |          |                           |       | then schedule to host1,    |
# |          |                           |       | reqspec.AZ="AZ1", otherwise|
# |          |                           |       | reject the request (3)     |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_host_server_with_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'host': 'host1'}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, 'zone1', 'host1')
        self._assert_request_spec_az(ctxt, server, 'zone1')
        self._assert_server_with_az_unshelved_to_specified_az(
            server, 'zone1')

    def test_unshelve_to_host_wrong_az_server_with_az_contraint(self):
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'host': 'host2'}
        }

        self._shelve_server(server, expected_state='SHELVED_OFFLOADED')
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.api.post_server_action,
            server['id'],
            req
        )

        self.assertEqual(409, exc.response.status_code)
        self.assertIn(
            'Host \\\"host2\\\" is not in the availability '
            'zone \\\"zone1\\\".',
            exc.response.text
        )

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ=null                   | Host1 | Schedule to host1,         |
# |          |                           |       | reqspec.AZ=None            |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_host_and_unpin_server_with_az_contraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'host': 'host2',
                         'availability_zone': None,
                        }
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, 'zone2', 'host2')
        self._assert_request_spec_az(ctxt, server, None)

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ="AZ2"                  | No    | Schedule to AZ2,           |
# |          |                           |       | reqspec.AZ="AZ2"           |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_az_a_server_with_az_constraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'availability_zone': 'zone2'}
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, 'zone2', 'host2')
        self._assert_request_spec_az(ctxt, server, 'zone2')
        self._assert_server_with_az_unshelved_to_specified_az(
            server, 'zone2')

# +----------+---------------------------+-------+----------------------------+
# |  AZ1     | AZ="AZ2"                  | Host1 | If host1 in AZ2 then       |
# |          |                           |       | schedule to host1,         |
# |          |                           |       | reqspec.AZ="AZ2",          |
# |          |                           |       | otherwise reject (3)       |
# +----------+---------------------------+-------+----------------------------+
    def test_unshelve_to_host_and_az_a_server_with_az_constraint(self):
        ctxt = context.get_admin_context()
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'host': 'host2',
                         'availability_zone': 'zone2',
                        }
        }

        server = self._shelve_unshelve_server(ctxt, server, req)
        self._assert_instance_az_and_host(server, 'zone2', 'host2')
        self._assert_request_spec_az(ctxt, server, 'zone2')
        self._assert_server_with_az_unshelved_to_specified_az(
            server, 'zone2')

    def test_unshelve_to_host_and_wrong_az_a_server_with_az_constraint(self):
        server = self._create_server('server01', 'zone1')

        req = {
            'unshelve': {'host': 'host2',
                         'availability_zone': 'zone1',
                        }
        }

        self._shelve_server(server, expected_state='SHELVED_OFFLOADED')
        exc = self.assertRaises(
            api_client.OpenStackApiException,
            self.api.post_server_action,
            server['id'],
            req
        )

        self.assertEqual(409, exc.response.status_code)
        self.assertIn(
            'Host \\\"host2\\\" is not in the availability '
            'zone \\\"zone1\\\".',
            exc.response.text

        )

    def test_resize_revert_across_azs(self):
        """Creates two compute service hosts in separate AZs. Creates a server
        without an explicit AZ so it lands in one AZ, and then resizes the
        server which moves it to the other AZ. Then the resize is reverted and
        asserts the server is shown as back in the original source host AZ.
        """
        server = self._create_server('test_resize_revert_across_azs')
        original_host = server['OS-EXT-SRV-ATTR:host']
        original_az = 'zone1' if original_host == 'host1' else 'zone2'

        # Resize the server which should move it to the other zone.
        self.api.post_server_action(
            server['id'], {'resize': {'flavorRef': self.flavor2}})
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')

        # Now the server should be in the other AZ.
        new_zone = 'zone2' if original_host == 'host1' else 'zone1'
        self._assert_instance_az_and_host(server, new_zone)

        # Revert the resize and the server should be back in the original AZ.
        self.api.post_server_action(server['id'], {'revertResize': None})
        server = self._wait_for_state_change(server, 'ACTIVE')
        self._assert_instance_az_and_host(server, original_az)
