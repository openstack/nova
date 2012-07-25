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

import datetime
from sqlalchemy import MetaData, Table
from sqlalchemy import and_, between


TABLES = ('instance_metadata',
          'instance_system_metadata',
          'block_device_mapping')


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)

    instance_list = list(instances.select().\
                        where(instances.c.deleted == True).execute())
    for table_name in TABLES:
        table = Table(table_name, meta, autoload=True)

        for instance in instance_list:
            if not instance['deleted_at']:
                continue
            table.update(
                (and_(table.c.deleted == True,
                      table.c.instance_uuid == instance['uuid'],
                      between(table.c.deleted_at,
                      instance['deleted_at'] - datetime.timedelta(seconds=2),
                      instance['deleted_at'] + datetime.timedelta(seconds=2)))
                ),
                {table.c.deleted: False,
                 table.c.deleted_at: None}
            ).execute()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)

    instance_list = list(instances.select().\
                        where(instances.c.deleted == True).execute())
    for table_name in TABLES:
        table = Table(table_name, meta, autoload=True)
        for instance in instance_list:
            table.update(
                (and_(table.c.deleted == False,
                      table.c.instance_uuid == instance['uuid'])
                ),
                {table.c.deleted: True,
                 table.c.deleted_at: instance['deleted_at']}
            ).execute()
