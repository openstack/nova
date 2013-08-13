# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

from sqlalchemy import MetaData, String, Table
from sqlalchemy.dialects import postgresql


CIDR_TABLE_COLUMNS = [
    # table name, column name
    ('shadow_security_group_rules', 'cidr'),
    ('shadow_provider_fw_rules', 'cidr'),
    ('shadow_networks', 'cidr'),
    ('shadow_networks', 'cidr_v6')]


def upgrade(migrate_engine):
    """Convert String columns holding IP addresses to INET for postgresql."""
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect()

    if dialect is not postgresql.dialect:
        # NOTE(jhesketh): Postgres was always of TYPE INET so there is nothing
        # to undo here (see migration 149).
        for table, column in CIDR_TABLE_COLUMNS:
            t = Table(table, meta, autoload=True)
            getattr(t.c, column).alter(type=String(43))


def downgrade(migrate_engine):
    """Convert columns back to the larger String(255)."""
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect()

    if dialect is not postgresql.dialect:
        # NOTE(jhesketh): Postgres was always of TYPE INET so there is nothing
        # to undo here (see migration 149).
        for table, column in CIDR_TABLE_COLUMNS:
            t = Table(table, meta, autoload=True)
            getattr(t.c, column).alter(type=String(39))
