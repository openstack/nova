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

from sqlalchemy import Column, Float, Integer, MetaData, Table

meta = MetaData()

zones = Table('zones', meta,
        Column('id', Integer(), primary_key=True, nullable=False),
        )

weight_offset = Column('weight_offset', Float(), default=0.0)
weight_scale = Column('weight_scale', Float(), default=1.0)


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    zones.create_column(weight_offset)
    zones.create_column(weight_scale)


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    zones.drop_column(weight_offset)
    zones.drop_column(weight_scale)
