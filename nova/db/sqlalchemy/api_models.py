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
from sqlalchemy import Boolean
from sqlalchemy import Column
from sqlalchemy import DateTime
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy import Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Index
from sqlalchemy import Integer
from sqlalchemy import orm
from sqlalchemy.orm import backref
from sqlalchemy import schema
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy import Unicode

LOG = logging.getLogger(__name__)


def MediumText():
    return Text().with_variant(MEDIUMTEXT(), 'mysql')


class _NovaAPIBase(models.ModelBase, models.TimestampMixin):
    pass


API_BASE = declarative_base(cls=_NovaAPIBase)


class AggregateHost(API_BASE):
    """Represents a host that is member of an aggregate."""
    __tablename__ = 'aggregate_hosts'
    __table_args__ = (schema.UniqueConstraint(
        "host", "aggregate_id",
         name="uniq_aggregate_hosts0host0aggregate_id"
        ),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255))
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class AggregateMetadata(API_BASE):
    """Represents a metadata key/value pair for an aggregate."""
    __tablename__ = 'aggregate_metadata'
    __table_args__ = (
        schema.UniqueConstraint("aggregate_id", "key",
            name="uniq_aggregate_metadata0aggregate_id0key"
            ),
        Index('aggregate_metadata_key_idx', 'key'),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)
    value = Column(String(255), nullable=False)
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class Aggregate(API_BASE):
    """Represents a cluster of hosts that exists in this zone."""
    __tablename__ = 'aggregates'
    __table_args__ = (Index('aggregate_uuid_idx', 'uuid'),
                      schema.UniqueConstraint(
                      "name", name="uniq_aggregate0name")
        )
    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36))
    name = Column(String(255))
    _hosts = orm.relationship(AggregateHost,
                    primaryjoin='Aggregate.id == AggregateHost.aggregate_id',
                    cascade='delete')
    _metadata = orm.relationship(AggregateMetadata,
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


class CellMapping(API_BASE):
    """Contains information on communicating with a cell"""
    __tablename__ = 'cell_mappings'
    __table_args__ = (Index('uuid_idx', 'uuid'),
                      schema.UniqueConstraint('uuid',
                          name='uniq_cell_mappings0uuid'))

    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)
    name = Column(String(255))
    transport_url = Column(Text())
    database_connection = Column(Text())
    disabled = Column(Boolean, default=False)
    host_mapping = orm.relationship('HostMapping',
                            backref=backref('cell_mapping', uselist=False),
                            foreign_keys=id,
                            primaryjoin=(
                                  'CellMapping.id == HostMapping.cell_id'))


class InstanceMapping(API_BASE):
    """Contains the mapping of an instance to which cell it is in"""
    __tablename__ = 'instance_mappings'
    __table_args__ = (Index('project_id_idx', 'project_id'),
                      Index('instance_uuid_idx', 'instance_uuid'),
                      schema.UniqueConstraint('instance_uuid',
                          name='uniq_instance_mappings0instance_uuid'),
                      Index('instance_mappings_user_id_project_id_idx',
                            'user_id', 'project_id'))

    id = Column(Integer, primary_key=True)
    instance_uuid = Column(String(36), nullable=False)
    cell_id = Column(Integer, ForeignKey('cell_mappings.id'),
            nullable=True)
    project_id = Column(String(255), nullable=False)
    # FIXME(melwitt): This should eventually be non-nullable, but we need a
    # transition period first.
    user_id = Column(String(255), nullable=True)
    queued_for_delete = Column(Boolean)
    cell_mapping = orm.relationship('CellMapping',
            backref=backref('instance_mapping', uselist=False),
            foreign_keys=cell_id,
            primaryjoin=('InstanceMapping.cell_id == CellMapping.id'))


class HostMapping(API_BASE):
    """Contains mapping of a compute host to which cell it is in"""
    __tablename__ = "host_mappings"
    __table_args__ = (Index('host_idx', 'host'),
                      schema.UniqueConstraint('host',
                        name='uniq_host_mappings0host'))

    id = Column(Integer, primary_key=True)
    cell_id = Column(Integer, ForeignKey('cell_mappings.id'),
            nullable=False)
    host = Column(String(255), nullable=False)


class RequestSpec(API_BASE):
    """Represents the information passed to the scheduler."""

    __tablename__ = 'request_specs'
    __table_args__ = (
        Index('request_spec_instance_uuid_idx', 'instance_uuid'),
        schema.UniqueConstraint('instance_uuid',
            name='uniq_request_specs0instance_uuid'),
        )

    id = Column(Integer, primary_key=True)
    instance_uuid = Column(String(36), nullable=False)
    spec = Column(MediumText(), nullable=False)


