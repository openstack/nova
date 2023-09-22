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


# NOTE(stephenfin): This is a list of fields that have been removed from
# various SQLAlchemy models but which still exist in the underlying tables. Our
# upgrade policy dictates that we remove fields from models at least one cycle
# before we remove the column from the underlying table. Not doing so would
# prevent us from applying the new database schema before rolling out any of
# the new code since the old code could attempt to access data in the removed
# columns. Alembic identifies this temporary mismatch between the models and
# underlying tables and attempts to resolve it. Tell it instead to ignore these
# until we're ready to remove them ourselves.
REMOVED_COLUMNS = []

# NOTE(stephenfin): A list of foreign key constraints that were removed when
# the column they were covering was removed.
REMOVED_FKEYS = []

# NOTE(stephenfin): A list of entire models that have been removed.
REMOVED_TABLES = {
    # Tables that were moved the placement database in Train. The
    # models were removed in Y and the tables can be dropped in Z or
    # later
    'allocations',
    'consumers',
    'inventories',
    'placement_aggregates',
    'projects',
    'resource_classes',
    'resource_provider_aggregates',
    'resource_provider_traits',
    'resource_providers',
    'traits',
    'users',
}


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
        back_populates='cell_mapping',
    )
    instance_mapping = orm.relationship(
        'InstanceMapping',
        back_populates='cell_mapping',
    )


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
        back_populates='instance_mapping',
    )


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

    cell_mapping = orm.relationship(
        'CellMapping',
        back_populates='host_mapping',
    )


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

    extra_specs = orm.relationship('FlavorExtraSpecs', back_populates='flavor')
    projects = orm.relationship('FlavorProjects', back_populates='flavor')


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

    flavor = orm.relationship(Flavors, back_populates='extra_specs')


class FlavorProjects(BASE):
    """Represents projects associated with flavors"""
    __tablename__ = 'flavor_projects'
    __table_args__ = (schema.UniqueConstraint('flavor_id', 'project_id',
        name='uniq_flavor_projects0flavor_id0project_id'),)

    id = sa.Column(sa.Integer, primary_key=True)
    flavor_id = sa.Column(
        sa.Integer, sa.ForeignKey('flavors.id'), nullable=False)
    project_id = sa.Column(sa.String(255), nullable=False)

    flavor = orm.relationship(Flavors, back_populates='projects')


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

    _policies = orm.relationship(InstanceGroupPolicy)
    _members = orm.relationship(InstanceGroupMember)

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

    usage = orm.relationship('QuotaUsage')
