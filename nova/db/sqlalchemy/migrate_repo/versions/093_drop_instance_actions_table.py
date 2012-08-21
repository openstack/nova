# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack, LLC.
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
from sqlalchemy import Integer, MetaData, String, Table, Text


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instance_actions = Table('instance_actions', meta, autoload=True)
    instance_actions.drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True,
                      autoload_with=migrate_engine)

    instance_actions = Table('instance_actions', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('instance_id',
                   Integer(),
                   ForeignKey('instances.id')),
            Column('action',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            Column('error',
                   Text(length=None, convert_unicode=False,
                        assert_unicode=None,
                        unicode_error=None, _warn_on_bytestring=False)),
            )
    instance_actions.create()
