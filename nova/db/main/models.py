# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Piston Cloud Computing, Inc.
# All Rights Reserved.
#
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
"""
SQLAlchemy models for nova data.
"""

from oslo_config import cfg
from oslo_db.sqlalchemy import models
from oslo_utils import timeutils
import sqlalchemy as sa
import sqlalchemy.dialects.mysql
from sqlalchemy.ext import declarative
from sqlalchemy import orm
from sqlalchemy import schema

from nova.db import types

CONF = cfg.CONF

# NOTE(stephenfin): This is a list of fields that have been removed from
# various SQLAlchemy models but which still exist in the underlying tables. Our
# upgrade policy dictates that we remove fields from models at least one cycle
# before we remove the column from the underlying table. Not doing so would
# prevent us from applying the new database schema before rolling out any of
# the new code since the old code could attempt to access data in the removed
# columns. Alembic identifies this temporary mismatch between the models and
# underlying tables and attempts to resolve it. Tell it instead to ignore these
# until we're ready to remove them ourselves.
REMOVED_COLUMNS = {
    ('instances', 'internal_id'),
    ('instance_extra', 'vpmems'),
}

# NOTE(stephenfin): A list of foreign key constraints that were removed when
# the column they were covering was removed.
REMOVED_FKEYS = []

# NOTE(stephenfin): A list of entire models that have been removed.
REMOVED_TABLES = {
    # Tables that were moved to the API database in Newton. The models
    # were removed in Y and the tables can be dropped in Z or later
    'aggregate_hosts',
    'aggregate_metadata',
    'aggregates',
    'allocations',
    'instance_group_member',
    'instance_group_policy',
    'instance_groups',
    'instance_type_extra_specs',
    'instance_type_projects',
    'instance_types',
    'inventories',
    'key_pairs',
    'resource_provider_aggregates',
    'resource_providers',

    # Tables for the removed XenAPI virt driver. The models were
    # removed in Y and the tables can be dropped in Z or later
    'agent_builds',
    'bw_usage_cache',
    'console_pools',
    'consoles',

    # Tables for the removed cells v1 feature. The model was removed in
    # Y and the table can be dropped in Z or later
    'cells',

    # Tables for the removed volume snapshot feature. The model was
    # removed in Y and the table can be dropped in Z or later
    'snapshots',

    # Tables for the removed in-tree EC2 API. The models were removed
    # in Y and the table can be dropped in Z or later
    'snapshot_id_mappings',
    'volume_id_mappings',

    # Tables for the removed nova-network feature. The models were
    # removed in Y and the tables can be dropped in Z or later
    'dns_domains',
    'fixed_ips',
    'floating_ips',
    'networks',
    'provider_fw_rules',
    'security_group_default_rules',
}

# we don't configure 'cls' since we have models that don't use the
# TimestampMixin
BASE = declarative.declarative_base()


class NovaBase(models.TimestampMixin, models.ModelBase):

    def __copy__(self):
        """Implement a safe copy.copy().

        SQLAlchemy-mapped objects travel with an object
        called an InstanceState, which is pegged to that object
        specifically and tracks everything about that object.  It's
        critical within all attribute operations, including gets
        and deferred loading.   This object definitely cannot be
        shared among two instances, and must be handled.

        The copy routine here makes use of session.merge() which
        already essentially implements a "copy" style of operation,
        which produces a new instance with a new InstanceState and copies
        all the data along mapped attributes without using any SQL.

        The mode we are using here has the caveat that the given object
        must be "clean", e.g. that it has no database-loaded state
        that has been updated and not flushed.   This is a good thing,
        as creating a copy of an object including non-flushed, pending
        database state is probably not a good idea; neither represents
        what the actual row looks like, and only one should be flushed.

        """
        session = orm.Session()

        copy = session.merge(self, load=False)
        session.expunge(copy)
        return copy


