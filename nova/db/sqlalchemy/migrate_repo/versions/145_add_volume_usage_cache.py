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

from sqlalchemy import Column, DateTime
from sqlalchemy import Boolean, BigInteger, MetaData, Integer, String, Table

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Create new table
    volume_usage_cache = Table('volume_usage_cache', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('volume_id', String(36), nullable=False),
            Column("instance_id", Integer()),
            Column('tot_last_refreshed', DateTime(timezone=False)),
            Column('tot_reads', BigInteger(), default=0),
            Column('tot_read_bytes', BigInteger(), default=0),
            Column('tot_writes', BigInteger(), default=0),
            Column('tot_write_bytes', BigInteger(), default=0),
            Column('curr_last_refreshed', DateTime(timezone=False)),
            Column('curr_reads', BigInteger(), default=0),
            Column('curr_read_bytes', BigInteger(), default=0),
            Column('curr_writes', BigInteger(), default=0),
            Column('curr_write_bytes', BigInteger(), default=0),
            mysql_engine='InnoDB',
            mysql_charset='utf8'
    )

    try:
        volume_usage_cache.create()
    except Exception:
        LOG.exception("Exception while creating table 'volume_usage_cache'")
        meta.drop_all(tables=[volume_usage_cache])
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volume_usage_cache = Table('volume_usage_cache', meta, autoload=True)
    try:
        volume_usage_cache.drop()
    except Exception:
        LOG.error(_("volume_usage_cache table not dropped"))
        raise
