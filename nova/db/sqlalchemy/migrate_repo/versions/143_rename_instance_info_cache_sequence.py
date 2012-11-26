# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table


OLD_MYSQL_NAME = 'instance_id'
NEW_MYSQL_NAME = 'instance_uuid'

OLD_PG_NAME = 'instance_info_caches_instance_id_key'
NEW_PG_NAME = 'instance_info_caches_instance_uuid_key'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # NOTE(dprince): Rename the unique key constraints for both MySQL
    # and PostgreSQL so they reflect the most recent UUID conversions
    # from Folsom.
    instance_info_caches = Table('instance_info_caches', meta, autoload=True)

    if migrate_engine.name == "mysql":
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=NEW_MYSQL_NAME).create()
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=OLD_MYSQL_NAME).drop()
    if migrate_engine.name == "postgresql":
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=NEW_PG_NAME).create()
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=OLD_PG_NAME).drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_info_caches = Table('instance_info_caches', meta, autoload=True)

    if migrate_engine.name == "mysql":
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=OLD_MYSQL_NAME).create()
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=NEW_MYSQL_NAME).drop()
    if migrate_engine.name == "postgresql":
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=OLD_PG_NAME).create()
        UniqueConstraint('instance_uuid', table=instance_info_caches,
                         name=NEW_PG_NAME).drop()
