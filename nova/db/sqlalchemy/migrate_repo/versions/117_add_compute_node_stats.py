# Copyright (c) 2012 OpenStack, LLC.
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
from sqlalchemy import Index, MetaData, String, Table
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    # create new table
    compute_node_stats = Table('compute_node_stats', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False,
                autoincrement=True),
            Column('compute_node_id', Integer, index=True, nullable=False),
            Column('key', String(length=255, convert_unicode=True,
                assert_unicode=None, unicode_error=None,
                _warn_on_bytestring=False), nullable=False),
            Column('value', String(length=255, convert_unicode=True,
                assert_unicode=None, unicode_error=None,
                _warn_on_bytestring=False)),
            mysql_engine='InnoDB')
    try:
        compute_node_stats.create()
    except Exception:
        LOG.exception("Exception while creating table 'compute_node_stats'")
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    compute_node_stats = Table('compute_node_stats', meta, autoload=True)
    compute_node_stats.drop()
