# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy.orm import relationship, backref, object_mapper
from sqlalchemy import Column, Integer, String, schema
from sqlalchemy import ForeignKey, DateTime, Boolean, Text, Float
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import ForeignKeyConstraint

from nova.db.sqlalchemy.session import get_session

from nova import auth
from nova import exception
from nova import flags
from nova import ipv6
from nova import utils


FLAGS = flags.FLAGS
BASE = declarative_base()


class NovaBase(object):
    """Base class for Nova Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    created_at = Column(DateTime, default=utils.utcnow)
    updated_at = Column(DateTime, onupdate=utils.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)
    metadata = None

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = get_session()
        session.add(self)
        try:
            session.flush()
        except IntegrityError, e:
            if str(e).endswith('is not unique'):
                raise exception.Duplicate(str(e))
            else:
                raise

    def delete(self, session=None):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = utils.utcnow()
        self.save(session=session)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def update(self, values):
        """Make the model object behave like a dict"""
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
    availability_zone = Column(String(255), default='nova')


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
                                'ComputeNode.deleted == False)')

    vcpus = Column(Integer)
    memory_mb = Column(Integer)
    local_gb = Column(Integer)
    vcpus_used = Column(Integer)
    memory_mb_used = Column(Integer)
    local_gb_used = Column(Integer)
    hypervisor_type = Column(Text)
    hypervisor_version = Column(Integer)

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


class Certificate(BASE, NovaBase):
    """Represents a an x509 certificate"""
    __tablename__ = 'certificates'
    id = Column(Integer, primary_key=True)

    user_id = Column(String(255))
    project_id = Column(String(255))
    file_name = Column(String(255))


class Instance(BASE, NovaBase):
    """Represents a guest vm."""
    __tablename__ = 'instances'
    injected_files = []

    id = Column(Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        base_name = FLAGS.instance_name_template % self.id
        if getattr(self, '_rescue', False):
            base_name += "-rescue"
        return base_name

    user_id = Column(String(255))
    project_id = Column(String(255))

    image_ref = Column(String(255))
    kernel_id = Column(String(255))
    ramdisk_id = Column(String(255))
    server_name = Column(String(255))

#    image_ref = Column(Integer, ForeignKey('images.id'), nullable=True)
#    kernel_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk = relationship(Ramdisk, backref=backref('instances', order_by=id))
#    kernel = relationship(Kernel, backref=backref('instances', order_by=id))
#    project = relationship(Project, backref=backref('instances', order_by=id))

    launch_index = Column(Integer)
    key_name = Column(String(255))
    key_data = Column(Text)

    power_state = Column(Integer)
    vm_state = Column(String(255))
    task_state = Column(String(255))

    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    local_gb = Column(Integer)

    hostname = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))

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

    # To remember on which host a instance booted.
    # An instance may have moved to another host by live migraiton.
    launched_on = Column(Text)
    locked = Column(Boolean)

    os_type = Column(String(255))
    architecture = Column(String(255))
    vm_mode = Column(String(255))
    uuid = Column(String(36))

    root_device_name = Column(String(255))
    default_local_device = Column(String(255), nullable=True)
    default_swap_device = Column(String(255), nullable=True)
    config_drive = Column(String(255))

    # User editable field meant to represent what ip should be used
    # to connect to the instance
    access_ip_v4 = Column(String(255))
    access_ip_v6 = Column(String(255))


class VirtualStorageArray(BASE, NovaBase):
    """
    Represents a virtual storage array supplying block storage to instances.
    """
    __tablename__ = 'virtual_storage_arrays'

    id = Column(Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        return FLAGS.vsa_name_template % self.id

    # User editable field for display in user-facing UIs
    display_name = Column(String(255))
    display_description = Column(String(255))

    project_id = Column(String(255))
    availability_zone = Column(String(255))

    instance_type_id = Column(Integer, ForeignKey('instance_types.id'))
    image_ref = Column(String(255))
    vc_count = Column(Integer, default=0)   # number of requested VC instances
    vol_count = Column(Integer, default=0)  # total number of BE volumes
    status = Column(String(255))


class InstanceActions(BASE, NovaBase):
    """Represents a guest VM's actions and results"""
    __tablename__ = "instance_actions"
    id = Column(Integer, primary_key=True)
    instance_id = Column(Integer, ForeignKey('instances.id'))

    action = Column(String(255))
    error = Column(Text)


