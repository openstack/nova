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

from sqlalchemy import String, Column, MetaData, Table
from migrate.changeset import UniqueConstraint

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dialect = migrate_engine.url.get_dialect().name

    aggregates = Table('aggregates', meta, autoload=True)
    if dialect.startswith('sqlite'):
        aggregates.c.name.alter(unique=False)
    elif dialect.startswith('postgres'):
        ucon = UniqueConstraint('name',
                                name='aggregates_name_key',
                                table=aggregates)
        ucon.drop()

    else:
        col2 = aggregates.c.name
        UniqueConstraint(col2, name='name').drop()


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    aggregates = Table('aggregates', meta, autoload=True)
    aggregates.c.name.alter(unique=True)
