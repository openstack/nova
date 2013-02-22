# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

from sqlalchemy import Index, MetaData, Table
from sqlalchemy.exc import IntegrityError


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('migrations', meta, autoload=True)

    # Based on migration_get_in_progress_by_host
    # from: nova/db/sqlalchemy/api.py
    i = Index('migrations_by_host_and_status_idx', t.c.deleted,
            t.c.source_compute, t.c.dest_compute, t.c.status)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('migrations', meta, autoload=True)

    i = Index('migrations_by_host_and_status_idx', t.c.deleted,
            t.c.source_compute, t.c.dest_compute, t.c.status)
    i.drop(migrate_engine)
