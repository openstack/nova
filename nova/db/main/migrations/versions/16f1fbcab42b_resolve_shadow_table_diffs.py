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

"""Resolve shadow table diffs

Revision ID: 16f1fbcab42b
Revises: 8f2f1571d55b
Create Date: 2021-08-20 13:26:30.204633
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '16f1fbcab42b'
down_revision = '8f2f1571d55b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # 244_increase_user_id_length_volume_usage_cache; the length in the
    # corresponding shadow table was not increased

    with op.batch_alter_table('shadow_volume_usage_cache') as batch_op:
        batch_op.alter_column(
            'user_id',
            type_=sa.String(64),
            existing_type=sa.String(36),
        )

    # 252_add_instance_extra_table; we shouldn't have created an index for the
    # shadow table

    op.drop_index(index_name='shadow_instance_extra_idx',
                  table_name='shadow_instance_extra')

    # 373_migration_uuid; we shouldn't have created an index for the shadow
    # table

    op.drop_index(index_name='shadow_migrations_uuid',
                  table_name='shadow_migrations')

    # 298_mysql_extra_specs_binary_collation; we changed the collation on the
    # main table but not the shadow table

    if bind.engine.name == 'mysql':
        op.execute(
            'ALTER TABLE shadow_instance_type_extra_specs '
            'CONVERT TO CHARACTER SET utf8 '
            'COLLATE utf8_bin'
        )
