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

from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class VirtCPUTopology(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'sockets': fields.IntegerField(nullable=True, default=1),
        'cores': fields.IntegerField(nullable=True, default=1),
        'threads': fields.IntegerField(nullable=True, default=1),
        }

    # NOTE(jaypipes): for backward compatibility, the virt CPU topology
    # data is stored in the database as a nested dict.
    @classmethod
    def from_dict(cls, data):
        return cls(sockets=data.get('sockets'),
                   cores=data.get('cores'),
                   threads=data.get('threads'))

    def to_dict(self):
        return {
            'sockets': self.sockets,
            'cores': self.cores,
            'threads': self.threads
        }
