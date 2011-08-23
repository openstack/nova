# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Piston Cloud Computing, Inc.
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

from nova import utils


meta = MetaData()

instances = Table("instances", meta,
        Column("id", Integer(), primary_key=True, nullable=False))

# matches the size of an image_ref
config_drive_column = Column("config_drive", String(255), nullable=True)


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instances.create_column(config_drive_column)


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instances.drop_column(config_drive_column)
