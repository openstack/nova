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

import bisect
import hashlib

import six

from nova import exception
from nova.i18n import _


# NOTE(jroll) these constants will be config options in Ocata, when the hash
# ring code is in oslo.
# Number of partitions per service is 2^PARTITION_EXPONENT.
# 5 should be fine for most deployments, as an experimental feature.
PARTITION_EXPONENT = 5
# This should always be 1 in nova, as two compute daemons handling the same
# node should not be possible.
DISTRIBUTION_REPLICAS = 1


class HashRing(object):
    """A stable hash ring.

    We map item N to a host Y based on the closest lower hash:

    - hash(item) -> partition
    - hash(host) -> divider
    - closest lower divider is the host to use
    - we hash each host many times to spread load more finely
      as otherwise adding a host gets (on average) 50% of the load of
      just one other host assigned to it.
    """

    def __init__(self, hosts):
        """Create a new hash ring across the specified hosts.

        :param hosts: an iterable of hosts which will be mapped.
        """
        replicas = DISTRIBUTION_REPLICAS

        try:
            self.hosts = set(hosts)
            self.replicas = replicas if replicas <= len(hosts) else len(hosts)
        except TypeError:
            raise exception.Invalid(
                _("Invalid hosts supplied when building HashRing."))

        self._host_hashes = {}
        for host in hosts:
            key = str(host).encode('utf8')
            key_hash = hashlib.md5(key)
            for p in range(2 ** PARTITION_EXPONENT):
                key_hash.update(key)
                hashed_key = self._hash2int(key_hash)
                self._host_hashes[hashed_key] = host
        # Gather the (possibly colliding) resulting hashes into a bisectable
        # list.
        self._partitions = sorted(self._host_hashes.keys())

    def _hash2int(self, key_hash):
        """Convert the given hash's digest to a numerical value for the ring.

        :returns: An integer equivalent value of the digest.
        """
        return int(key_hash.hexdigest(), 16)

    def _get_partition(self, data):
        try:
            if six.PY3 and data is not None:
                data = data.encode('utf-8')
            key_hash = hashlib.md5(data)
            hashed_key = self._hash2int(key_hash)
            position = bisect.bisect(self._partitions, hashed_key)
            return position if position < len(self._partitions) else 0
        except TypeError:
            raise exception.Invalid(
                _("Invalid data supplied to HashRing.get_hosts."))

    def get_hosts(self, data, ignore_hosts=None):
        """Get the list of hosts which the supplied data maps onto.

        :param data: A string identifier to be mapped across the ring.
        :param ignore_hosts: A list of hosts to skip when performing the hash.
                             Useful to temporarily skip down hosts without
                             performing a full rebalance.
                             Default: None.
        :returns: a list of hosts.
                  The length of this list depends on the number of replicas
                  this `HashRing` was created with. It may be less than this
                  if ignore_hosts is not None.
        """
        hosts = []
        if ignore_hosts is None:
            ignore_hosts = set()
        else:
            ignore_hosts = set(ignore_hosts)
            ignore_hosts.intersection_update(self.hosts)
        partition = self._get_partition(data)
        for replica in range(0, self.replicas):
            if len(hosts) + len(ignore_hosts) == len(self.hosts):
                # prevent infinite loop - cannot allocate more fallbacks.
                break
            # Linear probing: partition N, then N+1 etc.
            host = self._get_host(partition)
            while host in hosts or host in ignore_hosts:
                partition += 1
                if partition >= len(self._partitions):
                    partition = 0
                host = self._get_host(partition)
            hosts.append(host)
        return hosts

    def _get_host(self, partition):
        """Find what host is serving a partition.

        :param partition: The index of the partition in the partition map.
            e.g. 0 is the first partition, 1 is the second.
        :return: The host object the ring was constructed with.
        """
        return self._host_hashes[self._partitions[partition]]
