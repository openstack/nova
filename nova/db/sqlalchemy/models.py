# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import datetime

from sqlalchemy.orm import relationship, backref, object_mapper
from sqlalchemy import Column, Integer, String, schema
from sqlalchemy import ForeignKey, DateTime, Boolean, Text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import ForeignKeyConstraint

from nova.db.sqlalchemy.session import get_session

from nova import auth
from nova import exception
from nova import flags


FLAGS = flags.FLAGS
BASE = declarative_base()


class NovaBase(object):
    """Base class for Nova Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.datetime.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)

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
        self.deleted_at = datetime.datetime.utcnow()
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
        """Make the model object behave like a dict"""
        return iter(self)


# TODO(vish): Store images in the database instead of file system
#class Image(BASE, NovaBase):
#    """Represents an image in the datastore"""
#    __tablename__ = 'images'
#    id = Column(Integer, primary_key=True)
#    ec2_id = Column(String(12), unique=True)
#    user_id = Column(String(255))
#    project_id = Column(String(255))
#    image_type = Column(String(255))
#    public = Column(Boolean, default=False)
#    state = Column(String(255))
#    location = Column(String(255))
#    arch = Column(String(255))
#    default_kernel_id = Column(String(255))
#    default_ramdisk_id = Column(String(255))
#
#    @validates('image_type')
#    def validate_image_type(self, key, image_type):
#        assert(image_type in ['machine', 'kernel', 'ramdisk', 'raw'])
#
#    @validates('state')
#    def validate_state(self, key, state):
#        assert(state in ['available', 'pending', 'disabled'])
#
#    @validates('default_kernel_id')
#    def validate_kernel_id(self, key, val):
#        if val != 'machine':
#            assert(val is None)
#
#    @validates('default_ramdisk_id')
#    def validate_ramdisk_id(self, key, val):
#        if val != 'machine':
#            assert(val is None)
#
#
# TODO(vish): To make this into its own table, we need a good place to
#             create the host entries. In config somwhere? Or the first
#             time any object sets host? This only becomes particularly
#             important if we need to store per-host data.
#class Host(BASE, NovaBase):
#    """Represents a host where services are running"""
#    __tablename__ = 'hosts'
#    id = Column(String(255), primary_key=True)


class Service(BASE, NovaBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)


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
    id = Column(Integer, primary_key=True)
    internal_id = Column(Integer, unique=True)

    admin_pass = Column(String(255))

    user_id = Column(String(255))
    project_id = Column(String(255))

    @property
    def user(self):
        return auth.manager.AuthManager().get_user(self.user_id)

    @property
    def project(self):
        return auth.manager.AuthManager().get_project(self.project_id)

    @property
    def name(self):
        return "instance-%d" % self.internal_id

    image_id = Column(String(255))
    kernel_id = Column(String(255))
    ramdisk_id = Column(String(255))

#    image_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    kernel_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk_id = Column(Integer, ForeignKey('images.id'), nullable=True)
#    ramdisk = relationship(Ramdisk, backref=backref('instances', order_by=id))
#    kernel = relationship(Kernel, backref=backref('instances', order_by=id))
#    project = relationship(Project, backref=backref('instances', order_by=id))

    launch_index = Column(Integer)
    key_name = Column(String(255))
    key_data = Column(Text)

    state = Column(Integer)
    state_description = Column(String(255))

    memory_mb = Column(Integer)
    vcpus = Column(Integer)
    local_gb = Column(Integer)

    hostname = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))

    instance_type = Column(String(255))

    user_data = Column(Text)

    reservation_id = Column(String(255))
    mac_address = Column(String(255))

    scheduled_at = Column(DateTime)
    launched_at = Column(DateTime)
    terminated_at = Column(DateTime)

    availability_zone = Column(String(255))

    # User editable field for display in user-facing UIs
    display_name = Column(String(255))
    display_description = Column(String(255))

    # TODO(vish): see Ewan's email about state improvements, probably
    #             should be in a driver base class or some such
    # vmstate_state = running, halted, suspended, paused
    # power_state = what we have
    # task_state = transitory and may trigger power state transition

    #@validates('state')
    #def validate_state(self, key, state):
    #    assert(state in ['nostate', 'running', 'blocked', 'paused',
    #                     'shutdown', 'shutoff', 'crashed'])


class InstanceActions(BASE, NovaBase):
    """Represents a guest VM's actions and results"""
    __tablename__ = "instance_actions"
    id = Column(Integer, primary_key=True)
    instance_id = Column(Integer, ForeignKey('instances.id'))

    action = Column(String(255))
    error = Column(Text)


