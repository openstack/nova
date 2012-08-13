# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Boolean, Column, DateTime, String, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_types = Table('instance_types', meta, autoload=True)
    is_public = Column('is_public', Boolean)

    instance_types.create_column(is_public)
    instance_types.update().values(is_public=True).execute()

    # New table.
    instance_type_projects = Table('instance_type_projects', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(), default=False),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_type_id',
                Integer,
                ForeignKey('instance_types.id'),
                nullable=False),
        Column('project_id', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
        )

    try:
        instance_type_projects.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(instance_type_projects))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_types = Table('instance_types', meta, autoload=True)
    is_public = Column('is_public', Boolean)

    instance_types.drop_column(is_public)

    instance_type_projects = Table(
            'instance_type_projects', meta, autoload=True)
    instance_type_projects.drop()
