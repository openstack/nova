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

    # NOTE(dprince): Remove unused snapshots/volumes sequences.
    # These are leftovers from the ID --> UUID conversion for these tables
    # that occurred in Folsom.
    if migrate_engine.name == "postgresql":
        base_query = """SELECT COUNT(*) FROM pg_class c
                     WHERE c.relkind = 'S'
                     AND relname = '%s';"""
        result = migrate_engine.execute(base_query % "snapshots_id_seq")
        if result.scalar() > 0:
            sql = "DROP SEQUENCE snapshots_id_seq CASCADE;"
            migrate_engine.execute(sql)

        result = migrate_engine.execute(base_query % "volumes_id_seq")
        if result.scalar() > 0:
            sql = "DROP SEQUENCE volumes_id_seq CASCADE;"
            migrate_engine.execute(sql)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    if migrate_engine.name == "postgresql":
        sql = """CREATE SEQUENCE snapshots_id_seq START WITH 1 INCREMENT BY 1
              NO MINVALUE NO MAXVALUE CACHE 1;
              ALTER SEQUENCE snapshots_id_seq OWNED BY snapshots.id;
              SELECT pg_catalog.setval('snapshots_id_seq', 1, false);
              ALTER TABLE ONLY snapshots ALTER COLUMN id SET DEFAULT
              nextval('snapshots_id_seq'::regclass);"""

        sql += """CREATE SEQUENCE volumes_id_seq START WITH 1 INCREMENT BY 1
               NO MINVALUE NO MAXVALUE CACHE 1;
               ALTER SEQUENCE volumes_id_seq OWNED BY volumes.id;
               SELECT pg_catalog.setval('volumes_id_seq', 1, false);
               ALTER TABLE ONLY volumes ALTER COLUMN id SET DEFAULT
               nextval('volumes_id_seq'::regclass);"""
        migrate_engine.execute(sql)