class Flavors(API_BASE):
    """Represents possible flavors for instances"""
    __tablename__ = 'flavors'
    __table_args__ = (
        schema.UniqueConstraint("flavorid", name="uniq_flavors0flavorid"),
        schema.UniqueConstraint("name", name="uniq_flavors0name"))

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    memory_mb = Column(Integer, nullable=False)
    vcpus = Column(Integer, nullable=False)
    root_gb = Column(Integer)
    ephemeral_gb = Column(Integer)
    flavorid = Column(String(255), nullable=False)
    swap = Column(Integer, nullable=False, default=0)
    rxtx_factor = Column(Float, default=1)
    vcpu_weight = Column(Integer)
    disabled = Column(Boolean, default=False)
    is_public = Column(Boolean, default=True)
    description = Column(Text)


class FlavorExtraSpecs(API_BASE):
    """Represents additional specs as key/value pairs for a flavor"""
    __tablename__ = 'flavor_extra_specs'
    __table_args__ = (
        Index('flavor_extra_specs_flavor_id_key_idx', 'flavor_id', 'key'),
        schema.UniqueConstraint('flavor_id', 'key',
            name='uniq_flavor_extra_specs0flavor_id0key'),
        {'mysql_collate': 'utf8_bin'},
    )

    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)
    value = Column(String(255))
    flavor_id = Column(Integer, ForeignKey('flavors.id'), nullable=False)
    flavor = orm.relationship(Flavors, backref='extra_specs',
                              foreign_keys=flavor_id,
                              primaryjoin=(
                                  'FlavorExtraSpecs.flavor_id == Flavors.id'))


class FlavorProjects(API_BASE):
    """Represents projects associated with flavors"""
    __tablename__ = 'flavor_projects'
    __table_args__ = (schema.UniqueConstraint('flavor_id', 'project_id',
        name='uniq_flavor_projects0flavor_id0project_id'),)

    id = Column(Integer, primary_key=True)
    flavor_id = Column(Integer, ForeignKey('flavors.id'), nullable=False)
    project_id = Column(String(255), nullable=False)
    flavor = orm.relationship(Flavors, backref='projects',
                              foreign_keys=flavor_id,
                              primaryjoin=(
                                  'FlavorProjects.flavor_id == Flavors.id'))


class BuildRequest(API_BASE):
    """Represents the information passed to the scheduler."""

    __tablename__ = 'build_requests'
    __table_args__ = (
        Index('build_requests_instance_uuid_idx', 'instance_uuid'),
        Index('build_requests_project_id_idx', 'project_id'),
        schema.UniqueConstraint('instance_uuid',
            name='uniq_build_requests0instance_uuid'),
        )

    id = Column(Integer, primary_key=True)
    # TODO(mriedem): instance_uuid should be nullable=False
    instance_uuid = Column(String(36))
    project_id = Column(String(255), nullable=False)
    instance = Column(MediumText())
    block_device_mappings = Column(MediumText())
    tags = Column(Text())
    # TODO(alaski): Drop these from the db in Ocata
    # columns_to_drop = ['request_spec_id', 'user_id', 'display_name',
    #         'instance_metadata', 'progress', 'vm_state', 'task_state',
    #         'image_ref', 'access_ip_v4', 'access_ip_v6', 'info_cache',
    #         'security_groups', 'config_drive', 'key_name', 'locked_by',
    #         'reservation_id', 'launch_index', 'hostname', 'kernel_id',
    #         'ramdisk_id', 'root_device_name', 'user_data']


class KeyPair(API_BASE):
    """Represents a public key pair for ssh / WinRM."""
    __tablename__ = 'key_pairs'
    __table_args__ = (
        schema.UniqueConstraint("user_id", "name",
                                name="uniq_key_pairs0user_id0name"),
    )
    id = Column(Integer, primary_key=True, nullable=False)

    name = Column(String(255), nullable=False)

    user_id = Column(String(255), nullable=False)

    fingerprint = Column(String(255))
    public_key = Column(Text())
    type = Column(Enum('ssh', 'x509', name='keypair_types'),
                  nullable=False, server_default='ssh')


class ResourceClass(API_BASE):
    """Represents the type of resource for an inventory or allocation."""
    __tablename__ = 'resource_classes'
    __table_args__ = (
        schema.UniqueConstraint("name", name="uniq_resource_classes0name"),
    )

    id = Column(Integer, primary_key=True, nullable=False)
    name = Column(String(255), nullable=False)


