# Copyright 2013 IBM Corp.
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

from sqlalchemy import MetaData, Table
from nova.openstack.common import timeutils


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    sys_meta = Table('instance_system_metadata', meta, autoload=True)

    sys_meta.update().\
        values(value=None).\
        where(sys_meta.c.key != 'instance_type_name').\
        where(sys_meta.c.key != 'instance_type_flavorid').\
        where(sys_meta.c.key.like('instance_type_%')).\
        where(sys_meta.c.value == 'None').\
        execute()

    now = timeutils.utcnow()
    sys_meta.update().\
        values(created_at=now).\
        where(sys_meta.c.created_at == None).\
        where(sys_meta.c.key.like('instance_type_%')).\
        execute()


def downgrade(migration_engine):
    # This migration only touches data, and only metadata at that. No need
    # to go through and delete old metadata items.
    pass
