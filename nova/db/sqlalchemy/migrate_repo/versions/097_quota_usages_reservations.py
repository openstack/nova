# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Boolean, Column, DateTime
from sqlalchemy import MetaData, Integer, String, Table, ForeignKey

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # New tables
    quota_usages = Table('quota_usages', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True),
            Column('project_id',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False),
                   index=True),
            Column('resource',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False)),
            Column('in_use', Integer(), nullable=False),
            Column('reserved', Integer(), nullable=False),
            Column('until_refresh', Integer(), nullable=True),
            mysql_engine='InnoDB',
            mysql_charset='utf8',
            )

    try:
        quota_usages.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(quota_usages))
        raise

    reservations = Table('reservations', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True),
            Column('uuid',
                   String(length=36, convert_unicode=True,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False), nullable=False),
            Column('usage_id', Integer(), ForeignKey('quota_usages.id'),
                   nullable=False),
            Column('project_id',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False),
                   index=True),
            Column('resource',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None, unicode_error=None,
                          _warn_on_bytestring=False)),
            Column('delta', Integer(), nullable=False),
            Column('expire', DateTime(timezone=False)),
            mysql_engine='InnoDB',
            mysql_charset='utf8',
            )

    try:
        reservations.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(reservations))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    quota_usages = Table('quota_usages', meta, autoload=True)
    try:
        quota_usages.drop()
    except Exception:
        LOG.error(_("quota_usages table not dropped"))
        raise

    reservations = Table('reservations', meta, autoload=True)
    try:
        reservations.drop()
    except Exception:
        LOG.error(_("reservations table not dropped"))
        raise
