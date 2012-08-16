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

from migrate import ForeignKeyConstraint
from sqlalchemy import Integer
from sqlalchemy import MetaData, String, Table

from migrate import ForeignKeyConstraint
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
    sm_volume = Table('sm_volume', meta, autoload=True)
    block_device_mapping = Table('block_device_mapping', meta, autoload=True)

    try:
        fkeys = list(snapshots.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[snapshots.c.volume_id],
                    refcolumns=[volumes.c.id],
                    name=fkey_name).drop()

        fkeys = list(iscsi_targets.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[iscsi_targets.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(volume_metadata.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[volume_metadata.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(sm_volume.c.id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[sm_volume.c.id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(block_device_mapping.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[block_device_mapping.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(block_device_mapping.c.snapshot_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[block_device_mapping.c.snapshot_id],
                                 refcolumns=[snapshots.c.id],
                                 name=fkey_name).drop()

    except Exception:
        LOG.error(_("Foreign Key constraint couldn't be removed"))
        raise

    volumes.c.id.alter(String(36), primary_key=True)
    volumes.c.snapshot_id.alter(String(36))
    volume_metadata.c.volume_id.alter(String(36), nullable=False)
    snapshots.c.id.alter(String(36), primary_key=True)
    snapshots.c.volume_id.alter(String(36))
    sm_volume.c.id.alter(String(36))
    block_device_mapping.c.volume_id.alter(String(36))
    block_device_mapping.c.snapshot_id.alter(String(36))
    iscsi_targets.c.volume_id.alter(String(36), nullable=True)

    try:
        fkeys = list(snapshots.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[snapshots.c.volume_id],
                    refcolumns=[volumes.c.id],
                    name=fkey_name).create()

        fkeys = list(iscsi_targets.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[iscsi_targets.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()

        fkeys = list(volume_metadata.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[volume_metadata.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()

        fkeys = list(sm_volume.c.id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[sm_volume.c.id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()
        # NOTE(jdg) We're intentionally leaving off FK's on BDM

    except Exception:
        LOG.error(_("Foreign Key constraint couldn't be removed"))
        raise


def downgrade(migrate_engine):
    """Convert volume and snapshot id columns back to int."""
    meta = MetaData()
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name

    if dialect.startswith('sqlite'):
        return

    volumes = Table('volumes', meta, autoload=True)
    snapshots = Table('snapshots', meta, autoload=True)
    iscsi_targets = Table('iscsi_targets', meta, autoload=True)
    volume_metadata = Table('volume_metadata', meta, autoload=True)
    sm_volume = Table('sm_volume', meta, autoload=True)
    block_device_mapping = Table('block_device_mapping', meta, autoload=True)

    try:
        fkeys = list(snapshots.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[snapshots.c.volume_id],
                    refcolumns=[volumes.c.id],
                    name=fkey_name).drop()

        fkeys = list(iscsi_targets.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[iscsi_targets.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(volume_metadata.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[volume_metadata.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(sm_volume.c.id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[sm_volume.c.id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

    except Exception:
        LOG.error(_("Foreign Key constraint couldn't be removed"))
        raise

    volumes.c.id.alter(Integer, primary_key=True, autoincrement=True)
    volumes.c.snapshot_id.alter(Integer)
    volume_metadata.c.volume_id.alter(Integer, nullable=False)
    snapshots.c.id.alter(Integer, primary_key=True, autoincrement=True)
    snapshots.c.volume_id.alter(Integer)
    sm_volume.c.id.alter(Integer)
    block_device_mapping.c.volume_id.alter(Integer)
    block_device_mapping.c.snapshot_id.alter(Integer)
    iscsi_targets.c.volume_id.alter(Integer, nullable=True)

    try:
        fkeys = list(snapshots.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[snapshots.c.volume_id],
                    refcolumns=[volumes.c.id],
                    name=fkey_name).create()

        fkeys = list(iscsi_targets.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[iscsi_targets.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()

        fkeys = list(volume_metadata.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[volume_metadata.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()

        fkeys = list(sm_volume.c.id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[sm_volume.c.id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).create()

        # NOTE(jdg) Put the BDM foreign keys back in place
        fkeys = list(block_device_mapping.c.volume_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[block_device_mapping.c.volume_id],
                                 refcolumns=[volumes.c.id],
                                 name=fkey_name).drop()

        fkeys = list(block_device_mapping.c.snapshot_id.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(columns=[block_device_mapping.c.snapshot_id],
                                 refcolumns=[snapshots.c.id],
                                 name=fkey_name).drop()

    except Exception:
        LOG.error(_("Foreign Key constraint couldn't be removed"))
        raise
