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

from migrate.changeset.constraint import ForeignKeyConstraint
from migrate import UniqueConstraint
import sqlalchemy as sa
from sqlalchemy import dialects

from nova.db import types
from nova.objects import keypair


def InetSmall():
    return sa.String(length=39).with_variant(
        dialects.postgresql.INET(), 'postgresql'
    )


def upgrade(migrate_engine):
    meta = sa.MetaData()
    # NOTE(stephenfin): This is not compatible with SQLAlchemy 2.0 but neither
    # is sqlalchemy-migrate which requires this. We'll remove these migrations
    # when dropping SQLAlchemy < 2.x support
    meta.bind = migrate_engine

    cell_mappings = sa.Table('cell_mappings', meta,
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
        UniqueConstraint('uuid', name='uniq_cell_mappings0uuid'),
        sa.Index('uuid_idx', 'uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    host_mappings = sa.Table('host_mappings', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('cell_id', sa.Integer, nullable=False),
        sa.Column('host', sa.String(length=255), nullable=False),
        UniqueConstraint(
            'host', name='uniq_host_mappings0host'),
        sa.Index('host_idx', 'host'),
        ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=[cell_mappings.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    instance_mappings = sa.Table('instance_mappings', meta,
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
        UniqueConstraint(
            'instance_uuid', name='uniq_instance_mappings0instance_uuid'),
        sa.Index('instance_uuid_idx', 'instance_uuid'),
        sa.Index('project_id_idx', 'project_id'),
        sa.Index(
            'instance_mappings_user_id_project_id_idx', 'user_id',
            'project_id'),
        ForeignKeyConstraint(
            columns=['cell_id'], refcolumns=[cell_mappings.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavors = sa.Table('flavors', meta,
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
        UniqueConstraint('flavorid', name='uniq_flavors0flavorid'),
        UniqueConstraint('name', name='uniq_flavors0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavor_extra_specs = sa.Table('flavor_extra_specs', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('flavor_id', sa.Integer, nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255)),
        UniqueConstraint(
            'flavor_id', 'key', name='uniq_flavor_extra_specs0flavor_id0key'),
        sa.Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        ForeignKeyConstraint(columns=['flavor_id'], refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    flavor_projects = sa.Table('flavor_projects', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('flavor_id', sa.Integer, nullable=False),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        UniqueConstraint(
            'flavor_id', 'project_id',
            name='uniq_flavor_projects0flavor_id0project_id'),
        ForeignKeyConstraint(
            columns=['flavor_id'], refcolumns=[flavors.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    request_specs = sa.Table('request_specs', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('instance_uuid', sa.String(36), nullable=False),
        sa.Column('spec', types.MediumText(), nullable=False),
        UniqueConstraint(
            'instance_uuid', name='uniq_request_specs0instance_uuid'),
        sa.Index('request_spec_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    build_requests = sa.Table('build_requests', meta,
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
        UniqueConstraint(
            'instance_uuid', name='uniq_build_requests0instance_uuid'),
        sa.Index('build_requests_project_id_idx', 'project_id'),
        sa.Index('build_requests_instance_uuid_idx', 'instance_uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    keypairs = sa.Table('key_pairs', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('user_id', sa.String(255), nullable=False),
        sa.Column('fingerprint', sa.String(255)),
        sa.Column('public_key', sa.Text()),
        sa.Column(
            'type',
            sa.Enum('ssh', 'x509', metadata=meta, name='keypair_types'),
            nullable=False, server_default=keypair.KEYPAIR_TYPE_SSH),
        UniqueConstraint(
            'user_id', 'name', name='uniq_key_pairs0user_id0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    projects = sa.Table('projects', meta,
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        UniqueConstraint('external_id', name='uniq_projects0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    users = sa.Table('users', meta,
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('external_id', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        UniqueConstraint('external_id', name='uniq_users0external_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    resource_classes = sa.Table('resource_classes', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        UniqueConstraint('name', name='uniq_resource_classes0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    nameargs = {}
    if migrate_engine.name == 'mysql':
        nameargs['collation'] = 'utf8_bin'

    resource_providers = sa.Table(
        'resource_providers', meta,
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
        UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        UniqueConstraint('name', name='uniq_resource_providers0name'),
        sa.Index('resource_providers_name_idx', 'name'),
        sa.Index('resource_providers_uuid_idx', 'uuid'),
        sa.Index(
            'resource_providers_root_provider_id_idx', 'root_provider_id'),
        sa.Index(
            'resource_providers_parent_provider_id_idx', 'parent_provider_id'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    inventories = sa.Table(
        'inventories', meta,
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
        UniqueConstraint(
            'resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    traits = sa.Table(
        'traits', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column(
            'id', sa.Integer, primary_key=True, nullable=False,
            autoincrement=True),
        sa.Column('name', sa.Unicode(255, **nameargs), nullable=False),
        UniqueConstraint('name', name='uniq_traits0name'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    allocations = sa.Table(
        'allocations', meta,
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

    consumers = sa.Table(
        'consumers', meta,
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
        UniqueConstraint('uuid', name='uniq_consumers0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    resource_provider_aggregates = sa.Table(
        'resource_provider_aggregates', meta,
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

    resource_provider_traits = sa.Table(
        'resource_provider_traits', meta,
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
        ForeignKeyConstraint(
            columns=['resource_provider_id'],
            refcolumns=[resource_providers.c.id]),
        mysql_engine='InnoDB',
        mysql_charset='latin1',
    )

    placement_aggregates = sa.Table('placement_aggregates', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36), index=True),
        UniqueConstraint('uuid', name='uniq_placement_aggregates0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='latin1'
    )

    aggregates = sa.Table('aggregates', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('uuid', sa.String(length=36)),
        sa.Column('name', sa.String(length=255)),
        sa.Index('aggregate_uuid_idx', 'uuid'),
        UniqueConstraint('name', name='uniq_aggregate0name'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_hosts = sa.Table('aggregate_hosts', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('host', sa.String(length=255)),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        UniqueConstraint(
            'host', 'aggregate_id',
            name='uniq_aggregate_hosts0host0aggregate_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    aggregate_metadata = sa.Table('aggregate_metadata', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column(
            'aggregate_id', sa.Integer, sa.ForeignKey('aggregates.id'),
            nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        UniqueConstraint(
            'aggregate_id', 'key',
            name='uniq_aggregate_metadata0aggregate_id0key'),
        sa.Index('aggregate_metadata_key_idx', 'key'),
        mysql_engine='InnoDB',
        mysql_charset='utf8'
    )

    groups = sa.Table('instance_groups', meta,
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(length=255)),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('uuid', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=255)),
        UniqueConstraint(
            'uuid', name='uniq_instance_groups0uuid'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    group_policy = sa.Table('instance_group_policy', meta,
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

    group_member = sa.Table('instance_group_member', meta,
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

    quota_classes = sa.Table('quota_classes', meta,
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

    quota_usages = sa.Table('quota_usages', meta,
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

    quotas = sa.Table('quotas', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('project_id', sa.String(length=255)),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer),
        UniqueConstraint(
            'project_id', 'resource', name='uniq_quotas0project_id0resource'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    project_user_quotas = sa.Table('project_user_quotas', meta,
        sa.Column('id', sa.Integer, primary_key=True, nullable=False),
        sa.Column('created_at', sa.DateTime),
        sa.Column('updated_at', sa.DateTime),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('project_id', sa.String(length=255), nullable=False),
        sa.Column('resource', sa.String(length=255), nullable=False),
        sa.Column('hard_limit', sa.Integer, nullable=True),
        UniqueConstraint(
            'user_id', 'project_id', 'resource',
            name='uniq_project_user_quotas0user_id0project_id0resource'),
        sa.Index(
            'project_user_quotas_project_id_idx', 'project_id'),
        sa.Index(
            'project_user_quotas_user_id_idx', 'user_id'),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    reservations = sa.Table('reservations', meta,
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

    tables = [
        cell_mappings,
        host_mappings,
        instance_mappings,
        flavors,
        flavor_extra_specs,
        flavor_projects,
        request_specs,
        build_requests,
        keypairs,
        projects,
        users,
        resource_classes,
        resource_providers,
        inventories,
        traits,
        allocations,
        consumers,
        resource_provider_aggregates,
        resource_provider_traits,
        placement_aggregates,
        aggregates,
        aggregate_hosts,
        aggregate_metadata,
        groups,
        group_policy,
        group_member,
        quota_classes,
        quota_usages,
        quotas,
        project_user_quotas,
        reservations,
    ]
    for table in tables:
        table.create(checkfirst=True)
