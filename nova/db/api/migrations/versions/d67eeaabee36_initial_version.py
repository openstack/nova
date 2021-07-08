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

"""Initial version

Revision ID: d67eeaabee36
Revises:
Create Date: 2021-04-13 12:45:35.549607
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import dialects

from nova.db import types
from nova.objects import keypair

# revision identifiers, used by Alembic.
revision = 'd67eeaabee36'
down_revision = None
branch_labels = None
depends_on = None


def InetSmall():
    return sa.String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql'
    )


def upgrade():
    bind = op.get_bind()

    op.create_table(
        'cell_mappings',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255)),
        sa.Column('transport_url', sa.Text()),
        sa.Column('database_connection', sa.Text()),
        # NOTE(stephenfin): These were originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'disabled', sa.Boolean(create_constraint=False), default=False),
        sa.UniqueConstraint('uuid', name='uniq_cell_mappings0uuid'),
        sa.Index('uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'host_mappings',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('cell_id', sa.Integer, nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.UniqueConstraint(
            'host', name='uniq_host_mappings0host'),
        sa.Index('host_idx', 'host'),
        sa.ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=['cell_mappings.id']),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'instance_mappings',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_uuid', sa.String(length=36), nullable=False),
        sa.Column('cell_id', sa.Integer, nullable=True),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        # NOTE(stephenfin): These were originally added by sqlalchemy-migrate
        # which did not generate the constraints
        sa.Column(
            'queued_for_delete', sa.Boolean(create_constraint=False),
            default=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.UniqueConstraint(
            'instance_uuid', name='uniq_instance_mappings0instance_uuid'),
        sa.Index('instance_uuid_idx', 'instance_uuid'),
        sa.Index('project_id_idx', 'project_id'),
        sa.Index(
            'instance_mappings_user_id_project_id_idx', 'user_id',
            'project_id'),
        sa.ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=['cell_mappings.id']),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'flavors',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('memory_mb', sa.Integer, nullable=False),
        sa.Column('vcpus', sa.Integer, nullable=False),
        sa.Column('swap', sa.Integer, nullable=False),
        sa.Column('vcpu_weight', sa.Integer),
        sa.Column('flavorid', sa.String(length=255), nullable=False),
        sa.Column('rxtx_factor', sa.Float),
        sa.Column('root_gb', sa.Integer),
        sa.Column('ephemeral_gb', sa.Integer),
        sa.Column('disabled', sa.Boolean),
        sa.Column('is_public', sa.Boolean),
        sa.Column('description', sa.Text()),
        sa.UniqueConstraint('flavorid', name='uniq_flavors0flavorid'),
        sa.UniqueConstraint('name', name='uniq_flavors0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'flavor_extra_specs',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('flavor_id', sa.Integer, nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255)),
        sa.UniqueConstraint(
            'flavor_id', 'key', name='uniq_flavor_extra_specs0flavor_id0key'),
        sa.Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        sa.ForeignKeyConstraint(
            columns=['flavor_id'], refcolumns=['flavors.id']),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'flavor_projects',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('flavor_id', sa.Integer, nullable=False),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        sa.UniqueConstraint(
            'flavor_id', 'project_id',
            name='uniq_flavor_projects0flavor_id0project_id'),
        sa.ForeignKeyConstraint(
            columns=['flavor_id'], refcolumns=['flavors.id']),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'request_specs',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_uuid', sa.String(36), nullable=False),
        sa.Column('spec', types.MediumText(), nullable=False),
        sa.UniqueConstraint(
            'instance_uuid', name='uniq_request_specs0instance_uuid'),
        sa.Index('request_spec_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'build_requests',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('request_spec_id', sa.Integer, nullable=True),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('display_name', sa.String(length=255)),
        sa.Column('instance_metadata', sa.Text),
        sa.Column('progress', sa.Integer),
        sa.Column('vm_state', sa.String(length=255)),
        sa.Column('task_state', sa.String(length=255)),
        sa.Column('image_ref', sa.String(length=255)),
        sa.Column('access_ip_v4', InetSmall()),
        sa.Column('access_ip_v6', InetSmall()),
        sa.Column('info_cache', sa.Text),
        sa.Column('security_groups', sa.Text, nullable=True),
        sa.Column('config_drive', sa.Boolean, default=False, nullable=True),
        sa.Column('key_name', sa.String(length=255)),
        sa.Column(
            'locked_by',
            sa.Enum('owner', 'admin', name='build_requests0locked_by')),
        sa.Column('instance_uuid', sa.String(length=36)),
        sa.Column('instance', types.MediumText()),
        sa.Column('block_device_mappings', types.MediumText()),
        sa.Column('tags', sa.Text()),
        sa.UniqueConstraint(
            'instance_uuid', name='uniq_build_requests0instance_uuid'),
        sa.Index('build_requests_project_id_idx', 'project_id'),
        sa.Index('build_requests_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'key_pairs',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('fingerprint', sa.String(255)),
        sa.Column('public_key', sa.Text()),
        sa.Column(
            'type',
            sa.Enum('ssh', 'x509', name='keypair_types'),
            nullable=False, server_default=keypair.KEYPAIR_TYPE_SSH),
        sa.UniqueConstraint(
            'user_id', 'name', name='uniq_key_pairs0user_id0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'projects',
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.UniqueConstraint('external_id', name='uniq_projects0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    op.create_table(
        'users',
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.UniqueConstraint('external_id', name='uniq_users0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    op.create_table(
        'resource_classes',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.UniqueConstraint('name', name='uniq_resource_classes0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    nameargs = {}
    if bind.engine.name == 'mysql':
        nameargs['collation'] = 'utf8_bin'

    op.create_table(
        'resource_providers',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(36), nullable=False),
        sa.Column('name', sa.Unicode(200, **nameargs), nullable=True),
        sa.Column('generation', sa.Integer, default=0),
        sa.Column('can_host', sa.Integer, default=0),
        sa.Column(
            'root_provider_id', sa.Integer,
            sa.ForeignKey('resource_providers.id')),
        sa.Column(
            'parent_provider_id', sa.Integer,
            sa.ForeignKey('resource_providers.id')),
        sa.UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        sa.UniqueConstraint('name', name='uniq_resource_providers0name'),
        sa.Index('resource_providers_name_idx', 'name'),
        sa.Index('resource_providers_uuid_idx', 'uuid'),
        sa.Index(
            'resource_providers_root_provider_id_idx', 'root_provider_id'),
        sa.Index(
            'resource_providers_parent_provider_id_idx', 'parent_provider_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    op.create_table(
        'inventories',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('resource_provider_id', sa.Integer, nullable=False),
        sa.Column('resource_class_id', sa.Integer, nullable=False),
        sa.Column('total', sa.Integer, nullable=False),
        sa.Column('reserved', sa.Integer, nullable=False),
        sa.Column('min_unit', sa.Integer, nullable=False),
        sa.Column('max_unit', sa.Integer, nullable=False),
        sa.Column('step_size', sa.Integer, nullable=False),
        sa.Column('allocation_ratio', sa.Float, nullable=False),
        sa.Index(
            'inventories_resource_provider_id_idx', 'resource_provider_id'),
        sa.Index(
            'inventories_resource_provider_resource_class_idx',
            'resource_provider_id', 'resource_class_id'),
        sa.Index(
            'inventories_resource_class_id_idx', 'resource_class_id'),
        sa.UniqueConstraint(
            'resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    op.create_table(
        'traits',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('name', sa.Unicode(255, **nameargs), nullable=False),
        sa.UniqueConstraint('name', name='uniq_traits0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    op.create_table(
        'allocations',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('resource_provider_id', sa.Integer, nullable=False),
        sa.Column('consumer_id', sa.String(36), nullable=False),
        sa.Column('resource_class_id', sa.Integer, nullable=False),
        sa.Column('used', sa.Integer, nullable=False),
        sa.Index(
            'allocations_resource_provider_class_used_idx',
            'resource_provider_id', 'resource_class_id', 'used'),
        sa.Index(
            'allocations_resource_class_id_idx', 'resource_class_id'),
        sa.Index('allocations_consumer_id_idx', 'consumer_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    op.create_table(
        'consumers',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.Integer, nullable=False),
        sa.Column('user_id', sa.Integer, nullable=False),
        sa.Column(
            'generation', sa.Integer, default=0, server_default=sa.text('0'),
            nullable=False),
        sa.Index('consumers_project_id_uuid_idx', 'project_id', 'uuid'),
        sa.Index(
            'consumers_project_id_user_id_uuid_idx', 'project_id', 'user_id',
            'uuid'),
        sa.UniqueConstraint('uuid', name='uniq_consumers0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    op.create_table(
        'resource_provider_aggregates',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column(
            'resource_provider_id', sa.Integer, primary_key=True,
            nullable=False),
        sa.Column(
            'aggregate_id', sa.Integer, primary_key=True, nullable=False),
        sa.Index(
            'resource_provider_aggregates_aggregate_id_idx', 'aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    op.create_table(
        'resource_provider_traits',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column(
            'trait_id', sa.Integer, sa.ForeignKey('traits.id'),
            primary_key=True, nullable=False),
        sa.Column(
            'resource_provider_id', sa.Integer, primary_key=True,
            nullable=False),
        sa.Index(
            'resource_provider_traits_resource_provider_trait_idx',
            'resource_provider_id', 'trait_id'),
        sa.ForeignKeyConstraint(
            columns=['resource_provider_id'],
            refcolumns=['resource_providers.id']),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    op.create_table(
        'placement_aggregates',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), index=True),
        sa.UniqueConstraint('uuid', name='uniq_placement_aggregates0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    op.create_table(
        'aggregates',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('name', sa.String(length=255)),
        sa.Index('aggregate_uuid_idx', 'uuid'),
        sa.UniqueConstraint('name', name='uniq_aggregate0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'aggregate_hosts',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(length=255)),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        sa.UniqueConstraint(
            'host', 'aggregate_id',
            name='uniq_aggregate_hosts0host0aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'aggregate_metadata',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.UniqueConstraint(
            'aggregate_id', 'key',
            name='uniq_aggregate_metadata0aggregate_id0key'),
        sa.Index('aggregate_metadata_key_idx', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    op.create_table(
        'instance_groups',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255)),
        sa.UniqueConstraint(
            'uuid', name='uniq_instance_groups0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'instance_group_policy',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('policy', sa.String(length=255)),
        sa.Column(
            'group_id', sa.Integer, sa.ForeignKey('instance_groups.id'),
            nullable=False),
        sa.Column('rules', sa.Text),
        sa.Index('instance_group_policy_policy_idx', 'policy'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'instance_group_member',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_uuid', sa.String(length=255)),
        sa.Column(
            'group_id', sa.Integer, sa.ForeignKey('instance_groups.id'),
            nullable=False),
        sa.Index('instance_group_member_instance_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quota_classes',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('class_name', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255)),
        sa.Column('hard_limit', sa.Integer),
        sa.Index('quota_classes_class_name_idx', 'class_name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quota_usages',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('in_use', sa.Integer, nullable=False),
        sa.Column('reserved', sa.Integer, nullable=False),
        sa.Column('until_refresh', sa.Integer),
        sa.Column('user_id', sa.String(length=255)),
        sa.Index('quota_usages_project_id_idx', 'project_id'),
        sa.Index('quota_usages_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'quotas',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer),
        sa.UniqueConstraint(
            'project_id', 'resource', name='uniq_quotas0project_id0resource'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'project_user_quotas',
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer, nullable=True),
        sa.UniqueConstraint(
            'user_id', 'project_id', 'resource',
            name='uniq_project_user_quotas0user_id0project_id0resource'),
        sa.Index(
            'project_user_quotas_project_id_idx', 'project_id'),
        sa.Index(
            'project_user_quotas_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    op.create_table(
        'reservations',
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column(
            'usage_id', sa.Integer, sa.ForeignKey('quota_usages.id'),
            nullable=False),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255)),
        sa.Column('delta', sa.Integer, nullable=False),
        sa.Column('expire', sa.DateTime),
        sa.Column('user_id', sa.String(length=255)),
        sa.Index('reservations_project_id_idx', 'project_id'),
        sa.Index('reservations_uuid_idx', 'uuid'),
        sa.Index('reservations_expire_idx', 'expire'),
        sa.Index('reservations_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )


def downgrade():
    pass
