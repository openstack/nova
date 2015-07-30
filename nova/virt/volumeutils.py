# Copyright 2014 Hewlett-Packard Development Company, L.P.
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
Volume utilities for virt drivers.
"""
from os_brick.initiator import connector
from oslo_concurrency import processutils as putils

from nova import utils


def get_iscsi_initiator(execute=None):
    """Get iscsi initiator name for this machine."""

    root_helper = utils.get_root_helper()
    # so we can mock out the execute itself
    # in unit tests.
    if not execute:
        execute = putils.execute
    iscsi = connector.ISCSIConnector(root_helper=root_helper,
                                     execute=execute)
    return iscsi.get_initiator()
