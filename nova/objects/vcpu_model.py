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

from oslo.serialization import jsonutils

from nova.compute import arch
from nova.compute import cpumodel
from nova import db
from nova.objects import base
from nova.objects import fields


class VirtCPUModel(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'arch': fields.EnumField(nullable=True,
                                 valid_values=arch.ALL),
        'vendor': fields.StringField(nullable=True),
        'topology': fields.ObjectField('VirtCPUTopology',
                                       nullable=True),
        'features': fields.ListOfObjectsField("VirtCPUFeature",
                                              default=[]),
        'mode': fields.EnumField(nullable=True,
                                 valid_values=cpumodel.ALL_CPUMODES),
        'model': fields.StringField(nullable=True),
        'match': fields.EnumField(nullable=True,
                                  valid_values=cpumodel.ALL_MATCHES),
    }

    obj_relationships = {
        'topology': [('1.0', '1.0')],
        'features': [('1.0', '1.0')],
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


class VirtCPUFeature(base.NovaObject):
    VERSION = VirtCPUModel.VERSION

    fields = {
        'policy': fields.EnumField(nullable=True,
                                   valid_values=cpumodel.ALL_POLICIES),
        'name': fields.StringField(nullable=False),
    }

    def obj_load_attr(self, attrname):
        setattr(self, attrname, None)
