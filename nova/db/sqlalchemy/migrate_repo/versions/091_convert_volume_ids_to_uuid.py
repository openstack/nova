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

from sqlalchemy import MetaData, select, Table

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Convert volume and snapshot id columns from int to varchar."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    snapshots = Table('snapshots', meta, autoload=True)
    iscsi_targets = Table('iscsi_targets', meta, autoload=True)
    volume_metadata = Table('volume_metadata', meta, autoload=True)
    block_device_mapping = Table('block_device_mapping', meta, autoload=True)
    sm_volumes = Table('sm_volume', meta, autoload=True)

    volume_mappings = Table('volume_id_mappings', meta, autoload=True)
    snapshot_mappings = Table('snapshot_id_mappings', meta, autoload=True)

    volume_list = list(volumes.select().execute())
    for v in volume_list:
        new_id = select([volume_mappings.c.uuid],
            volume_mappings.c.id == v['id'])

        volumes.update().\
            where(volumes.c.id == v['id']).\
            values(id=new_id).execute()

        sm_volumes.update().\
            where(sm_volumes.c.id == v['id']).\
            values(id=new_id).execute()

        snapshots.update().\
            where(snapshots.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        iscsi_targets.update().\
            where(iscsi_targets.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        volume_metadata.update().\
            where(volume_metadata.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        block_device_mapping.update().\
            where(block_device_mapping.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

    snapshot_list = list(snapshots.select().execute())
    for s in snapshot_list:
        new_id = select([snapshot_mappings.c.uuid],
            volume_mappings.c.id == s['id'])

        volumes.update().\
            where(volumes.c.snapshot_id == s['id']).\
            values(snapshot_id=new_id).execute()

        snapshots.update().\
            where(snapshots.c.id == s['id']).\
            values(volume_id=new_id).execute()

        block_device_mapping.update().\
            where(block_device_mapping.c.snapshot_id == s['id']).\
            values(snapshot_id=new_id).execute()


def downgrade(migrate_engine):
    """Convert volume and snapshot id columns back to int."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    snapshots = Table('snapshots', meta, autoload=True)
    iscsi_targets = Table('iscsi_targets', meta, autoload=True)
    volume_metadata = Table('volume_metadata', meta, autoload=True)
    block_device_mapping = Table('block_device_mapping', meta, autoload=True)
    sm_volumes = Table('sm_volume', meta, autoload=True)

    volume_mappings = Table('volume_id_mappings', meta, autoload=True)
    snapshot_mappings = Table('snapshot_id_mappings', meta, autoload=True)

    volume_list = list(volumes.select().execute())
    for v in volume_list:
        new_id = select([volume_mappings.c.id],
            volume_mappings.c.uuid == v['id'])

        volumes.update().\
            where(volumes.c.id == v['id']).\
            values(id=new_id).execute()

        sm_volumes.update().\
            where(sm_volumes.c.id == v['id']).\
            values(id=new_id).execute()

        snapshots.update().\
            where(snapshots.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        iscsi_targets.update().\
            where(iscsi_targets.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        volume_metadata.update().\
            where(volume_metadata.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

        block_device_mapping.update().\
            where(block_device_mapping.c.volume_id == v['id']).\
            values(volume_id=new_id).execute()

    snapshot_list = list(snapshots.select().execute())
    for s in snapshot_list:
        new_id = select([snapshot_mappings.c.id],
            volume_mappings.c.uuid == s['id'])

        volumes.update().\
            where(volumes.c.snapshot_id == s['id']).\
            values(snapshot_id=new_id).execute()

        snapshots.update().\
            where(snapshots.c.id == s['id']).\
            values(volume_id=new_id).execute()

        block_device_mapping.update().\
            where(block_device_mapping.c.snapshot_id == s['id']).\
            values(snapshot_id=new_id).execute()
