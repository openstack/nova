# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

    t = Table('floating_ips', meta, autoload=True)

    # Based on floating_ip_get_all_by_host
    # from: nova/db/sqlalchemy/api.py
    i = Index('floating_ips_host_idx', t.c.host)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on floating_ip_get_all_by_project
    # from: nova/db/sqlalchemy/api.py
    i = Index('floating_ips_project_id_idx', t.c.project_id)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on floating_ip_allocate_address
    # from: nova/db/sqlalchemy/api.py
    i = Index('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
              t.c.pool, t.c.deleted, t.c.fixed_ip_id, t.c.project_id)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('floating_ips', meta, autoload=True)

    i = Index('floating_ips_host_idx', t.c.host)
    i.drop(migrate_engine)

    i = Index('floating_ips_project_id_idx', t.c.project_id)
    i.drop(migrate_engine)

    i = Index('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
              t.c.pool, t.c.deleted, t.c.fixed_ip_id, t.c.project_id)
    i.drop(migrate_engine)
