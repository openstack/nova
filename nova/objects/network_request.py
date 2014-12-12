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

from nova.objects import base as obj_base
from nova.objects import fields
from nova import utils


# TODO(berrange): Remove NovaObjectDictCompat
class NetworkRequest(obj_base.NovaObject,
                     obj_base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added pci_request_id
    VERSION = '1.1'
    fields = {
        'network_id': fields.StringField(nullable=True),
        'address': fields.IPAddressField(nullable=True),
        'port_id': fields.UUIDField(nullable=True),
        'pci_request_id': fields.UUIDField(nullable=True),
    }

    def obj_load_attr(self, attr):
        setattr(self, attr, None)

    def to_tuple(self):
        address = str(self.address) if self.address is not None else None
        if utils.is_neutron():
            return self.network_id, address, self.port_id, self.pci_request_id
        else:
            return self.network_id, address

    @classmethod
    def from_tuple(cls, net_tuple):
        if len(net_tuple) == 4:
            network_id, address, port_id, pci_request_id = net_tuple
            return cls(network_id=network_id, address=address,
                       port_id=port_id, pci_request_id=pci_request_id)
        elif len(net_tuple) == 3:
            # NOTE(alex_xu): This is only for compatible with icehouse , and
            # should be removed in the next cycle.
            network_id, address, port_id = net_tuple
            return cls(network_id=network_id, address=address,
                       port_id=port_id)
        else:
            network_id, address = net_tuple
            return cls(network_id=network_id, address=address)


class NetworkRequestList(obj_base.ObjectListBase, obj_base.NovaObject):
    fields = {
        'objects': fields.ListOfObjectsField('NetworkRequest'),
        }

    child_versions = {
        '1.0': '1.0',
        '1.1': '1.1',
        }
    VERSION = '1.1'

    def as_tuples(self):
        return [x.to_tuple() for x in self.objects]

    @property
    def is_single_unspecified(self):
        return ((len(self.objects) == 1) and
            (self.objects[0].to_tuple() == NetworkRequest().to_tuple()))
