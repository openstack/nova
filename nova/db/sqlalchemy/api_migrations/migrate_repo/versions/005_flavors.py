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

from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    flavors = Table('flavors', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('name', String(length=255), nullable=False),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('memory_mb', Integer, nullable=False),
        Column('vcpus', Integer, nullable=False),
        Column('swap', Integer, nullable=False),
        Column('vcpu_weight', Integer),
        Column('flavorid', String(length=255), nullable=False),
        Column('rxtx_factor', Float),
        Column('root_gb', Integer),
        Column('ephemeral_gb', Integer),
        Column('disabled', Boolean),
        Column('is_public', Boolean),
        UniqueConstraint("flavorid", name="uniq_flavors0flavorid"),
        UniqueConstraint("name", name="uniq_flavors0name"),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    flavors.create(checkfirst=True)

    flavor_extra_specs = Table('flavor_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255)),
        UniqueConstraint('flavor_id', 'key',
            name='uniq_flavor_extra_specs0flavor_id0key'),
        Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        ForeignKeyConstraint(columns=['flavor_id'], refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavor_extra_specs.create(checkfirst=True)

    flavor_projects = Table('flavor_projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, nullable=False),
        Column('project_id', String(length=255), nullable=False),
        UniqueConstraint('flavor_id', 'project_id',
            name='uniq_flavor_projects0flavor_id0project_id'),
        ForeignKeyConstraint(columns=['flavor_id'],
            refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )
    flavor_projects.create(checkfirst=True)
