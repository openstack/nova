#    Copyright 2014 Red Hat, Inc.
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

from oslo_utils import versionutils

from nova.objects import base as obj_base
from nova.objects import fields

# These are special case enums for the auto-allocate scenario. 'none' means
# do not allocate a network on server create. 'auto' means auto-allocate a
# network (if possible) if none are already available to the project. Other
# values for network_id can be a specific network id, or None, where None
# is the case before auto-allocation was supported in the compute API.
NETWORK_ID_NONE = 'none'
NETWORK_ID_AUTO = 'auto'


@obj_base.NovaObjectRegistry.register
class NetworkRequest(obj_base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added pci_request_id
    # Version 1.2: Added tag field
    VERSION = '1.2'
    fields = {
        'network_id': fields.StringField(nullable=True),
        'address': fields.IPAddressField(nullable=True),
        'port_id': fields.UUIDField(nullable=True),
        'pci_request_id': fields.UUIDField(nullable=True),
        'tag': fields.StringField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'tag' in primitive:
            del primitive['tag']

    def obj_load_attr(self, attr):
        setattr(self, attr, None)

    def to_tuple(self):
        address = str(self.address) if self.address is not None else None
        return self.network_id, address, self.port_id, self.pci_request_id

    @classmethod
    def from_tuple(cls, net_tuple):
        network_id, address, port_id, pci_request_id = net_tuple
        return cls(network_id=network_id, address=address, port_id=port_id,
                   pci_request_id=pci_request_id)

    @property
    def auto_allocate(self):
        return self.network_id == NETWORK_ID_AUTO

    @property
    def no_allocate(self):
        return self.network_id == NETWORK_ID_NONE


@obj_base.NovaObjectRegistry.register
class NetworkRequestList(obj_base.ObjectListBase, obj_base.NovaObject):
    fields = {
        'objects': fields.ListOfObjectsField('NetworkRequest'),
        }

    VERSION = '1.1'

    def as_tuples(self):
        return [x.to_tuple() for x in self.objects]

    @classmethod
    def from_tuples(cls, net_tuples):
        """Convenience method for converting a list of network request tuples
        into a NetworkRequestList object.

        :param net_tuples: list of network request tuples
        :returns: NetworkRequestList object
        """
        requested_networks = cls(objects=[NetworkRequest.from_tuple(t)
                                          for t in net_tuples])
        return requested_networks

    @property
    def is_single_unspecified(self):
        return ((len(self.objects) == 1) and
            (self.objects[0].to_tuple() == NetworkRequest().to_tuple()))

    @property
    def auto_allocate(self):
        return len(self.objects) == 1 and self.objects[0].auto_allocate

    @property
    def no_allocate(self):
        return len(self.objects) == 1 and self.objects[0].no_allocate
