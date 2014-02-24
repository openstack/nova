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

from sqlalchemy import Column, Index, Integer, BigInteger, Enum, String, schema
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean, Text, Float
from sqlalchemy.orm import relationship, backref, object_mapper
from oslo.config import cfg

from nova.db.sqlalchemy import types
from nova.openstack.common.db.sqlalchemy import models
from nova.openstack.common import timeutils

CONF = cfg.CONF
BASE = declarative_base()


def MediumText():
    return Text().with_variant(MEDIUMTEXT(), 'mysql')


class NovaBase(models.SoftDeleteMixin,
               models.TimestampMixin,
               models.ModelBase):
    metadata = None

    def save(self, session=None):
        from nova.db.sqlalchemy import api

        if session is None:
            session = api.get_session()

        super(NovaBase, self).save(session=session)


class Service(BASE, NovaBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    __table_args__ = (
        schema.UniqueConstraint("host", "topic", "deleted",
                                name="uniq_services0host0topic0deleted"),
        schema.UniqueConstraint("host", "binary", "deleted",
                                name="uniq_services0host0binary0deleted")
        )

    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    disabled_reason = Column(String(255))


class ComputeNode(BASE, NovaBase):
    """Represents a running compute service on a host."""

    __tablename__ = 'compute_nodes'
    __table_args__ = ()
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=False)
    service = relationship(Service,
                           backref=backref('compute_node'),
                           foreign_keys=service_id,
                           primaryjoin='and_('
                                'ComputeNode.service_id == Service.id,'
                                'ComputeNode.deleted == 0)')

    vcpus = Column(Integer, nullable=False)
    memory_mb = Column(Integer, nullable=False)
    local_gb = Column(Integer, nullable=False)
    vcpus_used = Column(Integer, nullable=False)
    memory_mb_used = Column(Integer, nullable=False)
    local_gb_used = Column(Integer, nullable=False)
    hypervisor_type = Column(MediumText(), nullable=False)
    hypervisor_version = Column(Integer, nullable=False)
    hypervisor_hostname = Column(String(255))

    # Free Ram, amount of activity (resize, migration, boot, etc) and
    # the number of running VM's are a good starting point for what's
    # important when making scheduling decisions.
    free_ram_mb = Column(Integer)
    free_disk_gb = Column(Integer)
    current_workload = Column(Integer)
    running_vms = Column(Integer)

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
    cpu_info = Column(MediumText(), nullable=False)
    disk_available_least = Column(Integer)
    host_ip = Column(types.IPAddress())
    supported_instances = Column(Text)
    metrics = Column(Text)

    # Note(yongli): json string PCI Stats
    # '{"vendor_id":"8086", "product_id":"1234", "count":3 }'
    pci_stats = Column(Text)

    # extra_resources is a json string containing arbitrary
    # data about additional resources.
    extra_resources = Column(Text)

    # json-encode string containing compute node statistics
    stats = Column(Text, default='{}')


class Certificate(BASE, NovaBase):
    """Represents a x509 certificate."""
    __tablename__ = 'certificates'
    __table_args__ = (
        Index('certificates_project_id_deleted_idx', 'project_id', 'deleted'),
        Index('certificates_user_id_deleted_idx', 'user_id', 'deleted')
    )
    id = Column(Integer, primary_key=True)

    user_id = Column(String(255))
    project_id = Column(String(255))
    file_name = Column(String(255))


