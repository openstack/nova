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

from oslo_serialization import jsonutils

from nova.db import api as db
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class VirtCPUModel(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'arch': fields.ArchitectureField(nullable=True),
        'vendor': fields.StringField(nullable=True),
        'topology': fields.ObjectField('VirtCPUTopology',
                                       nullable=True),
        'features': fields.ListOfObjectsField("VirtCPUFeature",
                                              default=[]),
        'mode': fields.CPUModeField(nullable=True),
        'model': fields.StringField(nullable=True),
        'match': fields.CPUMatchField(nullable=True),
    }

    def obj_load_attr(self, attrname):
        setattr(self, attrname, None)

    def to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())

    @classmethod
    def from_json(cls, jsonstr):
        return cls.obj_from_primitive(jsonutils.loads(jsonstr))

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['vcpu_model'])
        if not db_extra or not db_extra['vcpu_model']:
            return None
        return cls.obj_from_primitive(jsonutils.loads(db_extra['vcpu_model']))


@base.NovaObjectRegistry.register
class VirtCPUFeature(base.NovaObject):
    VERSION = '1.0'

    fields = {
        'policy': fields.CPUFeaturePolicyField(nullable=True),
        'name': fields.StringField(nullable=False),
    }

    def obj_load_attr(self, attrname):
        setattr(self, attrname, None)