class InstanceTypes(BASE, NovaBase):
    """Represent possible instance_types or flavor of VM offered"""
    __tablename__ = "instance_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True)
    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    local_gb = Column(Integer)
    flavorid = Column(Integer, unique=True)
    swap = Column(Integer, nullable=False, default=0)
    rxtx_quota = Column(Integer, nullable=False, default=0)
    rxtx_cap = Column(Integer, nullable=False, default=0)

    instances = relationship(Instance,
                           backref=backref('instance_type', uselist=False),
                           foreign_keys=id,
                           primaryjoin='and_(Instance.instance_type_id == '
                                       'InstanceTypes.id)')

    vsas = relationship(VirtualStorageArray,
                       backref=backref('vsa_instance_type', uselist=False),
                       foreign_keys=id,
                       primaryjoin='and_(VirtualStorageArray.instance_type_id'
                                   ' == InstanceTypes.id)')


class Volume(BASE, NovaBase):
    """Represents a block storage device that can be attached to a vm."""
    __tablename__ = 'volumes'
    id = Column(Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        return FLAGS.volume_name_template % self.id

    user_id = Column(String(255))
    project_id = Column(String(255))

    snapshot_id = Column(String(255))

    host = Column(String(255))  # , ForeignKey('hosts.id'))
    size = Column(Integer)
    availability_zone = Column(String(255))  # TODO(vish): foreign key?
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=True)
    instance = relationship(Instance,
                            backref=backref('volumes'),
                            foreign_keys=instance_id,
                            primaryjoin='and_(Volume.instance_id==Instance.id,'
                                             'Volume.deleted==False)')
    mountpoint = Column(String(255))
    attach_time = Column(String(255))  # TODO(vish): datetime
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


class VolumeMetadata(BASE, NovaBase):
    """Represents a metadata key/value pair for a volume"""
    __tablename__ = 'volume_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_id = Column(Integer, ForeignKey('volumes.id'), nullable=False)
    volume = relationship(Volume, backref="volume_metadata",
                            foreign_keys=volume_id,
                            primaryjoin='and_('
                                'VolumeMetadata.volume_id == Volume.id,'
                                'VolumeMetadata.deleted == False)')


class VolumeTypes(BASE, NovaBase):
    """Represent possible volume_types of volumes offered"""
    __tablename__ = "volume_types"
    id = Column(Integer, primary_key=True)
    name = Column(String(255), unique=True)

    volumes = relationship(Volume,
                           backref=backref('volume_type', uselist=False),
                           foreign_keys=id,
                           primaryjoin='and_(Volume.volume_type_id == '
                                       'VolumeTypes.id)')


class VolumeTypeExtraSpecs(BASE, NovaBase):
    """Represents additional specs as key/value pairs for a volume_type"""
    __tablename__ = 'volume_type_extra_specs'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    volume_type_id = Column(Integer, ForeignKey('volume_types.id'),
                              nullable=False)
    volume_type = relationship(VolumeTypes, backref="extra_specs",
                 foreign_keys=volume_type_id,
                 primaryjoin='and_('
                 'VolumeTypeExtraSpecs.volume_type_id == VolumeTypes.id,'
                 'VolumeTypeExtraSpecs.deleted == False)')


class Quota(BASE, NovaBase):
    """Represents a single quota override for a project.

    If there is no row for a given project id and resource, then
    the default for the deployment is used. If the row is present
    but the hard limit is Null, then the resource is unlimited.
    """

    __tablename__ = 'quotas'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255), index=True)

    resource = Column(String(255))
    hard_limit = Column(Integer, nullable=True)


class Snapshot(BASE, NovaBase):
    """Represents a block storage device that can be attached to a vm."""
    __tablename__ = 'snapshots'
    id = Column(Integer, primary_key=True, autoincrement=True)

    @property
    def name(self):
        return FLAGS.snapshot_name_template % self.id

    @property
    def volume_name(self):
        return FLAGS.volume_name_template % self.volume_id

    user_id = Column(String(255))
    project_id = Column(String(255))

    volume_id = Column(Integer)
    status = Column(String(255))
    progress = Column(String(255))
    volume_size = Column(Integer)

    display_name = Column(String(255))
    display_description = Column(String(255))


