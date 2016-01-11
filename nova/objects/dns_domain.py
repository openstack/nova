# Copyright (C) 2014, Red Hat, Inc.
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

from nova import db
from nova import objects
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class DNSDomain(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'domain': fields.StringField(),
        'scope': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),
    }

    @staticmethod
    def _from_db_object(context, vif, db_vif):
        for field in vif.fields:
            setattr(vif, field, db_vif[field])
        vif._context = context
        vif.obj_reset_changes()
        return vif

    @base.remotable_classmethod
    def get_by_domain(cls, context, domain):
        db_dnsd = db.dnsdomain_get(context, domain)
        if db_dnsd:
            return cls._from_db_object(context, cls(), db_dnsd)

    @base.remotable_classmethod
    def register_for_zone(cls, context, domain, zone):
        db.dnsdomain_register_for_zone(context, domain, zone)

    @base.remotable_classmethod
    def register_for_project(cls, context, domain, project):
        db.dnsdomain_register_for_project(context, domain, project)

    @base.remotable_classmethod
    def delete_by_domain(cls, context, domain):
        db.dnsdomain_unregister(context, domain)


@base.NovaObjectRegistry.register
class DNSDomainList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('DNSDomain'),
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        db_domains = db.dnsdomain_get_all(context)
        return base.obj_make_list(context, cls(context), objects.DNSDomain,
                                  db_domains)
