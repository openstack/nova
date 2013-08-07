# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table

from nova.db.sqlalchemy import utils


TABLE_NAME = 'cells'
OLD_NAME = 'uniq_cell_name0deleted'
NEW_NAME = 'uniq_cells0name0deleted'
COLUMNS = ('name', 'deleted')


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    table = Table(TABLE_NAME, meta, autoload=True)
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, OLD_NAME,
                                 *COLUMNS)
    uc_new = UniqueConstraint(*COLUMNS, table=table, name=NEW_NAME)
    uc_new.create()


def downgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    table = Table(TABLE_NAME, meta, autoload=True)
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, NEW_NAME,
                                 *COLUMNS)
    uc_old = UniqueConstraint(*COLUMNS, table=table, name=OLD_NAME)
    uc_old.create()
