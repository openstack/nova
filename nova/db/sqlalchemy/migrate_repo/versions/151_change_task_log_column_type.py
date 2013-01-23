# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013 Wenhao Xu <xuwenhao2008@gmail.com>.
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

from sqlalchemy import MetaData, String, Table, DateTime
from sqlalchemy.dialects import postgresql


def upgrade(migrate_engine):
    """Convert period_beginning and period_ending to DateTime."""
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect()

    if dialect is postgresql.dialect:
        # We need to handle postresql specially.
        # Can't use migrate's alter() because it does not support
        # explicit casting
        for column in ('period_beginning', 'period_ending'):
            migrate_engine.execute(
                "ALTER TABLE task_log "
                "ALTER COLUMN %s TYPE TIMESTAMP WITHOUT TIME ZONE "
                "USING %s::TIMESTAMP WITHOUT TIME ZONE"
                % (column, column))
    else:
        migrations = Table('task_log', meta, autoload=True)
        migrations.c.period_beginning.alter(DateTime)
        migrations.c.period_ending.alter(DateTime)


def downgrade(migrate_engine):
    """Convert columns back to String(255)."""
    meta = MetaData()
    meta.bind = migrate_engine

    # don't need to handle postgresql here.
    migrations = Table('task_log', meta, autoload=True)
    migrations.c.period_beginning.alter(String(255))
    migrations.c.period_ending.alter(String(255))
