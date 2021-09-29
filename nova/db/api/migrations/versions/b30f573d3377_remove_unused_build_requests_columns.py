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

"""Remove unused build_requests columns

Revision ID: b30f573d3377
Revises: d67eeaabee36
Create Date: 2021-09-27 14:46:05.986174
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'b30f573d3377'
down_revision = 'd67eeaabee36'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('build_requests', schema=None) as batch_op:
        batch_op.drop_column('vm_state')
        batch_op.drop_column('access_ip_v6')
        batch_op.drop_column('config_drive')
        batch_op.drop_column('locked_by')
        batch_op.drop_column('security_groups')
        batch_op.drop_column('progress')
        batch_op.drop_column('info_cache')
        batch_op.drop_column('display_name')
        batch_op.drop_column('instance_metadata')
        batch_op.drop_column('image_ref')
        batch_op.drop_column('key_name')
        batch_op.drop_column('user_id')
        batch_op.drop_column('access_ip_v4')
        batch_op.drop_column('task_state')
        batch_op.drop_column('request_spec_id')
