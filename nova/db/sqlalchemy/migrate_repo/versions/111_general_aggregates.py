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

from sqlalchemy import String, Column, MetaData, Table, delete, select
from migrate.changeset import UniqueConstraint

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dialect = migrate_engine.url.get_dialect().name

    aggregates = Table('aggregates', meta, autoload=True)
    aggregate_metadata = Table('aggregate_metadata', meta, autoload=True)
    record_list = list(aggregates.select().execute())
    for rec in record_list:
        row = aggregate_metadata.insert()
        row.execute({'created_at': rec['created_at'],
                    'updated_at': rec['updated_at'],
                    'deleted_at': rec['deleted_at'],
                    'deleted': rec['deleted'],
                    'key': 'operational_state',
                    'value': rec['operational_state'],
                    'aggregate_id': rec['id'],
                    })
    aggregates.drop_column('operational_state')

    aggregate_hosts = Table('aggregate_hosts', meta, autoload=True)
    if dialect.startswith('sqlite'):
        aggregate_hosts.drop_column('host')
        aggregate_hosts.create_column(Column('host', String(255)))
    else:
        col = aggregate_hosts.c.host
        UniqueConstraint(col, name='host').drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    aggregates = Table('aggregates', meta, autoload=True)
    aggregate_metadata = Table('aggregate_metadata', meta, autoload=True)
    operational_state = Column('operational_state', String(255))
    aggregates.create_column(operational_state)
    aggregates.update().values(operational_state=select(
        [aggregate_metadata.c.value]).where(aggregates.c.id ==
        aggregate_metadata.c.aggregate_id and aggregate_metadata.c.key ==
        'operational_state')).execute()
    delete(aggregate_metadata, aggregate_metadata.c.key == 'operational_state')
    aggregates.c.operational_state.alter(nullable=False)
    aggregate_hosts = Table('aggregate_hosts', meta, autoload=True)
    aggregate_hosts.c.host.alter(unique=True)
