# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2012 Michael Still and Canonical Inc
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

from sqlalchemy import MetaData, Table
from migrate import ForeignKeyConstraint

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    instance_info_caches = Table('instance_info_caches', meta, autoload=True)

    # We need to remove the foreign key constraint or the column rename will
    # fail
    fkeys = list(instance_info_caches.c.instance_id.foreign_keys)
    try:
        fkey_name = fkeys[0].constraint.name
        ForeignKeyConstraint(
            columns=[instance_info_caches.c.instance_id],
            refcolumns=[instances.c.uuid],
            name=fkey_name).drop()
    except Exception:
        LOG.error(_("foreign key constraint couldn't be removed"))
        raise

    instance_info_caches.c.instance_id.alter(name='instance_uuid')


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)
    instance_info_caches = Table('instance_info_caches', meta, autoload=True)

    # We need to remove the foreign key constraint or the column rename will
    # fail
    fkeys = list(instance_info_caches.c.instance_uuid.foreign_keys)
    if fkeys:
        try:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[instance_info_caches.c.instance_uuid],
                refcolumns=[instances.c.uuid],
                name=fkey_name).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be removed"))
            raise

    instance_info_caches.c.instance_uuid.alter(name='instance_id')
