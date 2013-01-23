# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import Column, Integer, BigInteger, String, schema
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean, Text, Float
from sqlalchemy.orm import relationship, backref, object_mapper

from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy.types import IPAddress
from nova.openstack.common import cfg
from nova.openstack.common import timeutils


CONF = cfg.CONF
BASE = declarative_base()


class NovaBase(object):
    """Base class for Nova Models."""
    __table_initialized__ = False
    created_at = Column(DateTime, default=timeutils.utcnow)
    updated_at = Column(DateTime, onupdate=timeutils.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Integer, default=0)
    metadata = None

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = get_session()
        # NOTE(boris-42): This part of code should be look like:
        #                       sesssion.add(self)
        #                       session.flush()
        #                 But there is a bug in sqlalchemy and eventlet that
        #                 raises NoneType exception if there is no running
        #                 transaction and rollback is called. As long as
        #                 sqlalchemy has this bug we have to create transaction
        #                 explicity.
        with session.begin(subtransactions=True):
            session.add(self)
            session.flush()

    def soft_delete(self, session=None):
        """Mark this object as deleted."""
        self.deleted = self.id
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        columns = dict(object_mapper(self).columns).keys()
        # NOTE(russellb): Allow models to specify other keys that can be looked
        # up, beyond the actual db columns.  An example would be the 'name'
        # property for an Instance.
        if hasattr(self, '_extra_keys'):
            columns.extend(self._extra_keys())
        self._i = iter(columns)
        return self

    def next(self):
        n = self._i.next()
        return n, getattr(self, n)

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in values.iteritems():
            setattr(self, k, v)

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins."""
        local = dict(self)
        joined = dict([(k, v) for k, v in self.__dict__.iteritems()
                      if not k[0] == '_'])
        local.update(joined)
        return local.iteritems()


class Service(BASE, NovaBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)


class ComputeNode(BASE, NovaBase):
    """Represents a running compute service on a host."""

    __tablename__ = 'compute_nodes'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=True)
    service = relationship(Service,
                           backref=backref('compute_node'),
                           foreign_keys=service_id,
                           primaryjoin='and_('
                                'ComputeNode.service_id == Service.id,'
                                'ComputeNode.deleted == 0)')

    vcpus = Column(Integer)
    memory_mb = Column(Integer)
    local_gb = Column(Integer)
    vcpus_used = Column(Integer)
    memory_mb_used = Column(Integer)
    local_gb_used = Column(Integer)
    hypervisor_type = Column(Text)
    hypervisor_version = Column(Integer)
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
    cpu_info = Column(Text, nullable=True)
    disk_available_least = Column(Integer)


class ComputeNodeStat(BASE, NovaBase):
    """Stats related to the current workload of a compute host that are
    intended to aid in making scheduler decisions."""
    __tablename__ = 'compute_node_stats'
    id = Column(Integer, primary_key=True)
    key = Column(String(511))
    value = Column(String(255))
    compute_node_id = Column(Integer, ForeignKey('compute_nodes.id'))

    primary_join = ('and_(ComputeNodeStat.compute_node_id == '
                    'ComputeNode.id, ComputeNodeStat.deleted == 0)')
    stats = relationship("ComputeNode", backref="stats",
            primaryjoin=primary_join)

    def __str__(self):
        return "{%d: %s = %s}" % (self.compute_node_id, self.key, self.value)


class Certificate(BASE, NovaBase):
    """Represents a x509 certificate."""
    __tablename__ = 'certificates'
    id = Column(Integer, primary_key=True)

    user_id = Column(String(255))
    project_id = Column(String(255))
    file_name = Column(String(255))


class Instance(BASE, NovaBase):
    """Represents a guest VM."""
    __tablename__ = 'instances'
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

    def _extra_keys(self):
        return ['name', 'system_metadata']

    user_id = Column(String(255))
    project_id = Column(String(255))

    image_ref = Column(String(255))
    kernel_id = Column(String(255))
    ramdisk_id = Column(String(255))
    hostname = Column(String(255))

#    image_ref = Column(Integer, ForeignKey('images.id'), nullable=True)
#    kernel_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk = relationship(Ramdisk, backref=backref('instances', order_by=id))
#    kernel = relationship(Kernel, backref=backref('instances', order_by=id))

    launch_index = Column(Integer)
    key_name = Column(String(255))
    key_data = Column(Text)

    power_state = Column(Integer)
    vm_state = Column(String(255))
    task_state = Column(String(255))

    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    root_gb = Column(Integer)
    ephemeral_gb = Column(Integer)

    # This is not related to hostname, above.  It refers
    #  to the nova node.
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    # To identify the "ComputeNode" which the instance resides in.
    # This equals to ComputeNode.hypervisor_hostname.
    node = Column(String(255))

    # *not* flavor_id
    instance_type_id = Column(Integer)

    user_data = Column(Text)

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
    launched_on = Column(Text)
    locked = Column(Boolean)

    os_type = Column(String(255))
    architecture = Column(String(255))
    vm_mode = Column(String(255))
    uuid = Column(String(36))

    root_device_name = Column(String(255))
    default_ephemeral_device = Column(String(255), nullable=True)
    default_swap_device = Column(String(255), nullable=True)
    config_drive = Column(String(255))

    # User editable field meant to represent what ip should be used
    # to connect to the instance
    access_ip_v4 = Column(IPAddress())
    access_ip_v6 = Column(IPAddress())

    auto_disk_config = Column(Boolean())
    progress = Column(Integer)

    # EC2 instance_initiated_shutdown_terminate
    # True: -> 'terminate'
    # False: -> 'stop'
    # Note(maoy): currently Nova will always stop instead of terminate
    # no matter what the flag says. So we set the default to False.
    shutdown_terminate = Column(Boolean(), default=False, nullable=False)

    # EC2 disable_api_termination
    disable_terminate = Column(Boolean(), default=False, nullable=False)

    # OpenStack compute cell name.  This will only be set at the top of
    # the cells tree and it'll be a full cell name such as 'api!hop1!hop2'
    cell_name = Column(String(255))


class InstanceInfoCache(BASE, NovaBase):
    """
    Represents a cache of information about an instance
    """
    __tablename__ = 'instance_info_caches'
    id = Column(Integer, primary_key=True, autoincrement=True)

    # text column used for storing a json object of network data for api
    network_info = Column(Text)

    instance_uuid = Column(String(36), ForeignKey('instances.uuid'),
                           nullable=False, unique=True)
    instance = relationship(Instance,
                            backref=backref('info_cache', uselist=False),
                            foreign_keys=instance_uuid,
                            primaryjoin=instance_uuid == Instance.uuid)


class InstanceTypes(BASE, NovaBase):
    """Represent possible instance_types or flavor of VM offered."""
    __tablename__ = "instance_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    root_gb = Column(Integer)
    ephemeral_gb = Column(Integer)
    flavorid = Column(String(255))
    swap = Column(Integer, nullable=False, default=0)
    rxtx_factor = Column(Float, nullable=False, default=1)
    vcpu_weight = Column(Integer, nullable=True)
    disabled = Column(Boolean, default=False)
    is_public = Column(Boolean, default=True)

    instances = relationship(Instance,
                           backref=backref('instance_type', uselist=False),
                           foreign_keys=id,
                           primaryjoin='and_('
                               'Instance.instance_type_id == '
                               'InstanceTypes.id)')


class Volume(BASE, NovaBase):
    """Represents a block storage device that can be attached to a VM."""
    __tablename__ = 'volumes'
    id = Column(String(36), primary_key=True)
    deleted = Column(String(36), default="")

    @property
    def name(self):
        return CONF.volume_name_template % self.id

    ec2_id = Column(Integer)
    user_id = Column(String(255))
    project_id = Column(String(255))

    snapshot_id = Column(String(36))

    host = Column(String(255))  # , ForeignKey('hosts.id'))
    size = Column(Integer)
    availability_zone = Column(String(255))  # TODO(vish): foreign key?
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

    provider_location = Column(String(255))
    provider_auth = Column(String(255))

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
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255), index=True)

    resource = Column(String(255))
    hard_limit = Column(Integer, nullable=True)


class QuotaClass(BASE, NovaBase):
    """Represents a single quota override for a quota class.

    If there is no row for a given quota class and resource, then the
    default for the deployment is used.  If the row is present but the
    hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quota_classes'
    id = Column(Integer, primary_key=True)

    class_name = Column(String(255), index=True)

    resource = Column(String(255))
    hard_limit = Column(Integer, nullable=True)


