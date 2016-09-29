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

from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
from sqlalchemy.engine import reflection
from sqlalchemy import MetaData
from sqlalchemy import Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    build_requests = Table('build_requests', meta, autoload=True)
    request_specs = Table('request_specs', meta, autoload=True)

    for fkey in build_requests.foreign_keys:
        if fkey.target_fullname == 'request_specs.id':
            ForeignKeyConstraint(columns=['request_spec_id'],
                    refcolumns=[request_specs.c.id],
                    table=build_requests,
                    name=fkey.name).drop()
            break

    # These are being made nullable because they are no longer used after the
    # addition of the instance column. However they need a deprecation period
    # before they can be dropped.
    columns_to_nullify = ['request_spec_id', 'user_id', 'security_groups',
            'config_drive']
    for column in columns_to_nullify:
        getattr(build_requests.c, column).alter(nullable=True)

    inspector = reflection.Inspector.from_engine(migrate_engine)
    constrs = inspector.get_unique_constraints('build_requests')
    constr_names = [constr['name'] for constr in constrs]
    if 'uniq_build_requests0request_spec_id' in constr_names:
        UniqueConstraint('request_spec_id', table=build_requests,
                name='uniq_build_requests0request_spec_id').drop()