class BlockDeviceMapping(BASE, NovaBase):
    """Represents block device mapping that is defined by EC2"""
    __tablename__ = "block_device_mapping"
    id = Column(Integer, primary_key=True, autoincrement=True)

    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=False)
    instance = relationship(Instance,
                            backref=backref('balock_device_mapping'),
                            foreign_keys=instance_id,
                            primaryjoin='and_(BlockDeviceMapping.instance_id=='
                                              'Instance.id,'
                                              'BlockDeviceMapping.deleted=='
                                              'False)')
    device_name = Column(String(255), nullable=False)

    # default=False for compatibility of the existing code.
    # With EC2 API,
    # default True for ami specified device.
    # default False for created with other timing.
    delete_on_termination = Column(Boolean, default=False)

    # for ephemeral device
    virtual_name = Column(String(255), nullable=True)

    # for snapshot or volume
    snapshot_id = Column(Integer, ForeignKey('snapshots.id'), nullable=True)
    # outer join
    snapshot = relationship(Snapshot,
                            foreign_keys=snapshot_id)

    volume_id = Column(Integer, ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume,
                          foreign_keys=volume_id)
    volume_size = Column(Integer, nullable=True)

    # for no device to suppress devices.
    no_device = Column(Boolean, nullable=True)


class ExportDevice(BASE, NovaBase):
    """Represates a shelf and blade that a volume can be exported on."""
    __tablename__ = 'export_devices'
    __table_args__ = (schema.UniqueConstraint("shelf_id", "blade_id"),
                      {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer)
    blade_id = Column(Integer)
    volume_id = Column(Integer, ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume,
                          backref=backref('export_device', uselist=False),
                          foreign_keys=volume_id,
                          primaryjoin='and_(ExportDevice.volume_id==Volume.id,'
                                           'ExportDevice.deleted==False)')


class IscsiTarget(BASE, NovaBase):
    """Represates an iscsi target for a given host"""
    __tablename__ = 'iscsi_targets'
    __table_args__ = (schema.UniqueConstraint("target_num", "host"),
                      {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)
    target_num = Column(Integer)
    host = Column(String(255))
    volume_id = Column(Integer, ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume,
                          backref=backref('iscsi_target', uselist=False),
                          foreign_keys=volume_id,
                          primaryjoin='and_(IscsiTarget.volume_id==Volume.id,'
                                           'IscsiTarget.deleted==False)')


class SecurityGroupInstanceAssociation(BASE, NovaBase):
    __tablename__ = 'security_group_instance_association'
    id = Column(Integer, primary_key=True)
    security_group_id = Column(Integer, ForeignKey('security_groups.id'))
    instance_id = Column(Integer, ForeignKey('instances.id'))


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
        'SecurityGroupInstanceAssociation.deleted == False,'
        'SecurityGroup.deleted == False)',
                             secondaryjoin='and_('
        'SecurityGroupInstanceAssociation.instance_id == Instance.id,'
        # (anthony) the condition below shouldn't be necessary now that the
        # association is being marked as deleted.  However, removing this
        # may cause existing deployments to choke, so I'm leaving it
        'Instance.deleted == False)',
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
        'SecurityGroupIngressRule.deleted == False)')

    protocol = Column(String(5))  # "tcp", "udp", or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(String(255))

    # Note: This is not the parent SecurityGroup. It's SecurityGroup we're
    # granting access for.
    group_id = Column(Integer, ForeignKey('security_groups.id'))
    grantee_group = relationship("SecurityGroup",
                                 foreign_keys=group_id,
                                 primaryjoin='and_('
        'SecurityGroupIngressRule.group_id == SecurityGroup.id,'
        'SecurityGroupIngressRule.deleted == False)')


class ProviderFirewallRule(BASE, NovaBase):
    """Represents a rule in a security group."""
    __tablename__ = 'provider_fw_rules'
    id = Column(Integer, primary_key=True)

    protocol = Column(String(5))  # "tcp", "udp", or "icmp"
    from_port = Column(Integer)
    to_port = Column(Integer)
    cidr = Column(String(255))


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
    source_compute = Column(String(255))
    dest_compute = Column(String(255))
    dest_host = Column(String(255))
    old_instance_type_id = Column(Integer())
    new_instance_type_id = Column(Integer())
    instance_uuid = Column(String(255), ForeignKey('instances.uuid'),
            nullable=True)
    #TODO(_cerberus_): enum
    status = Column(String(255))


class Network(BASE, NovaBase):
    """Represents a network."""
    __tablename__ = 'networks'
    __table_args__ = (schema.UniqueConstraint("vpn_public_address",
                                              "vpn_public_port"),
                      {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)
    label = Column(String(255))

    injected = Column(Boolean, default=False)
    cidr = Column(String(255), unique=True)
    cidr_v6 = Column(String(255), unique=True)
    multi_host = Column(Boolean, default=False)

    gateway_v6 = Column(String(255))
    netmask_v6 = Column(String(255))
    netmask = Column(String(255))
    bridge = Column(String(255))
    bridge_interface = Column(String(255))
    gateway = Column(String(255))
    broadcast = Column(String(255))
    dns1 = Column(String(255))
    dns2 = Column(String(255))

    vlan = Column(Integer)
    vpn_public_address = Column(String(255))
    vpn_public_port = Column(Integer)
    vpn_private_address = Column(String(255))
    dhcp_start = Column(String(255))

    project_id = Column(String(255))
    priority = Column(Integer)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    uuid = Column(String(36))


class VirtualInterface(BASE, NovaBase):
    """Represents a virtual interface on an instance."""
    __tablename__ = 'virtual_interfaces'
    id = Column(Integer, primary_key=True)
    address = Column(String(255), unique=True)
    network_id = Column(Integer, ForeignKey('networks.id'))
    network = relationship(Network, backref=backref('virtual_interfaces'))

    # TODO(tr3buchet): cut the cord, removed foreign key and backrefs
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=False)
    instance = relationship(Instance, backref=backref('virtual_interfaces'))

    uuid = Column(String(36))

    @property
    def fixed_ipv6(self):
        cidr_v6 = self.network.cidr_v6
        if cidr_v6 is None:
            ipv6_address = None
        else:
            project_id = self.instance.project_id
            mac = self.address
            ipv6_address = ipv6.to_global(cidr_v6, mac, project_id)

        return ipv6_address


# TODO(vish): can these both come from the same baseclass?
class FixedIp(BASE, NovaBase):
    """Represents a fixed ip for an instance."""
    __tablename__ = 'fixed_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
    network_id = Column(Integer, ForeignKey('networks.id'), nullable=True)
    network = relationship(Network, backref=backref('fixed_ips'))
    virtual_interface_id = Column(Integer, ForeignKey('virtual_interfaces.id'),
                                                                 nullable=True)
    virtual_interface = relationship(VirtualInterface,
                                     backref=backref('fixed_ips'))
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=True)
    instance = relationship(Instance,
                            backref=backref('fixed_ips'),
                            foreign_keys=instance_id,
                            primaryjoin='and_('
                                'FixedIp.instance_id == Instance.id,'
                                'FixedIp.deleted == False)')
    # associated means that a fixed_ip has its instance_id column set
    # allocated means that a fixed_ip has a its virtual_interface_id column set
    allocated = Column(Boolean, default=False)
    # leased means dhcp bridge has leased the ip
    leased = Column(Boolean, default=False)
    reserved = Column(Boolean, default=False)
    host = Column(String(255))


