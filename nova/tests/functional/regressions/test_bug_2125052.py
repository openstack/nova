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

from nova.scheduler import weights
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class HostNameWeigher(weights.BaseHostWeigher):
    # We want to predictabilly have host1 first
    _weights = {'host1': 1, 'host2': 0}

    def _weigh_object(self, host_state, weight_properties):
        # Any undefined host gets no weight.
        return self._weights.get(host_state.host, 0)


class TestImagePropsWeigher(integrated_helpers._IntegratedTestBase):
    """Tests for image props weigher """

    compute_driver = 'fake.MediumFakeDriver'
    microversion = 'latest'
    ADMIN_API = True

    def setUp(self):
        weight_classes = [
            __name__ + '.HostNameWeigher',
            'nova.scheduler.weights.image_props.ImagePropertiesWeigher'
        ]
        self.flags(weight_classes=weight_classes,
                   group='filter_scheduler')
        self.flags(image_props_weight_multiplier=2.0, group='filter_scheduler')
        super(TestImagePropsWeigher, self).setUp()
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))

        self.compute1 = self._start_compute('host1')
        self.compute2 = self._start_compute('host2')

    def test_boot(self):
        server1 = self._create_server(
            name='inst1',
            networks='none',
            )
        self.assertEqual('host1', server1['OS-EXT-SRV-ATTR:host'])
        server2 = self._create_server(
            name='inst2',
            host='host2',
            networks='none',
            )
        self.assertEqual('host2', server2['OS-EXT-SRV-ATTR:host'])

        server3 = self._create_server(
            name='inst3',
            networks='none',
            )
        #  server3 is now on the same host than host1 as the weigh multiplier
        #  makes the scheduler to pack instances sharing the same image props.
        self.assertEqual('host1', server3['OS-EXT-SRV-ATTR:host'])

        server4 = self._create_server(
            name='inst4',
            networks='none',
            )
        #  server4 is now packed with server1 and server3.
        self.assertEqual('host1', server4['OS-EXT-SRV-ATTR:host'])
