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

    t = Table('instances', meta, autoload=True)

    # Based on service_get_all_compute_sorted
    # from: nova/db/sqlalchemy/api.py
    i = Index('instances_host_deleted_idx',
              t.c.host, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on instance_get_all_by_reservation
    # from: nova/db/sqlalchemy/api.py
    i = Index('instances_reservation_id_idx', t.c.reservation_id)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on instance_get_active_by_window
    # from: nova/db/sqlalchemy/api.py
    i = Index('instances_terminated_at_launched_at_idx',
              t.c.terminated_at, t.c.launched_at)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on security_group_in_use
    # from: nova/db/sqlalchemy/api.py
    i = Index('instances_uuid_deleted_idx',
              t.c.uuid, t.c.deleted)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass

    # Based on instance_get_all_hung_in_rebooting
    # from: nova/db/sqlalchemy/api.py
    i = Index('instances_task_state_updated_at_idx',
              t.c.task_state, t.c.updated_at)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('instances', meta, autoload=True)

    i = Index('instances_host_deleted_idx',
              t.c.host, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('instances_reservation_id_idx', t.c.reservation_id)
    i.drop(migrate_engine)

    i = Index('instances_terminated_at_launched_at_idx',
              t.c.terminated_at, t.c.launched_at)
    i.drop(migrate_engine)

    i = Index('instances_uuid_deleted_idx',
              t.c.uuid, t.c.deleted)
    i.drop(migrate_engine)

    i = Index('instances_task_state_updated_at_idx',
              t.c.task_state, t.c.updated_at)
    i.drop(migrate_engine)