class QuotaUsage(BASE, NovaBase):
    """Represents the current usage for a given resource."""

    __tablename__ = 'quota_usages'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255), index=True)
    resource = Column(String(255))

    in_use = Column(Integer)
    reserved = Column(Integer)

    @property
    def total(self):
        return self.in_use + self.reserved

    until_refresh = Column(Integer, nullable=True)


class Reservation(BASE, NovaBase):
    """Represents a resource reservation for quotas."""

    __tablename__ = 'reservations'
    id = Column(Integer, primary_key=True)
    uuid = Column(String(36), nullable=False)

    usage_id = Column(Integer, ForeignKey('quota_usages.id'), nullable=False)

    project_id = Column(String(255), index=True)
    resource = Column(String(255))

    delta = Column(Integer)
    expire = Column(DateTime, nullable=False)

    usage = relationship(
        "QuotaUsage",
        foreign_keys=usage_id,
        primaryjoin='and_(Reservation.usage_id == QuotaUsage.id,'
                         'QuotaUsage.deleted == 0)')


class Snapshot(BASE, NovaBase):
    """Represents a block storage device that can be attached to a VM."""
    __tablename__ = 'snapshots'
    id = Column(String(36), primary_key=True)
    deleted = Column(String(36), default="")

    @property
    def name(self):
        return CONF.snapshot_name_template % self.id

    @property
    def volume_name(self):
        return CONF.volume_name_template % self.volume_id

    user_id = Column(String(255))
    project_id = Column(String(255))

    volume_id = Column(String(36))
    status = Column(String(255))
    progress = Column(String(255))
    volume_size = Column(Integer)

    display_name = Column(String(255))
    display_description = Column(String(255))


