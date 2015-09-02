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

EVENT_NAMES = [
    # Network has changed for this instance, rebuild info_cache
    'network-changed',

    # VIF plugging notifications, tag is port_id
    'network-vif-plugged',
    'network-vif-unplugged',
    'network-vif-deleted',

]

EVENT_STATUSES = ['failed', 'completed', 'in-progress']


@obj_base.NovaObjectRegistry.register
class InstanceExternalEvent(obj_base.NovaObject):
    # Version 1.0: Initial version
    #              Supports network-changed and vif-plugged
    # Version 1.1: adds network-vif-deleted event
    VERSION = '1.1'

    fields = {
        'instance_uuid': fields.UUIDField(),
        'name': fields.EnumField(valid_values=EVENT_NAMES),
        'status': fields.EnumField(valid_values=EVENT_STATUSES),
        'tag': fields.StringField(nullable=True),
        'data': fields.DictOfStringsField(),
        }

    @staticmethod
    def make_key(name, tag=None):
        if tag is not None:
            return '%s-%s' % (name, tag)
        else:
            return name

    @property
    def key(self):
        return self.make_key(self.name, self.tag)
