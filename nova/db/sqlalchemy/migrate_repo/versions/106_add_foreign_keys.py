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

    for table in ['block_device_mapping',
                  'consoles',
                  'instance_info_caches',
                  'instance_metadata',
                  'security_group_instance_association']:
        t = Table(table, meta, autoload=True)

        try:
            ForeignKeyConstraint(
                columns=[t.c.instance_uuid],
                refcolumns=[instances.c.uuid]).create()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be created"))
            raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True)

    for table in ['block_device_mapping',
                  'consoles',
                  'instance_info_caches',
                  'instance_metadata',
                  'security_group_instance_association']:
        t = Table(table, meta, autoload=True)

        try:
            ForeignKeyConstraint(
                columns=[t.c.instance_uuid],
                refcolumns=[instances.c.uuid]).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be dropped"))
            raise
