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

import logging
from nova.db.main import api as db
from nova import exception
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class ShareMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'uuid': fields.UUIDField(nullable=False),
        'instance_uuid': fields.UUIDField(nullable=False),
        'share_id': fields.UUIDField(nullable=False),
        'status': fields.ShareMappingStatusField(),
        'tag': fields.StringField(nullable=False),
        'export_location': fields.StringField(nullable=False),
        'share_proto': fields.ShareMappingProtoField()
    }

    @staticmethod
    def _from_db_object(context, share_mapping, db_share_mapping):
        for field in share_mapping.fields:
            setattr(share_mapping, field, db_share_mapping[field])
        share_mapping._context = context
        share_mapping.obj_reset_changes()
        return share_mapping

    @base.remotable
    def save(self):
        db_share_mapping = db.share_mapping_update(
            self._context, self.uuid, self.instance_uuid, self.share_id,
            self.status, self.tag, self.export_location, self.share_proto)
        self._from_db_object(self._context, self, db_share_mapping)

    def create(self):
        LOG.info(
            "Associate share '%s' to instance '%s'.",
            self.share_id, self.instance_uuid)

        self.save()

    @base.remotable
    def delete(self):
        LOG.info(
            "Dissociate share '%s' from instance '%s'.",
            self.share_id,
            self.instance_uuid,
        )
        db.share_mapping_delete_by_instance_uuid_and_share_id(
            self._context, self.instance_uuid, self.share_id
        )

    def attach(self):
        LOG.info(
            "Share '%s' about to be attached to instance '%s'.",
            self.share_id, self.instance_uuid)

        self.status = fields.ShareMappingStatus.ACTIVE
        self.save()

    def detach(self):
        LOG.info(
            "Share '%s' about to be detached from instance '%s'.",
            self.share_id,
            self.instance_uuid,
        )
        self.status = fields.ShareMappingStatus.INACTIVE
        self.save()

    @base.remotable_classmethod
    def get_by_instance_uuid_and_share_id(
            cls, context, instance_uuid, share_id):
        """This query returns only one element as a share can be
        associated only one time to an instance.
        Note: the REST API prevent the user to create duplicate share
        mapping by raising an exception.ShareMappingAlreadyExists.
        """
        share_mapping = ShareMapping(context)
        db_share_mapping = db.share_mapping_get_by_instance_uuid_and_share_id(
            context, instance_uuid, share_id)
        if not db_share_mapping:
            raise exception.ShareNotFound(share_id=share_id)
        return ShareMapping._from_db_object(
                context,
                share_mapping,
                db_share_mapping)

    def get_share_host_provider(self):
        if not self.export_location:
            return None
        if self.share_proto == 'NFS':
            rhost, _ = self.export_location.strip().split(':')
        else:
            raise NotImplementedError()
        return rhost


@base.NovaObjectRegistry.register
class ShareMappingList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('ShareMapping'),
    }

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_share_mappings = db.share_mapping_get_by_instance_uuid(
            context, instance_uuid)
        return base.obj_make_list(
            context, cls(context), ShareMapping, db_share_mappings)

    @base.remotable_classmethod
    def get_by_share_id(cls, context, share_id):
        db_share_mappings = db.share_mapping_get_by_share_id(
            context, share_id)
        return base.obj_make_list(
            context, cls(context), ShareMapping, db_share_mappings)

    def attach_all(self):
        for share in self:
            share.attach()

    def detach_all(self):
        for share in self:
            share.detach()
