# Copyright 2015 Intel Corporation
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

from migrate.changeset import UniqueConstraint
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    """Function enforces non-null value for keypairs name field."""
    meta = MetaData(bind=migrate_engine)
    key_pairs = Table('key_pairs', meta, autoload=True)

    # Note: Since we are altering name field, this constraint on name needs to
    # first be dropped before we can alter name. We then re-create the same
    # constraint. It was first added in 216_havana.py so no need to remove
    # constraint on downgrade.
    UniqueConstraint('user_id', 'name', 'deleted', table=key_pairs,
                     name='uniq_key_pairs0user_id0name0deleted').drop()

    key_pairs.c.name.alter(nullable=False)

    UniqueConstraint('user_id', 'name', 'deleted', table=key_pairs,
                     name='uniq_key_pairs0user_id0name0deleted').create()
