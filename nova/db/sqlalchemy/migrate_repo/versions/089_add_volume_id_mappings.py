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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table

from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Build mapping tables for our volume uuid migration.

    These mapping tables serve two purposes:
    1. Provide a method for downgrade after UUID conversion
    2. Provide a uuid to associate with existing volumes and snapshots
       when we do the actual datatype migration from int to uuid

    """
    meta = MetaData()
    meta.bind = migrate_engine

    volume_id_mappings = Table('volume_id_mappings', meta,
                    Column('created_at',
                                      DateTime(timezone=False)),
                    Column('updated_at',
                                      DateTime(timezone=False)),
                    Column('deleted_at',
                                      DateTime(timezone=False)),
                    Column('deleted',
                           Boolean(create_constraint=True, name=None)),
                    Column('id', Integer(),
                                      primary_key=True,
                                      nullable=False,
                                      autoincrement=True),
                    Column('uuid', String(36),
                                      nullable=False))
    try:
        volume_id_mappings.create()
    except Exception:
        LOG.exception("Exception while creating table 'volume_id_mappings'")
        meta.drop_all(tables=[volume_id_mappings])
        raise

    snapshot_id_mappings = Table('snapshot_id_mappings', meta,
                    Column('created_at',
                                      DateTime(timezone=False)),
                    Column('updated_at',
                                      DateTime(timezone=False)),
                    Column('deleted_at',
                                      DateTime(timezone=False)),
                    Column('deleted',
                           Boolean(create_constraint=True, name=None)),
                    Column('id', Integer(),
                                      primary_key=True,
                                      nullable=False,
                                      autoincrement=True),
                    Column('uuid', String(36),
                                      nullable=False))
    try:
        snapshot_id_mappings.create()
    except Exception:
        LOG.exception("Exception while creating table 'snapshot_id_mappings'")
        meta.drop_all(tables=[snapshot_id_mappings])
        raise

    if migrate_engine.name == "mysql":
        migrate_engine.execute("ALTER TABLE volume_id_mappings Engine=InnoDB")
        migrate_engine.execute("ALTER TABLE snapshot_id_mappings "\
                "Engine=InnoDB")

    volumes = Table('volumes', meta, autoload=True)
    snapshots = Table('snapshots', meta, autoload=True)
    volume_id_mappings = Table('volume_id_mappings', meta, autoload=True)
    snapshot_id_mappings = Table('snapshot_id_mappings', meta, autoload=True)

    volume_list = list(volumes.select().execute())
    for v in volume_list:
        old_id = v['id']
        new_id = utils.gen_uuid()
        row = volume_id_mappings.insert()
        row.execute({'id': old_id,
              'uuid': str(new_id)})

    snapshot_list = list(snapshots.select().execute())
    for s in snapshot_list:
        old_id = s['id']
        new_id = utils.gen_uuid()
        row = snapshot_id_mappings.insert()
        row.execute({'id': old_id,
              'uuid': str(new_id)})


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    volume_id_mappings = Table('volume_id_mappings', meta, autoload=True)
    volume_id_mappings.drop()

    snapshot_id_mappings = Table('snapshot_id_mappings', meta, autoload=True)
    snapshot_id_mappings.drop()
