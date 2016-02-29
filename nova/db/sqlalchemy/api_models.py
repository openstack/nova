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
from sqlalchemy import Boolean
from sqlalchemy import Column
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

from nova.db.sqlalchemy import types


class _NovaAPIBase(models.ModelBase, models.TimestampMixin):
    pass


API_BASE = declarative_base(cls=_NovaAPIBase)


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
                          name='uniq_instance_mappings0instance_uuid'))

    id = Column(Integer, primary_key=True)
    instance_uuid = Column(String(36), nullable=False)
    cell_id = Column(Integer, ForeignKey('cell_mappings.id'),
            nullable=True)
    project_id = Column(String(255), nullable=False)
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
    spec = Column(Text, nullable=False)
    build_request = orm.relationship('BuildRequest',
                    back_populates='request_spec',
                    uselist=False,
                    primaryjoin=(
                        'RequestSpec.id == BuildRequest.request_spec_id'))


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
        Index('build_requests_project_id_idx', 'project_id'),
        schema.UniqueConstraint('request_spec_id',
            name='uniq_build_requests0request_spec_id')
        )

    id = Column(Integer, primary_key=True)
    request_spec_id = Column(Integer, ForeignKey('request_specs.id'),
            nullable=False)
    request_spec = orm.relationship(RequestSpec,
            foreign_keys=request_spec_id,
            back_populates='build_request',
            primaryjoin=request_spec_id == RequestSpec.id)
    project_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    display_name = Column(String(255))
    instance_metadata = Column(Text)
    progress = Column(Integer)
    vm_state = Column(String(255))
    task_state = Column(String(255))
    image_ref = Column(String(255))
    access_ip_v4 = Column(types.IPAddress())
    access_ip_v6 = Column(types.IPAddress())
    info_cache = Column(Text)
    security_groups = Column(Text, nullable=False)
    config_drive = Column(Boolean, default=False, nullable=False)
    key_name = Column(String(255))
    locked_by = Column(Enum('owner', 'admin'))