class BlockDeviceMapping(BASE, NovaBase):
    """Represents block device mapping that is defined by EC2."""
    __tablename__ = "block_device_mapping"
    id = Column(Integer, primary_key=True, autoincrement=True)

    instance_uuid = Column(Integer, ForeignKey('instances.uuid'),
                           nullable=False)
    instance = relationship(Instance,
                            backref=backref('block_device_mapping'),
                            foreign_keys=instance_uuid,
                            primaryjoin='and_(BlockDeviceMapping.'
                                              'instance_uuid=='
                                              'Instance.uuid,'
                                              'BlockDeviceMapping.deleted=='
                                              '0)')
    device_name = Column(String(255), nullable=False)

    # default=False for compatibility of the existing code.
    # With EC2 API,
    # default True for ami specified device.
    # default False for created with other timing.
    delete_on_termination = Column(Boolean, default=False)

    # for ephemeral device
    virtual_name = Column(String(255), nullable=True)

    snapshot_id = Column(String(36))

    volume_id = Column(String(36), nullable=True)
    volume_size = Column(Integer, nullable=True)

    # for no device to suppress devices.
    no_device = Column(Boolean, nullable=True)

    connection_info = Column(Text, nullable=True)


class IscsiTarget(BASE, NovaBase):
    """Represents an iscsi target for a given host."""
    __tablename__ = 'iscsi_targets'
    __table_args__ = (schema.UniqueConstraint("target_num", "host"), )
    id = Column(Integer, primary_key=True)
    target_num = Column(Integer)
    host = Column(String(255))
    volume_id = Column(String(36), ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume,
                          backref=backref('iscsi_target', uselist=False),
                          foreign_keys=volume_id,
                          primaryjoin='and_(IscsiTarget.volume_id==Volume.id,'
                                           'IscsiTarget.deleted==0)')


class SecurityGroupInstanceAssociation(BASE, NovaBase):
    __tablename__ = 'security_group_instance_association'
    id = Column(Integer, primary_key=True)
    security_group_id = Column(Integer, ForeignKey('security_groups.id'))
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'))


