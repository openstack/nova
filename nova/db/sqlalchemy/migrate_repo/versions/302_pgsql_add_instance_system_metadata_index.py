# Copyright 2015 Huawei.
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


from oslo_db.sqlalchemy import utils


INDEX_COLUMNS = ['instance_uuid']
# using the index name same with mysql
INDEX_NAME = 'instance_uuid'
SYS_META_TABLE_NAME = 'instance_system_metadata'


def upgrade(migrate_engine):
    """Add instance_system_metadata indexes missing on PostgreSQL and other DB.
    """

    # This index was already added by migration 216 for MySQL
    if migrate_engine.name != 'mysql':
        # Adds index for PostgreSQL and other DB
        if not utils.index_exists(migrate_engine, SYS_META_TABLE_NAME,
                                  INDEX_NAME):
            utils.add_index(migrate_engine, SYS_META_TABLE_NAME, INDEX_NAME,
                            INDEX_COLUMNS)