class ResourceProvider(API_BASE):
    """Represents a mapping to a providers of resources."""

    __tablename__ = "resource_providers"
    __table_args__ = (
        Index('resource_providers_uuid_idx', 'uuid'),
        schema.UniqueConstraint('uuid',
            name='uniq_resource_providers0uuid'),
        Index('resource_providers_name_idx', 'name'),
        Index('resource_providers_root_provider_id_idx',
              'root_provider_id'),
        Index('resource_providers_parent_provider_id_idx',
              'parent_provider_id'),
        schema.UniqueConstraint('name',
            name='uniq_resource_providers0name')
    )

    id = Column(Integer, primary_key=True, nullable=False)
    uuid = Column(String(36), nullable=False)
    name = Column(Unicode(200), nullable=True)
    generation = Column(Integer, default=0)
    # Represents the root of the "tree" that the provider belongs to
    root_provider_id = Column(Integer, ForeignKey('resource_providers.id'),
        nullable=True)
    # The immediate parent provider of this provider, or NULL if there is no
    # parent. If parent_provider_id == NULL then root_provider_id == id
    parent_provider_id = Column(Integer, ForeignKey('resource_providers.id'),
        nullable=True)


class Inventory(API_BASE):
    """Represents a quantity of available resource."""

    __tablename__ = "inventories"
    __table_args__ = (
        Index('inventories_resource_provider_id_idx',
              'resource_provider_id'),
        Index('inventories_resource_class_id_idx',
              'resource_class_id'),
        Index('inventories_resource_provider_resource_class_idx',
              'resource_provider_id', 'resource_class_id'),
        schema.UniqueConstraint('resource_provider_id', 'resource_class_id',
            name='uniq_inventories0resource_provider_resource_class')
    )

    id = Column(Integer, primary_key=True, nullable=False)
    resource_provider_id = Column(Integer, nullable=False)
    resource_class_id = Column(Integer, nullable=False)
    total = Column(Integer, nullable=False)
    reserved = Column(Integer, nullable=False)
    min_unit = Column(Integer, nullable=False)
    max_unit = Column(Integer, nullable=False)
    step_size = Column(Integer, nullable=False)
    allocation_ratio = Column(Float, nullable=False)
    resource_provider = orm.relationship(
        "ResourceProvider",
        primaryjoin=('Inventory.resource_provider_id == '
                     'ResourceProvider.id'),
        foreign_keys=resource_provider_id)


class Allocation(API_BASE):
    """A use of inventory."""

    __tablename__ = "allocations"
    __table_args__ = (
        Index('allocations_resource_provider_class_used_idx',
              'resource_provider_id', 'resource_class_id',
              'used'),
        Index('allocations_resource_class_id_idx',
              'resource_class_id'),
        Index('allocations_consumer_id_idx', 'consumer_id')
    )

    id = Column(Integer, primary_key=True, nullable=False)
    resource_provider_id = Column(Integer, nullable=False)
    consumer_id = Column(String(36), nullable=False)
    resource_class_id = Column(Integer, nullable=False)
    used = Column(Integer, nullable=False)
    resource_provider = orm.relationship(
        "ResourceProvider",
        primaryjoin=('Allocation.resource_provider_id == '
                     'ResourceProvider.id'),
        foreign_keys=resource_provider_id)


class ResourceProviderAggregate(API_BASE):
    """Associate a resource provider with an aggregate."""

    __tablename__ = 'resource_provider_aggregates'
    __table_args__ = (
        Index('resource_provider_aggregates_aggregate_id_idx',
              'aggregate_id'),
    )

    resource_provider_id = Column(Integer, primary_key=True, nullable=False)
    aggregate_id = Column(Integer, primary_key=True, nullable=False)


