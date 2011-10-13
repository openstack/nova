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

from sqlalchemy import Column, Integer, MetaData, Table

meta = MetaData()

instance_types = Table("instance_types", meta, Column("id", Integer(),
        primary_key=True, nullable=False))

vcpu_weight = Column("vcpu_weight", Integer())


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types.create_column(vcpu_weight)


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types.drop_column(vcpu_weight)