class SecurityGroup(BASE, NovaBase):
    """Represents a security group."""
    __tablename__ = 'security_groups'
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
    id = Column(Integer, primary_key=True)

    parent_group_id = Column(Integer, ForeignKey('security_groups.id'))
    parent_group = relationship("SecurityGroup", backref="rules",
                                foreign_keys=parent_group_id,
                                primaryjoin='and_('
        'SecurityGroupIngressRule.parent_group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')

    protocol = Column(String(5))  # "tcp", "udp", or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(IPAddress())

    # Note: This is not the parent SecurityGroup. It's SecurityGroup we're
    # granting access for.
    group_id = Column(Integer, ForeignKey('security_groups.id'))
    grantee_group = relationship("SecurityGroup",
                                 foreign_keys=group_id,
                                 primaryjoin='and_('
        'SecurityGroupIngressRule.group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == 0)')


class ProviderFirewallRule(BASE, NovaBase):
    """Represents a rule in a security group."""
    __tablename__ = 'provider_fw_rules'
    id = Column(Integer, primary_key=True)

    protocol = Column(String(5))  # "tcp", "udp", or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(IPAddress())


class KeyPair(BASE, NovaBase):
    """Represents a public key pair for ssh."""
    __tablename__ = 'key_pairs'
    id = Column(Integer, primary_key=True)

    name = Column(String(255))

    user_id = Column(String(255))

    fingerprint = Column(String(255))
    public_key = Column(Text)


class Migration(BASE, NovaBase):
    """Represents a running host-to-host migration."""
    __tablename__ = 'migrations'
    id = Column(Integer, primary_key=True, nullable=False)
    # NOTE(tr3buchet): the ____compute variables are instance['host']
    source_compute = Column(String(255))
    dest_compute = Column(String(255))
    # nodes are equivalent to a compute node's 'hypvervisor_hostname'
    source_node = Column(String(255))
    dest_node = Column(String(255))
    # NOTE(tr3buchet): dest_host, btw, is an ip address
    dest_host = Column(String(255))
    old_instance_type_id = Column(Integer())
    new_instance_type_id = Column(Integer())
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'),
            nullable=True)
    #TODO(_cerberus_): enum
    status = Column(String(255))

    instance = relationship("Instance", foreign_keys=instance_uuid,
                            primaryjoin='and_(Migration.instance_uuid == '
                                        'Instance.uuid, Instance.deleted == '
                                        '0)')


class Network(BASE, NovaBase):
    """Represents a network."""
    __tablename__ = 'networks'
    __table_args__ = (schema.UniqueConstraint("vpn_public_address",
                                              "vpn_public_port"), )
    id = Column(Integer, primary_key=True)
    label = Column(String(255))

    injected = Column(Boolean, default=False)
    cidr = Column(IPAddress(), unique=True)
    cidr_v6 = Column(IPAddress(), unique=True)
    multi_host = Column(Boolean, default=False)

    gateway_v6 = Column(IPAddress())
    netmask_v6 = Column(IPAddress())
    netmask = Column(IPAddress())
    bridge = Column(String(255))
    bridge_interface = Column(String(255))
    gateway = Column(IPAddress())
    broadcast = Column(IPAddress())
    dns1 = Column(IPAddress())
    dns2 = Column(IPAddress())

    vlan = Column(Integer)
    vpn_public_address = Column(IPAddress())
    vpn_public_port = Column(Integer)
    vpn_private_address = Column(IPAddress())
    dhcp_start = Column(IPAddress())

    rxtx_base = Column(Integer)

    project_id = Column(String(255))
    priority = Column(Integer)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    uuid = Column(String(36))


class VirtualInterface(BASE, NovaBase):
    """Represents a virtual interface on an instance."""
    __tablename__ = 'virtual_interfaces'
    id = Column(Integer, primary_key=True)
    address = Column(String(255), unique=True)
    network_id = Column(Integer, nullable=False)
    instance_uuid = Column(String(36), nullable=False)
    uuid = Column(String(36))


