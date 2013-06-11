# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import itertools
import re

from sqlalchemy import Column, Integer, MetaData, String, Table
from sqlalchemy.sql.expression import select

from nova.openstack.common import log as logging
from oslo.config import cfg


CONF = cfg.CONF
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
LOG = logging.getLogger(__name__)


_ephemeral = re.compile('^ephemeral(\d|[1-9]\d+)$')


def _is_ephemeral(device_name):
    return bool(_ephemeral.match(device_name))


def _is_swap_or_ephemeral(device_name):
    return (device_name and
            (device_name == 'swap' or _is_ephemeral(device_name)))


_dev = re.compile('^/dev/')


def strip_dev(device_name):
    """remove leading '/dev/'."""
    return _dev.sub('', device_name) if device_name else device_name


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for table in ('block_device_mapping', 'shadow_block_device_mapping'):
        block_device_mapping = Table(table,
                                     meta, autoload=True)

        source_type = Column('source_type', String(255))
        destination_type = Column('destination_type', String(255))
        guest_format = Column('guest_format', String(255))
        device_type = Column('device_type', String(255))
        disk_bus = Column('disk_bus', String(255))
        boot_index = Column('boot_index', Integer)
        image_id = Column('image_id', String(36))

        source_type.create(block_device_mapping)
        destination_type.create(block_device_mapping)
        guest_format.create(block_device_mapping)
        device_type.create(block_device_mapping)
        disk_bus.create(block_device_mapping)
        boot_index.create(block_device_mapping)
        image_id.create(block_device_mapping)

        device_name = block_device_mapping.c.device_name
        device_name.alter(nullable=True)

        _upgrade_bdm_v2(meta, block_device_mapping)

        virtual_name = block_device_mapping.c.virtual_name
        virtual_name.drop()


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    for table in ('block_device_mapping', 'shadow_block_device_mapping'):
        block_device_mapping = Table(table, meta, autoload=True)

        virtual_name = Column('virtual_name', String(255), nullable=True)
        virtual_name.create(block_device_mapping)

        _downgrade_bdm_v2(meta, block_device_mapping)

        device_name = block_device_mapping.c.device_name
        device_name.alter(nullable=True)

        block_device_mapping.c.source_type.drop()
        block_device_mapping.c.destination_type.drop()
        block_device_mapping.c.guest_format.drop()
        block_device_mapping.c.device_type.drop()
        block_device_mapping.c.disk_bus.drop()
        block_device_mapping.c.boot_index.drop()
        block_device_mapping.c.image_id.drop()


