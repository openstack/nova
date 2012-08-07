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

    # Based on agent_build_get_by_triple
    # from: nova/db/sqlalchemy/api.py
    t = Table('agent_builds', meta, autoload=True)
    i = Index('agent_builds_hypervisor_os_arch_idx',
              t.c.hypervisor, t.c.os, t.c.architecture)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('agent_builds', meta, autoload=True)
    i = Index('agent_builds_hypervisor_os_arch_idx',
              t.c.hypervisor, t.c.os, t.c.architecture)
    i.drop(migrate_engine)
