# Copyright (c) 2015 Umea University
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
from nova.objects import base
from nova.objects import fields


class FaultToleranceRelation(base.NovaPersistentObject, base.NovaObject):
    """Object representing a primary/secondary relation between instances."""

    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'primary_instance_uuid': fields.UUIDField(),
        'secondary_instance_uuid': fields.UUIDField(),
        }

    def __str__(self):
        return "[FaultToleranceRelation: Primary instance: %s, "\
                "Secondary instance: %s]" % (self.primary_instance_uuid,
                                             self.secondary_instance_uuid)

    def __contains__(self, instance_uuid):
        return instance_uuid in (self.primary_instance_uuid,
                                 self.secondary_instance_uuid)

    def get_counterpart(self, uuid):
        if uuid == self.primary_instance_uuid:
            return self.secondary_instance_uuid
        elif uuid == self.secondary_instance_uuid:
            return self.primary_instance_uuid
        else:
            raise AttributeError("UUID '%s' not in relation %s.", uuid, self)

    @staticmethod
    def _from_db_object(context, ft_relation, db_relation):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """

        for field in ft_relation.fields:
            ft_relation[field] = db_relation[field]
        ft_relation._context = context
        ft_relation.obj_reset_changes()

        return ft_relation

    @base.remotable_classmethod
    def get_by_uuids(cls, context, primary_instance_uuid,
                     secondary_instance_uuid):
        """Get a relation between a specific pair of instances.

        Raises FaultToleranceRelationNotFound if the relation does not exist.
        """

        db_relation = db.ft_relation_get_by_uuids(context,
                                                  primary_instance_uuid,
                                                  secondary_instance_uuid)

        return cls._from_db_object(context, cls(), db_relation)

    @base.remotable_classmethod
    def get_by_secondary_instance_uuid(cls, context, instance_uuid):
        """Get a relation where the secondary instance is the provided UUID.

        :raises: FaultToleranceRelationBySecondaryNotFound
        """
        db_relation = db.ft_relation_get_by_secondary_instance_uuid(
                context, instance_uuid)

        return cls._from_db_object(context, cls(), db_relation)

    @base.remotable
    def create(self, context):
        """Create this fault tolerance relation object."""
        updates = self.obj_get_changes()
        db_relation = db.ft_relation_create(context, updates)
        self._from_db_object(context, self, db_relation)

    @base.remotable
    def destroy(self, context):
        """Delete this fault tolerance relation object."""
        db.ft_relation_destroy(context, self.primary_instance_uuid,
                               self.secondary_instance_uuid)


class FaultToleranceRelationList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('FaultToleranceRelation'),
        }

    child_versions = {
        '1.0': '1.0',
        }

    def __init__(self):
        super(FaultToleranceRelationList, self).__init__()
        self.objects = []
        self.obj_reset_changes()

    @base.remotable_classmethod
    def get_by_primary_instance_uuid(cls, context, instance_uuid):
        """Get all relations where the primary instance is the provided UUID.

        :raises: FaultToleranceRelationByPrimaryNotFound
        """
        db_relations = db.ft_relation_get_by_primary_instance_uuid(
            context, instance_uuid)

        return base.obj_make_list(context, FaultToleranceRelationList(),
                                  FaultToleranceRelation, db_relations)

    @base.remotable_classmethod
    def get_by_instance_uuids(cls, context, instance_uuids):
        """Get all relations where the the provided UUID is included."""
        db_relations = db.ft_relation_get_by_instance_uuids(context,
                                                            instance_uuids)

        return base.obj_make_list(context, FaultToleranceRelationList(),
                                  FaultToleranceRelation, db_relations)