class FloatingIp(BASE, NovaBase):
    """Represents a floating ip that dynamically forwards to a fixed ip."""
    __tablename__ = 'floating_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
    fixed_ip_id = Column(Integer, ForeignKey('fixed_ips.id'), nullable=True)
    fixed_ip = relationship(FixedIp,
                            backref=backref('floating_ips'),
                            foreign_keys=fixed_ip_id,
                            primaryjoin='and_('
                                'FloatingIp.fixed_ip_id == FixedIp.id,'
                                'FloatingIp.deleted == False)')
    project_id = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    auto_assigned = Column(Boolean, default=False, nullable=False)


class AuthToken(BASE, NovaBase):
    """Represents an authorization token for all API transactions.

    Fields are a string representing the actual token and a user id for
    mapping to the actual user

    """
    __tablename__ = 'auth_tokens'
    token_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255))
    server_management_url = Column(String(255))
    storage_url = Column(String(255))
    cdn_management_url = Column(String(255))


class User(BASE, NovaBase):
    """Represents a user."""
    __tablename__ = 'users'
    id = Column(String(255), primary_key=True)

    name = Column(String(255))
    access_key = Column(String(255))
    secret_key = Column(String(255))

    is_admin = Column(Boolean)


class Project(BASE, NovaBase):
    """Represents a project."""
    __tablename__ = 'projects'
    id = Column(String(255), primary_key=True)
    name = Column(String(255))
    description = Column(String(255))

    project_manager = Column(String(255), ForeignKey(User.id))

    members = relationship(User,
                           secondary='user_project_association',
                           backref='projects')


