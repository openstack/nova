# Copyright 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
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

import hashlib

import mock
from testtools import matchers

from nova import exception
from nova import hash_ring
from nova import test


class HashRingTestCase(test.TestCase):

    # NOTE(deva): the mapping used in these tests is as follows:
    #             if hosts = [foo, bar]:
    #                fake -> foo, bar
    #             if hosts = [foo, bar, baz]:
    #                fake -> foo, bar, baz
    #                fake-again -> bar, baz, foo

    @mock.patch.object(hashlib, 'md5', autospec=True)
    def test__hash2int_returns_int(self, mock_md5):
        r1 = 32 * 'a'
        r2 = 32 * 'b'
        # 2**PARTITION_EXPONENT calls to md5.update per host
        # PARTITION_EXPONENT is currently always 5, so 32 calls each here
        mock_md5.return_value.hexdigest.side_effect = [r1] * 32 + [r2] * 32

        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts)

        self.assertIn(int(r1, 16), ring._host_hashes)
        self.assertIn(int(r2, 16), ring._host_hashes)

    def test_create_ring(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts)
        self.assertEqual(set(hosts), ring.hosts)
        self.assertEqual(1, ring.replicas)
        self.assertEqual(2 ** 5 * 2, len(ring._partitions))

    def test_distribution_one_replica(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts)
        fake_1_hosts = ring.get_hosts('fake')
        fake_2_hosts = ring.get_hosts('fake-again')
        # We should have one hosts for each thing
        self.assertThat(fake_1_hosts, matchers.HasLength(1))
        self.assertThat(fake_2_hosts, matchers.HasLength(1))
        # And they must not be the same answers even on this simple data.
        self.assertNotEqual(fake_1_hosts, fake_2_hosts)

    def test_ignore_hosts(self):
        hosts = ['foo', 'bar', 'baz']
        ring = hash_ring.HashRing(hosts)
        equals_bar_or_baz = matchers.MatchesAny(
            matchers.Equals(['bar']),
            matchers.Equals(['baz']))
        self.assertThat(
            ring.get_hosts('fake', ignore_hosts=['foo']),
            equals_bar_or_baz)
        self.assertThat(
            ring.get_hosts('fake', ignore_hosts=['foo', 'bar']),
            equals_bar_or_baz)
        self.assertEqual([], ring.get_hosts('fake', ignore_hosts=hosts))

    def _compare_rings(self, nodes, conductors, ring,
                       new_conductors, new_ring):
        delta = {}
        mapping = {'node': ring.get_hosts(node)[0] for node in nodes}
        new_mapping = {'node': new_ring.get_hosts(node)[0] for node in nodes}

        for key, old in mapping.items():
            new = new_mapping.get(key, None)
            if new != old:
                delta[key] = (old, new)
        return delta

    def test_rebalance_stability_join(self):
        num_services = 10
        num_nodes = 10000
        # Adding 1 service to a set of N should move 1/(N+1) of all nodes
        # Eg, for a cluster of 10 nodes, adding one should move 1/11, or 9%
        # We allow for 1/N to allow for rounding in tests.
        redistribution_factor = 1.0 / num_services

        nodes = [str(x) for x in range(num_nodes)]
        services = [str(x) for x in range(num_services)]
        new_services = services + ['new']
        delta = self._compare_rings(
            nodes, services, hash_ring.HashRing(services),
            new_services, hash_ring.HashRing(new_services))

        self.assertLess(len(delta), num_nodes * redistribution_factor)

    def test_rebalance_stability_leave(self):
        num_services = 10
        num_nodes = 10000
        # Removing 1 service from a set of N should move 1/(N) of all nodes
        # Eg, for a cluster of 10 nodes, removing one should move 1/10, or 10%
        # We allow for 1/(N-1) to allow for rounding in tests.
        redistribution_factor = 1.0 / (num_services - 1)

        nodes = [str(x) for x in range(num_nodes)]
        services = [str(x) for x in range(num_services)]
        new_services = services[:]
        new_services.pop()
        delta = self._compare_rings(
            nodes, services, hash_ring.HashRing(services),
            new_services, hash_ring.HashRing(new_services))

        self.assertLess(len(delta), num_nodes * redistribution_factor)

    def test_ignore_non_existent_host(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts)
        self.assertEqual(['foo'], ring.get_hosts('fake',
                                                 ignore_hosts=['baz']))

    def test_create_ring_invalid_data(self):
        hosts = None
        self.assertRaises(exception.Invalid,
                          hash_ring.HashRing,
                          hosts)

    def test_get_hosts_invalid_data(self):
        hosts = ['foo', 'bar']
        ring = hash_ring.HashRing(hosts)
        self.assertRaises(exception.Invalid,
                          ring.get_hosts,
                          None)
