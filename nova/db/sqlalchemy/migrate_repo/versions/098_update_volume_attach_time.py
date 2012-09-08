# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2012 Canonical Ltd.
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

from sqlalchemy import select, Column, Table, MetaData, String, DateTime


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    attach_datetime = Column('attachtime_datetime', DateTime(timezone=False))
    attach_datetime.create(volumes)

    old_attachtime = volumes.c.attach_time

    try:
        volumes_list = list(volumes.select().execute())
        for v in volumes_list:
            attach_time = select([volumes.c.attach_time],
                volumes.c.id == v['id']).execute().fetchone()[0]
            volumes.update().\
                where(volumes.c.id == v['id']).\
                values(attachtime_datetime=attach_time).execute()
    except Exception:
        attach_datetime.drop()
        raise

    old_attachtime.alter(name='attach_time_old')
    attach_datetime.alter(name='attach_time')
    old_attachtime.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    attach_string = Column('attachtime_string', String(255))
    attach_string.create(volumes)

    old_attachtime = volumes.c.attach_time

    try:
        volumes_list = list(volumes.select().execute())
        for v in volumes_list:
            attach_time = select([volumes.c.attach_time],
                volumes.c.id == v['id']).execute().fetchone()[0]
            volumes.update().\
                where(volumes.c.id == v['id']).\
                values(attachtime_string=attach_time).execute()
    except Exception:
        attach_string.drop()
        raise

    old_attachtime.alter(name='attach_time_old')
    attach_string.alter(name='attach_time')
    old_attachtime.drop()