class Service(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    __table_args__ = (
        schema.UniqueConstraint("host", "topic", "deleted",
                                name="uniq_services0host0topic0deleted"),
        schema.UniqueConstraint("host", "binary", "deleted",
                                name="uniq_services0host0binary0deleted"),
        sa.Index('services_uuid_idx', 'uuid', unique=True),
    )

    id = sa.Column(sa.Integer, primary_key=True)
    uuid = sa.Column(sa.String(36), nullable=True)
    host = sa.Column(sa.String(255))
    binary = sa.Column(sa.String(255))
    topic = sa.Column(sa.String(255))
    report_count = sa.Column(sa.Integer, nullable=False, default=0)
    disabled = sa.Column(sa.Boolean, default=False)
    disabled_reason = sa.Column(sa.String(255))
    last_seen_up = sa.Column(sa.DateTime, nullable=True)
    forced_down = sa.Column(sa.Boolean, default=False)
    version = sa.Column(sa.Integer, default=0)

    instance = orm.relationship(
        "Instance",
        backref='services',
        primaryjoin='and_(Service.host == Instance.host,'
                    'Service.binary == "nova-compute",'
                    'Instance.deleted == 0)',
        foreign_keys=host,
    )


class ComputeNode(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a running compute service on a host."""

    __tablename__ = 'compute_nodes'
    __table_args__ = (
        sa.Index('compute_nodes_uuid_idx', 'uuid', unique=True),
        schema.UniqueConstraint(
            'host', 'hypervisor_hostname', 'deleted',
            name="uniq_compute_nodes0host0hypervisor_hostname0deleted"),
    )
    id = sa.Column(sa.Integer, primary_key=True)
    service_id = sa.Column(sa.Integer, nullable=True)

    # FIXME(sbauza: Host field is nullable because some old Juno compute nodes
    # can still report stats from an old ResourceTracker without setting this
    # field.
    # This field has to be set non-nullable in a later cycle (probably Lxxx)
    # once we are sure that all compute nodes in production report it.
    host = sa.Column(sa.String(255), nullable=True)
    uuid = sa.Column(sa.String(36), nullable=True)
    vcpus = sa.Column(sa.Integer, nullable=False)
    memory_mb = sa.Column(sa.Integer, nullable=False)
    local_gb = sa.Column(sa.Integer, nullable=False)
    vcpus_used = sa.Column(sa.Integer, nullable=False)
    memory_mb_used = sa.Column(sa.Integer, nullable=False)
    local_gb_used = sa.Column(sa.Integer, nullable=False)
    hypervisor_type = sa.Column(types.MediumText(), nullable=False)
    hypervisor_version = sa.Column(sa.Integer, nullable=False)
    hypervisor_hostname = sa.Column(sa.String(255))

    # Free Ram, amount of activity (resize, migration, boot, etc) and
    # the number of running VM's are a good starting point for what's
    # important when making scheduling decisions.
    free_ram_mb = sa.Column(sa.Integer)
    free_disk_gb = sa.Column(sa.Integer)
    current_workload = sa.Column(sa.Integer)
    running_vms = sa.Column(sa.Integer)

    # Note(masumotok): Expected Strings example:
    #
    # '{"arch":"x86_64",
    #   "model":"Nehalem",
    #   "topology":{"sockets":1, "threads":2, "cores":3},
    #   "features":["tdtscp", "xtpr"]}'
    #
    # Points are "json translatable" and it must have all dictionary keys
    # above, since it is copied from <cpu> tag of getCapabilities()
    # (See libvirt.virtConnection).
    cpu_info = sa.Column(types.MediumText(), nullable=False)
    disk_available_least = sa.Column(sa.Integer)
    host_ip = sa.Column(types.IPAddress())
    supported_instances = sa.Column(sa.Text)
    metrics = sa.Column(sa.Text)

    # Note(yongli): json string PCI Stats
    # '[{"vendor_id":"8086", "product_id":"1234", "count":3 }, ...]'
    pci_stats = sa.Column(sa.Text)

    # extra_resources is a json string containing arbitrary
    # data about additional resources.
    extra_resources = sa.Column(sa.Text)

    # json-encode string containing compute node statistics
    stats = sa.Column(sa.Text, default='{}')

    # json-encoded dict that contains NUMA topology as generated by
    # objects.NUMATopology._to_json()
    numa_topology = sa.Column(sa.Text)

    # allocation ratios provided by the RT
    ram_allocation_ratio = sa.Column(sa.Float, nullable=True)
    cpu_allocation_ratio = sa.Column(sa.Float, nullable=True)
    disk_allocation_ratio = sa.Column(sa.Float, nullable=True)
    mapped = sa.Column(sa.Integer, nullable=True, default=0)


class Certificate(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a x509 certificate."""
    __tablename__ = 'certificates'
    __table_args__ = (
        sa.Index(
            'certificates_project_id_deleted_idx', 'project_id', 'deleted',
        ),
        sa.Index('certificates_user_id_deleted_idx', 'user_id', 'deleted')
    )
    id = sa.Column(sa.Integer, primary_key=True)

    user_id = sa.Column(sa.String(255))
    project_id = sa.Column(sa.String(255))
    file_name = sa.Column(sa.String(255))


class Instance(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a guest VM."""
    __tablename__ = 'instances'
    __table_args__ = (
        sa.Index('uuid', 'uuid', unique=True),
        sa.Index('instances_project_id_idx', 'project_id'),
        sa.Index('instances_project_id_deleted_idx',
              'project_id', 'deleted'),
        sa.Index('instances_reservation_id_idx',
              'reservation_id'),
        sa.Index('instances_terminated_at_launched_at_idx',
              'terminated_at', 'launched_at'),
        sa.Index('instances_uuid_deleted_idx',
              'uuid', 'deleted'),
        sa.Index('instances_task_state_updated_at_idx',
              'task_state', 'updated_at'),
        sa.Index('instances_host_node_deleted_idx',
              'host', 'node', 'deleted'),
        sa.Index('instances_host_deleted_cleaned_idx',
              'host', 'deleted', 'cleaned'),
        sa.Index('instances_deleted_created_at_idx',
              'deleted', 'created_at'),
        sa.Index('instances_updated_at_project_id_idx',
              'updated_at', 'project_id'),
        schema.UniqueConstraint('uuid', name='uniq_instances0uuid'),
    )
    injected_files = []

    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        try:
            base_name = CONF.instance_name_template % self.id
        except TypeError:
            # Support templates like "uuid-%(uuid)s", etc.
            info = {}
            # NOTE(russellb): Don't use self.iteritems() here, as it will
            # result in infinite recursion on the name property.
            for column in iter(orm.object_mapper(self).columns):
                key = column.name
                # prevent recursion if someone specifies %(name)s
                # %(name)s will not be valid.
                if key == 'name':
                    continue
                info[key] = self[key]
            try:
                base_name = CONF.instance_name_template % info
            except KeyError:
                base_name = self.uuid
        return base_name

    @property
    def _extra_keys(self):
        return ['name']

    user_id = sa.Column(sa.String(255))
    project_id = sa.Column(sa.String(255))

    image_ref = sa.Column(sa.String(255))
    kernel_id = sa.Column(sa.String(255))
    ramdisk_id = sa.Column(sa.String(255))
    hostname = sa.Column(sa.String(255))

    launch_index = sa.Column(sa.Integer)
    key_name = sa.Column(sa.String(255))
    key_data = sa.Column(types.MediumText())

    power_state = sa.Column(sa.Integer)
    vm_state = sa.Column(sa.String(255))
    task_state = sa.Column(sa.String(255))

    memory_mb = sa.Column(sa.Integer)
    vcpus = sa.Column(sa.Integer)
    root_gb = sa.Column(sa.Integer)
    ephemeral_gb = sa.Column(sa.Integer)
    ephemeral_key_uuid = sa.Column(sa.String(36))

    # This is not related to hostname, above.  It refers
    #  to the nova node.
    host = sa.Column(sa.String(255))
    # To identify the "ComputeNode" which the instance resides in.
    # This equals to ComputeNode.hypervisor_hostname.
    node = sa.Column(sa.String(255))

    # *not* flavorid, this is the internal primary_key
    instance_type_id = sa.Column(sa.Integer)

    user_data = sa.Column(types.MediumText())

    reservation_id = sa.Column(sa.String(255))

    launched_at = sa.Column(sa.DateTime)
    terminated_at = sa.Column(sa.DateTime)

    # This always refers to the availability_zone kwarg passed in /servers and
    # provided as an API option, not at all related to the host AZ the instance
    # belongs to.
    availability_zone = sa.Column(sa.String(255))

    # User editable field for display in user-facing UIs
    display_name = sa.Column(sa.String(255))
    display_description = sa.Column(sa.String(255))

    # To remember on which host an instance booted.
    # An instance may have moved to another host by live migration.
    launched_on = sa.Column(types.MediumText())

    # locked is superseded by locked_by and locked is not really
    # necessary but still used in API code so it remains.
    locked = sa.Column(sa.Boolean)
    locked_by = sa.Column(
        sa.Enum('owner', 'admin', name='instances0locked_by'))

    os_type = sa.Column(sa.String(255))
    architecture = sa.Column(sa.String(255))
    vm_mode = sa.Column(sa.String(255))
    uuid = sa.Column(sa.String(36), nullable=False)

    root_device_name = sa.Column(sa.String(255))
    default_ephemeral_device = sa.Column(sa.String(255))
    default_swap_device = sa.Column(sa.String(255))
    config_drive = sa.Column(sa.String(255))

    # User editable field meant to represent what ip should be used
    # to connect to the instance
    access_ip_v4 = sa.Column(types.IPAddress())
    access_ip_v6 = sa.Column(types.IPAddress())

    auto_disk_config = sa.Column(sa.Boolean())
    progress = sa.Column(sa.Integer)

    # EC2 instance_initiated_shutdown_terminate
    # True: -> 'terminate'
    # False: -> 'stop'
    # Note(maoy): currently Nova will always stop instead of terminate
    # no matter what the flag says. So we set the default to False.
    shutdown_terminate = sa.Column(sa.Boolean(), default=False)

    # EC2 disable_api_termination
    disable_terminate = sa.Column(sa.Boolean(), default=False)

    # OpenStack compute cell name.  This will only be set at the top of
    # the cells tree and it'll be a full cell name such as 'api!hop1!hop2'
    # TODO(stephenfin): Remove this
    cell_name = sa.Column(sa.String(255))

    # NOTE(pumaranikar): internal_id attribute is no longer used (bug 1441242)
    # Hence, removing from object layer in current release (Ocata) and will
    # treated as deprecated. The column can be removed from schema with
    # a migration at the start of next release.
    # internal_id = sa.Column(sa.Integer)

    # Records whether an instance has been deleted from disk
    cleaned = sa.Column(sa.Integer, default=0)

    hidden = sa.Column(sa.Boolean, default=False)


class InstanceInfoCache(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a cache of information about an instance
    """
    __tablename__ = 'instance_info_caches'
    __table_args__ = (
        schema.UniqueConstraint(
            "instance_uuid",
            name="uniq_instance_info_caches0instance_uuid"),)
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    # text column used for storing a json object of network data for api
    network_info = sa.Column(types.MediumText())

    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'),
                           nullable=False)
    instance = orm.relationship(Instance,
                            backref=orm.backref('info_cache', uselist=False),
                            foreign_keys=instance_uuid,
                            primaryjoin=instance_uuid == Instance.uuid)


class InstanceExtra(BASE, NovaBase, models.SoftDeleteMixin):
    __tablename__ = 'instance_extra'
    __table_args__ = (
        sa.Index('instance_extra_idx', 'instance_uuid'),)
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'),
                           nullable=False)
    device_metadata = orm.deferred(sa.Column(sa.Text))
    numa_topology = orm.deferred(sa.Column(sa.Text))
    pci_requests = orm.deferred(sa.Column(sa.Text))
    flavor = orm.deferred(sa.Column(sa.Text))
    vcpu_model = orm.deferred(sa.Column(sa.Text))
    migration_context = orm.deferred(sa.Column(sa.Text))
    keypairs = orm.deferred(sa.Column(sa.Text))
    trusted_certs = orm.deferred(sa.Column(sa.Text))
    # NOTE(Luyao): 'vpmems' is still in the database
    # and can be removed in the future release.
    resources = orm.deferred(sa.Column(sa.Text))
    instance = orm.relationship(Instance,
                            backref=orm.backref('extra',
                                                uselist=False),
                            foreign_keys=instance_uuid,
                            primaryjoin=instance_uuid == Instance.uuid)


class Quota(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then the
    default for the quota class is used.  If there is no row for a
    given quota class and resource, then the default for the
    deployment is used. If the row is present but the hard limit is
    Null, then the resource is unlimited.
    """

    __tablename__ = 'quotas'
    __table_args__ = (
        schema.UniqueConstraint("project_id", "resource", "deleted",
        name="uniq_quotas0project_id0resource0deleted"
        ),
    )
    id = sa.Column(sa.Integer, primary_key=True)

    project_id = sa.Column(sa.String(255))

    resource = sa.Column(sa.String(255), nullable=False)
    hard_limit = sa.Column(sa.Integer)


class ProjectUserQuota(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a single quota override for a user with in a project."""

    __tablename__ = 'project_user_quotas'
    uniq_name = "uniq_project_user_quotas0user_id0project_id0resource0deleted"
    __table_args__ = (
        schema.UniqueConstraint("user_id", "project_id", "resource", "deleted",
                                name=uniq_name),
        sa.Index('project_user_quotas_project_id_deleted_idx',
              'project_id', 'deleted'),
        sa.Index('project_user_quotas_user_id_deleted_idx',
              'user_id', 'deleted')
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)

    project_id = sa.Column(sa.String(255), nullable=False)
    user_id = sa.Column(sa.String(255), nullable=False)

    resource = sa.Column(sa.String(255), nullable=False)
    hard_limit = sa.Column(sa.Integer)


class QuotaClass(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    __table_args__ = (
        sa.Index('ix_quota_classes_class_name', 'class_name'),
    )
    id = sa.Column(sa.Integer, primary_key=True)

    class_name = sa.Column(sa.String(255))

    resource = sa.Column(sa.String(255))
    hard_limit = sa.Column(sa.Integer)


class QuotaUsage(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    __table_args__ = (
        sa.Index('ix_quota_usages_project_id', 'project_id'),
        sa.Index('ix_quota_usages_user_id_deleted', 'user_id', 'deleted'),
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


class Reservation(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    __table_args__ = (
        sa.Index('ix_reservations_project_id', 'project_id'),
        sa.Index('reservations_uuid_idx', 'uuid'),
        sa.Index('reservations_deleted_expire_idx', 'deleted', 'expire'),
        sa.Index('ix_reservations_user_id_deleted', 'user_id', 'deleted'),
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
        primaryjoin='and_(Reservation.usage_id == QuotaUsage.id,'
                         'QuotaUsage.deleted == 0)')


class BlockDeviceMapping(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents block device mapping that is defined by EC2."""
    __tablename__ = "block_device_mapping"
    __table_args__ = (
        sa.Index('snapshot_id', 'snapshot_id'),
        sa.Index('volume_id', 'volume_id'),
        sa.Index('block_device_mapping_instance_uuid_device_name_idx',
              'instance_uuid', 'device_name'),
        sa.Index('block_device_mapping_instance_uuid_volume_id_idx',
              'instance_uuid', 'volume_id'),
        sa.Index('block_device_mapping_instance_uuid_idx', 'instance_uuid'),
        schema.UniqueConstraint('uuid', name='uniq_block_device_mapping0uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)

    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'))
    # NOTE(mdbooth): The REST API for BDMs includes a UUID field. That uuid
    # refers to an image, volume, or snapshot which will be used in the
    # initialisation of the BDM. It is only relevant during the API call, and
    # is not persisted directly. This is the UUID of the BDM itself.
    # FIXME(danms): This should eventually be non-nullable, but we need a
    # transition period first.
    uuid = sa.Column(sa.String(36))
    instance = orm.relationship(Instance,
                            backref=orm.backref('block_device_mapping'),
                            foreign_keys=instance_uuid,
                            primaryjoin='and_(BlockDeviceMapping.'
                                              'instance_uuid=='
                                              'Instance.uuid,'
                                              'BlockDeviceMapping.deleted=='
                                              '0)')

    source_type = sa.Column(sa.String(255))
    destination_type = sa.Column(sa.String(255))
    guest_format = sa.Column(sa.String(255))
    device_type = sa.Column(sa.String(255))
    disk_bus = sa.Column(sa.String(255))

    boot_index = sa.Column(sa.Integer)

    device_name = sa.Column(sa.String(255))

    # default=False for compatibility of the existing code.
    # With EC2 API,
    # default True for ami specified device.
    # default False for created with other timing.
    # TODO(sshturm) add default in db
    delete_on_termination = sa.Column(sa.Boolean, default=False)

    snapshot_id = sa.Column(sa.String(36))

    volume_id = sa.Column(sa.String(36))
    volume_size = sa.Column(sa.Integer)

    volume_type = sa.Column(sa.String(255))

    image_id = sa.Column(sa.String(36))

    # for no device to suppress devices.
    no_device = sa.Column(sa.Boolean)

    connection_info = sa.Column(types.MediumText())

    tag = sa.Column(sa.String(255))

    attachment_id = sa.Column(sa.String(36))


# TODO(stephenfin): Remove once we drop the security_groups field from the
# Instance table. Until then, this is tied to the SecurityGroup table
class SecurityGroupInstanceAssociation(BASE, NovaBase, models.SoftDeleteMixin):
    __tablename__ = 'security_group_instance_association'
    __table_args__ = (
        sa.Index('security_group_instance_association_instance_uuid_idx',
              'instance_uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    security_group_id = sa.Column(
        sa.Integer, sa.ForeignKey('security_groups.id'))
    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'))


# TODO(stephenfin): Remove once we drop the security_groups field from the
# Instance table
class SecurityGroup(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a security group."""
    __tablename__ = 'security_groups'
    __table_args__ = (
        schema.UniqueConstraint('project_id', 'name', 'deleted',
                                name='uniq_security_groups0project_id0'
                                     'name0deleted'),
    )
    id = sa.Column(sa.Integer, primary_key=True)

    name = sa.Column(sa.String(255))
    description = sa.Column(sa.String(255))
    user_id = sa.Column(sa.String(255))
    project_id = sa.Column(sa.String(255))

    instances = orm.relationship(Instance,
                             secondary="security_group_instance_association",
                             primaryjoin='and_('
        'SecurityGroup.id == '
        'SecurityGroupInstanceAssociation.security_group_id,'
        'SecurityGroupInstanceAssociation.deleted == 0,'
        'SecurityGroup.deleted == 0)',
                             secondaryjoin='and_('
        'SecurityGroupInstanceAssociation.instance_uuid == Instance.uuid,'
        # (anthony) the condition below shouldn't be necessary now that the
        # association is being marked as deleted.  However, removing this
        # may cause existing deployments to choke, so I'm leaving it
        'Instance.deleted == 0)',
                             backref='security_groups')


# TODO(stephenfin): Remove once we drop the security_groups field from the
# Instance table. Until then, this is tied to the SecurityGroup table
class SecurityGroupIngressRule(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a rule in a security group."""
    __tablename__ = 'security_group_rules'
    __table_args__ = ()
    id = sa.Column(sa.Integer, primary_key=True)

    parent_group_id = sa.Column(
        sa.Integer, sa.ForeignKey('security_groups.id'))
    parent_group = orm.relationship("SecurityGroup", backref="rules",
                                foreign_keys=parent_group_id,
                                primaryjoin='and_('
        'SecurityGroupIngressRule.parent_group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')

    protocol = sa.Column(sa.String(255))
    from_port = sa.Column(sa.Integer)
    to_port = sa.Column(sa.Integer)
    cidr = sa.Column(types.CIDR())

    # Note: This is not the parent SecurityGroup. It's SecurityGroup we're
    # granting access for.
    group_id = sa.Column(sa.Integer, sa.ForeignKey('security_groups.id'))
    grantee_group = orm.relationship("SecurityGroup",
                                 foreign_keys=group_id,
                                 primaryjoin='and_('
        'SecurityGroupIngressRule.group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')


class Migration(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a running host-to-host migration."""
    __tablename__ = 'migrations'
    __table_args__ = (
        sa.Index('migrations_instance_uuid_and_status_idx', 'deleted',
              'instance_uuid', 'status'),
        sa.Index('migrations_by_host_nodes_and_status_idx', 'deleted',
              'source_compute', 'dest_compute', 'source_node', 'dest_node',
              'status'),
        sa.Index('migrations_uuid', 'uuid', unique=True),
        sa.Index('migrations_updated_at_idx', 'updated_at'),
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    # NOTE(tr3buchet): the ____compute variables are instance['host']
    source_compute = sa.Column(sa.String(255))
    dest_compute = sa.Column(sa.String(255))
    # nodes are equivalent to a compute node's 'hypervisor_hostname'
    source_node = sa.Column(sa.String(255))
    dest_node = sa.Column(sa.String(255))
    # NOTE(tr3buchet): dest_host, btw, is an ip address
    dest_host = sa.Column(sa.String(255))
    old_instance_type_id = sa.Column(sa.Integer())
    new_instance_type_id = sa.Column(sa.Integer())
    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'))
    uuid = sa.Column(sa.String(36), nullable=True)
    # TODO(_cerberus_): enum
    status = sa.Column(sa.String(255))
    migration_type = sa.Column(sa.Enum('migration', 'resize', 'live-migration',
                                 'evacuation', name='migration_type'),
                            nullable=True)
    hidden = sa.Column(sa.Boolean, default=False)
    memory_total = sa.Column(sa.BigInteger, nullable=True)
    memory_processed = sa.Column(sa.BigInteger, nullable=True)
    memory_remaining = sa.Column(sa.BigInteger, nullable=True)
    disk_total = sa.Column(sa.BigInteger, nullable=True)
    disk_processed = sa.Column(sa.BigInteger, nullable=True)
    disk_remaining = sa.Column(sa.BigInteger, nullable=True)
    cross_cell_move = sa.Column(sa.Boolean, default=False)

    user_id = sa.Column(sa.String(255), nullable=True)
    project_id = sa.Column(sa.String(255), nullable=True)

    instance = orm.relationship("Instance", foreign_keys=instance_uuid,
                            primaryjoin='and_(Migration.instance_uuid == '
                                        'Instance.uuid, Instance.deleted == '
                                        '0)')


class VirtualInterface(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a virtual interface on an instance."""
    __tablename__ = 'virtual_interfaces'
    __table_args__ = (
        schema.UniqueConstraint("address", "deleted",
                        name="uniq_virtual_interfaces0address0deleted"),
        sa.Index('virtual_interfaces_network_id_idx', 'network_id'),
        sa.Index('virtual_interfaces_instance_uuid_fkey', 'instance_uuid'),
        sa.Index('virtual_interfaces_uuid_idx', 'uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    address = sa.Column(sa.String(255))
    network_id = sa.Column(sa.Integer)
    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'))
    uuid = sa.Column(sa.String(36))
    tag = sa.Column(sa.String(255))


class InstanceMetadata(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a user-provided metadata key/value pair for an instance."""
    __tablename__ = 'instance_metadata'
    __table_args__ = (
        sa.Index('instance_metadata_instance_uuid_idx', 'instance_uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True)
    key = sa.Column(sa.String(255))
    value = sa.Column(sa.String(255))
    instance_uuid = sa.Column(sa.String(36), sa.ForeignKey('instances.uuid'))
    instance = orm.relationship(Instance, backref="metadata",
                            foreign_keys=instance_uuid,
                            primaryjoin='and_('
                                'InstanceMetadata.instance_uuid == '
                                     'Instance.uuid,'
                                'InstanceMetadata.deleted == 0)')


class InstanceSystemMetadata(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a system-owned metadata key/value pair for an instance."""
    __tablename__ = 'instance_system_metadata'
    __table_args__ = (
        sa.Index('instance_uuid', 'instance_uuid'),
    )
    id = sa.Column(sa.Integer, primary_key=True)
    key = sa.Column(sa.String(255), nullable=False)
    value = sa.Column(sa.String(255))
    instance_uuid = sa.Column(sa.String(36),
                           sa.ForeignKey('instances.uuid'),
                           nullable=False)

    instance = orm.relationship(Instance, backref="system_metadata",
                            foreign_keys=instance_uuid)


class VolumeUsage(BASE, NovaBase, models.SoftDeleteMixin):
    """Cache for volume usage data pulled from the hypervisor."""
    __tablename__ = 'volume_usage_cache'
    __table_args__ = ()
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    volume_id = sa.Column(sa.String(36), nullable=False)
    instance_uuid = sa.Column(sa.String(36))
    project_id = sa.Column(sa.String(36))
    user_id = sa.Column(sa.String(64))
    availability_zone = sa.Column(sa.String(255))
    tot_last_refreshed = sa.Column(sa.DateTime)
    tot_reads = sa.Column(sa.BigInteger, default=0)
    tot_read_bytes = sa.Column(sa.BigInteger, default=0)
    tot_writes = sa.Column(sa.BigInteger, default=0)
    tot_write_bytes = sa.Column(sa.BigInteger, default=0)
    curr_last_refreshed = sa.Column(sa.DateTime)
    curr_reads = sa.Column(sa.BigInteger, default=0)
    curr_read_bytes = sa.Column(sa.BigInteger, default=0)
    curr_writes = sa.Column(sa.BigInteger, default=0)
    curr_write_bytes = sa.Column(sa.BigInteger, default=0)


class S3Image(BASE, NovaBase, models.SoftDeleteMixin):
    """Compatibility layer for the S3 image service talking to Glance."""
    __tablename__ = 's3_images'
    __table_args__ = ()
    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = sa.Column(sa.String(36), nullable=False)


class InstanceFault(BASE, NovaBase, models.SoftDeleteMixin):
    __tablename__ = 'instance_faults'
    __table_args__ = (
        sa.Index('instance_faults_host_idx', 'host'),
        sa.Index('instance_faults_instance_uuid_deleted_created_at_idx',
              'instance_uuid', 'deleted', 'created_at')
    )

    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    instance_uuid = sa.Column(sa.String(36),
                           sa.ForeignKey('instances.uuid'))
    code = sa.Column(sa.Integer(), nullable=False)
    message = sa.Column(sa.String(255))
    details = sa.Column(types.MediumText())
    host = sa.Column(sa.String(255))


class InstanceAction(BASE, NovaBase, models.SoftDeleteMixin):
    """Track client actions on an instance.

    The intention is that there will only be one of these per user request.  A
    lookup by (instance_uuid, request_id) should always return a single result.
    """
    __tablename__ = 'instance_actions'
    __table_args__ = (
        sa.Index('instance_uuid_idx', 'instance_uuid'),
        sa.Index('request_id_idx', 'request_id'),
        sa.Index('instance_actions_instance_uuid_updated_at_idx',
              'instance_uuid', 'updated_at')
    )

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    action = sa.Column(sa.String(255))
    instance_uuid = sa.Column(sa.String(36),
                           sa.ForeignKey('instances.uuid'))
    request_id = sa.Column(sa.String(255))
    user_id = sa.Column(sa.String(255))
    project_id = sa.Column(sa.String(255))
    start_time = sa.Column(sa.DateTime, default=timeutils.utcnow)
    finish_time = sa.Column(sa.DateTime)
    message = sa.Column(sa.String(255))


class InstanceActionEvent(BASE, NovaBase, models.SoftDeleteMixin):
    """Track events that occur during an InstanceAction."""
    __tablename__ = 'instance_actions_events'
    __table_args__ = ()

    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    event = sa.Column(sa.String(255))
    action_id = sa.Column(sa.Integer, sa.ForeignKey('instance_actions.id'))
    start_time = sa.Column(sa.DateTime, default=timeutils.utcnow)
    finish_time = sa.Column(sa.DateTime)
    result = sa.Column(sa.String(255))
    traceback = sa.Column(sa.Text)
    host = sa.Column(sa.String(255))
    details = sa.Column(sa.Text)


class InstanceIdMapping(BASE, NovaBase, models.SoftDeleteMixin):
    """Compatibility layer for the EC2 instance service."""
    __tablename__ = 'instance_id_mappings'
    __table_args__ = (
        sa.Index('ix_instance_id_mappings_uuid', 'uuid'),
    )
    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = sa.Column(sa.String(36), nullable=False)


class TaskLog(BASE, NovaBase, models.SoftDeleteMixin):
    """Audit log for background periodic tasks."""
    __tablename__ = 'task_log'
    __table_args__ = (
        schema.UniqueConstraint(
            'task_name', 'host', 'period_beginning', 'period_ending',
            name="uniq_task_log0task_name0host0period_beginning0period_ending"
        ),
        sa.Index('ix_task_log_period_beginning', 'period_beginning'),
        sa.Index('ix_task_log_host', 'host'),
        sa.Index('ix_task_log_period_ending', 'period_ending'),
    )
    id = sa.Column(
        sa.Integer, primary_key=True, nullable=False, autoincrement=True)
    task_name = sa.Column(sa.String(255), nullable=False)
    state = sa.Column(sa.String(255), nullable=False)
    host = sa.Column(sa.String(255), nullable=False)
    period_beginning = sa.Column(sa.DateTime, default=timeutils.utcnow,
                              nullable=False)
    period_ending = sa.Column(sa.DateTime, default=timeutils.utcnow,
                           nullable=False)
    message = sa.Column(sa.String(255), nullable=False)
    task_items = sa.Column(sa.Integer(), default=0)
    errors = sa.Column(sa.Integer(), default=0)


class PciDevice(BASE, NovaBase, models.SoftDeleteMixin):
    """Represents a PCI host device that can be passed through to instances.
    """
    __tablename__ = 'pci_devices'
    __table_args__ = (
        sa.Index('ix_pci_devices_compute_node_id_deleted',
              'compute_node_id', 'deleted'),
        sa.Index('ix_pci_devices_instance_uuid_deleted',
              'instance_uuid', 'deleted'),
        sa.Index('ix_pci_devices_compute_node_id_parent_addr_deleted',
              'compute_node_id', 'parent_addr', 'deleted'),
        schema.UniqueConstraint(
            "compute_node_id", "address", "deleted",
            name="uniq_pci_devices0compute_node_id0address0deleted")
    )
    id = sa.Column(sa.Integer, primary_key=True)
    uuid = sa.Column(sa.String(36))
    compute_node_id = sa.Column(sa.Integer, sa.ForeignKey('compute_nodes.id'),
                             nullable=False)

    # physical address of device domain:bus:slot.func (0000:09:01.1)
    address = sa.Column(sa.String(12), nullable=False)

    vendor_id = sa.Column(sa.String(4), nullable=False)
    product_id = sa.Column(sa.String(4), nullable=False)
    dev_type = sa.Column(sa.String(8), nullable=False)
    dev_id = sa.Column(sa.String(255))

    # label is abstract device name, that is used to unify devices with the
    # same functionality with different addresses or host.
    label = sa.Column(sa.String(255), nullable=False)

    status = sa.Column(sa.String(36), nullable=False)
    # the request_id is used to identify a device that is allocated for a
    # particular request
    request_id = sa.Column(sa.String(36), nullable=True)

    extra_info = sa.Column(sa.Text)

    instance_uuid = sa.Column(sa.String(36))

    numa_node = sa.Column(sa.Integer, nullable=True)

    parent_addr = sa.Column(sa.String(12), nullable=True)
    instance = orm.relationship(Instance, backref="pci_devices",
                                foreign_keys=instance_uuid,
                                primaryjoin='and_('
                                'PciDevice.instance_uuid == Instance.uuid,'
                                'PciDevice.deleted == 0)')


class Tag(BASE, models.ModelBase):
    """Represents the tag for a resource."""

    __tablename__ = "tags"
    __table_args__ = (
        sa.Index('tags_tag_idx', 'tag'),
    )
    resource_id = sa.Column(sa.String(36), primary_key=True, nullable=False)
    tag = sa.Column(sa.Unicode(80), primary_key=True, nullable=False)

    instance = orm.relationship(
        "Instance",
        backref='tags',
        primaryjoin='and_(Tag.resource_id == Instance.uuid,'
                    'Instance.deleted == 0)',
        foreign_keys=resource_id
    )


class ConsoleAuthToken(BASE, NovaBase):
    """Represents a console auth token"""

    __tablename__ = 'console_auth_tokens'
    __table_args__ = (
        sa.Index('console_auth_tokens_instance_uuid_idx', 'instance_uuid'),
        sa.Index('console_auth_tokens_host_expires_idx', 'host', 'expires'),
        sa.Index('console_auth_tokens_token_hash_idx', 'token_hash'),
        sa.Index(
            'console_auth_tokens_token_hash_instance_uuid_idx', 'token_hash',
            'instance_uuid',
        ),
        schema.UniqueConstraint("token_hash",
                                name="uniq_console_auth_tokens0token_hash")
    )
    id = sa.Column(sa.Integer, primary_key=True, nullable=False)
    token_hash = sa.Column(sa.String(255), nullable=False)
    console_type = sa.Column(sa.String(255), nullable=False)
    host = sa.Column(sa.String(255), nullable=False)
    port = sa.Column(sa.Integer, nullable=False)
    internal_access_path = sa.Column(sa.String(255))
    instance_uuid = sa.Column(sa.String(36), nullable=False)
    expires = sa.Column(sa.Integer, nullable=False)
    access_url_base = sa.Column(sa.String(255))

    instance = orm.relationship(
        "Instance",
        backref='console_auth_tokens',
        primaryjoin='and_(ConsoleAuthToken.instance_uuid == Instance.uuid,'
                    'Instance.deleted == 0)',
        foreign_keys=instance_uuid
    )