class Instance(BASE, NovaBase):
    """Represents a guest VM."""
    __tablename__ = 'instances'
    __table_args__ = (
        Index('uuid', 'uuid', unique=True),
        Index('project_id', 'project_id'),
        Index('instances_host_deleted_idx',
              'host', 'deleted'),
        Index('instances_reservation_id_idx',
              'reservation_id'),
        Index('instances_terminated_at_launched_at_idx',
              'terminated_at', 'launched_at'),
        Index('instances_uuid_deleted_idx',
              'uuid', 'deleted'),
        Index('instances_task_state_updated_at_idx',
              'task_state', 'updated_at'),
        Index('instances_host_node_deleted_idx',
              'host', 'node', 'deleted'),
        Index('instances_host_deleted_cleaned_idx',
              'host', 'deleted', 'cleaned'),
    )
    injected_files = []

    id = Column(Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        try:
            base_name = CONF.instance_name_template % self.id
        except TypeError:
            # Support templates like "uuid-%(uuid)s", etc.
            info = {}
            # NOTE(russellb): Don't use self.iteritems() here, as it will
            # result in infinite recursion on the name property.
            for column in iter(object_mapper(self).columns):
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

    user_id = Column(String(255))
    project_id = Column(String(255))

    image_ref = Column(String(255))
    kernel_id = Column(String(255))
    ramdisk_id = Column(String(255))
    hostname = Column(String(255))

    launch_index = Column(Integer)
    key_name = Column(String(255))
    key_data = Column(MediumText())

    power_state = Column(Integer)
    vm_state = Column(String(255))
    task_state = Column(String(255))

    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    root_gb = Column(Integer)
    ephemeral_gb = Column(Integer)
    ephemeral_key_uuid = Column(String(36))

    # This is not related to hostname, above.  It refers
    #  to the nova node.
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    # To identify the "ComputeNode" which the instance resides in.
    # This equals to ComputeNode.hypervisor_hostname.
    node = Column(String(255))

    # *not* flavorid, this is the internal primary_key
    instance_type_id = Column(Integer)

    user_data = Column(MediumText())

    reservation_id = Column(String(255))

    scheduled_at = Column(DateTime)
    launched_at = Column(DateTime)
    terminated_at = Column(DateTime)

    availability_zone = Column(String(255))

    # User editable field for display in user-facing UIs
    display_name = Column(String(255))
    display_description = Column(String(255))

    # To remember on which host an instance booted.
    # An instance may have moved to another host by live migration.
    launched_on = Column(MediumText())

    # NOTE(jdillaman): locked deprecated in favor of locked_by,
    # to be removed in Icehouse
    locked = Column(Boolean)
    locked_by = Column(Enum('owner', 'admin'))

    os_type = Column(String(255))
    architecture = Column(String(255))
    vm_mode = Column(String(255))
    uuid = Column(String(36))

    root_device_name = Column(String(255))
    default_ephemeral_device = Column(String(255))
    default_swap_device = Column(String(255))
    config_drive = Column(String(255))

    # User editable field meant to represent what ip should be used
    # to connect to the instance
    access_ip_v4 = Column(types.IPAddress())
    access_ip_v6 = Column(types.IPAddress())

    auto_disk_config = Column(Boolean())
    progress = Column(Integer)

    # EC2 instance_initiated_shutdown_terminate
    # True: -> 'terminate'
    # False: -> 'stop'
    # Note(maoy): currently Nova will always stop instead of terminate
    # no matter what the flag says. So we set the default to False.
    shutdown_terminate = Column(Boolean(), default=False)

    # EC2 disable_api_termination
    disable_terminate = Column(Boolean(), default=False)

    # OpenStack compute cell name.  This will only be set at the top of
    # the cells tree and it'll be a full cell name such as 'api!hop1!hop2'
    cell_name = Column(String(255))
    internal_id = Column(Integer)

    # Records whether an instance has been deleted from disk
    cleaned = Column(Integer, default=0)


class InstanceInfoCache(BASE, NovaBase):
    """Represents a cache of information about an instance
    """
    __tablename__ = 'instance_info_caches'
    __table_args__ = (
        schema.UniqueConstraint(
            "instance_uuid",
            name="uniq_instance_info_caches0instance_uuid"),)
    id = Column(Integer, primary_key=True, autoincrement=True)

    # text column used for storing a json object of network data for api
    network_info = Column(MediumText())

    instance_uuid = Column(String(36), ForeignKey('instances.uuid'),
                           nullable=False)
    instance = relationship(Instance,
                            backref=backref('info_cache', uselist=False),
                            foreign_keys=instance_uuid,
                            primaryjoin=instance_uuid == Instance.uuid)


class InstanceTypes(BASE, NovaBase):
    """Represents possible flavors for instances.

    Note: instance_type and flavor are synonyms and the term instance_type is
    deprecated and in the process of being removed.
    """
    __tablename__ = "instance_types"

    __table_args__ = (
        schema.UniqueConstraint("flavorid", "deleted",
                                name="uniq_instance_types0flavorid0deleted"),
        schema.UniqueConstraint("name", "deleted",
                                name="uniq_instance_types0name0deleted")
    )

    # Internal only primary key/id
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    memory_mb = Column(Integer, nullable=False)
    vcpus = Column(Integer, nullable=False)
    root_gb = Column(Integer)
    ephemeral_gb = Column(Integer)
    # Public facing id will be renamed public_id
    flavorid = Column(String(255))
    swap = Column(Integer, nullable=False, default=0)
    rxtx_factor = Column(Float, default=1)
    vcpu_weight = Column(Integer)
    disabled = Column(Boolean, default=False)
    is_public = Column(Boolean, default=True)


class Volume(BASE, NovaBase):
    """Represents a block storage device that can be attached to a VM."""
    __tablename__ = 'volumes'
    __table_args__ = (
        Index('volumes_instance_uuid_idx', 'instance_uuid'),
    )
    id = Column(String(36), primary_key=True, nullable=False)
    deleted = Column(String(36), default="")

    @property
    def name(self):
        return CONF.volume_name_template % self.id

    ec2_id = Column(String(255))
    user_id = Column(String(255))
    project_id = Column(String(255))

    snapshot_id = Column(String(36))

    host = Column(String(255))
    size = Column(Integer)
    availability_zone = Column(String(255))
    instance_uuid = Column(String(36))
    mountpoint = Column(String(255))
    attach_time = Column(DateTime)
    status = Column(String(255))  # TODO(vish): enum?
    attach_status = Column(String(255))  # TODO(vish): enum

    scheduled_at = Column(DateTime)
    launched_at = Column(DateTime)
    terminated_at = Column(DateTime)

    display_name = Column(String(255))
    display_description = Column(String(255))

    provider_location = Column(String(256))
    provider_auth = Column(String(256))

    volume_type_id = Column(Integer)


class Quota(BASE, NovaBase):
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
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255))

    resource = Column(String(255), nullable=False)
    hard_limit = Column(Integer)


