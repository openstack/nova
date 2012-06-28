# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2012 Michael Still and Canonical Inc
# All Rights Reserved.
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

from migrate import ForeignKeyConstraint
from sqlalchemy import MetaData, String, Table
from sqlalchemy import select, Column, ForeignKey, Integer

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instance_metadata = Table('instance_metadata', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)
    uuid_column = Column('instance_uuid', String(36))
    uuid_column.create(instance_metadata)

    try:
        instance_metadata.update().values(
            instance_uuid=select(
                [instances.c.uuid],
                instances.c.id == instance_metadata.c.instance_id)
        ).execute()
    except Exception:
        uuid_column.drop()
        raise

    fkeys = list(instance_metadata.c.instance_id.foreign_keys)
    if fkeys:
        try:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[instance_metadata.c.instance_id],
                refcolumns=[instances.c.id],
                name=fkey_name).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be removed"))
            raise

    instance_metadata.c.instance_id.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instance_metadata = Table('instance_metadata', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)
    id_column = Column('instance_id', Integer, ForeignKey('instances.id'))
    id_column.create(instance_metadata)

    try:
        instance_metadata.update().values(
            instance_id=select(
                [instances.c.id],
                instances.c.uuid == instance_metadata.c.instance_uuid)
        ).execute()
    except Exception:
        id_column.drop()
        raise

    instance_metadata.c.instance_uuid.drop()
