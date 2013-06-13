# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Svetlana Shturm (sshturm@mirantis.com).
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String, Table

from nova.db.sqlalchemy import utils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    meta.bind = migrate_engine

    tables = [
        'sm_volume',
        'sm_backend_config',
        'sm_flavors',
        'virtual_storage_arrays',
        'volume_metadata',
        'volume_type_extra_specs',
        'volume_types']
    for TABLE_NAME in tables:
        t = Table(TABLE_NAME, meta, autoload=True)
        t_shadow = Table('shadow_' + TABLE_NAME, meta, autoload=True)
        t.drop()
        t_shadow.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    sm_backend_config = Table('sm_backend_config', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('flavor_id', Integer, ForeignKey('sm_flavors.id'),
               nullable=False),
        Column('sr_uuid', String(length=255)),
        Column('sr_type', String(length=255)),
        Column('config_params', String(length=2047)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_flavors = Table('sm_flavors', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('label', String(length=255)),
        Column('description', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    sm_volume = Table('sm_volume', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=36), primary_key=True,
                  nullable=False, autoincrement=False),
        Column('backend_id', Integer, ForeignKey('sm_backend_config.id'),
               nullable=False),
        Column('vdi_uuid', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    virtual_storage_arrays = Table('virtual_storage_arrays', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('project_id', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('instance_type_id', Integer, nullable=False),
        Column('image_ref', String(length=255)),
        Column('vc_count', Integer, nullable=False),
        Column('vol_count', Integer, nullable=False),
        Column('status', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volumes = Table('volumes', meta, autoload=True)

    volume_metadata = Table('volume_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_id', String(length=36), ForeignKey('volumes.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_type_extra_specs = Table('volume_type_extra_specs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('volume_type_id', Integer, ForeignKey('volume_types.id'),
               nullable=False),
        Column('key', String(length=255)),
        Column('value', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    volume_types = Table('volume_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('name', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    tables = [
        sm_flavors,
        sm_backend_config,
        sm_volume,
        virtual_storage_arrays,
        volume_metadata,
        volume_types,
        volume_type_extra_specs]

    for table in tables:
        try:
            table.create()
            utils.create_shadow_table(migrate_engine, table.name)
        except Exception:
            LOG.info(repr(table))
            LOG.exception(_('Exception while creating table.'))
            raise
