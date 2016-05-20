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

from migrate import UniqueConstraint
from sqlalchemy import Column
from sqlalchemy.engine import reflection
from sqlalchemy import Index
from sqlalchemy import MetaData
from sqlalchemy import String
from sqlalchemy import Table
from sqlalchemy import Text


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    build_requests = Table('build_requests', meta, autoload=True)

    columns_to_add = [
            ('instance_uuid',
                Column('instance_uuid', String(length=36))),
            ('instance',
                Column('instance', Text())),
    ]
    for (col_name, column) in columns_to_add:
        if not hasattr(build_requests.c, col_name):
            build_requests.create_column(column)

    for index in build_requests.indexes:
        if [c.name for c in index.columns] == ['instance_uuid']:
            break
    else:
        index = Index('build_requests_instance_uuid_idx',
                build_requests.c.instance_uuid)
        index.create()

    inspector = reflection.Inspector.from_engine(migrate_engine)
    constrs = inspector.get_unique_constraints('build_requests')
    constr_names = [constr['name'] for constr in constrs]
    if 'uniq_build_requests0instance_uuid' not in constr_names:
        UniqueConstraint('instance_uuid', table=build_requests,
                name='uniq_build_requests0instance_uuid').create()
