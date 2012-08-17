# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2012 SINA Corp.
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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # create new table
    task_log = Table('task_log', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted',
                    Boolean(create_constraint=True, name=None)),
            Column('id', Integer(),
                    primary_key=True,
                    nullable=False,
                    autoincrement=True),
            Column('task_name', String(255), nullable=False),
            Column('state', String(255), nullable=False),
            Column('host', String(255), index=True, nullable=False),
            Column('period_beginning', String(255),
                                       index=True, nullable=False),
            Column('period_ending', String(255), index=True, nullable=False),
            Column('message', String(255), nullable=False),
            Column('task_items', Integer()),
            Column('errors', Integer()),
            )
    try:
        task_log.create()
    except Exception:
        meta.drop_all(tables=[task_log])
        raise

    if migrate_engine.name == "mysql":
        migrate_engine.execute("ALTER TABLE task_log "
                "Engine=InnoDB")


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    task_log = Table('task_log', meta, autoload=True)
    task_log.drop()
