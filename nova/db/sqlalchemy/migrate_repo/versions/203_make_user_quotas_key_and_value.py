# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack LLC.
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

from sqlalchemy import Column, DateTime, Integer
from sqlalchemy import Index, UniqueConstraint, MetaData, String, Table

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import utils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # Add 'user_id' column to quota_usages table and its shadow table.
    quota_usages = utils.get_table(migrate_engine, 'quota_usages')
    user_id = Column('user_id',
                     String(length=255))
    quota_usages.create_column(user_id)

    shadow_quota_usages = utils.get_table(migrate_engine,
                                db._SHADOW_TABLE_PREFIX + 'quota_usages')
    user_id = Column('user_id',
                     String(length=255))
    shadow_quota_usages.create_column(user_id)

    # Add 'user_id' column to reservations table and its shadow table.
    reservations = utils.get_table(migrate_engine, 'reservations')
    user_id = Column('user_id',
                     String(length=255))
    reservations.create_column(user_id)

    shadow_reservations = utils.get_table(migrate_engine,
                                db._SHADOW_TABLE_PREFIX + 'reservations')
    user_id = Column('user_id',
                     String(length=255))
    shadow_reservations.create_column(user_id)

    if migrate_engine.name == 'mysql' or migrate_engine.name == 'postgresql':
        indexes = [
            Index('ix_quota_usages_user_id_deleted',
                  quota_usages.c.user_id, quota_usages.c.deleted),
            Index('ix_reservations_user_id_deleted',
                  reservations.c.user_id, reservations.c.deleted)
        ]
        for index in indexes:
            index.create(migrate_engine)

    uniq_name = "uniq_project_user_quotas0user_id0project_id0resource0deleted"
    project_user_quotas = Table('project_user_quotas', meta,
                        Column('id', Integer, primary_key=True,
                               nullable=False),
                        Column('created_at', DateTime),
                        Column('updated_at', DateTime),
                        Column('deleted_at', DateTime),
                        Column('deleted', Integer),
                        Column('user_id',
                               String(length=255),
                               nullable=False),
                        Column('project_id',
                               String(length=255),
                               nullable=False),
                        Column('resource',
                               String(length=25),
                               nullable=False),
                        Column('hard_limit', Integer, nullable=True),
                        UniqueConstraint('user_id', 'project_id', 'resource',
                                         'deleted', name=uniq_name),
                        Index('project_user_quotas_project_id_deleted_idx',
                              'project_id', 'deleted'),
                        Index('project_user_quotas_user_id_deleted_idx',
                              'project_id', 'deleted'),
                        mysql_engine='InnoDB',
                        mysql_charset='utf8',
                        )

    try:
        project_user_quotas.create()
        utils.create_shadow_table(migrate_engine, table=project_user_quotas)
    except Exception:
        LOG.exception("Exception while creating table 'project_user_quotas'")
        meta.drop_all(tables=[project_user_quotas])
        raise


def downgrade(migrate_engine):
    quota_usages = utils.get_table(migrate_engine, 'quota_usages')
    reservations = utils.get_table(migrate_engine, 'reservations')

    if migrate_engine.name == 'mysql' or migrate_engine.name == 'postgresql':
        # Remove the indexes first
        indexes = [
            Index('ix_quota_usages_user_id_deleted',
                quota_usages.c.user_id, quota_usages.c.deleted),
            Index('ix_reservations_user_id_deleted',
                reservations.c.user_id, reservations.c.deleted)
        ]
        for index in indexes:
            index.drop(migrate_engine)

    quota_usages.drop_column('user_id')
    shadow_quota_usages = utils.get_table(migrate_engine,
                                db._SHADOW_TABLE_PREFIX + 'quota_usages')
    shadow_quota_usages.drop_column('user_id')

    reservations.drop_column('user_id')
    shadow_reservations = utils.get_table(migrate_engine,
                                db._SHADOW_TABLE_PREFIX + 'reservations')
    shadow_reservations.drop_column('user_id')

    project_user_quotas = utils.get_table(migrate_engine,
                                          'project_user_quotas')
    try:
        project_user_quotas.drop()
    except Exception:
        LOG.error(_("project_user_quotas table not dropped"))
        raise

    shadow_table_name = db._SHADOW_TABLE_PREFIX + 'project_user_quotas'
    shadow_table = utils.get_table(migrate_engine, shadow_table_name)
    try:
        shadow_table.drop()
    except Exception:
        LOG.error(_("%s table not dropped") % shadow_table_name)
        raise
