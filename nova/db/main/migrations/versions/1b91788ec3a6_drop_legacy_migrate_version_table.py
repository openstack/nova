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

"""Drop legacy migrate_version table

Revision ID: 1b91788ec3a6
Revises: 960aac0e09ea
Create Date: 2023-02-01 16:46:24.206580
"""

from alembic import op
from sqlalchemy.engine import reflection

# revision identifiers, used by Alembic.
revision = '1b91788ec3a6'
down_revision = '960aac0e09ea'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = reflection.Inspector.from_engine(conn)
    tables = inspector.get_table_names()

    if 'migrate_version' in tables:
        op.drop_table('migrate_version')
