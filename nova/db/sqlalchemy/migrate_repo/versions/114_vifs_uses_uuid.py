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
    virtual_interfaces = Table('virtual_interfaces', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)
    uuid_column = Column('instance_uuid', String(36))
    uuid_column.create(virtual_interfaces)

    try:
        virtual_interfaces.update().values(
            instance_uuid=select(
                [instances.c.uuid],
                instances.c.id == virtual_interfaces.c.instance_id)
        ).execute()
    except Exception:
        uuid_column.drop()
        raise

    fkeys = list(virtual_interfaces.c.instance_id.foreign_keys)
    if fkeys:
        try:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[virtual_interfaces.c.instance_id],
                refcolumns=[instances.c.id],
                name=fkey_name).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be removed"))
            raise

    virtual_interfaces.c.instance_id.drop()

    try:
        ForeignKeyConstraint(
            columns=[virtual_interfaces.c.instance_uuid],
            refcolumns=[instances.c.uuid]).create()
    except Exception:
        LOG.error(_("foreign key constraint couldn't be created"))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    virtual_interfaces = Table('virtual_interfaces', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)
    id_column = Column('instance_id', Integer, ForeignKey('instances.id'))
    id_column.create(virtual_interfaces)

    fkeys = list(virtual_interfaces.c.instance_uuid.foreign_keys)
    if fkeys:
        try:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[virtual_interfaces.c.instance_uuid],
                refcolumns=[instances.c.uuid],
                name=fkey_name).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be removed"))
            raise

    try:
        virtual_interfaces.update().values(
            instance_id=select(
                [instances.c.id],
                instances.c.uuid == virtual_interfaces.c.instance_uuid)
        ).execute()
    except Exception:
        id_column.drop()
        raise

    virtual_interfaces.c.instance_uuid.drop()

    try:
        ForeignKeyConstraint(
            columns=[virtual_interfaces.c.instance_id],
            refcolumns=[instances.c.id]).create()
    except Exception:
        LOG.error(_("foreign key constraint couldn't be created"))
        raise
