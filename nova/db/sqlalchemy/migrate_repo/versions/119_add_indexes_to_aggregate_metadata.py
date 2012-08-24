# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from sqlalchemy import Index, MetaData, Table
from sqlalchemy.exc import IntegrityError


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # Based on aggregate_metadata_get_item
    # from: nova/db/sqlalchemy/api.py
    t = Table('aggregate_metadata', meta, autoload=True)
    i = Index('aggregate_metadata_key_idx', t.c.key)
    try:
        i.create(migrate_engine)
    except IntegrityError:
        pass


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    t = Table('aggregate_metadata', meta, autoload=True)
    i = Index('aggregate_metadata_key_idx', t.c.key)
    i.drop(migrate_engine)
