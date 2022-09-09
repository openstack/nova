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

"""de-duplicate_indexes_in_instances__console_auth_tokens

Revision ID: 960aac0e09ea
Revises: ccb0fa1a2252
Create Date: 2022-09-15 17:00:23.175991
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = '960aac0e09ea'
down_revision = 'ccb0fa1a2252'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('console_auth_tokens', schema=None) as batch_op:
        batch_op.drop_index('console_auth_tokens_token_hash_idx')

    with op.batch_alter_table('instances', schema=None) as batch_op:
        batch_op.drop_index('uuid')
