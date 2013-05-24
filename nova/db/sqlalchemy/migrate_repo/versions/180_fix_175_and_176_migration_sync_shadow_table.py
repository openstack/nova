# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Mirantis, Inc.
# Copyright 2013 OpenStack Foundation
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
#
# @author: Boris Pavlovic, Mirantis Inc

from sqlalchemy import MetaData, Integer, String, Table, Column


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    shadow_volume_usage_cache = Table('shadow_volume_usage_cache', meta,
                                      autoload=True)
    # fix for 175 migration
    shadow_volume_usage_cache.drop_column('instance_id')

    instance_id = Column('instance_uuid', String(36))
    project_id = Column('project_id', String(36))
    user_id = Column('user_id', String(36))

    shadow_volume_usage_cache.create_column(instance_id)
    shadow_volume_usage_cache.create_column(project_id)
    shadow_volume_usage_cache.create_column(user_id)

    # fix for 176 migration
    availability_zone = Column('availability_zone', String(255))
    shadow_volume_usage_cache.create_column(availability_zone)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    shadow_volume_usage_cache = Table('shadow_volume_usage_cache', meta,
                                      autoload=True)

    # fix for 175 migration
    shadow_volume_usage_cache.drop_column('instance_uuid')
    shadow_volume_usage_cache.drop_column('user_id')
    shadow_volume_usage_cache.drop_column('project_id')

    instance_id = Column('instance_id', Integer)
    shadow_volume_usage_cache.create_column(instance_id)

    # fix for 176 migration
    shadow_volume_usage_cache.drop_column('availability_zone')
