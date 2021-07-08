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


from oslo_db.sqlalchemy import models
from oslo_log import log as logging
import sqlalchemy as sa
import sqlalchemy.dialects.mysql
from sqlalchemy.ext import declarative
from sqlalchemy import orm
from sqlalchemy import schema

from nova.db import types

LOG = logging.getLogger(__name__)


class _NovaAPIBase(models.ModelBase, models.TimestampMixin):
    pass


BASE = declarative.declarative_base(cls=_NovaAPIBase)


class AggregateHost(BASE):
    """Represents a host that is member of an aggregate."""
    __tablename__ = 'aggregate_hosts'
    __table_args__ = (schema.UniqueConstraint(
        "host", "aggregate_id",
         name="uniq_aggregate_hosts0host0aggregate_id"
        ),
    )
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    host = sa.Column(sa.String(255))
    aggregate_id = sa.Column(
        sa.Integer, sa.ForeignKey('aggregates.id'), nullable=False)


class AggregateMetadata(BASE):
    """Represents a metadata key/value pair for an aggregate."""
    __tablename__ = 'aggregate_metadata'
    __table_args__ = (
        schema.UniqueConstraint("aggregate_id", "key",
            name="uniq_aggregate_metadata0aggregate_id0key"
            ),
        sa.Index('aggregate_metadata_key_idx', 'key'),
    )
    id = sa.Column(sa.Integer, primary_key=True)
    key = sa.Column(sa.String(255), nullable=False)
    value = sa.Column(sa.String(255), nullable=False)
    aggregate_id = sa.Column(
        sa.Integer, sa.ForeignKey('aggregates.id'), nullable=False)


class Aggregate(BASE):
    """Represents a cluster of hosts that exists in this zone."""
    __tablename__ = 'aggregates'
    __table_args__ = (
        sa.Index('aggregate_uuid_idx', 'uuid'),
        schema.UniqueConstraint("name", name="uniq_aggregate0name")
    )
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    uuid = sa.Column(sa.String(36))
    name = sa.Column(sa.String(255))
    _hosts = orm.relationship(
        AggregateHost,
        primaryjoin='Aggregate.id == AggregateHost.aggregate_id',
        cascade='delete')
    _metadata = orm.relationship(
        AggregateMetadata,
        primaryjoin='Aggregate.id == AggregateMetadata.aggregate_id',
        cascade='delete')

    @property
    def _extra_keys(self):
        return ['hosts', 'metadetails', 'availability_zone']

    @property
    def hosts(self):
        return [h.host for h in self._hosts]

    @property
    def metadetails(self):
        return {m.key: m.value for m in self._metadata}

    @property
    def availability_zone(self):
        if 'availability_zone' not in self.metadetails:
            return None
        return self.metadetails['availability_zone']


