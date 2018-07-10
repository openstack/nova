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
class TrustedCerts(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'ids': fields.ListOfStringsField(nullable=False),
    }

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['trusted_certs'])
        if not db_extra or not db_extra['trusted_certs']:
            return None
        return cls.obj_from_primitive(
            jsonutils.loads(db_extra['trusted_certs']))
