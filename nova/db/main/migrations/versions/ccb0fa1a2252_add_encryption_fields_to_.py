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

"""Add encryption fields to BlockDeviceMapping

Revision ID: ccb0fa1a2252
Revises: 16f1fbcab42b
Create Date: 2022-01-12 15:22:47.524285
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'ccb0fa1a2252'
down_revision = '16f1fbcab42b'
branch_labels = None
depends_on = None


def upgrade():
    for prefix in ('', 'shadow_'):
        table_name = prefix + 'block_device_mapping'
        with op.batch_alter_table(table_name, schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'encrypted',
                    sa.Boolean(),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    'encryption_secret_uuid',
                    sa.String(length=36),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column('encryption_format',
                    sa.String(length=128),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column('encryption_options',
                    sa.String(length=4096),
                    nullable=True,
                )
            )
