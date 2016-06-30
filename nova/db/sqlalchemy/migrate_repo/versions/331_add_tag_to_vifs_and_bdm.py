# Copyright (C) 2016, Red Hat, Inc.
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


from oslo_db.sqlalchemy import utils
from sqlalchemy import Column
from sqlalchemy import MetaData
from sqlalchemy import String

from nova.db.sqlalchemy import api


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    shadow_prefix = api._SHADOW_TABLE_PREFIX
    tag = Column('tag', String(255))

    vifs = utils.get_table(migrate_engine, 'virtual_interfaces')
    if not hasattr(vifs.c, 'tag'):
        vifs.create_column(tag.copy())

    shadow_vifs = utils.get_table(migrate_engine,
                                  '%svirtual_interfaces' % shadow_prefix)
    if not hasattr(shadow_vifs.c, 'tag'):
        shadow_vifs.create_column(tag.copy())

    bdm = utils.get_table(migrate_engine, 'block_device_mapping')
    if not hasattr(bdm.c, 'tag'):
        bdm.create_column(tag.copy())

    shadow_bdm = utils.get_table(migrate_engine,
                                 '%sblock_device_mapping' % shadow_prefix)
    if not hasattr(shadow_bdm.c, 'tag'):
        shadow_bdm.create_column(tag.copy())
