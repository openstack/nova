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

    t = Table('networks', meta, autoload=True)

    # Based on network_get_by_bridge
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_bridge_deleted_idx',
              t.c.bridge, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on network_get_all_by_host
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_host_idx', t.c.host)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on network_query
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_project_id_deleted_idx',
              t.c.project_id, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on network_get_all_by_uuids
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_uuid_project_id_deleted_idx',
              t.c.uuid, t.c.project_id, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on network_create_safe
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_vlan_deleted_idx',
              t.c.vlan, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on network_get_by_cidr
    # from: nova/db/sqlalchemy/api.py
    i = Index('networks_cidr_v6_idx', t.c.cidr_v6)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('networks', meta, autoload=True)

    i = Index('networks_bridge_deleted_idx',
              t.c.bridge, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('networks_host_idx', t.c.host)
    i.drop(migrate_engine)

    i = Index('networks_project_id_deleted_idx',
              t.c.project_id, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('networks_uuid_project_id_deleted_idx',
              t.c.uuid, t.c.project_id, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('networks_vlan_deleted_idx',
              t.c.vlan, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('networks_cidr_v6_idx', t.c.cidr_v6)
    i.drop(migrate_engine)
