# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Openstack, LLC.
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy import MetaData, String, Table

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    instance_system_metadata = Table('instance_system_metadata', meta,
            Column('created_at', DateTime(timezone=False)),
            Column('updated_at', DateTime(timezone=False)),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True, nullable=False),
            Column('instance_uuid',
                   String(36),
                   ForeignKey('instances.uuid'),
                   nullable=False),
            Column('key',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False),
                   nullable=False),
            Column('value',
                   String(length=255, convert_unicode=True,
                          assert_unicode=None,
                          unicode_error=None, _warn_on_bytestring=False)),
            mysql_engine='InnoDB')

    try:
        instance_system_metadata.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(instance_system_metadata))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    instance_system_metadata = Table(
            'instance_system_metadata', meta, autoload=True)
    instance_system_metadata.drop()