# TODO(vish): can these both come from the same baseclass?
class FixedIp(BASE, NovaBase):
    """Represents a fixed ip for an instance."""
    __tablename__ = 'fixed_ips'
    id = Column(Integer, primary_key=True)
    address = Column(IPAddress())
    network_id = Column(Integer, nullable=True)
    virtual_interface_id = Column(Integer, nullable=True)
    instance_uuid = Column(String(36), nullable=True)
    # associated means that a fixed_ip has its instance_id column set
    # allocated means that a fixed_ip has its virtual_interface_id column set
    allocated = Column(Boolean, default=False)
    # leased means dhcp bridge has leased the ip
    leased = Column(Boolean, default=False)
    reserved = Column(Boolean, default=False)
    host = Column(String(255))


class FloatingIp(BASE, NovaBase):
    """Represents a floating ip that dynamically forwards to a fixed ip."""
    __tablename__ = 'floating_ips'
    id = Column(Integer, primary_key=True)
    address = Column(IPAddress())
    fixed_ip_id = Column(Integer, nullable=True)
    project_id = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    auto_assigned = Column(Boolean, default=False, nullable=False)
    pool = Column(String(255))
    interface = Column(String(255))


class DNSDomain(BASE, NovaBase):
    """Represents a DNS domain with availability zone or project info."""
    __tablename__ = 'dns_domains'
    deleted = Column(Boolean, default=False)
    domain = Column(String(512), primary_key=True)
    scope = Column(String(255))
    availability_zone = Column(String(255))
    project_id = Column(String(255))


class ConsolePool(BASE, NovaBase):
    """Represents pool of consoles on the same physical node."""
    __tablename__ = 'console_pools'
    id = Column(Integer, primary_key=True)
    address = Column(IPAddress())
    username = Column(String(255))
    password = Column(String(255))
    console_type = Column(String(255))
    public_hostname = Column(String(255))
    host = Column(String(255))
    compute_host = Column(String(255))


class Console(BASE, NovaBase):
    """Represents a console session for an instance."""
    __tablename__ = 'consoles'
    id = Column(Integer, primary_key=True)
    instance_name = Column(String(255))
    instance_uuid = Column(String(36))
    password = Column(String(255))
    port = Column(Integer, nullable=True)
    pool_id = Column(Integer, ForeignKey('console_pools.id'))
    pool = relationship(ConsolePool, backref=backref('consoles'))


class InstanceMetadata(BASE, NovaBase):
    """Represents a user-provided metadata key/value pair for an instance."""
    __tablename__ = 'instance_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    instance_uuid = Column(String(36), ForeignKey('instances.uuid'),
                           nullable=False)
    instance = relationship(Instance, backref="metadata",
                            foreign_keys=instance_uuid,
                            primaryjoin='and_('
                                'InstanceMetadata.instance_uuid == '
                                     'Instance.uuid,'
                                'InstanceMetadata.deleted == 0)')


class InstanceSystemMetadata(BASE, NovaBase):
    """Represents a system-owned metadata key/value pair for an instance."""
    __tablename__ = 'instance_system_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
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
    id = Column(Integer, primary_key=True)
    # Name here is the 'short name' of a cell.  For instance: 'child1'
    name = Column(String(255))
    api_url = Column(String(255))
    # FIXME(comstud): username and password refer to the credentials
    # used for talking with the AMQP server within a particular cell.
    # This table needs cleanup to support more generic cells
    # communication (including via 0mq, for instance)
    username = Column(String(255))
    password = Column(String(255))
    weight_offset = Column(Float(), default=0.0)
    weight_scale = Column(Float(), default=1.0)
    is_parent = Column(Boolean())
    rpc_host = Column(String(255))
    rpc_port = Column(Integer())
    rpc_virtual_host = Column(String(255))


class AggregateHost(BASE, NovaBase):
    """Represents a host that is member of an aggregate."""
    __tablename__ = 'aggregate_hosts'
    id = Column(Integer, primary_key=True, autoincrement=True)
    host = Column(String(255), unique=False)
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class AggregateMetadata(BASE, NovaBase):
    """Represents a metadata key/value pair for an aggregate."""
    __tablename__ = 'aggregate_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255), nullable=False)
    value = Column(String(255), nullable=False)
    aggregate_id = Column(Integer, ForeignKey('aggregates.id'), nullable=False)


