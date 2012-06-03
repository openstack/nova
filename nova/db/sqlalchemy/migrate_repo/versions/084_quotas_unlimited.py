# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc
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

import sqlalchemy


def upgrade(migrate_engine):
    """Map quotas hard_limit from NULL to -1"""
    _migrate_unlimited(migrate_engine, None, -1)


def downgrade(migrate_engine):
    """Map quotas hard_limit from -1 to NULL"""
    _migrate_unlimited(migrate_engine, -1, None)


def _migrate_unlimited(migrate_engine, old_limit, new_limit):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    def _migrate(table_name):
        table = sqlalchemy.Table(table_name, meta, autoload=True)
        table.update().\
            where(table.c.hard_limit == old_limit).\
            values(hard_limit=new_limit).execute()

    _migrate('quotas')
    _migrate('quota_classes')