class Volume(BASE, NovaBase):
    """Represents a block storage device that can be attached to a vm."""
    __tablename__ = 'volumes'
    id = Column(Integer, primary_key=True)
    ec2_id = Column(String(12), unique=True)

    user_id = Column(String(255))
    project_id = Column(String(255))

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

    @property
    def name(self):
        return self.ec2_id


class Quota(BASE, NovaBase):
    """Represents quota overrides for a project."""
    __tablename__ = 'quotas'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255))

    instances = Column(Integer)
    cores = Column(Integer)
    volumes = Column(Integer)
    gigabytes = Column(Integer)
    floating_ips = Column(Integer)


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
        'SecurityGroup.deleted == False)',
                             secondaryjoin='and_('
        'SecurityGroupInstanceAssociation.instance_id == Instance.id,'
        'Instance.deleted == False)',
                             backref='security_groups')

    @property
    def user(self):
        return auth.manager.AuthManager().get_user(self.user_id)

    @property
    def project(self):
        return auth.manager.AuthManager().get_project(self.project_id)


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


class KeyPair(BASE, NovaBase):
    """Represents a public key pair for ssh."""
    __tablename__ = 'key_pairs'
    id = Column(Integer, primary_key=True)

    name = Column(String(255))

    user_id = Column(String(255))

    fingerprint = Column(String(255))
    public_key = Column(Text)


class Network(BASE, NovaBase):
    """Represents a network."""
    __tablename__ = 'networks'
    __table_args__ = (schema.UniqueConstraint("vpn_public_address",
                                              "vpn_public_port"),
                      {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)

    injected = Column(Boolean, default=False)
    cidr = Column(String(255), unique=True)
    netmask = Column(String(255))
    bridge = Column(String(255))
    gateway = Column(String(255))
    broadcast = Column(String(255))
    dns = Column(String(255))

    vlan = Column(Integer)
    vpn_public_address = Column(String(255))
    vpn_public_port = Column(Integer)
    vpn_private_address = Column(String(255))
    dhcp_start = Column(String(255))

    # NOTE(vish): The unique constraint below helps avoid a race condition
    #             when associating a network, but it also means that we
    #             can't associate two networks with one project.
    project_id = Column(String(255), unique=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))


class AuthToken(BASE, NovaBase):
    """Represents an authorization token for all API transactions.

    Fields are a string representing the actual token and a user id for
    mapping to the actual user

    """
    __tablename__ = 'auth_tokens'
    token_hash = Column(String(255), primary_key=True)
    user_id = Column(String(255))
    server_manageent_url = Column(String(255))
    storage_url = Column(String(255))
    cdn_management_url = Column(String(255))


# TODO(vish): can these both come from the same baseclass?
class FixedIp(BASE, NovaBase):
    """Represents a fixed ip for an instance."""
    __tablename__ = 'fixed_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
    network_id = Column(Integer, ForeignKey('networks.id'), nullable=True)
    network = relationship(Network, backref=backref('fixed_ips'))
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=True)
    instance = relationship(Instance,
                            backref=backref('fixed_ip', uselist=False),
                            foreign_keys=instance_id,
                            primaryjoin='and_('
                                'FixedIp.instance_id == Instance.id,'
                                'FixedIp.deleted == False)')
    allocated = Column(Boolean, default=False)
    leased = Column(Boolean, default=False)
    reserved = Column(Boolean, default=False)


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


def register_models():
    """Register Models and create metadata.

    Called from nova.db.sqlalchemy.__init__ as part of loading the driver,
    it will never need to be called explicitly elsewhere unless the
    connection is lost and needs to be reestablished.
    """
    from sqlalchemy import create_engine
    models = (Service, Instance, InstanceActions,
              Volume, ExportDevice, IscsiTarget, FixedIp, FloatingIp,
              Network, SecurityGroup, SecurityGroupIngressRule,
              SecurityGroupInstanceAssociation, AuthToken, User,
              Project, Certificate)  # , Image, Host
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