class UserProjectRoleAssociation(BASE, NovaBase):
    __tablename__ = 'user_project_role_association'
    user_id = Column(String(255), primary_key=True)
    user = relationship(User,
                        primaryjoin=user_id == User.id,
                        foreign_keys=[User.id],
                        uselist=False)

    project_id = Column(String(255), primary_key=True)
    project = relationship(Project,
                           primaryjoin=project_id == Project.id,
                           foreign_keys=[Project.id],
                           uselist=False)

    role = Column(String(255), primary_key=True)
    ForeignKeyConstraint(['user_id',
                          'project_id'],
                         ['user_project_association.user_id',
                          'user_project_association.project_id'])


class UserRoleAssociation(BASE, NovaBase):
    __tablename__ = 'user_role_association'
    user_id = Column(String(255), ForeignKey('users.id'), primary_key=True)
    user = relationship(User, backref='roles')
    role = Column(String(255), primary_key=True)


class UserProjectAssociation(BASE, NovaBase):
    __tablename__ = 'user_project_association'
    user_id = Column(String(255), ForeignKey(User.id), primary_key=True)
    project_id = Column(String(255), ForeignKey(Project.id), primary_key=True)


class ConsolePool(BASE, NovaBase):
    """Represents pool of consoles on the same physical node."""
    __tablename__ = 'console_pools'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
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
    instance_id = Column(Integer)
    password = Column(String(255))
    port = Column(Integer, nullable=True)
    pool_id = Column(Integer, ForeignKey('console_pools.id'))
    pool = relationship(ConsolePool, backref=backref('consoles'))


class InstanceMetadata(BASE, NovaBase):
    """Represents a metadata key/value pair for an instance"""
    __tablename__ = 'instance_metadata'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    value = Column(String(255))
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=False)
    instance = relationship(Instance, backref="metadata",
                            foreign_keys=instance_id,
                            primaryjoin='and_('
                                'InstanceMetadata.instance_id == Instance.id,'
                                'InstanceMetadata.deleted == False)')


class InstanceTypeExtraSpecs(BASE, NovaBase):
    """Represents additional specs as key/value pairs for an instance_type"""
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
                 'InstanceTypeExtraSpecs.deleted == False)')


class Zone(BASE, NovaBase):
    """Represents a child zone of this zone."""
    __tablename__ = 'zones'
    id = Column(Integer, primary_key=True)
    api_url = Column(String(255))
    username = Column(String(255))
    password = Column(String(255))
    weight_offset = Column(Float(), default=0.0)
    weight_scale = Column(Float(), default=1.0)


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


def register_models():
    """Register Models and create metadata.

    Called from nova.db.sqlalchemy.__init__ as part of loading the driver,
    it will never need to be called explicitly elsewhere unless the
    connection is lost and needs to be reestablished.
    """
    from sqlalchemy import create_engine
    models = (Service, Instance, InstanceActions, InstanceTypes,
              Volume, ExportDevice, IscsiTarget, FixedIp, FloatingIp,
              Network, SecurityGroup, SecurityGroupIngressRule,
              SecurityGroupInstanceAssociation, AuthToken, User,
              Project, Certificate, ConsolePool, Console, Zone,
              VolumeMetadata, VolumeTypes, VolumeTypeExtraSpecs,
              AgentBuild, InstanceMetadata, InstanceTypeExtraSpecs, Migration,
              VirtualStorageArray)
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
