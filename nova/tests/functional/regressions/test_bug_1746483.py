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

from nova import config
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture
from nova import utils

CONF = config.CONF


class TestBootFromVolumeIsolatedHostsFilter(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Regression test for bug #1746483

    The IsolatedHostsFilter checks for images restricted to certain hosts via
    config options. When creating a server from a root volume, the image is
    in the volume (and it's related metadata from Cinder). When creating a
    volume-backed server, the imageRef is not required.

    The regression is that the RequestSpec.image.id field is not set and the
    IsolatedHostsFilter blows up trying to load the image id.
    """
    def setUp(self):
        super(TestBootFromVolumeIsolatedHostsFilter, self).setUp()

        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.glance = self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.CinderFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.admin_api

        self.start_service('conductor')

        # Add the IsolatedHostsFilter to the list of enabled filters since it
        # is not enabled by default.
        enabled_filters = CONF.filter_scheduler.enabled_filters
        enabled_filters.append('IsolatedHostsFilter')
        self.flags(
            enabled_filters=enabled_filters,
            isolated_images=[self.glance.auto_disk_config_enabled_image['id']],
            isolated_hosts=['host1'],
            restrict_isolated_hosts_to_isolated_images=True,
            group='filter_scheduler')
        self.start_service('scheduler')

        # Create two compute nodes/services so we can restrict the image
        # we'll use to one of the hosts.
        for host in ('host1', 'host2'):
            self.start_service('compute', host=host)

    def test_boot_from_volume_with_isolated_image(self):
        # Create our server without networking just to keep things simple.
        image_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server_req_body = {
            # There is no imageRef because this is boot from volume.
            'server': {
                'flavorRef': '1',   # m1.tiny from DefaultFlavorsFixture,
                'name': 'test_boot_from_volume_with_isolated_image',
                'networks': 'none',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'uuid': image_id,
                    'source_type': 'volume',
                    'destination_type': 'volume'
                }]
            }
        }
        # Note that we're using v2.1 by default but need v2.37 to use
        # networks='none'.
        with utils.temporary_mutation(self.api, microversion='2.37'):
            server = self.api.post_server(server_req_body)
        server = self._wait_for_state_change(server, 'ACTIVE')
        # NOTE(mriedem): The instance is successfully scheduled but since
        # the image_id from the volume_image_metadata isn't stored in the
        # RequestSpec.image.id, and restrict_isolated_hosts_to_isolated_images
        # is True, the isolated host (host1) is filtered out because the
        # filter doesn't have enough information to know if the image within
        # the volume can be used on that host.
        self.assertEqual('host2', server['OS-EXT-SRV-ATTR:host'])
