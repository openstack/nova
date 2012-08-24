# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Index, MetaData, Table
from sqlalchemy.exc import IntegrityError


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('block_device_mapping', meta, autoload=True)

    # Based on block_device_mapping_update_or_create
    # from: nova/db/sqlalchemy/api.py
    i = Index('block_device_mapping_instance_uuid_device_name_idx',
              t.c.instance_uuid, t.c.device_name)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on block_device_mapping_update_or_create
    # from: nova/db/sqlalchemy/api.py
    i = Index(
            'block_device_mapping_instance_uuid_virtual_name_device_name_idx',
            t.c.instance_uuid, t.c.virtual_name, t.c.device_name)
    i.create(migrate_engine)

    # Based on block_device_mapping_destroy_by_instance_and_volume
    # from: nova/db/sqlalchemy/api.py
    i = Index('block_device_mapping_instance_uuid_volume_id_idx',
              t.c.instance_uuid, t.c.volume_id)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('block_device_mapping', meta, autoload=True)

    i = Index('block_device_mapping_instance_uuid_device_name_idx',
              t.c.instance_uuid, t.c.device_name)
    i.drop(migrate_engine)

    i = Index(
            'block_device_mapping_instance_uuid_virtual_name_device_name_idx',
            t.c.instance_uuid, t.c.virtual_name, t.c.device_name)
    i.drop(migrate_engine)

    i = Index('block_device_mapping_instance_uuid_volume_id_idx',
              t.c.instance_uuid, t.c.volume_id)
    i.drop(migrate_engine)