class Aggregate(BASE, NovaBase):
    """Represents a cluster of hosts that exists in this zone."""
    __tablename__ = 'aggregates'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255))
    _hosts = relationship(AggregateHost,
                          lazy="joined",
                          secondary="aggregate_hosts",
                          primaryjoin='and_('
                                 'Aggregate.id == AggregateHost.aggregate_id,'
                                 'AggregateHost.deleted == 0,'
                                 'Aggregate.deleted == 0)',
                         secondaryjoin='and_('
                                'AggregateHost.aggregate_id == Aggregate.id, '
                                'AggregateHost.deleted == 0,'
                                'Aggregate.deleted == 0)',
                         backref='aggregates')

    _metadata = relationship(AggregateMetadata,
                         secondary="aggregate_metadata",
                         primaryjoin='and_('
                             'Aggregate.id == AggregateMetadata.aggregate_id,'
                             'AggregateMetadata.deleted == 0,'
                             'Aggregate.deleted == 0)',
                         secondaryjoin='and_('
                             'AggregateMetadata.aggregate_id == Aggregate.id, '
                             'AggregateMetadata.deleted == 0,'
                             'Aggregate.deleted == 0)',
                         backref='aggregates')

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
    id = Column(Integer, primary_key=True, nullable=False)
    uuid = Column(String(36), nullable=False)
    mac = Column(String(255), nullable=False)
    start_period = Column(DateTime, nullable=False)
    last_refreshed = Column(DateTime)
    bw_in = Column(BigInteger)
    bw_out = Column(BigInteger)
    last_ctr_in = Column(BigInteger)
    last_ctr_out = Column(BigInteger)


class VolumeUsage(BASE, NovaBase):
    """Cache for volume usage data pulled from the hypervisor."""
    __tablename__ = 'volume_usage_cache'
    id = Column(Integer, primary_key=True, nullable=False)
    volume_id = Column(String(36), nullable=False)
    instance_id = Column(Integer)
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
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class VolumeIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 volume service."""
    __tablename__ = 'volume_id_mappings'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class SnapshotIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 snapshot service."""
    __tablename__ = 'snapshot_id_mappings'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class InstanceFault(BASE, NovaBase):
    __tablename__ = 'instance_faults'
    id = Column(Integer(), primary_key=True, autoincrement=True)
    instance_uuid = Column(String(36),
                           ForeignKey('instances.uuid'),
                           nullable=False)
    code = Column(Integer(), nullable=False)
    message = Column(String(255))
    details = Column(Text)
    host = Column(String(255))


class InstanceAction(BASE, NovaBase):
    """Track client actions on an instance."""
    __tablename__ = 'instance_actions'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    action = Column(String(255))
    instance_uuid = Column(String(36),
                           ForeignKey('instances.uuid'),
                           nullable=False)
    request_id = Column(String(255))
    user_id = Column(String(255))
    project_id = Column(String(255))
    start_time = Column(DateTime, default=timeutils.utcnow)
    finish_time = Column(DateTime)
    message = Column(String(255))


class InstanceActionEvent(BASE, NovaBase):
    """Track events that occur during an InstanceAction."""
    __tablename__ = 'instance_actions_events'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    event = Column(String(255))
    action_id = Column(Integer, ForeignKey('instance_actions.id'),
                       nullable=False)
    start_time = Column(DateTime, default=timeutils.utcnow)
    finish_time = Column(DateTime)
    result = Column(String(255))
    traceback = Column(Text)


class InstanceIdMapping(BASE, NovaBase):
    """Compatibility layer for the EC2 instance service."""
    __tablename__ = 'instance_id_mappings'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    uuid = Column(String(36), nullable=False)


class TaskLog(BASE, NovaBase):
    """Audit log for background periodic tasks."""
    __tablename__ = 'task_log'
    id = Column(Integer, primary_key=True, nullable=False, autoincrement=True)
    task_name = Column(String(255), nullable=False)
    state = Column(String(255), nullable=False)
    host = Column(String(255))
    period_beginning = Column(DateTime, default=timeutils.utcnow)
    period_ending = Column(DateTime, default=timeutils.utcnow)
    message = Column(String(255), nullable=False)
    task_items = Column(Integer(), default=0)
    errors = Column(Integer(), default=0)
