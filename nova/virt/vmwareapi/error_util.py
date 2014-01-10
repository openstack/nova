# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
Exception classes specific for the VMware driver.
"""
from oslo.vmware import exceptions as vexc

from nova.i18n import _

# Most VMware-specific exception classes are now centrally defined in
# oslo.vmware.
# Note(vui):
# - map back to NovaException?


class VMwareDriverConfigurationException(vexc.VMwareDriverException):
    """Base class for all configuration exceptions.
    """
    msg_fmt = _("VMware Driver configuration fault.")


class UseLinkedCloneConfigurationFault(VMwareDriverConfigurationException):
    msg_fmt = _("No default value for use_linked_clone found.")


class NoRootDiskDefined(vexc.VMwareDriverException):
    msg_fmt = _("No root disk defined.")


class TaskInProgress(vexc.VMwareDriverException):
    msg_fmt = _("Virtual machine is busy.")
