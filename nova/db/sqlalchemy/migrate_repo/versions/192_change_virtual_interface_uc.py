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
from sqlalchemy import MetaData, Table, Index

from nova.db.sqlalchemy import utils


OLD_UC_NAME = 'uniq_virtual_interfaces0address'
UC_NAME = 'uniq_virtual_interfaces0address0deleted'
OLD_COLUMN = 'address'
COLUMNS = ('address', 'deleted')
TABLE_NAME = 'virtual_interfaces'


def upgrade(migrate_engine):
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, OLD_UC_NAME,
                                 OLD_COLUMN)
    meta = MetaData(bind=migrate_engine)
    t = Table(TABLE_NAME, meta, autoload=True)
    if migrate_engine.name == "mysql":
        index = Index(OLD_COLUMN, t.c[OLD_COLUMN], unique=True)
        index.drop()
    uc = UniqueConstraint(*COLUMNS, table=t, name=UC_NAME)
    uc.create()


def downgrade(migrate_engine):
    utils.drop_unique_constraint(migrate_engine, TABLE_NAME, UC_NAME, *COLUMNS)
    meta = MetaData(bind=migrate_engine)
    t = Table(TABLE_NAME, meta, autoload=True)
    delete_statement = t.delete().where(t.c.deleted != 0)
    migrate_engine.execute(delete_statement)
    uc = UniqueConstraint(OLD_COLUMN, table=t, name=OLD_UC_NAME)
    uc.create()
    if migrate_engine.name == "mysql":
        index = Index(OLD_COLUMN, t.c[OLD_COLUMN], unique=True)
        index.create()
