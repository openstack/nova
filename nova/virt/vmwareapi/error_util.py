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

from nova import exception
from nova.i18n import _


class DatastoreRegexUnspecified(exception.Invalid):
    msg_fmt = "vmware.datastore_hagroup_regex is set without " \
              "vmware.datastore_regex being set."


class DatastoreRegexNoHagroup(exception.Invalid):
    msg_fmt = "vmware.datastore_hagroup_regex is set but does not contain " \
              "a named group 'hagroup'"


class NoRootDiskDefined(exception.NovaException):
    msg_fmt = _("No root disk defined.")


class PbmDefaultPolicyUnspecified(exception.Invalid):
    msg_fmt = _("Default PBM policy is required if PBM is enabled.")


class PbmDefaultPolicyDoesNotExist(exception.NovaException):
    msg_fmt = _("The default PBM policy doesn't exist on the backend.")


class InvalidHostAddrFormat(exception.NovaException):
    msg_fmt = _("The provided host address couldn't be recognised as a valid "
                "format supported by the VMwareVCDriver.")


class InClustervMotionCheckError(exception.Invalid):
    msg_fmt = _("in cluster migration failed: %(reason)s")


class EvcModeDoesNotExist(exception.Invalid):
    msg_fmt = _("The requested EVCMode %(evc_mode)s does not exist")
