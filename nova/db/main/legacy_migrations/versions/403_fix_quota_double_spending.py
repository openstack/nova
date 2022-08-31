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

# This is a placeholder for backports.
# Do not use this number for new work.  New work starts after
# all the placeholders.
#
# See this for more information:
# http://lists.openstack.org/pipermail/openstack-dev/2013-March/006827.html


from sqlalchemy.engine.reflection import Inspector
from sqlalchemy import MetaData, Table
from migrate.changeset.constraint import UniqueConstraint


COLUMNS = ['project_id', 'user_id', 'resource', 'deleted']


def _build_constraint(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    table = Table('quota_usages', meta, autoload=True)
    return UniqueConstraint(
        *COLUMNS,
        table=table,
    )


def upgrade(migrate_engine):
    # check if the constraint already exists
    inspector = Inspector(migrate_engine)
    wanted_column_names = sorted(COLUMNS)
    for constraint in inspector.get_unique_constraints('quota_usages'):
        column_names = sorted(constraint['column_names'])
        if column_names == wanted_column_names:
            return

    cons = _build_constraint(migrate_engine)
    cons.create()
