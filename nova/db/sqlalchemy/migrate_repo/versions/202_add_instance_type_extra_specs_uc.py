# Copyright 2013 Mirantis Inc.
# All Rights Reserved
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table

from nova.db.sqlalchemy import utils


UC_NAME = 'uniq_instance_type_extra_specs0instance_type_id0key0deleted'
COLUMNS = ('instance_type_id', 'key', 'deleted')
TABLE_NAME = 'instance_type_extra_specs'


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    t = Table(TABLE_NAME, meta, autoload=True)

    utils.drop_old_duplicate_entries_from_table(migrate_engine, TABLE_NAME,
                                                True, *COLUMNS)
    uc = UniqueConstraint(*COLUMNS, table=t, name=UC_NAME)
    uc.create()


def downgrade(migrate_engine):
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME, *COLUMNS)