def _upgrade_bdm_v2(meta, bdm_table):
    # Rows needed to do the upgrade
    _bdm_rows_v1 = ('id', 'device_name', 'virtual_name',
                    'snapshot_id', 'volume_id', 'instance_uuid')

    _bdm_rows_v2 = ('id', 'source_type', 'destination_type', 'guest_format',
                    'device_type', 'disk_bus', 'boot_index', 'image_id')

    def _get_columns(table, names):
        return [getattr(table.c, name) for name in names]

    def _default_bdm():
        # Set some common default values
        default = {}
        default['destination_type'] = 'local'
        default['device_type'] = 'disk'
        default['boot_index'] = -1
        return default

    instance_table = Table('instances', meta, autoload=True)
    instance_shadow_table = Table('shadow_instances', meta, autoload=True)

    for instance in itertools.chain(
        instance_table.select().execute().fetchall(),
        instance_shadow_table.select().execute().fetchall()):
        # Get all the bdms for an instance
        bdm_q = select(_get_columns(bdm_table, _bdm_rows_v1)).where(
            bdm_table.c.instance_uuid == instance.uuid)

        bdms_v1 = [val for val in bdm_q.execute().fetchall()]
        bdms_v2 = []
        image_bdm = None

        for bdm in bdms_v1:
            bdm_v2 = _default_bdm()
            # Copy over some fields we'll need
            bdm_v2['id'] = bdm['id']
            bdm_v2['device_name'] = bdm['device_name']

            virt_name = bdm.virtual_name
            if _is_swap_or_ephemeral(virt_name):
                bdm_v2['source_type'] = 'blank'

                if virt_name == 'swap':
                    bdm_v2['guest_format'] = 'swap'
                else:
                    bdm_v2['guest_format'] = CONF.default_ephemeral_format

                bdms_v2.append(bdm_v2)

            elif bdm.snapshot_id:
                bdm_v2['source_type'] = 'snapshot'
                bdm_v2['destination_type'] = 'volume'

                bdms_v2.append(bdm_v2)

            elif bdm.volume_id:
                bdm_v2['source_type'] = 'volume'
                bdm_v2['destination_type'] = 'volume'

                bdms_v2.append(bdm_v2)
            else:  # Log a warning that the bdm is not as expected
                LOG.warn("Got an unexpected block device %s"
                         "that cannot be converted to v2 format" % bdm)

        if instance.image_ref:
            image_bdm = _default_bdm()
            image_bdm['source_type'] = 'image'
            image_bdm['instance_uuid'] = instance.uuid
            image_bdm['image_id'] = instance.image_ref

        # NOTE (ndipanov): Mark only the image or the bootable volume
        #                  with boot index, as we don't support it yet.
        #                  Also, make sure that instances started with
        #                  the old syntax of specifying an image *and*
        #                  a bootable volume still have consistend data.
        bootable = [bdm for bdm in bdms_v2
                    if strip_dev(bdm['device_name']) ==
                       strip_dev(instance.root_device_name)
                    and bdm['source_type'] != 'blank']

        if len(bootable) > 1:
            LOG.warn("Found inconsistent block device data for "
                     "instance %s - non-unique bootable device."
                     % instance.uuid)
        if bootable:
            bootable[0]['boot_index'] = 0
        elif instance.image_ref:
            image_bdm['boot_index'] = 0
        else:
            LOG.warn("No bootable device found for instance %s."
                     % instance.uuid)

        # Update the DB
        if image_bdm:
            bdm_table.insert().values(**image_bdm).execute()

        for bdm in bdms_v2:
            bdm_table.update().where(
                bdm_table.c.id == bdm['id']
            ).values(**bdm).execute()


def _downgrade_bdm_v2(meta, bdm_table):
    # First delete all the image bdms

    # NOTE (ndipanov): This will delete all the image bdms, even the ones
    #                   that were potentially created as part of th normal
    #                   operation, not only the upgrade. We have to do it,
    #                   as we have no way of handling them in the old code.
    bdm_table.delete().where(bdm_table.c.source_type == 'image').execute()

    # NOTE (ndipanov):  Set all NULL device_names (if any) to '' and let the
    #                   Nova code deal with that. This is needed so that the
    #                   return of nullable=True does not break, and should
    #                   happen only if there are instances that are just
    #                   starting up when we do the downgrade
    bdm_table.update().where(
        bdm_table.c.device_name == None
    ).values(device_name='').execute()

    instance = Table('instances', meta, autoload=True)
    instance_shadow = Table('shadow_instances', meta, autoload=True)
    instance_q = select([instance.c.uuid])
    instance_shadow_q = select([instance_shadow.c.uuid])

    for instance_uuid, in itertools.chain(
        instance_q.execute().fetchall(),
        instance_shadow_q.execute().fetchall()):
        # Get all the bdms for an instance
        bdm_q = select(
            [bdm_table.c.id, bdm_table.c.source_type, bdm_table.c.guest_format]
        ).where(
            (bdm_table.c.instance_uuid == instance_uuid) &
            (bdm_table.c.source_type == 'blank')
        ).order_by(bdm_table.c.id.asc())

        blanks = [
            dict(zip(('id', 'source', 'format'), row))
            for row in bdm_q.execute().fetchall()
        ]

        swap = [dev for dev in blanks if dev['format'] == 'swap']
        assert len(swap) < 2
        ephemerals = [dev for dev in blanks if dev not in swap]

        for index, eph in enumerate(ephemerals):
            eph['virtual_name'] = 'ephemeral' + str(index)

        if swap:
            swap[0]['virtual_name'] = 'swap'

        for bdm in swap + ephemerals:
            bdm_table.update().where(
                bdm_table.c.id == bdm['id']
            ).values(**bdm).execute()
