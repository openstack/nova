# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""db: add indexes for source/dest migrations

Revision ID: ab450ba04102
Revises: 2903cd72dc14
Create Date: 2025-08-26 17:12:03.998297
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'ab450ba04102'
down_revision = '2903cd72dc14'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("migrations", schema=None) as batch_op:
        batch_op.create_index(
            "migrations_by_dest_host_nodes_and_status_idx",
            ["deleted", "dest_compute", "dest_node", "status"],
            unique=False,
        )
        batch_op.create_index(
            "migrations_by_src_host_nodes_and_status_idx",
            ["deleted", "source_compute", "source_node", "status"],
            unique=False,
        )
