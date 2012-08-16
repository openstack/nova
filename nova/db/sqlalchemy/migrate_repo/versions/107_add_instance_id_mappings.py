# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2012 SINA Corp.
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

from nova.openstack.common import log as logging
from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # create new table
    instance_id_mappings = Table('instance_id_mappings', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted',
                    Boolean(create_constraint=True, name=None)),
            Column('id', Integer(),
                    primary_key=True,
                    nullable=False,
                    autoincrement=True),
            Column('uuid', String(36), index=True, nullable=False))
    try:
        instance_id_mappings.create()
    except Exception:
        LOG.exception("Exception while creating table 'instance_id_mappings'")
        meta.drop_all(tables=[instance_id_mappings])
        raise

    if migrate_engine.name == "mysql":
        migrate_engine.execute("ALTER TABLE instance_id_mappings "
                "Engine=InnoDB")

    instances = Table('instances', meta, autoload=True)
    instance_id_mappings = Table('instance_id_mappings', meta, autoload=True)

    instance_list = list(instances.select().execute())
    for instance in instance_list:
        instance_id = instance['id']
        uuid = instance['uuid']
        row = instance_id_mappings.insert()
        row.execute({'id': instance_id, 'uuid': uuid})


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_id_mappings = Table('instance_id_mappings', meta, autoload=True)
    instance_id_mappings.drop()
