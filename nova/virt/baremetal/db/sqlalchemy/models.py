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

from sqlalchemy import Column, Boolean, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, Text

from nova.db.sqlalchemy import models


BASE = declarative_base()


class BareMetalNode(BASE, models.NovaBase):
    """Represents a bare metal node."""

    __tablename__ = 'bm_nodes'
    id = Column(Integer, primary_key=True)
    deleted = Column(Boolean, default=False)
    uuid = Column(String(36))
    service_host = Column(String(255))
    instance_uuid = Column(String(36))
    instance_name = Column(String(255))
    cpus = Column(Integer)
    memory_mb = Column(Integer)
    local_gb = Column(Integer)
    pm_address = Column(Text)
    pm_user = Column(Text)
    pm_password = Column(Text)
    task_state = Column(String(255))
    terminal_port = Column(Integer)
    image_path = Column(String(255))
    pxe_config_path = Column(String(255))
    deploy_key = Column(String(255))
    # root_mb, swap_mb and ephemeral_mb are cached flavor values for the
    # current deployment not attributes of the node.
    root_mb = Column(Integer)
    swap_mb = Column(Integer)
    ephemeral_mb = Column(Integer)


class BareMetalInterface(BASE, models.NovaBase):
    __tablename__ = 'bm_interfaces'
    id = Column(Integer, primary_key=True)
    deleted = Column(Boolean, default=False)
    bm_node_id = Column(Integer, ForeignKey('bm_nodes.id'))
    address = Column(String(255), unique=True)
    datapath_id = Column(String(255))
    port_no = Column(Integer)
    vif_uuid = Column(String(36), unique=True)
