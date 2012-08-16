# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
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

from nova.openstack.common import log as logging
from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Reverse the previous migration
    meta = MetaData()
    meta.bind = migrate_engine

    reservations = Table('reservations', meta, autoload=True)
    d = reservations.delete(reservations.c.deleted == True)
    d.execute()
    reservations.drop_column('user_id')

    quota_usages = Table('quota_usages', meta, autoload=True)
    d = quota_usages.delete(quota_usages.c.user_id != None)
    d.execute()
    quota_usages.drop_column('user_id')

    user_quotas = Table('user_quotas', meta, autoload=True)
    try:
        user_quotas.drop()
    except Exception:
        LOG.error(_("user_quotas table not dropped"))
        raise


def downgrade(migrate_engine):
    # Undo the reversal of the previous migration
    # (data is not preserved)
    meta = MetaData()
    meta.bind = migrate_engine

    # Add 'user_id' column to quota_usages table.
    quota_usages = Table('quota_usages', meta, autoload=True)
    user_id = Column('user_id',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None, unicode_error=None,
                            _warn_on_bytestring=False))
    quota_usages.create_column(user_id)

    # Add 'user_id' column to reservations table.
    reservations = Table('reservations', meta, autoload=True)
    user_id = Column('user_id',
                     String(length=255, convert_unicode=False,
                            assert_unicode=None, unicode_error=None,
                            _warn_on_bytestring=False))
    reservations.create_column(user_id)

    # New table.
    user_quotas = Table('user_quotas', meta,
                        Column('id', Integer(), primary_key=True),
                        Column('created_at', DateTime(timezone=False)),
                        Column('updated_at', DateTime(timezone=False)),
                        Column('deleted_at', DateTime(timezone=False)),
                        Column('deleted', Boolean(), default=False),
                        Column('user_id',
                               String(length=255, convert_unicode=False,
                                      assert_unicode=None, unicode_error=None,
                                      _warn_on_bytestring=False)),
                        Column('project_id',
                               String(length=255, convert_unicode=False,
                                      assert_unicode=None, unicode_error=None,
                                      _warn_on_bytestring=False)),
                        Column('resource',
                               String(length=255, convert_unicode=False,
                                      assert_unicode=None, unicode_error=None,
                                      _warn_on_bytestring=False),
                               nullable=False),
                        Column('hard_limit', Integer(), nullable=True),
                        mysql_engine='InnoDB',
                        mysql_charset='utf8',
                        )

    try:
        user_quotas.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(user_quotas))
        raise
