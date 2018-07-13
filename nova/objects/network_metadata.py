# Copyright 2018 Red Hat, Inc.
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

from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class NetworkMetadata(base.NovaObject):
    """Hold aggregate metadata for a collection of networks.

    This object holds aggregate information for a collection of neutron
    networks. There are two types of network collections we care about and use
    this for: the collection of networks configured or requested for a guest
    and the collection of networks available to a host. We want this
    information to allow us to map a given neutron network to the logical NICs
    it does or will use (or, rather, to identify the NUMA affinity of those
    NICs and therefore the networks). Given that there are potentially tens of
    thousands of neutron networks accessible from a given host and tens or
    hundreds of networks configured for an instance, we need a way to group
    networks by some common attribute that would identify the logical NIC it
    would use. For L2 networks, this is the physnet attribute (e.g.
    ``provider:physical_network=provider1``), which is an arbitrary string used
    to distinguish between multiple physical (in the sense of physical wiring)
    networks. For L3 (tunneled) networks, this is merely the fact that they are
    L3 networks (e.g.  ``provider:network_type=vxlan``) because, in neutron,
    *all* L3 networks must use the same logical NIC.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'physnets': fields.SetOfStringsField(),
        'tunneled': fields.BooleanField(),
    }