class CellMapping(BASE):
    """Contains information on communicating with a cell"""
    __tablename__ = 'cell_mappings'
    __table_args__ = (
        sa.Index('uuid_idx', 'uuid'),
        schema.UniqueConstraint('uuid', name='uniq_cell_mappings0uuid'),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    uuid = sa.Column(sa.String(36), nullable=False)
    name = sa.Column(sa.String(255))
    transport_url = sa.Column(sa.Text())
    database_connection = sa.Column(sa.Text())
    disabled = sa.Column(sa.Boolean, default=False)
    host_mapping = orm.relationship(
        'HostMapping',
        backref=orm.backref('cell_mapping', uselist=False),
        foreign_keys=id,
        primaryjoin='CellMapping.id == HostMapping.cell_id')


class InstanceMapping(BASE):
    """Contains the mapping of an instance to which cell it is in"""
    __tablename__ = 'instance_mappings'
    __table_args__ = (
        sa.Index('project_id_idx', 'project_id'),
        sa.Index('instance_uuid_idx', 'instance_uuid'),
        schema.UniqueConstraint(
            'instance_uuid', name='uniq_instance_mappings0instance_uuid'),
        sa.Index(
            'instance_mappings_user_id_project_id_idx',
            'user_id',
            'project_id',
        ),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    instance_uuid = sa.Column(sa.String(36), nullable=False)
    cell_id = sa.Column(
        sa.Integer, sa.ForeignKey('cell_mappings.id'), nullable=True)
    project_id = sa.Column(sa.String(255), nullable=False)
    # FIXME(melwitt): This should eventually be non-nullable, but we need a
    # transition period first.
    user_id = sa.Column(sa.String(255), nullable=True)
    queued_for_delete = sa.Column(sa.Boolean)
    cell_mapping = orm.relationship(
        'CellMapping',
        backref=orm.backref('instance_mapping', uselist=False),
        foreign_keys=cell_id,
        primaryjoin='InstanceMapping.cell_id == CellMapping.id')


class HostMapping(BASE):
    """Contains mapping of a compute host to which cell it is in"""
    __tablename__ = "host_mappings"
    __table_args__ = (
        sa.Index('host_idx', 'host'),
        schema.UniqueConstraint('host', name='uniq_host_mappings0host'),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    cell_id = sa.Column(
        sa.Integer, sa.ForeignKey('cell_mappings.id'), nullable=False)
    host = sa.Column(sa.String(255), nullable=False)


class RequestSpec(BASE):
    """Represents the information passed to the scheduler."""

    __tablename__ = 'request_specs'
    __table_args__ = (
        sa.Index('request_spec_instance_uuid_idx', 'instance_uuid'),
        schema.UniqueConstraint(
            'instance_uuid', name='uniq_request_specs0instance_uuid'),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    instance_uuid = sa.Column(sa.String(36), nullable=False)
    spec = sa.Column(types.MediumText(), nullable=False)


class Flavors(BASE):
    """Represents possible flavors for instances"""
    __tablename__ = 'flavors'
    __table_args__ = (
        schema.UniqueConstraint("flavorid", name="uniq_flavors0flavorid"),
        schema.UniqueConstraint("name", name="uniq_flavors0name"))

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String(255), nullable=False)
    memory_mb = sa.Column(sa.Integer, nullable=False)
    vcpus = sa.Column(sa.Integer, nullable=False)
    root_gb = sa.Column(sa.Integer)
    ephemeral_gb = sa.Column(sa.Integer)
    flavorid = sa.Column(sa.String(255), nullable=False)
    swap = sa.Column(sa.Integer, nullable=False, default=0)
    rxtx_factor = sa.Column(sa.Float, default=1)
    vcpu_weight = sa.Column(sa.Integer)
    disabled = sa.Column(sa.Boolean, default=False)
    is_public = sa.Column(sa.Boolean, default=True)
    description = sa.Column(sa.Text)


class FlavorExtraSpecs(BASE):
    """Represents additional specs as key/value pairs for a flavor"""
    __tablename__ = 'flavor_extra_specs'
    __table_args__ = (
        sa.Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        schema.UniqueConstraint('flavor_id', 'key',
            name='uniq_flavor_extra_specs0flavor_id0key'),
        {'mysql_collate': 'utf8_bin'},
    )

    id = sa.Column(sa.Integer, primary_key=True)
    key = sa.Column(sa.String(255), nullable=False)
    value = sa.Column(sa.String(255))
    flavor_id = sa.Column(
        sa.Integer, sa.ForeignKey('flavors.id'), nullable=False)
    flavor = orm.relationship(
        Flavors, backref='extra_specs',
        foreign_keys=flavor_id,
        primaryjoin='FlavorExtraSpecs.flavor_id == Flavors.id')


class FlavorProjects(BASE):
    """Represents projects associated with flavors"""
    __tablename__ = 'flavor_projects'
    __table_args__ = (schema.UniqueConstraint('flavor_id', 'project_id',
        name='uniq_flavor_projects0flavor_id0project_id'),)

    id = sa.Column(sa.Integer, primary_key=True)
    flavor_id = sa.Column(
        sa.Integer, sa.ForeignKey('flavors.id'), nullable=False)
    project_id = sa.Column(sa.String(255), nullable=False)
    flavor = orm.relationship(
        Flavors, backref='projects',
        foreign_keys=flavor_id,
        primaryjoin='FlavorProjects.flavor_id == Flavors.id')


class BuildRequest(BASE):
    """Represents the information passed to the scheduler."""

    __tablename__ = 'build_requests'
    __table_args__ = (
        sa.Index('build_requests_instance_uuid_idx', 'instance_uuid'),
        sa.Index('build_requests_project_id_idx', 'project_id'),
        schema.UniqueConstraint(
            'instance_uuid', name='uniq_build_requests0instance_uuid'),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    # TODO(mriedem): instance_uuid should be nullable=False
    instance_uuid = sa.Column(sa.String(36))
    project_id = sa.Column(sa.String(255), nullable=False)
    instance = sa.Column(types.MediumText())
    block_device_mappings = sa.Column(types.MediumText())
    tags = sa.Column(sa.Text())
    # TODO(alaski): Drop these from the db in Ocata
    # columns_to_drop = ['request_spec_id', 'user_id', 'display_name',
    #         'instance_metadata', 'progress', 'vm_state', 'task_state',
    #         'image_ref', 'access_ip_v4', 'access_ip_v6', 'info_cache',
    #         'security_groups', 'config_drive', 'key_name', 'locked_by',
    #         'reservation_id', 'launch_index', 'hostname', 'kernel_id',
    #         'ramdisk_id', 'root_device_name', 'user_data']


class KeyPair(BASE):
    """Represents a public key pair for ssh / WinRM."""
    __tablename__ = 'key_pairs'
    __table_args__ = (
        schema.UniqueConstraint(
            "user_id", "name", name="uniq_key_pairs0user_id0name"),
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    name = sa.Column(sa.String(255), nullable=False)
    user_id = sa.Column(sa.String(255), nullable=False)
    fingerprint = sa.Column(sa.String(255))
    public_key = sa.Column(sa.Text())
    type = sa.Column(
        sa.Enum('ssh', 'x509', name='keypair_types'),
        nullable=False, server_default='ssh')


# TODO(stephenfin): Remove this as it's now unused post-placement split
class ResourceClass(BASE):
    """Represents the type of resource for an inventory or allocation."""
    __tablename__ = 'resource_classes'
    __table_args__ = (
        schema.UniqueConstraint("name", name="uniq_resource_classes0name"),
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    name = sa.Column(sa.String(255), nullable=False)


# TODO(stephenfin): Remove this as it's now unused post-placement split
class ResourceProvider(BASE):
    """Represents a mapping to a providers of resources."""

    __tablename__ = "resource_providers"
    __table_args__ = (
        sa.Index('resource_providers_uuid_idx', 'uuid'),
        schema.UniqueConstraint('uuid', name='uniq_resource_providers0uuid'),
        sa.Index('resource_providers_name_idx', 'name'),
        sa.Index(
            'resource_providers_root_provider_id_idx', 'root_provider_id'),
        sa.Index(
            'resource_providers_parent_provider_id_idx', 'parent_provider_id'),
        schema.UniqueConstraint(
            'name', name='uniq_resource_providers0name')
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    uuid = sa.Column(sa.String(36), nullable=False)
    name = sa.Column(sa.Unicode(200), nullable=True)
    generation = sa.Column(sa.Integer, default=0)
    # Represents the root of the "tree" that the provider belongs to
    root_provider_id = sa.Column(
        sa.Integer, sa.ForeignKey('resource_providers.id'), nullable=True)
    # The immediate parent provider of this provider, or NULL if there is no
    # parent. If parent_provider_id == NULL then root_provider_id == id
    parent_provider_id = sa.Column(
        sa.Integer, sa.ForeignKey('resource_providers.id'), nullable=True)
    # TODO(stephenfin): Drop these from the db at some point
    # columns_to_drop = ['can_host']


# TODO(stephenfin): Remove this as it's now unused post-placement split
class Inventory(BASE):
    """Represents a quantity of available resource."""

    __tablename__ = "inventories"
    __table_args__ = (
        sa.Index(
            'inventories_resource_provider_id_idx', 'resource_provider_id'),
        sa.Index(
            'inventories_resource_class_id_idx', 'resource_class_id'),
        sa.Index(
            'inventories_resource_provider_resource_class_idx',
            'resource_provider_id',
            'resource_class_id',
        ),
        schema.UniqueConstraint(
            'resource_provider_id',
            'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class'
        ),
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    resource_provider_id = sa.Column(sa.Integer, nullable=False)
    resource_class_id = sa.Column(sa.Integer, nullable=False)
    total = sa.Column(sa.Integer, nullable=False)
    reserved = sa.Column(sa.Integer, nullable=False)
    min_unit = sa.Column(sa.Integer, nullable=False)
    max_unit = sa.Column(sa.Integer, nullable=False)
    step_size = sa.Column(sa.Integer, nullable=False)
    allocation_ratio = sa.Column(sa.Float, nullable=False)
    resource_provider = orm.relationship(
        "ResourceProvider",
        primaryjoin='Inventory.resource_provider_id == ResourceProvider.id',
        foreign_keys=resource_provider_id)


# TODO(stephenfin): Remove this as it's now unused post-placement split
class Allocation(BASE):
    """A use of inventory."""

    __tablename__ = "allocations"
    __table_args__ = (
        sa.Index(
            'allocations_resource_provider_class_used_idx',
            'resource_provider_id',
            'resource_class_id',
            'used',
        ),
        sa.Index('allocations_resource_class_id_idx', 'resource_class_id'),
        sa.Index('allocations_consumer_id_idx', 'consumer_id')
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    resource_provider_id = sa.Column(sa.Integer, nullable=False)
    consumer_id = sa.Column(sa.String(36), nullable=False)
    resource_class_id = sa.Column(sa.Integer, nullable=False)
    used = sa.Column(sa.Integer, nullable=False)
    resource_provider = orm.relationship(
        "ResourceProvider",
        primaryjoin='Allocation.resource_provider_id == ResourceProvider.id',
        foreign_keys=resource_provider_id)


# TODO(stephenfin): Remove this as it's now unused post-placement split
class ResourceProviderAggregate(BASE):
    """Associate a resource provider with an aggregate."""

    __tablename__ = 'resource_provider_aggregates'
    __table_args__ = (
        sa.Index(
            'resource_provider_aggregates_aggregate_id_idx', 'aggregate_id'),
    )

    resource_provider_id = sa.Column(
        sa.Integer, primary_key=True, nullable=False)
    aggregate_id = sa.Column(sa.Integer, primary_key=True, nullable=False)


# TODO(stephenfin): Remove this as it's now unused post-placement split
class PlacementAggregate(BASE):
    """A grouping of resource providers."""
    __tablename__ = 'placement_aggregates'
    __table_args__ = (
        schema.UniqueConstraint("uuid", name="uniq_placement_aggregates0uuid"),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    uuid = sa.Column(sa.String(36), index=True)


class InstanceGroupMember(BASE):
    """Represents the members for an instance group."""
    __tablename__ = 'instance_group_member'
    __table_args__ = (
        sa.Index('instance_group_member_instance_idx', 'instance_uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    instance_uuid = sa.Column(sa.String(255))
    group_id = sa.Column(
        sa.Integer, sa.ForeignKey('instance_groups.id'), nullable=False)


class InstanceGroupPolicy(BASE):
    """Represents the policy type for an instance group."""
    __tablename__ = 'instance_group_policy'
    __table_args__ = (
        sa.Index('instance_group_policy_policy_idx', 'policy'),
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    policy = sa.Column(sa.String(255))
    group_id = sa.Column(
        sa.Integer, sa.ForeignKey('instance_groups.id'), nullable=False)
    rules = sa.Column(sa.Text)


class InstanceGroup(BASE):
    """Represents an instance group.

    A group will maintain a collection of instances and the relationship
    between them.
    """

    __tablename__ = 'instance_groups'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_instance_groups0uuid'),
    )

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    user_id = sa.Column(sa.String(255))
    project_id = sa.Column(sa.String(255))
    uuid = sa.Column(sa.String(36), nullable=False)
    name = sa.Column(sa.String(255))
    _policies = orm.relationship(
        InstanceGroupPolicy,
        primaryjoin='InstanceGroup.id == InstanceGroupPolicy.group_id')
    _members = orm.relationship(
        InstanceGroupMember,
        primaryjoin='InstanceGroup.id == InstanceGroupMember.group_id')

    @property
    def policy(self):
        if len(self._policies) > 1:
            msg = ("More than one policy (%(policies)s) is associated with "
                   "group %(group_name)s, only the first one in the list "
                   "would be returned.")
            LOG.warning(msg, {"policies": [p.policy for p in self._policies],
                              "group_name": self.name})
        return self._policies[0] if self._policies else None

    @property
    def members(self):
        return [m.instance_uuid for m in self._members]


class Quota(BASE):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then the
    default for the quota class is used.  If there is no row for a
    given quota class and resource, then the default for the
    deployment is used. If the row is present but the hard limit is
    Null, then the resource is unlimited.
    """
    __tablename__ = 'quotas'
    __table_args__ = (
        schema.UniqueConstraint(
            "project_id",
            "resource",
            name="uniq_quotas0project_id0resource"
        ),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    project_id = sa.Column(sa.String(255))
    resource = sa.Column(sa.String(255), nullable=False)
    hard_limit = sa.Column(sa.Integer)


class ProjectUserQuota(BASE):
    """Represents a single quota override for a user with in a project."""

    __tablename__ = 'project_user_quotas'
    __table_args__ = (
        schema.UniqueConstraint(
            "user_id",
            "project_id",
            "resource",
            name="uniq_project_user_quotas0user_id0project_id0resource",
        ),
        sa.Index(
            'project_user_quotas_project_id_idx', 'project_id'),
        sa.Index(
            'project_user_quotas_user_id_idx', 'user_id',)
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    project_id = sa.Column(sa.String(255), nullable=False)
    user_id = sa.Column(sa.String(255), nullable=False)
    resource = sa.Column(sa.String(255), nullable=False)
    hard_limit = sa.Column(sa.Integer)


class QuotaClass(BASE):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    __table_args__ = (
        sa.Index('quota_classes_class_name_idx', 'class_name'),
    )
    id = sa.Column(sa.Integer, primary_key=True)

    class_name = sa.Column(sa.String(255))

    resource = sa.Column(sa.String(255))
    hard_limit = sa.Column(sa.Integer)


class QuotaUsage(BASE):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    __table_args__ = (
        sa.Index('quota_usages_project_id_idx', 'project_id'),
        sa.Index('quota_usages_user_id_idx', 'user_id'),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    project_id = sa.Column(sa.String(255))
    user_id = sa.Column(sa.String(255))
    resource = sa.Column(sa.String(255), nullable=False)
    in_use = sa.Column(sa.Integer, nullable=False)
    reserved = sa.Column(sa.Integer, nullable=False)

    @property
    def total(self):
        return self.in_use + self.reserved

    until_refresh = sa.Column(sa.Integer)


class Reservation(BASE):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    __table_args__ = (
        sa.Index('reservations_project_id_idx', 'project_id'),
        sa.Index('reservations_uuid_idx', 'uuid'),
        sa.Index('reservations_expire_idx', 'expire'),
        sa.Index('reservations_user_id_idx', 'user_id'),
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    uuid = sa.Column(sa.String(36), nullable=False)
    usage_id = sa.Column(
        sa.Integer, sa.ForeignKey('quota_usages.id'), nullable=False)
    project_id = sa.Column(sa.String(255))
    user_id = sa.Column(sa.String(255))
    resource = sa.Column(sa.String(255))
    delta = sa.Column(sa.Integer, nullable=False)
    expire = sa.Column(sa.DateTime)
    usage = orm.relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='Reservation.usage_id == QuotaUsage.id')


class Trait(BASE):
    """Represents a trait."""

    __tablename__ = "traits"
    __table_args__ = (
        schema.UniqueConstraint('name', name='uniq_traits0name'),
    )

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    name = sa.Column(sa.Unicode(255), nullable=False)


# TODO(stephenfin): Remove this as it's now unused post-placement split
class ResourceProviderTrait(BASE):
    """Represents the relationship between traits and resource provider"""

    __tablename__ = "resource_provider_traits"
    __table_args__ = (
        sa.Index('resource_provider_traits_resource_provider_trait_idx',
              'resource_provider_id', 'trait_id'),
    )

    trait_id = sa.Column(
        sa.Integer, sa.ForeignKey('traits.id'), primary_key=True,
        nullable=False)
    resource_provider_id = sa.Column(
        sa.Integer,
        sa.ForeignKey('resource_providers.id'),
        primary_key=True,
        nullable=False)


# TODO(stephenfin): Remove this as it's unused
class Project(BASE):
    """The project is the Keystone project."""

    __tablename__ = 'projects'
    __table_args__ = (
        schema.UniqueConstraint(
            'external_id',
            name='uniq_projects0external_id',
        ),
    )

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    external_id = sa.Column(sa.String(255), nullable=False)


# TODO(stephenfin): Remove this as it's unused
class User(BASE):
    """The user is the Keystone user."""

    __tablename__ = 'users'
    __table_args__ = (
        schema.UniqueConstraint('external_id', name='uniq_users0external_id'),
    )

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    external_id = sa.Column(sa.String(255), nullable=False)


# TODO(stephenfin): Remove this as it's unused
class Consumer(BASE):
    """Represents a resource consumer."""

    __tablename__ = 'consumers'
    __table_args__ = (
        sa.Index('consumers_project_id_uuid_idx', 'project_id', 'uuid'),
        sa.Index(
            'consumers_project_id_user_id_uuid_idx',
            'project_id',
            'user_id',
            'uuid',
        ),
        schema.UniqueConstraint('uuid', name='uniq_consumers0uuid'),
    )

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = sa.Column(sa.String(36), nullable=False)
    project_id = sa.Column(sa.Integer, nullable=False)
    user_id = sa.Column(sa.Integer, nullable=False)
    # FIXME(mriedem): Change this to server_default=text("0") to match the
    # 059_add_consumer_generation script once bug 1776527 is fixed.
    generation = sa.Column(
        sa.Integer, nullable=False, server_default="0", default=0)
