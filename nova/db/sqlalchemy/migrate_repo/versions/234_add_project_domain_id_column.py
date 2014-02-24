# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from sqlalchemy import Column, MetaData, Boolean, Table, text


def upgrade(migrate_engine):
    # Upgrade operations go here. Don't create your own engine; bind
    # migrate_engine to your metadata
    meta = MetaData()
    meta.bind = migrate_engine
    project_table = Table('instances', meta, autoload=True)
    parent_project_id = Column('project_domain_id', String(255))
    project_table.create_column(parent_project_id)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    # Operations to reverse the above upgrade go here.
    project_table = Table('instances', meta, autoload=True)
    project_table.drop_column('project_domain_id')
