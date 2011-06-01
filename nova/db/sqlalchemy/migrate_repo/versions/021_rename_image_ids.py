# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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


meta = MetaData()


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine;
    # bind migrate_engine to your metadata
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True,
                      autoload_with=migrate_engine)

    image_id_column = instances.c.image_id
    image_id_column.alter(name='image_ref')


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instances = Table('instances', meta, autoload=True,
                      autoload_with=migrate_engine)

    image_ref_column = instances.c.image_ref
    image_ref_column.alter(name='image_id')
