# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from sqlalchemy import Column, Integer, MetaData, String, Table


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    instances_os_type = Column('os_type',
                               String(length=255, convert_unicode=False,
                                      assert_unicode=None, unicode_error=None,
                                      _warn_on_bytestring=False),
                               nullable=True)
    instances.create_column(instances_os_type)
    migrate_engine.execute(instances.update()\
                           .where(instances.c.os_type == None)\
                           .values(os_type='linux'))


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instances = Table('instances', meta, autoload=True)

    instances.drop_column('os_type')
