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
"""Exceptions for use in the Placement API."""

# NOTE(cdent): The exceptions are copied from nova.exception, where they
# were originally used. To prepare for extracting placement to its own
# repository we wish to no longer do that. Instead, exceptions used by
# placement should be in the placement hierarchy.

from oslo_log import log as logging

from nova.i18n import _


LOG = logging.getLogger(__name__)


class _BaseException(Exception):
    """Base Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.

    """
    msg_fmt = _("An unknown exception occurred.")

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if not message:
            try:
                message = self.msg_fmt % kwargs
            except Exception:
                # NOTE(melwitt): This is done in a separate method so it can be
                # monkey-patched during testing to make it a hard failure.
                self._log_exception()
                message = self.msg_fmt

        self.message = message
        super(_BaseException, self).__init__(message)

    def _log_exception(self):
        # kwargs doesn't match a variable in the message
        # log the issue and the kwargs
        LOG.exception('Exception in string format operation')
        for name, value in self.kwargs.items():
            LOG.error("%s: %s" % (name, value))  # noqa

    def format_message(self):
        # Use the first argument to the python Exception object which
        # should be our full exception message, (see __init__).
        return self.args[0]


class NotFound(_BaseException):
    msg_fmt = _("Resource could not be found.")


class Exists(_BaseException):
        msg_fmt = _("Resource already exists.")


class InvalidInventory(_BaseException):
    msg_fmt = _("Inventory for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s' invalid.")


class CannotDeleteParentResourceProvider(_BaseException):
    msg_fmt = _("Cannot delete resource provider that is a parent of "
                "another. Delete child providers first.")


class ConcurrentUpdateDetected(_BaseException):
    msg_fmt = _("Another thread concurrently updated the data. "
                "Please retry your update")


class ResourceProviderConcurrentUpdateDetected(ConcurrentUpdateDetected):
    msg_fmt = _("Another thread concurrently updated the resource provider "
                "data. Please retry your update")


class InvalidAllocationCapacityExceeded(InvalidInventory):
    msg_fmt = _("Unable to create allocation for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s'. The requested "
                "amount would exceed the capacity.")


class InvalidAllocationConstraintsViolated(InvalidInventory):
    msg_fmt = _("Unable to create allocation for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s'. The requested "
                "amount would violate inventory constraints.")


class InvalidInventoryCapacity(InvalidInventory):
    msg_fmt = _("Invalid inventory for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s'. "
                "The reserved value is greater than or equal to total.")


class InvalidInventoryCapacityReservedCanBeTotal(InvalidInventoryCapacity):
    msg_fmt = _("Invalid inventory for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s'. "
                "The reserved value is greater than total.")


# An exception with this name is used on both sides of the placement/
# nova interaction.
class InventoryInUse(InvalidInventory):
    # NOTE(mriedem): This message cannot change without impacting the
    # nova.scheduler.client.report._RE_INV_IN_USE regex.
    msg_fmt = _("Inventory for '%(resource_classes)s' on "
                "resource provider '%(resource_provider)s' in use.")


class InventoryWithResourceClassNotFound(NotFound):
    msg_fmt = _("No inventory of class %(resource_class)s found.")


class MaxDBRetriesExceeded(_BaseException):
    msg_fmt = _("Max retries of DB transaction exceeded attempting to "
                "perform %(action)s.")


class ObjectActionError(_BaseException):
    msg_fmt = _('Object action %(action)s failed because: %(reason)s')


class PolicyNotAuthorized(_BaseException):
    msg_fmt = _("Policy does not allow %(action)s to be performed.")


class ResourceClassCannotDeleteStandard(_BaseException):
    msg_fmt = _("Cannot delete standard resource class %(resource_class)s.")


class ResourceClassCannotUpdateStandard(_BaseException):
    msg_fmt = _("Cannot update standard resource class %(resource_class)s.")


class ResourceClassExists(_BaseException):
    msg_fmt = _("Resource class %(resource_class)s already exists.")


class ResourceClassInUse(_BaseException):
    msg_fmt = _("Cannot delete resource class %(resource_class)s. "
                "Class is in use in inventory.")


class ResourceClassNotFound(NotFound):
    msg_fmt = _("No such resource class %(resource_class)s.")


# An exception with this name is used on both sides of the placement/
# nova interaction.
class ResourceProviderInUse(_BaseException):
    msg_fmt = _("Resource provider has allocations.")


class TraitCannotDeleteStandard(_BaseException):
    msg_fmt = _("Cannot delete standard trait %(name)s.")


class TraitExists(_BaseException):
    msg_fmt = _("The Trait %(name)s already exists")


class TraitInUse(_BaseException):
    msg_fmt = _("The trait %(name)s is in use by a resource provider.")


class TraitNotFound(NotFound):
    msg_fmt = _("No such trait(s): %(names)s.")


class ProjectNotFound(NotFound):
    msg_fmt = _("No such project(s): %(external_id)s.")


class ProjectExists(Exists):
        msg_fmt = _("The project %(external_id)s already exists.")


class UserNotFound(NotFound):
    msg_fmt = _("No such user(s): %(external_id)s.")


class UserExists(Exists):
        msg_fmt = _("The user %(external_id)s already exists.")


class ConsumerNotFound(NotFound):
    msg_fmt = _("No such consumer(s): %(uuid)s.")


class ConsumerExists(Exists):
    msg_fmt = _("The consumer %(uuid)s already exists.")
