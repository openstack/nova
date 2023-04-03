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

"""Add compute_id to instance

Revision ID: 1acf2c98e646
Revises: 960aac0e09ea
Create Date: 2023-04-03 07:10:42.410832
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1acf2c98e646'
down_revision = '1b91788ec3a6'
branch_labels = None
depends_on = None


def upgrade():
    for prefix in ('', 'shadow_'):
        table_name = prefix + 'instances'
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'compute_id', sa.BigInteger(), nullable=True))
            if not prefix:
                batch_op.create_index('instances_compute_id_deleted_idx',
                                      ('compute_id', 'deleted'))

        table_name = prefix + 'migrations'
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'dest_compute_id', sa.BigInteger(), nullable=True))
            if not prefix:
                batch_op.create_index('migrations_dest_compute_id_deleted_idx',
                                      ('dest_compute_id', 'deleted'))
