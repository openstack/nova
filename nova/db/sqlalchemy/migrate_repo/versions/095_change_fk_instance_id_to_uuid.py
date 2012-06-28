# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
# Copyright 2012 SolidFire Inc
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
from sqlalchemy import MetaData, Integer, String, Table
from sqlalchemy import select, Column

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    volumes = Table('volumes', meta, autoload=True)
    instance_uuid_column = Column('instance_uuid', String(36))

    instance_uuid_column.create(volumes)
    try:
        volumes.update().values(
            instance_uuid=select(
                [instances.c.uuid],
                instances.c.id == volumes.c.instance_id)
                ).execute()
    except Exception:
        instance_uuid_column.drop()

    fkeys = list(volumes.c.instance_id.foreign_keys)
    if fkeys:
        try:
            fk_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[volumes.c.instance_id],
                refcolumns=[instances.c.id],
                name=fk_name).drop()

        except Exception:
            LOG.error(_("foreign key could not be dropped"))
            raise

    volumes.c.instance_id.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)
    volumes = Table('volumes', meta, autoload=True)
    instance_id_column = Column('instance_id', Integer)

    instance_id_column.create(volumes)
    try:
        volumes.update().values(
            instance_id=select(
                [instances.c.id],
                instances.c.uuid == volumes.c.instance_uuid)
                ).execute()
    except Exception:
        instance_id_column.drop()

    fkeys = list(volumes.c.instance_id.foreign_keys)
    if fkeys:
        try:
            fk_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[volumes.c.instance_id],
                refcolumns=[instances.c.id],
                name=fk_name).create()

        except Exception:
            LOG.error(_("foreign key could not be created"))
            raise

    volumes.c.instance_uuid.drop()
