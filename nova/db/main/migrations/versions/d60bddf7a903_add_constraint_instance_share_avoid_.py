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

"""add_constraint_instance_share_avoid_duplicates

Revision ID: d60bddf7a903
Revises: 13863f4e1612
Create Date: 2024-03-06 17:05:29.361678
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd60bddf7a903'
down_revision = '13863f4e1612'
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("share_mapping")
    op.create_table(
        "share_mapping",
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer, "sqlite"),
            primary_key=True,
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("uuid", sa.String(36)),
        sa.Column(
            "instance_uuid",
            sa.String(length=36),
            sa.ForeignKey(
                "instances.uuid", name="share_mapping_instance_uuid_fkey"
            ),
        ),
        sa.Column("share_id", sa.String(length=36)),
        sa.Column("status", sa.String(length=32)),
        sa.Column("tag", sa.String(48)),
        sa.Column("export_location", sa.Text),
        sa.Column("share_proto", sa.String(32)),
        sa.UniqueConstraint(
            "instance_uuid",
            "share_id",
            name="uniq_key_pairs0instance_uuid0share_id",
        ),
        sa.UniqueConstraint(
            "instance_uuid",
            "tag",
            name="uniq_key_pairs0instance_uuid0tag",
        ),
        sa.Index("share_idx", "share_id"),
        sa.Index(
            "share_mapping_instance_uuid_share_id_idx",
            "instance_uuid",
            "share_id",
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8",
    )
