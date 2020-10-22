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
from sqlalchemy import dialects
from sqlalchemy import Enum
from sqlalchemy import Float
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text


def InetSmall():
    return String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql'
    )


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    cell_mappings = Table('cell_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('uuid', String(length=36), nullable=False),
        Column('name', String(length=255)),
        Column('transport_url', Text()),
        Column('database_connection', Text()),
        UniqueConstraint('uuid', name='uniq_cell_mappings0uuid'),
        Index('uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    host_mappings = Table('host_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('cell_id', Integer, nullable=False),
        Column('host', String(length=255), nullable=False),
        UniqueConstraint(
            'host', name='uniq_host_mappings0host'),
        Index('host_idx', 'host'),
        ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=[cell_mappings.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_mappings = Table('instance_mappings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(length=36), nullable=False),
        Column('cell_id', Integer, nullable=True),
        Column('project_id', String(length=255), nullable=False),
        UniqueConstraint(
            'instance_uuid', name='uniq_instance_mappings0instance_uuid'),
        Index('instance_uuid_idx', 'instance_uuid'),
        Index('project_id_idx', 'project_id'),
        ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=[cell_mappings.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

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
        UniqueConstraint('flavorid', name='uniq_flavors0flavorid'),
        UniqueConstraint('name', name='uniq_flavors0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavor_extra_specs = Table('flavor_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, nullable=False),
        Column('key', String(length=255), nullable=False),
        Column('value', String(length=255)),
        UniqueConstraint(
            'flavor_id', 'key', name='uniq_flavor_extra_specs0flavor_id0key'),
        Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        ForeignKeyConstraint(columns=['flavor_id'], refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavor_projects = Table('flavor_projects', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, nullable=False),
        Column('project_id', String(length=255), nullable=False),
        UniqueConstraint(
            'flavor_id', 'project_id',
            name='uniq_flavor_projects0flavor_id0project_id'),
        ForeignKeyConstraint(columns=['flavor_id'],
            refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    request_specs = Table('request_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('instance_uuid', String(36), nullable=False),
        Column('spec', Text, nullable=False),
        UniqueConstraint(
            'instance_uuid', name='uniq_request_specs0instance_uuid'),
        Index('request_spec_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    build_requests = Table('build_requests', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('request_spec_id', Integer, nullable=False),
        Column('project_id', String(length=255), nullable=False),
        Column('user_id', String(length=255), nullable=False),
        Column('display_name', String(length=255)),
        Column('instance_metadata', Text),
        Column('progress', Integer),
        Column('vm_state', String(length=255)),
        Column('task_state', String(length=255)),
        Column('image_ref', String(length=255)),
        Column('access_ip_v4', InetSmall()),
        Column('access_ip_v6', InetSmall()),
        Column('info_cache', Text),
        Column('security_groups', Text, nullable=False),
        Column('config_drive', Boolean, default=False, nullable=False),
        Column('key_name', String(length=255)),
        Column(
            'locked_by',
            Enum('owner', 'admin', name='build_requests0locked_by')),
        UniqueConstraint(
            'request_spec_id', name='uniq_build_requests0request_spec_id'),
        Index('build_requests_project_id_idx', 'project_id'),
        ForeignKeyConstraint(columns=['request_spec_id'],
            refcolumns=[request_specs.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tables = [
        cell_mappings,
        host_mappings,
        instance_mappings,
        flavors,
        flavor_extra_specs,
        flavor_projects,
        request_specs,
        build_requests,
    ]
    for table in tables:
        table.create(checkfirst=True)
