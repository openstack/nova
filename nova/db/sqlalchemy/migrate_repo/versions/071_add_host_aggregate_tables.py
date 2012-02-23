# Copyright (c) 2011 Citrix Systems, Inc.
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

from sqlalchemy import Boolean, String, DateTime, Integer
from sqlalchemy import MetaData, Column, ForeignKey, Table

from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    #
    # New Tables
    #
    aggregates = Table('aggregates', meta,
              Column('created_at', DateTime(timezone=False)),
              Column('updated_at', DateTime(timezone=False)),
              Column('deleted_at', DateTime(timezone=False)),
              Column('deleted', Boolean(create_constraint=True, name=None)),
              Column('id', Integer(),
                     primary_key=True, nullable=False, autoincrement=True),
              Column('name',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False),
                     unique=True),
              Column('operational_state',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False),
                     nullable=False),
              Column('availability_zone',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None,
                            unicode_error=None, _warn_on_bytestring=False),
                     nullable=False),
              )

    hosts = Table('aggregate_hosts', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('host',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False),
                   unique=True),
            Column('aggregate_id', Integer(), ForeignKey('aggregates.id'),
                   nullable=False),
            )

    metadata = Table('aggregate_metadata', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('aggregate_id',
                   Integer(),
                   ForeignKey('aggregates.id'),
                   nullable=False),
            Column('key',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False),
                   nullable=False),
            Column('value',
                   String(length=255, convert_unicode=False,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False),
                   nullable=False))
    tables = (aggregates, hosts, metadata)
    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.exception(repr(table))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    aggregates = Table('aggregates', meta, autoload=True)
    hosts = Table('aggregate_hosts', meta, autoload=True)
    metadata = Table('aggregate_metadata', meta, autoload=True)
    # table order matters, don't change
    for table in (hosts, metadata, aggregates):
        try:
            table.drop()
        except Exception:
            LOG.exception(repr(table))