class PlacementAggregate(API_BASE):
    """A grouping of resource providers."""
    __tablename__ = 'placement_aggregates'
    __table_args__ = (
        schema.UniqueConstraint("uuid", name="uniq_placement_aggregates0uuid"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    uuid = Column(String(36), index=True)


class InstanceGroupMember(API_BASE):
    """Represents the members for an instance group."""
    __tablename__ = 'instance_group_member'
    __table_args__ = (
        Index('instance_group_member_instance_idx', 'instance_uuid'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    instance_uuid = Column(String(255))
    group_id = Column(Integer, ForeignKey('instance_groups.id'),
                      nullable=False)


class InstanceGroupPolicy(API_BASE):
    """Represents the policy type for an instance group."""
    __tablename__ = 'instance_group_policy'
    __table_args__ = (
        Index('instance_group_policy_policy_idx', 'policy'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    policy = Column(String(255))
    group_id = Column(Integer, ForeignKey('instance_groups.id'),
                      nullable=False)
    rules = Column(Text)


class InstanceGroup(API_BASE):
    """Represents an instance group.

    A group will maintain a collection of instances and the relationship
    between them.
    """

    __tablename__ = 'instance_groups'
    __table_args__ = (
        schema.UniqueConstraint('uuid', name='uniq_instance_groups0uuid'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255))
    project_id = Column(String(255))
    uuid = Column(String(36), nullable=False)
    name = Column(String(255))
    _policies = orm.relationship(InstanceGroupPolicy,
            primaryjoin='InstanceGroup.id == InstanceGroupPolicy.group_id')
    _members = orm.relationship(InstanceGroupMember,
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


class Quota(API_BASE):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then the
    default for the quota class is used.  If there is no row for a
    given quota class and resource, then the default for the
    deployment is used. If the row is present but the hard limit is
    Null, then the resource is unlimited.
    """

    __tablename__ = 'quotas'
    __table_args__ = (
        schema.UniqueConstraint("project_id", "resource",
        name="uniq_quotas0project_id0resource"
        ),
    )
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255))

    resource = Column(String(255), nullable=False)
    hard_limit = Column(Integer)


class ProjectUserQuota(API_BASE):
    """Represents a single quota override for a user with in a project."""

    __tablename__ = 'project_user_quotas'
    uniq_name = "uniq_project_user_quotas0user_id0project_id0resource"
    __table_args__ = (
        schema.UniqueConstraint("user_id", "project_id", "resource",
                                name=uniq_name),
        Index('project_user_quotas_project_id_idx',
              'project_id'),
        Index('project_user_quotas_user_id_idx',
              'user_id',)
    )
    id = Column(Integer, primary_key=True, nullable=False)

    project_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)

    resource = Column(String(255), nullable=False)
    hard_limit = Column(Integer)


class QuotaClass(API_BASE):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    __table_args__ = (
        Index('quota_classes_class_name_idx', 'class_name'),
    )
    id = Column(Integer, primary_key=True)

    class_name = Column(String(255))

    resource = Column(String(255))
    hard_limit = Column(Integer)


class QuotaUsage(API_BASE):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    __table_args__ = (
        Index('quota_usages_project_id_idx', 'project_id'),
        Index('quota_usages_user_id_idx', 'user_id'),
    )
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255))
    user_id = Column(String(255))
    resource = Column(String(255), nullable=False)

    in_use = Column(Integer, nullable=False)
    reserved = Column(Integer, nullable=False)

    @property
    def total(self):
        return self.in_use + self.reserved

    until_refresh = Column(Integer)


class Reservation(API_BASE):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    __table_args__ = (
        Index('reservations_project_id_idx', 'project_id'),
        Index('reservations_uuid_idx', 'uuid'),
        Index('reservations_expire_idx', 'expire'),
        Index('reservations_user_id_idx', 'user_id'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    uuid = Column(String(36), nullable=False)

    usage_id = Column(Integer, ForeignKey('quota_usages.id'), nullable=False)

    project_id = Column(String(255))
    user_id = Column(String(255))
    resource = Column(String(255))

    delta = Column(Integer, nullable=False)
    expire = Column(DateTime)

    usage = orm.relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='Reservation.usage_id == QuotaUsage.id')


class Trait(API_BASE):
    """Represents a trait."""

    __tablename__ = "traits"
    __table_args__ = (
        schema.UniqueConstraint('name', name='uniq_traits0name'),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    name = Column(Unicode(255), nullable=False)


class ResourceProviderTrait(API_BASE):
    """Represents the relationship between traits and resource provider"""

    __tablename__ = "resource_provider_traits"
    __table_args__ = (
        Index('resource_provider_traits_resource_provider_trait_idx',
              'resource_provider_id', 'trait_id'),
    )

    trait_id = Column(Integer, ForeignKey('traits.id'), primary_key=True,
                      nullable=False)
    resource_provider_id = Column(Integer,
                                  ForeignKey('resource_providers.id'),
                                  primary_key=True,
                                  nullable=False)


class Project(API_BASE):
    """The project is the Keystone project."""

    __tablename__ = 'projects'
    __table_args__ = (
        schema.UniqueConstraint(
            'external_id',
            name='uniq_projects0external_id',
        ),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    external_id = Column(String(255), nullable=False)


class User(API_BASE):
    """The user is the Keystone user."""

    __tablename__ = 'users'
    __table_args__ = (
        schema.UniqueConstraint(
            'external_id',
            name='uniq_users0external_id',
        ),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    external_id = Column(String(255), nullable=False)


class Consumer(API_BASE):
    """Represents a resource consumer."""

    __tablename__ = 'consumers'
    __table_args__ = (
        Index('consumers_project_id_uuid_idx', 'project_id', 'uuid'),
        Index('consumers_project_id_user_id_uuid_idx', 'project_id', 'user_id',
              'uuid'),
        schema.UniqueConstraint('uuid', name='uniq_consumers0uuid'),
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)
    project_id = Column(Integer, nullable=False)
    user_id = Column(Integer, nullable=False)
    # FIXME(mriedem): Change this to server_default=text("0") to match the
    # 059_add_consumer_generation script once bug 1776527 is fixed.
    generation = Column(Integer, nullable=False, server_default="0", default=0)