class ProjectUserQuota(BASE, NovaBase):
    """Represents a single quota override for a user with in a project."""

    __tablename__ = 'project_user_quotas'
    uniq_name = "uniq_project_user_quotas0user_id0project_id0resource0deleted"
    __table_args__ = (
        schema.UniqueConstraint("user_id", "project_id", "resource", "deleted",
                                name=uniq_name),
        Index('project_user_quotas_project_id_deleted_idx',
              'project_id', 'deleted'),
        Index('project_user_quotas_user_id_deleted_idx',
              'user_id', 'deleted')
    )
    id = Column(Integer, primary_key=True, nullable=False)

    project_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)

    resource = Column(String(255), nullable=False)
    hard_limit = Column(Integer)


class QuotaClass(BASE, NovaBase):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    __table_args__ = (
        Index('ix_quota_classes_class_name', 'class_name'),
    )
    id = Column(Integer, primary_key=True)

    class_name = Column(String(255))

    resource = Column(String(255))
    hard_limit = Column(Integer)


class QuotaUsage(BASE, NovaBase):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    __table_args__ = (
        Index('ix_quota_usages_project_id', 'project_id'),
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


class Reservation(BASE, NovaBase):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    __table_args__ = (
        Index('ix_reservations_project_id', 'project_id'),
        Index('reservations_uuid_idx', 'uuid'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    uuid = Column(String(36), nullable=False)

    usage_id = Column(Integer, ForeignKey('quota_usages.id'), nullable=False)

    project_id = Column(String(255))
    user_id = Column(String(255))
    resource = Column(String(255))

    delta = Column(Integer, nullable=False)
    expire = Column(DateTime)

    usage = relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='and_(Reservation.usage_id == QuotaUsage.id,'
                         'QuotaUsage.deleted == 0)')


class Snapshot(BASE, NovaBase):
    """Represents a block storage device that can be attached to a VM."""
    __tablename__ = 'snapshots'
    __table_args__ = ()
    id = Column(String(36), primary_key=True, nullable=False)
    deleted = Column(String(36), default="")

    @property
    def name(self):
        return CONF.snapshot_name_template % self.id

    @property
    def volume_name(self):
        return CONF.volume_name_template % self.volume_id

    user_id = Column(String(255))
    project_id = Column(String(255))

    volume_id = Column(String(36), nullable=False)
    status = Column(String(255))
    progress = Column(String(255))
    volume_size = Column(Integer)
    scheduled_at = Column(DateTime)

    display_name = Column(String(255))
    display_description = Column(String(255))


class BlockDeviceMapping(BASE, NovaBase):
    """Represents block device mapping that is defined by EC2."""
    __tablename__ = "block_device_mapping"
    __table_args__ = (
        Index('snapshot_id', 'snapshot_id'),
        Index('volume_id', 'volume_id'),
        Index('block_device_mapping_instance_uuid_device_name_idx',
              'instance_uuid', 'device_name'),
        Index('block_device_mapping_instance_uuid_volume_id_idx',
              'instance_uuid', 'volume_id'),
        Index('block_device_mapping_instance_uuid_idx', 'instance_uuid'),
        #TODO(sshturm) Should be dropped. `virtual_name` was dropped
        #in 186 migration,
        #Duplicates `block_device_mapping_instance_uuid_device_name_idx` index.
        Index("block_device_mapping_instance_uuid_virtual_name"
              "_device_name_idx", 'instance_uuid', 'device_name'),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)

    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    instance = relationship(Instance,
                            backref=backref('block_device_mapping'),
                            foreign_keys=instance_uuid,
                            primaryjoin='and_(BlockDeviceMapping.'
                                              'instance_uuid=='
                                              'Instance.uuid,'
                                              'BlockDeviceMapping.deleted=='
                                              '0)')

    source_type = Column(String(255))
    destination_type = Column(String(255))
    guest_format = Column(String(255))
    device_type = Column(String(255))
    disk_bus = Column(String(255))

    boot_index = Column(Integer)

    device_name = Column(String(255))

    # default=False for compatibility of the existing code.
    # With EC2 API,
    # default True for ami specified device.
    # default False for created with other timing.
    #TODO(sshturm) add default in db
    delete_on_termination = Column(Boolean, default=False)

    snapshot_id = Column(String(36))

    volume_id = Column(String(36))
    volume_size = Column(Integer)

    image_id = Column(String(36))

    # for no device to suppress devices.
    no_device = Column(Boolean)

    connection_info = Column(MediumText())


class IscsiTarget(BASE, NovaBase):
    """Represents an iscsi target for a given host."""
    __tablename__ = 'iscsi_targets'
    __table_args__ = (
        Index('iscsi_targets_volume_id_fkey', 'volume_id'),
        Index('iscsi_targets_host_idx', 'host'),
        Index('iscsi_targets_host_volume_id_deleted_idx', 'host', 'volume_id',
              'deleted')
    )
    id = Column(Integer, primary_key=True, nullable=False)
    target_num = Column(Integer)
    host = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'))
    volume = relationship(Volume,
                          backref=backref('iscsi_target', uselist=False),
                          foreign_keys=volume_id,
                          primaryjoin='and_(IscsiTarget.volume_id==Volume.id,'
                                           'IscsiTarget.deleted==0)')


class SecurityGroupInstanceAssociation(BASE, NovaBase):
    __tablename__ = 'security_group_instance_association'
    __table_args__ = (
        Index('security_group_instance_association_instance_uuid_idx',
              'instance_uuid'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    security_group_id = Column(Integer, ForeignKey('security_groups.id'))
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))


class SecurityGroup(BASE, NovaBase):
    """Represents a security group."""
    __tablename__ = 'security_groups'
    __table_args__ = (
        Index('uniq_security_groups0project_id0name0deleted', 'project_id',
              'name', 'deleted'),
    )
    id = Column(Integer, primary_key=True)

    name = Column(String(255))
    description = Column(String(255))
    user_id = Column(String(255))
    project_id = Column(String(255))

    instances = relationship(Instance,
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


class SecurityGroupIngressRule(BASE, NovaBase):
    """Represents a rule in a security group."""
    __tablename__ = 'security_group_rules'
    __table_args__ = ()
    id = Column(Integer, primary_key=True)

    parent_group_id = Column(Integer, ForeignKey('security_groups.id'))
    parent_group = relationship("SecurityGroup", backref="rules",
                                foreign_keys=parent_group_id,
                                primaryjoin='and_('
        'SecurityGroupIngressRule.parent_group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')

    protocol = Column(String(255))
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(types.CIDR())

    # Note: This is not the parent SecurityGroup. It's SecurityGroup we're
    # granting access for.
    group_id = Column(Integer, ForeignKey('security_groups.id'))
    grantee_group = relationship("SecurityGroup",
                                 foreign_keys=group_id,
                                 primaryjoin='and_('
        'SecurityGroupIngressRule.group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')


class SecurityGroupIngressDefaultRule(BASE, NovaBase):
    __tablename__ = 'security_group_default_rules'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False)
    protocol = Column(String(5))  # "tcp", "udp" or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(types.CIDR())


class ProviderFirewallRule(BASE, NovaBase):
    """Represents a rule in a security group."""
    __tablename__ = 'provider_fw_rules'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False)

    protocol = Column(String(5))  # "tcp", "udp", or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(types.CIDR())


class KeyPair(BASE, NovaBase):
    """Represents a public key pair for ssh."""
    __tablename__ = 'key_pairs'
    __table_args__ = (
        schema.UniqueConstraint("user_id", "name", "deleted",
                                name="uniq_key_pairs0user_id0name0deleted"),
    )
    id = Column(Integer, primary_key=True, nullable=False)

    name = Column(String(255))

    user_id = Column(String(255))

    fingerprint = Column(String(255))
    public_key = Column(MediumText())


class Migration(BASE, NovaBase):
    """Represents a running host-to-host migration."""
    __tablename__ = 'migrations'
    __table_args__ = (
        Index('migrations_instance_uuid_and_status_idx', 'instance_uuid',
              'status'),
        Index('migrations_by_host_nodes_and_status_idx', 'deleted',
              'source_compute', 'dest_compute', 'source_node', 'dest_node',
              'status'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    # NOTE(tr3buchet): the ____compute variables are instance['host']
    source_compute = Column(String(255))
    dest_compute = Column(String(255))
    # nodes are equivalent to a compute node's 'hypervisor_hostname'
    source_node = Column(String(255))
    dest_node = Column(String(255))
    # NOTE(tr3buchet): dest_host, btw, is an ip address
    dest_host = Column(String(255))
    old_instance_type_id = Column(Integer())
    new_instance_type_id = Column(Integer())
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    #TODO(_cerberus_): enum
    status = Column(String(255))

    instance = relationship("Instance", foreign_keys=instance_uuid,
                            primaryjoin='and_(Migration.instance_uuid == '
                                        'Instance.uuid, Instance.deleted == '
                                        '0)')


class Network(BASE, NovaBase):
    """Represents a network."""
    __tablename__ = 'networks'
    __table_args__ = (
        schema.UniqueConstraint("vlan", "deleted",
                                name="uniq_networks0vlan0deleted"),
       Index('networks_bridge_deleted_idx', 'bridge', 'deleted'),
       Index('networks_host_idx', 'host'),
       Index('networks_project_id_deleted_idx', 'project_id', 'deleted'),
       Index('networks_uuid_project_id_deleted_idx', 'uuid',
             'project_id', 'deleted'),
       Index('networks_vlan_deleted_idx', 'vlan', 'deleted'),
       Index('networks_cidr_v6_idx', 'cidr_v6')
    )

    id = Column(Integer, primary_key=True, nullable=False)
    label = Column(String(255))

    injected = Column(Boolean, default=False)
    cidr = Column(types.CIDR())
    cidr_v6 = Column(types.CIDR())
    multi_host = Column(Boolean, default=False)

    gateway_v6 = Column(types.IPAddress())
    netmask_v6 = Column(types.IPAddress())
    netmask = Column(types.IPAddress())
    bridge = Column(String(255))
    bridge_interface = Column(String(255))
    gateway = Column(types.IPAddress())
    broadcast = Column(types.IPAddress())
    dns1 = Column(types.IPAddress())
    dns2 = Column(types.IPAddress())

    vlan = Column(Integer)
    vpn_public_address = Column(types.IPAddress())
    vpn_public_port = Column(Integer)
    vpn_private_address = Column(types.IPAddress())
    dhcp_start = Column(types.IPAddress())

    rxtx_base = Column(Integer)

    project_id = Column(String(255))
    priority = Column(Integer)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    uuid = Column(String(36))


class VirtualInterface(BASE, NovaBase):
    """Represents a virtual interface on an instance."""
    __tablename__ = 'virtual_interfaces'
    __table_args__ = (
        schema.UniqueConstraint("address", "deleted",
                        name="uniq_virtual_interfaces0address0deleted"),
        Index('network_id', 'network_id'),
        Index('virtual_interfaces_instance_uuid_fkey', 'instance_uuid'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    address = Column(String(255))
    network_id = Column(Integer)
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    uuid = Column(String(36))


# TODO(vish): can these both come from the same baseclass?
class FixedIp(BASE, NovaBase):
    """Represents a fixed ip for an instance."""
    __tablename__ = 'fixed_ips'
    __table_args__ = (
        schema.UniqueConstraint(
            "address", "deleted", name="uniq_fixed_ips0address0deleted"),
        Index('fixed_ips_virtual_interface_id_fkey', 'virtual_interface_id'),
        Index('network_id', 'network_id'),
        Index('address', 'address'),
        Index('fixed_ips_instance_uuid_fkey', 'instance_uuid'),
        Index('fixed_ips_host_idx', 'host'),
        Index('fixed_ips_network_id_host_deleted_idx', 'network_id', 'host',
              'deleted'),
        Index('fixed_ips_address_reserved_network_id_deleted_idx',
              'address', 'reserved', 'network_id', 'deleted'),
        Index('fixed_ips_deleted_allocated_idx', 'address', 'deleted',
              'allocated')
    )
    id = Column(Integer, primary_key=True)
    address = Column(types.IPAddress())
    network_id = Column(Integer)
    virtual_interface_id = Column(Integer)
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    # associated means that a fixed_ip has its instance_id column set
    # allocated means that a fixed_ip has its virtual_interface_id column set
    #TODO(sshturm) add default in db
    allocated = Column(Boolean, default=False)
    # leased means dhcp bridge has leased the ip
    #TODO(sshturm) add default in db
    leased = Column(Boolean, default=False)
    #TODO(sshturm) add default in db
    reserved = Column(Boolean, default=False)
    host = Column(String(255))
    network = relationship(Network,
                           backref=backref('fixed_ips'),
                           foreign_keys=network_id,
                           primaryjoin='and_('
                                'FixedIp.network_id == Network.id,'
                                'FixedIp.deleted == 0,'
                                'Network.deleted == 0)')
    instance = relationship(Instance,
                            foreign_keys=instance_uuid,
                            primaryjoin='and_('
                                'FixedIp.instance_uuid == Instance.uuid,'
                                'FixedIp.deleted == 0,'
                                'Instance.deleted == 0)')


class FloatingIp(BASE, NovaBase):
    """Represents a floating ip that dynamically forwards to a fixed ip."""
    __tablename__ = 'floating_ips'
    __table_args__ = (
        schema.UniqueConstraint("address", "deleted",
                                name="uniq_floating_ips0address0deleted"),
        Index('fixed_ip_id', 'fixed_ip_id'),
        Index('floating_ips_host_idx', 'host'),
        Index('floating_ips_project_id_idx', 'project_id'),
        Index('floating_ips_pool_deleted_fixed_ip_id_project_id_idx',
              'pool', 'deleted', 'fixed_ip_id', 'project_id')
    )
    id = Column(Integer, primary_key=True)
    address = Column(types.IPAddress())
    fixed_ip_id = Column(Integer)
    project_id = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    auto_assigned = Column(Boolean, default=False)
    #TODO(sshturm) add default in db
    pool = Column(String(255))
    interface = Column(String(255))
    fixed_ip = relationship(FixedIp,
                            backref=backref('floating_ips'),
                            foreign_keys=fixed_ip_id,
                            primaryjoin='and_('
                                'FloatingIp.fixed_ip_id == FixedIp.id,'
                                'FloatingIp.deleted == 0,'
                                'FixedIp.deleted == 0)')


class DNSDomain(BASE, NovaBase):
    """Represents a DNS domain with availability zone or project info."""
    __tablename__ = 'dns_domains'
    __table_args__ = (
        Index('project_id', 'project_id'),
        Index('dns_domains_domain_deleted_idx', 'domain', 'deleted'),
    )
    deleted = Column(Boolean, default=False)
    domain = Column(String(255), primary_key=True)
    scope = Column(String(255))
    availability_zone = Column(String(255))
    project_id = Column(String(255))


class ConsolePool(BASE, NovaBase):
    """Represents pool of consoles on the same physical node."""
    __tablename__ = 'console_pools'
    __table_args__ = (
        schema.UniqueConstraint(
            "host", "console_type", "compute_host", "deleted",
            name="uniq_console_pools0host0console_type0compute_host0deleted"),
    )
    id = Column(Integer, primary_key=True)
    address = Column(types.IPAddress())
    username = Column(String(255))
    password = Column(String(255))
    console_type = Column(String(255))
    public_hostname = Column(String(255))
    host = Column(String(255))
    compute_host = Column(String(255))


class Console(BASE, NovaBase):
    """Represents a console session for an instance."""
    __tablename__ = 'consoles'
    __table_args__ = (
        Index('consoles_instance_uuid_idx', 'instance_uuid'),
    )
    id = Column(Integer, primary_key=True)
    instance_name = Column(String(255))
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    password = Column(String(255))
    port = Column(Integer)
    pool_id = Column(Integer, ForeignKey('console_pools.id'))
    pool = relationship(ConsolePool, backref=backref('consoles'))


class InstanceMetadata(BASE, NovaBase):
    """Represents a user-provided metadata key/value pair for an instance."""
    __tablename__ = 'instance_metadata'
    __table_args__ = (
        Index('instance_metadata_instance_uuid_idx', 'instance_uuid'),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))
    instance = relationship(Instance, backref="metadata",
                            foreign_keys=instance_uuid,
                            primaryjoin='and_('
                                'InstanceMetadata.instance_uuid == '
                                     'Instance.uuid,'
                                'InstanceMetadata.deleted == 0)')


class InstanceSystemMetadata(BASE, NovaBase):
    """Represents a system-owned metadata key/value pair for an instance."""
    __tablename__ = 'instance_system_metadata'
    __table_args__ = ()
    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)
    value = Column(String(255))
    instance_uuid = Column(String(36),
                           ForeignKey('instances.uuid'),
                           nullable=False)

    primary_join = ('and_(InstanceSystemMetadata.instance_uuid == '
                    'Instance.uuid, InstanceSystemMetadata.deleted == 0)')
    instance = relationship(Instance, backref="system_metadata",
                            foreign_keys=instance_uuid,
                            primaryjoin=primary_join)


class InstanceTypeProjects(BASE, NovaBase):
    """Represent projects associated instance_types."""
    __tablename__ = "instance_type_projects"
    __table_args__ = (schema.UniqueConstraint(
        "instance_type_id", "project_id", "deleted",
        name="uniq_instance_type_projects0instance_type_id0project_id0deleted"
        ),
    )
    id = Column(Integer, primary_key=True)
    instance_type_id = Column(Integer, ForeignKey('instance_types.id'),
                              nullable=False)
    project_id = Column(String(255))

    instance_type = relationship(InstanceTypes, backref="projects",
                 foreign_keys=instance_type_id,
                 primaryjoin='and_('
                 'InstanceTypeProjects.instance_type_id == InstanceTypes.id,'
                 'InstanceTypeProjects.deleted == 0)')


class InstanceTypeExtraSpecs(BASE, NovaBase):
    """Represents additional specs as key/value pairs for an instance_type."""
    __tablename__ = 'instance_type_extra_specs'
    __table_args__ = (
        Index('instance_type_extra_specs_instance_type_id_key_idx',
              'instance_type_id', 'key'),
        schema.UniqueConstraint(
              "instance_type_id", "key", "deleted",
              name=("uniq_instance_type_extra_specs0"
                    "instance_type_id0key0deleted")
        ),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    instance_type_id = Column(Integer, ForeignKey('instance_types.id'),
                              nullable=False)
    instance_type = relationship(InstanceTypes, backref="extra_specs",
                 foreign_keys=instance_type_id,
                 primaryjoin='and_('
                 'InstanceTypeExtraSpecs.instance_type_id == InstanceTypes.id,'
                 'InstanceTypeExtraSpecs.deleted == 0)')


class Cell(BASE, NovaBase):
    """Represents parent and child cells of this cell.  Cells can
    have multiple parents and children, so there could be any number
    of entries with is_parent=True or False
    """
    __tablename__ = 'cells'
    __table_args__ = (schema.UniqueConstraint(
        "name", "deleted", name="uniq_cells0name0deleted"
        ),
    )
    id = Column(Integer, primary_key=True)
    # Name here is the 'short name' of a cell.  For instance: 'child1'
    name = Column(String(255))
    api_url = Column(String(255))

    transport_url = Column(String(255), nullable=False)

    weight_offset = Column(Float(), default=0.0)
    weight_scale = Column(Float(), default=1.0)
    is_parent = Column(Boolean())


class AggregateHost(BASE, NovaBase):
    """Represents a host that is member of an aggregate."""
    __tablename__ = 'aggregate_hosts'
    __table_args__ = (schema.UniqueConstraint(
        "host", "aggregate_id", "deleted",
         name="uniq_aggregate_hosts0host0aggregate_id0deleted"
        ),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255))
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class AggregateMetadata(BASE, NovaBase):
    """Represents a metadata key/value pair for an aggregate."""
    __tablename__ = 'aggregate_metadata'
    __table_args__ = (
        schema.UniqueConstraint("aggregate_id", "key", "deleted",
            name="uniq_aggregate_metadata0aggregate_id0key0deleted"
            ),
        Index('aggregate_metadata_key_idx', 'key'),
    )
    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)
    value = Column(String(255), nullable=False)
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class Aggregate(BASE, NovaBase):
    """Represents a cluster of hosts that exists in this zone."""
    __tablename__ = 'aggregates'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    _hosts = relationship(AggregateHost,
                          primaryjoin='and_('
                          'Aggregate.id == AggregateHost.aggregate_id,'
                          'AggregateHost.deleted == 0,'
                          'Aggregate.deleted == 0)')

    _metadata = relationship(AggregateMetadata,
                             primaryjoin='and_('
                             'Aggregate.id == AggregateMetadata.aggregate_id,'
                             'AggregateMetadata.deleted == 0,'
                             'Aggregate.deleted == 0)')

    @property
    def _extra_keys(self):
        return ['hosts', 'metadetails', 'availability_zone']

    @property
    def hosts(self):
        return [h.host for h in self._hosts]

    @property
    def metadetails(self):
        return dict([(m.key, m.value) for m in self._metadata])

    @property
    def availability_zone(self):
        if 'availability_zone' not in self.metadetails:
            return None
        return self.metadetails['availability_zone']


class AgentBuild(BASE, NovaBase):
    """Represents an agent build."""
    __tablename__ = 'agent_builds'
    __table_args__ = (
        Index('agent_builds_hypervisor_os_arch_idx', 'hypervisor', 'os',
              'architecture'),
        schema.UniqueConstraint("hypervisor", "os", "architecture", "deleted",
                name="uniq_agent_builds0hypervisor0os0architecture0deleted"),
    )
    id = Column(Integer, primary_key=True)
    hypervisor = Column(String(255))
    os = Column(String(255))
    architecture = Column(String(255))
    version = Column(String(255))
    url = Column(String(255))
    md5hash = Column(String(255))


class BandwidthUsage(BASE, NovaBase):
    """Cache for instance bandwidth usage data pulled from the hypervisor."""
    __tablename__ = 'bw_usage_cache'
    __table_args__ = (
        Index('bw_usage_cache_uuid_start_period_idx', 'uuid',
              'start_period'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    uuid = Column(String(36))
    mac = Column(String(255))
    start_period = Column(DateTime, nullable=False)
    last_refreshed = Column(DateTime)
    bw_in = Column(BigInteger)
    bw_out = Column(BigInteger)
    last_ctr_in = Column(BigInteger)
    last_ctr_out = Column(BigInteger)


class VolumeUsage(BASE, NovaBase):
    """Cache for volume usage data pulled from the hypervisor."""
    __tablename__ = 'volume_usage_cache'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False)
    volume_id = Column(String(36), nullable=False)
    instance_uuid = Column(String(36))
    project_id = Column(String(36))
    user_id = Column(String(36))
    availability_zone = Column(String(255))
    tot_last_refreshed = Column(DateTime)
    tot_reads = Column(BigInteger, default=0)
    tot_read_bytes = Column(BigInteger, default=0)
    tot_writes = Column(BigInteger, default=0)
    tot_write_bytes = Column(BigInteger, default=0)
    curr_last_refreshed = Column(DateTime)
    curr_reads = Column(BigInteger, default=0)
    curr_read_bytes = Column(BigInteger, default=0)
    curr_writes = Column(BigInteger, default=0)
    curr_write_bytes = Column(BigInteger, default=0)


class S3Image(BASE, NovaBase):
    """Compatibility layer for the S3 image service talking to Glance."""
    __tablename__ = 's3_images'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class VolumeIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 volume service."""
    __tablename__ = 'volume_id_mappings'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class SnapshotIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 snapshot service."""
    __tablename__ = 'snapshot_id_mappings'
    __table_args__ = ()
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class InstanceFault(BASE, NovaBase):
    __tablename__ = 'instance_faults'
    __table_args__ = (
        Index('instance_faults_host_idx', 'host'),
        Index('instance_faults_instance_uuid_deleted_created_at_idx',
              'instance_uuid', 'deleted', 'created_at')
    )

    id = Column(Integer, primary_key=True, nullable=False)
    instance_uuid = Column(String(36),
                           ForeignKey('instances.uuid'))
    code = Column(Integer(), nullable=False)
    message = Column(String(255))
    details = Column(MediumText())
    host = Column(String(255))


class InstanceAction(BASE, NovaBase):
    """Track client actions on an instance.

    The intention is that there will only be one of these per user request.  A
    lookup by (instance_uuid, request_id) should always return a single result.
    """
    __tablename__ = 'instance_actions'
    __table_args__ = (
        Index('instance_uuid_idx', 'instance_uuid'),
        Index('request_id_idx', 'request_id')
    )

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    action = Column(String(255))
    instance_uuid = Column(String(36),
                           ForeignKey('instances.uuid'))
    request_id = Column(String(255))
    user_id = Column(String(255))
    project_id = Column(String(255))
    start_time = Column(DateTime, default=timeutils.utcnow)
    finish_time = Column(DateTime)
    message = Column(String(255))


class InstanceActionEvent(BASE, NovaBase):
    """Track events that occur during an InstanceAction."""
    __tablename__ = 'instance_actions_events'
    __table_args__ = ()

    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    event = Column(String(255))
    action_id = Column(Integer, ForeignKey('instance_actions.id'))
    start_time = Column(DateTime, default=timeutils.utcnow)
    finish_time = Column(DateTime)
    result = Column(String(255))
    traceback = Column(Text)
    host = Column(String(255))
    details = Column(Text)


class InstanceIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 instance service."""
    __tablename__ = 'instance_id_mappings'
    __table_args__ = (
        Index('ix_instance_id_mappings_uuid', 'uuid'),
    )
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class TaskLog(BASE, NovaBase):
    """Audit log for background periodic tasks."""
    __tablename__ = 'task_log'
    __table_args__ = (
        schema.UniqueConstraint(
            'task_name', 'host', 'period_beginning', 'period_ending',
            name="uniq_task_log0task_name0host0period_beginning0period_ending"
        ),
        Index('ix_task_log_period_beginning', 'period_beginning'),
        Index('ix_task_log_host', 'host'),
        Index('ix_task_log_period_ending', 'period_ending'),
    )
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    task_name = Column(String(255), nullable=False)
    state = Column(String(255), nullable=False)
    host = Column(String(255), nullable=False)
    period_beginning = Column(DateTime, default=timeutils.utcnow,
                              nullable=False)
    period_ending = Column(DateTime, default=timeutils.utcnow,
                           nullable=False)
    message = Column(String(255), nullable=False)
    task_items = Column(Integer(), default=0)
    errors = Column(Integer(), default=0)


class InstanceGroupMember(BASE, NovaBase):
    """Represents the members for an instance group."""
    __tablename__ = 'instance_group_member'
    __table_args__ = (
        Index('instance_group_member_instance_idx', 'instance_id'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    instance_id = Column(String(255))
    group_id = Column(Integer, ForeignKey('instance_groups.id'),
                      nullable=False)


class InstanceGroupPolicy(BASE, NovaBase):
    """Represents the policy type for an instance group."""
    __tablename__ = 'instance_group_policy'
    __table_args__ = (
        Index('instance_group_policy_policy_idx', 'policy'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    policy = Column(String(255))
    group_id = Column(Integer, ForeignKey('instance_groups.id'),
                      nullable=False)


class InstanceGroupMetadata(BASE, NovaBase):
    """Represents a key/value pair for an instance group."""
    __tablename__ = 'instance_group_metadata'
    __table_args__ = (
        Index('instance_group_metadata_key_idx', 'key'),
    )
    id = Column(Integer, primary_key=True, nullable=False)
    key = Column(String(255))
    value = Column(String(255))
    group_id = Column(Integer, ForeignKey('instance_groups.id'),
                      nullable=False)


class InstanceGroup(BASE, NovaBase):
    """Represents an instance group.

    A group will maintain a collection of instances and the relationship
    between them.
    """

    __tablename__ = 'instance_groups'
    __table_args__ = (
        schema.UniqueConstraint("uuid", "deleted",
                                 name="uniq_instance_groups0uuid0deleted"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(255))
    project_id = Column(String(255))
    uuid = Column(String(36), nullable=False)
    name = Column(String(255))
    _policies = relationship(InstanceGroupPolicy, primaryjoin='and_('
        'InstanceGroup.id == InstanceGroupPolicy.group_id,'
        'InstanceGroupPolicy.deleted == 0,'
        'InstanceGroup.deleted == 0)')
    _metadata = relationship(InstanceGroupMetadata, primaryjoin='and_('
        'InstanceGroup.id == InstanceGroupMetadata.group_id,'
        'InstanceGroupMetadata.deleted == 0,'
        'InstanceGroup.deleted == 0)')
    _members = relationship(InstanceGroupMember, primaryjoin='and_('
        'InstanceGroup.id == InstanceGroupMember.group_id,'
        'InstanceGroupMember.deleted == 0,'
        'InstanceGroup.deleted == 0)')

    @property
    def policies(self):
        return [p.policy for p in self._policies]

    @property
    def metadetails(self):
        return dict((m.key, m.value) for m in self._metadata)

    @property
    def members(self):
        return [m.instance_id for m in self._members]


class PciDevice(BASE, NovaBase):
    """Represents a PCI host device that can be passed through to instances.
    """
    __tablename__ = 'pci_devices'
    __table_args__ = (
        Index('ix_pci_devices_compute_node_id_deleted',
              'compute_node_id', 'deleted'),
        Index('ix_pci_devices_instance_uuid_deleted',
              'instance_uuid', 'deleted'),
        schema.UniqueConstraint(
            "compute_node_id", "address", "deleted",
            name="uniq_pci_devices0compute_node_id0address0deleted")
    )
    id = Column(Integer, primary_key=True)

    compute_node_id = Column(Integer, ForeignKey('compute_nodes.id'),
                             nullable=False)

    # physical address of device domain:bus:slot.func (0000:09:01.1)
    address = Column(String(12), nullable=False)

    vendor_id = Column(String(4), nullable=False)
    product_id = Column(String(4), nullable=False)
    dev_type = Column(String(8), nullable=False)
    dev_id = Column(String(255))

    # label is abstract device name, that is used to unify devices with the
    # same functionality with different addresses or host.
    label = Column(String(255), nullable=False)

    status = Column(String(36), nullable=False)

    extra_info = Column(Text)

    instance_uuid = Column(String(36))
    instance = relationship(Instance, backref="pci_devices",
                            foreign_keys=instance_uuid,
                            primaryjoin='and_('
                            'PciDevice.instance_uuid == Instance.uuid,'
                            'PciDevice.deleted == 0)')
