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
SQLAlchemy models for nova data
"""

import sys
import datetime

# TODO(vish): clean up these imports
from sqlalchemy.orm import relationship, backref, exc, object_mapper
from sqlalchemy import Column, Integer, String, schema
from sqlalchemy import ForeignKey, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base

from nova.db.sqlalchemy.session import get_session

from nova import auth
from nova import exception
from nova import flags

FLAGS = flags.FLAGS

BASE = declarative_base()


class NovaBase(object):
    """Base class for Nova Models"""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    __prefix__ = 'none'
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.datetime.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)

    @classmethod
    def all(cls, session=None, deleted=False):
        """Get all objects of this type"""
        if not session:
            session = get_session()
        return session.query(cls
                     ).filter_by(deleted=deleted
                     ).all()

    @classmethod
    def count(cls, session=None, deleted=False):
        """Count objects of this type"""
        if not session:
            session = get_session()
        return session.query(cls
                     ).filter_by(deleted=deleted
                     ).count()

    @classmethod
    def find(cls, obj_id, session=None, deleted=False):
        """Find object by id"""
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(id=obj_id
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for id %s" % obj_id)
            raise new_exc.__class__, new_exc, sys.exc_info()[2]

    @classmethod
    def find_by_str(cls, str_id, session=None, deleted=False):
        """Find object by str_id"""
        int_id = int(str_id.rpartition('-')[2])
        return cls.find(int_id, session=session, deleted=deleted)

    @property
    def str_id(self):
        """Get string id of object (generally prefix + '-' + id)"""
        return "%s-%s" % (self.__prefix__, self.id)

    def save(self, session=None):
        """Save this object"""
        if not session:
            session = get_session()
        session.add(self)
        session.flush()

    def delete(self, session=None):
        """Delete this object"""
        self.deleted = True
        self.deleted_at = datetime.datetime.utcnow()
        self.save(session=session)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

# TODO(vish): Store images in the database instead of file system
#class Image(BASE, NovaBase):
#    """Represents an image in the datastore"""
#    __tablename__ = 'images'
#    __prefix__ = 'ami'
#    id = Column(Integer, primary_key=True)
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
#
#
class Service(BASE, NovaBase):
    """Represents a running service on a host"""
    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)

    @classmethod
    def find_by_args(cls, host, binary, session=None, deleted=False):
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(host=host
                         ).filter_by(binary=binary
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for %s, %s" % (host,
                                                              binary))
            raise new_exc.__class__, new_exc, sys.exc_info()[2]


class Instance(BASE, NovaBase):
    """Represents a guest vm"""
    __tablename__ = 'instances'
    __prefix__ = 'i'
    id = Column(Integer, primary_key=True)

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
        return self.str_id

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
    security_group = Column(String(255))

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
    # TODO(vish): see Ewan's email about state improvements, probably
    #             should be in a driver base class or some such
    # vmstate_state = running, halted, suspended, paused
    # power_state = what we have
    # task_state = transitory and may trigger power state transition

    #@validates('state')
    #def validate_state(self, key, state):
    #    assert(state in ['nostate', 'running', 'blocked', 'paused',
    #                     'shutdown', 'shutoff', 'crashed'])


class Volume(BASE, NovaBase):
    """Represents a block storage device that can be attached to a vm"""
    __tablename__ = 'volumes'
    __prefix__ = 'vol'
    id = Column(Integer, primary_key=True)

    user_id = Column(String(255))
    project_id = Column(String(255))

    host = Column(String(255))  # , ForeignKey('hosts.id'))
    size = Column(Integer)
    availability_zone = Column(String(255))  # TODO(vish): foreign key?
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=True)
    instance = relationship(Instance, backref=backref('volumes'))
    mountpoint = Column(String(255))
    attach_time = Column(String(255))  # TODO(vish): datetime
    status = Column(String(255))  # TODO(vish): enum?
    attach_status = Column(String(255))  # TODO(vish): enum

    scheduled_at = Column(DateTime)
    launched_at = Column(DateTime)
    terminated_at = Column(DateTime)

class Quota(BASE, NovaBase):
    """Represents quota overrides for a project"""
    __tablename__ = 'quotas'
    id = Column(Integer, primary_key=True)

    project_id = Column(String(255))

    instances = Column(Integer)
    cores = Column(Integer)
    volumes = Column(Integer)
    gigabytes = Column(Integer)
    floating_ips = Column(Integer)

    @property
    def str_id(self):
        return self.project_id

    @classmethod
    def find_by_str(cls, str_id, session=None, deleted=False):
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(project_id=str_id
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for project_id %s" % str_id)
            raise new_exc.__class__, new_exc, sys.exc_info()[2]

class ExportDevice(BASE, NovaBase):
    """Represates a shelf and blade that a volume can be exported on"""
    __tablename__ = 'export_devices'
    __table_args__ = (schema.UniqueConstraint("shelf_id", "blade_id"), {'mysql_engine': 'InnoDB'})
    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer)
    blade_id = Column(Integer)
    volume_id = Column(Integer, ForeignKey('volumes.id'), nullable=True)
    volume = relationship(Volume, backref=backref('export_device',
                                                  uselist=False))


class KeyPair(BASE, NovaBase):
    """Represents a public key pair for ssh"""
    __tablename__ = 'key_pairs'
    id = Column(Integer, primary_key=True)
    name = Column(String(255))

    user_id = Column(String(255))

    fingerprint = Column(String(255))
    public_key = Column(Text)

    @property
    def str_id(self):
        return '%s.%s' % (self.user_id, self.name)

    @classmethod
    def find_by_str(cls, str_id, session=None, deleted=False):
        user_id, _sep, name = str_id.partition('.')
        return cls.find_by_str(user_id, name, session, deleted)

    @classmethod
    def find_by_args(cls, user_id, name, session=None, deleted=False):
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(user_id=user_id
                         ).filter_by(name=name
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for user %s, name %s" %
                                         (user_id, name))
            raise new_exc.__class__, new_exc, sys.exc_info()[2]


class Network(BASE, NovaBase):
    """Represents a network"""
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True)

    injected = Column(Boolean, default=False)
    cidr = Column(String(255))
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

    project_id = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))


class NetworkIndex(BASE, NovaBase):
    """Represents a unique offset for a network

    Currently vlan number, vpn port, and fixed ip ranges are keyed off of
    this index. These may ultimately need to be converted to separate
    pools.
    """
    __tablename__ = 'network_indexes'
    id = Column(Integer, primary_key=True)
    index = Column(Integer)
    network_id = Column(Integer, ForeignKey('networks.id'), nullable=True)
    network = relationship(Network, backref=backref('network_index',
                                                    uselist=False))


# TODO(vish): can these both come from the same baseclass?
class FixedIp(BASE, NovaBase):
    """Represents a fixed ip for an instance"""
    __tablename__ = 'fixed_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
    network_id = Column(Integer, ForeignKey('networks.id'), nullable=True)
    network = relationship(Network, backref=backref('fixed_ips'))
    instance_id = Column(Integer, ForeignKey('instances.id'), nullable=True)
    instance = relationship(Instance, backref=backref('fixed_ip',
                                                      uselist=False))
    allocated = Column(Boolean, default=False)
    leased = Column(Boolean, default=False)
    reserved = Column(Boolean, default=False)

    @property
    def str_id(self):
        return self.address

    @classmethod
    def find_by_str(cls, str_id, session=None, deleted=False):
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(address=str_id
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for address %s" % str_id)
            raise new_exc.__class__, new_exc, sys.exc_info()[2]


class FloatingIp(BASE, NovaBase):
    """Represents a floating ip that dynamically forwards to a fixed ip"""
    __tablename__ = 'floating_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255))
    fixed_ip_id = Column(Integer, ForeignKey('fixed_ips.id'), nullable=True)
    fixed_ip = relationship(FixedIp, backref=backref('floating_ips'))

    project_id = Column(String(255))
    host = Column(String(255))  # , ForeignKey('hosts.id'))

    @property
    def str_id(self):
        return self.address

    @classmethod
    def find_by_str(cls, str_id, session=None, deleted=False):
        if not session:
            session = get_session()
        try:
            return session.query(cls
                         ).filter_by(address=str_id
                         ).filter_by(deleted=deleted
                         ).one()
        except exc.NoResultFound:
            new_exc = exception.NotFound("No model for address %s" % str_id)
            raise new_exc.__class__, new_exc, sys.exc_info()[2]


def register_models():
    """Register Models and create metadata"""
    from sqlalchemy import create_engine
    models = (Service, Instance, Volume, ExportDevice,
              FixedIp, FloatingIp, Network, NetworkIndex)  # , Image, Host)
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
