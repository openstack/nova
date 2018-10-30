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

from oslo_utils.fixture import uuidsentinel as uuids

from nova import conf
from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import cross_cell
from nova import test
from nova.tests.unit.scheduler import fakes

CONF = conf.CONF


class CrossCellWeigherTestCase(test.NoDBTestCase):
    """Tests for the FilterScheduler CrossCellWeigher."""

    def setUp(self):
        super(CrossCellWeigherTestCase, self).setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [cross_cell.CrossCellWeigher()]

    def _get_weighed_hosts(self, request_spec):
        hosts = self._get_all_hosts()
        return self.weight_handler.get_weighed_objects(
            self.weighers, hosts, request_spec)

    @staticmethod
    def _get_all_hosts():
        """Provides two hosts, one in cell1 and one in cell2."""
        host_values = [
            ('host1', 'node1', {'cell_uuid': uuids.cell1}),
            ('host2', 'node2', {'cell_uuid': uuids.cell2}),
        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]

    def test_get_weighed_hosts_no_requested_destination_or_cell(self):
        """Weights should all be 0.0 given there is no requested_destination
        or source cell in the RequestSpec, e.g. initial server create scenario.
        """
        # Test the requested_destination field not being set.
        request_spec = objects.RequestSpec()
        weighed_hosts = self._get_weighed_hosts(request_spec)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))
        # Test the requested_destination field being set to None.
        request_spec.requested_destination = None
        weighed_hosts = self._get_weighed_hosts(request_spec)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))
        # Test the requested_destination field being set but without the
        # cell field set.
        request_spec.requested_destination = objects.Destination()
        weighed_hosts = self._get_weighed_hosts(request_spec)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))
        # Test the requested_destination field being set with the cell field
        # set but to None.
        request_spec.requested_destination = objects.Destination(cell=None)
        weighed_hosts = self._get_weighed_hosts(request_spec)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))

    def test_get_weighed_hosts_allow_cross_cell_move_false(self):
        """Tests the scenario that the source cell is set in the requested
        destination but it's not a cross cell move so the weights should all
        be 0.0.
        """
        request_spec = objects.RequestSpec(
            requested_destination=objects.Destination(
                cell=objects.CellMapping(uuid=uuids.cell1)))
        weighed_hosts = self._get_weighed_hosts(request_spec)
        self.assertTrue(all([wh.weight == 0.0
                             for wh in weighed_hosts]))

    def test_get_weighed_hosts_allow_cross_cell_move_true_positive(self):
        """Tests a cross-cell move where the host in the source (preferred)
        cell should be weighed higher than the host in the other cell based
        on the default configuration.
        """
        request_spec = objects.RequestSpec(
            requested_destination=objects.Destination(
                cell=objects.CellMapping(uuid=uuids.cell1),
                allow_cross_cell_move=True))
        weighed_hosts = self._get_weighed_hosts(request_spec)
        multiplier = CONF.filter_scheduler.cross_cell_move_weight_multiplier
        self.assertEqual([multiplier, 0.0],
                         [wh.weight for wh in weighed_hosts])
        # host1 should be preferred since it's in cell1
        preferred_host = weighed_hosts[0]
        self.assertEqual('host1', preferred_host.obj.host)

    def test_get_weighed_hosts_allow_cross_cell_move_true_negative(self):
        """Tests a cross-cell move where the host in another cell should be
        weighed higher than the host in the source cell because the weight
        value is negative.
        """
        self.flags(cross_cell_move_weight_multiplier=-1000,
                   group='filter_scheduler')
        request_spec = objects.RequestSpec(
            requested_destination=objects.Destination(
                # cell1 is the source cell
                cell=objects.CellMapping(uuid=uuids.cell1),
                allow_cross_cell_move=True))
        weighed_hosts = self._get_weighed_hosts(request_spec)
        multiplier = CONF.filter_scheduler.cross_cell_move_weight_multiplier
        self.assertEqual([0.0, multiplier],
                         [wh.weight for wh in weighed_hosts])
        # host2 should be preferred since it's *not* in cell1
        preferred_host = weighed_hosts[0]
        self.assertEqual('host2', preferred_host.obj.host)

    def test_multiplier(self):
        weigher = self.weighers[0]
        host1 = fakes.FakeHostState('fake-host', 'node', {})
        # By default, return the cross_cell_move_weight_multiplier
        # configuration directly since the host is not in an aggregate.
        self.assertEqual(
            CONF.filter_scheduler.cross_cell_move_weight_multiplier,
            weigher.weight_multiplier(host1))
        host1.aggregates = [
            objects.Aggregate(
                id=1,
                name='foo',
                hosts=['fake-host'],
                metadata={'cross_cell_move_weight_multiplier': '-1.0'},
            )]
        # Read the weight multiplier from aggregate metadata to override the
        # config.
        self.assertEqual(-1.0, weigher.weight_multiplier(host1))
