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

from unittest import mock

from nova.scheduler import weights
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

    def _setup_compute_service(self):
        # Override to prevent the default 'compute' service from starting
        pass

    def setUp(self):
        weight_classes = [
            __name__ + '.HostNameWeigher',
            'nova.scheduler.weights.image_props.ImagePropertiesWeigher'
        ]
        self.flags(weight_classes=weight_classes,
                   group='filter_scheduler')
        self.flags(image_props_weight_multiplier=2.0, group='filter_scheduler')
        super(TestImagePropsWeigher, self).setUp()

        # Start only the compute services we want for testing
        self.compute1 = self._start_compute('host1')
        self.compute2 = self._start_compute('host2')

    @mock.patch('nova.weights.LOG.debug')
    def test_boot(self, mock_debug):
        server1 = self._create_server(
            name='inst1',
            networks='none',
            )

        # the weigher sees that there are no existing instances on both hosts
        # with the same image props
        mock_debug.assert_any_call(
            "%s: raw weights %s",
            "ImagePropertiesWeigher",
            {('host2', 'host2'): 0.0, ('host1', 'host1'): 0.0})
        # because of the HostNameWeigher, we're sure that the instance lands
        # on host1
        self.assertEqual('host1', server1['OS-EXT-SRV-ATTR:host'])
        # let's make sure that we don't assert the calls from the previous
        # schedules.
        mock_debug.reset_mock()

        server2 = self._create_server(
            name='inst2',
            host='host2',
            networks='none',
            )
        # Since we force to a host, the weigher will not be called
        self.assertEqual('host2', server2['OS-EXT-SRV-ATTR:host'])

        server3 = self._create_server(
            name='inst3',
            networks='none',
            )

        # now the weigher sees that host1 has an instance with the same image
        # props
        mock_debug.assert_any_call(
            "%s: raw weights %s",
            "ImagePropertiesWeigher",
            {('host2', 'host2'): 1.0, ('host1', 'host1'): 1.0})
        mock_debug.reset_mock()
        # server3 is now on the same host than host1 as the weigh multiplier
        # makes the scheduler to pack instances sharing the same image props.
        self.assertEqual('host1', server3['OS-EXT-SRV-ATTR:host'])

        server4 = self._create_server(
            name='inst4',
            networks='none',
            )
        # eventually, the weigher sees the two existing instances on host1
        mock_debug.assert_any_call(
            "%s: raw weights %s",
            "ImagePropertiesWeigher",
            {('host2', 'host2'): 1.0, ('host1', 'host1'): 2.0})
        # server4 is now packed with server1 and server3.
        self.assertEqual('host1', server4['OS-EXT-SRV-ATTR:host'])
