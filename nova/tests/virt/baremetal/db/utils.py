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

"""Bare-metal test utils."""

from nova import test
from nova.virt.baremetal.db.sqlalchemy import models as bm_models


def new_bm_node(**kwargs):
    h = bm_models.BareMetalNode()
    h.id = kwargs.pop('id', None)
    h.uuid = kwargs.pop('uuid', None)
    h.service_host = kwargs.pop('service_host', None)
    h.instance_uuid = kwargs.pop('instance_uuid', None)
    h.cpus = kwargs.pop('cpus', 1)
    h.memory_mb = kwargs.pop('memory_mb', 1024)
    h.local_gb = kwargs.pop('local_gb', 64)
    h.pm_address = kwargs.pop('pm_address', '192.168.1.1')
    h.pm_user = kwargs.pop('pm_user', 'ipmi_user')
    h.pm_password = kwargs.pop('pm_password', 'ipmi_password')
    h.task_state = kwargs.pop('task_state', None)
    h.terminal_port = kwargs.pop('terminal_port', 8000)
    if len(kwargs) > 0:
        raise test.TestingException("unknown field: %s"
                                    % ','.join(kwargs.keys()))
    return h


def new_bm_interface(**kwargs):
    x = bm_models.BareMetalInterface()
    x.id = kwargs.pop('id', None)
    x.bm_node_id = kwargs.pop('bm_node_id', None)
    x.address = kwargs.pop('address', None)
    x.datapath_id = kwargs.pop('datapath_id', None)
    x.port_no = kwargs.pop('port_no', None)
    x.vif_uuid = kwargs.pop('vif_uuid', None)
    if len(kwargs) > 0:
        raise test.TestingException("unknown field: %s"
                                    % ','.join(kwargs.keys()))
    return x
