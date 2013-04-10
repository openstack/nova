# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_actions = Table('instance_actions', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('action', String(length=255)),
        Column('instance_uuid', String(length=36)),
        Column('request_id', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('start_time', DateTime),
        Column('finish_time', DateTime),
        Column('message', String(length=255)),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_actions_events = Table('instance_actions_events', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('event', String(length=255)),
        Column('action_id', Integer, ForeignKey('instance_actions.id')),
        Column('start_time', DateTime),
        Column('finish_time', DateTime),
        Column('result', String(length=255)),
        Column('traceback', Text),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    instance_actions.create()
    instance_actions_events.create()

    Index('instance_uuid_idx',
          instance_actions.c.instance_uuid).create(migrate_engine)
    Index('request_id_idx',
          instance_actions.c.request_id).create(migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_actions_events = Table('instance_actions_events', meta,
                                    autoload=True)
    instance_actions_events.drop()

    instance_actions = Table('instance_actions', meta, autoload=True)
    instance_actions.drop()
