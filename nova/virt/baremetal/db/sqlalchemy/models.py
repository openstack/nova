# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NTT DOCOMO, INC.
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
SQLAlchemy models for baremetal data.
"""

from sqlalchemy import Column, Integer, String
from sqlalchemy import ForeignKey, DateTime, Text, Index
from sqlalchemy.ext.declarative import declarative_base

from nova.db.sqlalchemy import models


BASE = declarative_base()


class BareMetalNode(BASE, models.NovaBase):
    """Represents a bare metal node."""

    __tablename__ = 'bm_nodes'
    id = Column(Integer, primary_key=True)
    service_host = Column(String(255))
    instance_uuid = Column(String(36), nullable=True)
    cpus = Column(Integer)
    memory_mb = Column(Integer)
    local_gb = Column(Integer)
    pm_address = Column(Text)
    pm_user = Column(Text)
    pm_password = Column(Text)
    prov_mac_address = Column(Text)
    registration_status = Column(String(16))
    task_state = Column(String(255))
    prov_vlan_id = Column(Integer)
    terminal_port = Column(Integer)


class BareMetalPxeIp(BASE, models.NovaBase):
    __tablename__ = 'bm_pxe_ips'
    id = Column(Integer, primary_key=True)
    address = Column(String(255), unique=True)
    server_address = Column(String(255), unique=True)
    bm_node_id = Column(Integer, ForeignKey('bm_nodes.id'), nullable=True)


class BareMetalInterface(BASE, models.NovaBase):
    __tablename__ = 'bm_interfaces'
    id = Column(Integer, primary_key=True)
    bm_node_id = Column(Integer, ForeignKey('bm_nodes.id'), nullable=True)
    address = Column(String(255), unique=True)
    datapath_id = Column(String(255))
    port_no = Column(Integer)
    vif_uuid = Column(String(36), unique=True)


class BareMetalDeployment(BASE, models.NovaBase):
    __tablename__ = 'bm_deployments'
    id = Column(Integer, primary_key=True)
    key = Column(String(255))
    image_path = Column(String(255))
    pxe_config_path = Column(String(255))
    root_mb = Column(Integer)
    swap_mb = Column(Integer)
