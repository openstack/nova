# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

from sqlalchemy import Column, Index, MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_faults = Table('instance_faults', meta, autoload=True)
    host = Column('host', String(length=255))
    instance_faults.create_column(host)
    Index('instance_faults_host_idx', instance_faults.c.host).create(
            migrate_engine)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    instance_faults = Table('instance_faults', meta, autoload=True)
    instance_faults.drop_column('host')
