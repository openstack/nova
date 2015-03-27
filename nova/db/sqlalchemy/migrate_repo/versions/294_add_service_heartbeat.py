# Copyright (c) 2015 Wind River Systems Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from sqlalchemy import MetaData, Table, Column, DateTime

BASE_TABLE_NAME = 'services'
NEW_COLUMN_NAME = 'last_seen_up'


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    for prefix in ('', 'shadow_'):
        table = Table(prefix + BASE_TABLE_NAME, meta, autoload=True)
        new_column = Column(NEW_COLUMN_NAME, DateTime, nullable=True)
        if not hasattr(table.c, NEW_COLUMN_NAME):
            table.create_column(new_column)
