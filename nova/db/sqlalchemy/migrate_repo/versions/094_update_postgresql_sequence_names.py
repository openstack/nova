# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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

from sqlalchemy import MetaData


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # NOTE(dprince): Need to rename the leftover zones stuff and quota_new
    # stuff from Essex for PostgreSQL.
    if migrate_engine.name == "postgresql":
        sql = """ALTER TABLE zones_id_seq RENAME TO cells_id_seq;
              ALTER TABLE ONLY cells DROP CONSTRAINT zones_pkey;
              ALTER TABLE ONLY cells ADD CONSTRAINT cells_pkey
              PRIMARY KEY (id);

              ALTER TABLE quotas_new_id_seq RENAME TO quotas_id_seq;
              ALTER TABLE ONLY quotas DROP CONSTRAINT quotas_new_pkey;
              ALTER TABLE ONLY quotas ADD CONSTRAINT quotas_pkey
              PRIMARY KEY (id);"""
        migrate_engine.execute(sql)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name == "postgresql":
        sql = """ALTER TABLE cells_id_seq RENAME TO zones_id_seq;
              ALTER TABLE ONLY cells DROP CONSTRAINT cells_pkey;
              ALTER TABLE ONLY cells ADD CONSTRAINT zones_pkey
              PRIMARY KEY (id);

              ALTER TABLE quotas_id_seq RENAME TO quotas_new_id_seq;
              ALTER TABLE ONLY quotas DROP CONSTRAINT quotas_pkey;
              ALTER TABLE ONLY quotas ADD CONSTRAINT quotas_new_pkey
              PRIMARY KEY (id);"""
        migrate_engine.execute(sql)
