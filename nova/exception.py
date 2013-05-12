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

"""Nova base exception handling.

Includes decorator for re-raising Nova-type exceptions.

SHOULD include dedicated exception logging.

"""

import functools

from oslo.config import cfg
import webob.exc

from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova import safe_utils

LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='make exception message format errors fatal'),
]

CONF = cfg.CONF
CONF.register_opts(exc_log_opts)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=0, title="", explanation=""):
        self.code = code
        self.title = title
        self.explanation = explanation
        super(ConvertedException, self).__init__()


def _cleanse_dict(original):
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return dict((k, v) for k, v in original.iteritems() if not "_pass" in k)


def wrap_exception(notifier=None, publisher_id=None, event_type=None,
                   level=None):
    """This decorator wraps a method to catch any exceptions that may
    get thrown. It logs the exception as well as optionally sending
    it to the notification system.
    """
    # TODO(sandy): Find a way to import nova.notifier.api so we don't have
    # to pass it in as a parameter. Otherwise we get a cyclic import of
    # nova.notifier.api -> nova.utils -> nova.exception :(
    def inner(f):
        def wrapped(self, context, *args, **kw):
            # Don't store self or context in the payload, it now seems to
            # contain confidential information.
            try:
                return f(self, context, *args, **kw)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    if notifier:
                        payload = dict(exception=e)
                        call_dict = safe_utils.getcallargs(f, *args, **kw)
                        cleansed = _cleanse_dict(call_dict)
                        payload.update({'args': cleansed})

                        # Use a temp vars so we don't shadow
                        # our outer definitions.
                        temp_level = level
                        if not temp_level:
                            temp_level = notifier.ERROR

                        temp_type = event_type
                        if not temp_type:
                            # If f has multiple decorators, they must use
                            # functools.wraps to ensure the name is
                            # propagated.
                            temp_type = f.__name__

                        notifier.notify(context, publisher_id, temp_type,
                                        temp_level, payload)

        return functools.wraps(f)(wrapped)
    return inner


class NovaException(Exception):
    """Base Nova Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        if not message:
            try:
                message = self.message % kwargs

            except Exception as e:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))

                if CONF.fatal_exception_format_errors:
                    raise e
                else:
                    # at least get the core message out if something happened
                    message = self.message

        super(NovaException, self).__init__(message)

    def format_message(self):
        if self.__class__.__name__.endswith('_Remote'):
            return self.args[0]
        else:
            return unicode(self)


class EC2APIError(NovaException):
    message = _("Unknown")

    def __init__(self, message=None, code=None):
        self.msg = message
        self.code = code
        outstr = '%s' % message
        super(EC2APIError, self).__init__(outstr)


class EncryptionFailure(NovaException):
    message = _("Failed to encrypt text: %(reason)s")


class DecryptionFailure(NovaException):
    message = _("Failed to decrypt text: %(reason)s")


class VirtualInterfaceCreateException(NovaException):
    message = _("Virtual Interface creation failed")


class VirtualInterfaceMacAddressException(NovaException):
    message = _("5 attempts to create virtual interface"
                "with unique mac address failed")


class GlanceConnectionFailed(NovaException):
    message = _("Connection to glance host %(host)s:%(port)s failed: "
        "%(reason)s")


class NotAuthorized(NovaException):
    message = _("Not authorized.")
    code = 403


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy doesn't allow %(action)s to be performed.")


class ImageNotActive(NovaException):
    message = _("Image %(image_id)s is not active.")


class ImageNotAuthorized(NovaException):
    message = _("Not authorized for image %(image_id)s.")


class Invalid(NovaException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidBDM(Invalid):
    message = _("Block Device Mapping is Invalid.")


class InvalidBDMSnapshot(InvalidBDM):
    message = _("Block Device Mapping is Invalid: "
                "failed to get snapshot %(id)s.")


class InvalidBDMVolume(InvalidBDM):
    message = _("Block Device Mapping is Invalid: "
                "failed to get volume %(id)s.")


class InvalidBDMFormat(InvalidBDM):
    message = _("Block Device Mapping is Invalid: "
                "some fields are not recognized, "
                "or have invalid values.")


class InvalidBDMForLegacy(InvalidBDM):
    message = _("Block Device Mapping cannot "
                "be converted to legacy format. ")


class VolumeUnattached(Invalid):
    message = _("Volume %(volume_id)s is not attached to anything")


class VolumeNotCreated(NovaException):
    message = _("Volume %(volume_id)s did not finish being created"
                " even after we waited %(seconds)s seconds or %(attempts)s"
                " attempts.")


class InvalidKeypair(Invalid):
    message = _("Keypair data is invalid")


class InvalidRequest(Invalid):
    message = _("The request is invalid.")


class InvalidInput(Invalid):
    message = _("Invalid input received") + ": %(reason)s"


class InvalidVolume(Invalid):
    message = _("Invalid volume") + ": %(reason)s"


class InvalidMetadata(Invalid):
    message = _("Invalid metadata") + ": %(reason)s"


class InvalidMetadataSize(Invalid):
    message = _("Invalid metadata size") + ": %(reason)s"


class InvalidPortRange(Invalid):
    message = _("Invalid port range %(from_port)s:%(to_port)s. %(msg)s")


class InvalidIpProtocol(Invalid):
    message = _("Invalid IP protocol %(protocol)s.")


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


class InvalidCidr(Invalid):
    message = _("Invalid cidr %(cidr)s.")


class InvalidUnicodeParameter(Invalid):
    message = _("Invalid Parameter: "
                "Unicode is not supported by the current database.")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class InvalidAggregateAction(Invalid):
    message = _("Cannot perform action '%(action)s' on aggregate "
                "%(aggregate_id)s. Reason: %(reason)s.")


class InvalidGroup(Invalid):
    message = _("Group not valid. Reason: %(reason)s")


class InvalidSortKey(Invalid):
    message = _("Sort key supplied was not valid.")


class InstanceInvalidState(Invalid):
    message = _("Instance %(instance_uuid)s in %(attr)s %(state)s. Cannot "
                "%(method)s while the instance is in this state.")


class InstanceNotRunning(Invalid):
    message = _("Instance %(instance_id)s is not running.")


class InstanceNotInRescueMode(Invalid):
    message = _("Instance %(instance_id)s is not in rescue mode")


class InstanceNotRescuable(Invalid):
    message = _("Instance %(instance_id)s cannot be rescued: %(reason)s")


class InstanceNotReady(Invalid):
    message = _("Instance %(instance_id)s is not ready")


class InstanceSuspendFailure(Invalid):
    message = _("Failed to suspend instance") + ": %(reason)s"


class InstanceResumeFailure(Invalid):
    message = _("Failed to resume instance: %(reason)s.")


class InstancePowerOnFailure(Invalid):
    message = _("Failed to power on instance: %(reason)s.")


class InstancePowerOffFailure(Invalid):
    message = _("Failed to power off instance: %(reason)s.")


class InstanceRebootFailure(Invalid):
    message = _("Failed to reboot instance") + ": %(reason)s"


class InstanceTerminationFailure(Invalid):
    message = _("Failed to terminate instance") + ": %(reason)s"


class InstanceDeployFailure(Invalid):
    message = _("Failed to deploy instance") + ": %(reason)s"


class ServiceUnavailable(Invalid):
    message = _("Service is unavailable at this time.")


class ComputeResourcesUnavailable(ServiceUnavailable):
    message = _("Insufficient compute resources.")


class ComputeServiceUnavailable(ServiceUnavailable):
    message = _("Compute service of %(host)s is unavailable at this time.")


class UnableToMigrateToSelf(Invalid):
    message = _("Unable to migrate instance (%(instance_id)s) "
                "to current host (%(host)s).")


class InvalidHypervisorType(Invalid):
    message = _("The supplied hypervisor type of is invalid.")


class DestinationHypervisorTooOld(Invalid):
    message = _("The instance requires a newer hypervisor version than "
                "has been provided.")


class DestinationDiskExists(Invalid):
    message = _("The supplied disk path (%(path)s) already exists, "
                "it is expected not to exist.")


class InvalidDevicePath(Invalid):
    message = _("The supplied device path (%(path)s) is invalid.")


class DevicePathInUse(Invalid):
    message = _("The supplied device path (%(path)s) is in use.")
    code = 409


class DeviceIsBusy(Invalid):
    message = _("The supplied device (%(device)s) is busy.")


class InvalidCPUInfo(Invalid):
    message = _("Unacceptable CPU info") + ": %(reason)s"


class InvalidIpAddressError(Invalid):
    message = _("%(address)s is not a valid IP v4/6 address.")


class InvalidVLANTag(Invalid):
    message = _("VLAN tag is not appropriate for the port group "
                "%(bridge)s. Expected VLAN tag is %(tag)s, "
                "but the one associated with the port group is %(pgroup)s.")


class InvalidVLANPortGroup(Invalid):
    message = _("vSwitch which contains the port group %(bridge)s is "
                "not associated with the desired physical adapter. "
                "Expected vSwitch is %(expected)s, but the one associated "
                "is %(actual)s.")


class InvalidDiskFormat(Invalid):
    message = _("Disk format %(disk_format)s is not acceptable")


class ImageUnacceptable(Invalid):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


class InstanceUnacceptable(Invalid):
    message = _("Instance %(instance_id)s is unacceptable: %(reason)s")


class InvalidEc2Id(Invalid):
    message = _("Ec2 id %(ec2_id)s is unacceptable.")


class InvalidUUID(Invalid):
    message = _("Expected a uuid but received %(uuid)s.")


class InvalidID(Invalid):
    message = _("Invalid ID received %(id)s.")


class ConstraintNotMet(NovaException):
    message = _("Constraint not met.")
    code = 412


class NotFound(NovaException):
    message = _("Resource could not be found.")
    code = 404


class AgentBuildNotFound(NotFound):
    message = _("No agent-build associated with id %(id)s.")


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")


class ISCSITargetNotFoundForVolume(NotFound):
    message = _("No target id found for volume %(volume_id)s.")


class DiskNotFound(NotFound):
    message = _("No disk at %(location)s")


class VolumeDriverNotFound(NotFound):
    message = _("Could not find a handler for %(driver_type)s volume.")


class InvalidImageRef(Invalid):
    message = _("Invalid image href %(image_href)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class ImageNotFoundEC2(ImageNotFound):
    message = _("Image %(image_id)s could not be found. The nova EC2 API "
                "assigns image ids dynamically when they are listed for the "
                "first time. Have you listed image ids since adding this "
                "image?")


class ProjectNotFound(NotFound):
    message = _("Project %(project_id)s could not be found.")


class StorageRepositoryNotFound(NotFound):
    message = _("Cannot find SR to read/write VDI.")


class NetworkDuplicated(NovaException):
    message = _("Network %(network_id)s is duplicated.")


class NetworkInUse(NovaException):
    message = _("Network %(network_id)s is still in use.")


class NetworkNotCreated(NovaException):
    message = _("%(req)s is required to create a network.")


class NetworkNotFound(NotFound):
    message = _("Network %(network_id)s could not be found.")


class PortNotFound(NotFound):
    message = _("Port id %(port_id)s could not be found.")


class NetworkNotFoundForBridge(NetworkNotFound):
    message = _("Network could not be found for bridge %(bridge)s")


class NetworkNotFoundForUUID(NetworkNotFound):
    message = _("Network could not be found for uuid %(uuid)s")


class NetworkNotFoundForCidr(NetworkNotFound):
    message = _("Network could not be found with cidr %(cidr)s.")


class NetworkNotFoundForInstance(NetworkNotFound):
    message = _("Network could not be found for instance %(instance_id)s.")


class NoNetworksFound(NotFound):
    message = _("No networks defined.")


class NetworkNotFoundForProject(NotFound):
    message = _("Either Network uuid %(network_uuid)s is not present or "
                "is not assigned to the project %(project_id)s.")


class DatastoreNotFound(NotFound):
    message = _("Could not find the datastore reference(s) which the VM uses.")


class PortInUse(NovaException):
    message = _("Port %(port_id)s is still in use.")


class PortNotUsable(NovaException):
    message = _("Port %(port_id)s not usable for instance %(instance)s.")


class PortNotFree(NovaException):
    message = _("No free port available for instance %(instance)s.")


class FixedIpNotFound(NotFound):
    message = _("No fixed IP associated with id %(id)s.")


class FixedIpNotFoundForAddress(FixedIpNotFound):
    message = _("Fixed ip not found for address %(address)s.")


class FixedIpNotFoundForInstance(FixedIpNotFound):
    message = _("Instance %(instance_uuid)s has zero fixed ips.")


class FixedIpNotFoundForNetworkHost(FixedIpNotFound):
    message = _("Network host %(host)s has zero fixed ips "
                "in network %(network_id)s.")


class FixedIpNotFoundForSpecificInstance(FixedIpNotFound):
    message = _("Instance %(instance_uuid)s doesn't have fixed ip '%(ip)s'.")


class FixedIpNotFoundForNetwork(FixedIpNotFound):
    message = _("Fixed IP address (%(address)s) does not exist in "
                "network (%(network_uuid)s).")


class FixedIpAlreadyInUse(NovaException):
    message = _("Fixed IP address %(address)s is already in use on instance "
                "%(instance_uuid)s.")


class FixedIpAssociatedWithMultipleInstances(NovaException):
    message = _("More than one instance is associated with fixed ip address "
                "'%(address)s'.")


class FixedIpInvalid(Invalid):
    message = _("Fixed IP address %(address)s is invalid.")


class NoMoreFixedIps(NovaException):
    message = _("Zero fixed ips available.")


class NoFixedIpsDefined(NotFound):
    message = _("Zero fixed ips could be found.")


#TODO(bcwaldon): EOL this exception!
class Duplicate(NovaException):
    pass


class FloatingIpExists(Duplicate):
    message = _("Floating ip %(address)s already exists.")


class FloatingIpNotFound(NotFound):
    message = _("Floating ip not found for id %(id)s.")


class FloatingIpDNSExists(Invalid):
    message = _("The DNS entry %(name)s already exists in domain %(domain)s.")


class FloatingIpNotFoundForAddress(FloatingIpNotFound):
    message = _("Floating ip not found for address %(address)s.")


class FloatingIpNotFoundForHost(FloatingIpNotFound):
    message = _("Floating ip not found for host %(host)s.")


class FloatingIpMultipleFoundForAddress(NovaException):
    message = _("Multiple floating ips are found for address %(address)s.")


class FloatingIpPoolNotFound(NotFound):
    message = _("Floating ip pool not found.")
    safe = True


class NoMoreFloatingIps(FloatingIpNotFound):
    message = _("Zero floating ips available.")
    safe = True


class FloatingIpAssociated(NovaException):
    message = _("Floating ip %(address)s is associated.")


class FloatingIpNotAssociated(NovaException):
    message = _("Floating ip %(address)s is not associated.")


class NoFloatingIpsDefined(NotFound):
    message = _("Zero floating ips exist.")


class NoFloatingIpInterface(NotFound):
    message = _("Interface %(interface)s not found.")


class CannotDisassociateAutoAssignedFloatingIP(NovaException):
    message = _("Cannot disassociate auto assigined floating ip")


class KeypairNotFound(NotFound):
    message = _("Keypair %(name)s not found for user %(user_id)s")


class CertificateNotFound(NotFound):
    message = _("Certificate %(certificate_id)s not found.")


class ServiceNotFound(NotFound):
    message = _("Service %(service_id)s could not be found.")


class HostNotFound(NotFound):
    message = _("Host %(host)s could not be found.")


class ComputeHostNotFound(HostNotFound):
    message = _("Compute host %(host)s could not be found.")


class HostBinaryNotFound(NotFound):
    message = _("Could not find binary %(binary)s on host %(host)s.")


class InvalidReservationExpiration(Invalid):
    message = _("Invalid reservation expiration %(expire)s.")


class InvalidQuotaValue(Invalid):
    message = _("Change would make usage less than 0 for the following "
                "resources: %(unders)s")


class QuotaNotFound(NotFound):
    message = _("Quota could not be found")


class QuotaResourceUnknown(QuotaNotFound):
    message = _("Unknown quota resources %(unknown)s.")


class ProjectQuotaNotFound(QuotaNotFound):
    message = _("Quota for project %(project_id)s could not be found.")


class QuotaClassNotFound(QuotaNotFound):
    message = _("Quota class %(class_name)s could not be found.")


class QuotaUsageNotFound(QuotaNotFound):
    message = _("Quota usage for project %(project_id)s could not be found.")


class ReservationNotFound(QuotaNotFound):
    message = _("Quota reservation %(uuid)s could not be found.")


class OverQuota(NovaException):
    message = _("Quota exceeded for resources: %(overs)s")


class SecurityGroupNotFound(NotFound):
    message = _("Security group %(security_group_id)s not found.")


class SecurityGroupNotFoundForProject(SecurityGroupNotFound):
    message = _("Security group %(security_group_id)s not found "
                "for project %(project_id)s.")


class SecurityGroupNotFoundForRule(SecurityGroupNotFound):
    message = _("Security group with rule %(rule_id)s not found.")


class SecurityGroupExistsForInstance(Invalid):
    message = _("Security group %(security_group_id)s is already associated"
                " with the instance %(instance_id)s")


class SecurityGroupNotExistsForInstance(Invalid):
    message = _("Security group %(security_group_id)s is not associated with"
                " the instance %(instance_id)s")


class SecurityGroupDefaultRuleNotFound(Invalid):
    message = _("Security group default rule (%rule_id)s not found.")


class SecurityGroupCannotBeApplied(Invalid):
    message = _("Network requires port_security_enabled and subnet associated"
                " in order to apply security groups.")


class NoUniqueMatch(NovaException):
    message = _("No Unique Match Found.")
    code = 409


class MigrationNotFound(NotFound):
    message = _("Migration %(migration_id)s could not be found.")


class MigrationNotFoundByStatus(MigrationNotFound):
    message = _("Migration not found for instance %(instance_id)s "
                "with status %(status)s.")


class ConsolePoolNotFound(NotFound):
    message = _("Console pool %(pool_id)s could not be found.")


class ConsolePoolNotFoundForHostType(NotFound):
    message = _("Console pool of type %(console_type)s "
                "for compute host %(compute_host)s "
                "on proxy host %(host)s not found.")


class ConsoleNotFound(NotFound):
    message = _("Console %(console_id)s could not be found.")


class ConsoleNotFoundForInstance(ConsoleNotFound):
    message = _("Console for instance %(instance_uuid)s could not be found.")


class ConsoleNotFoundInPoolForInstance(ConsoleNotFound):
    message = _("Console for instance %(instance_uuid)s "
                "in pool %(pool_id)s could not be found.")


class ConsoleTypeInvalid(Invalid):
    message = _("Invalid console type %(console_type)s")


class InstanceTypeNotFound(NotFound):
    message = _("Instance type %(instance_type_id)s could not be found.")


class InstanceTypeNotFoundByName(InstanceTypeNotFound):
    message = _("Instance type with name %(instance_type_name)s "
                "could not be found.")


class FlavorNotFound(NotFound):
    message = _("Flavor %(flavor_id)s could not be found.")


class FlavorAccessNotFound(NotFound):
    message = _("Flavor access not found for %(flavor_id)s / "
                "%(project_id)s combination.")


class CellNotFound(NotFound):
    message = _("Cell %(cell_name)s doesn't exist.")


class CellRoutingInconsistency(NovaException):
    message = _("Inconsistency in cell routing: %(reason)s")


class CellServiceAPIMethodNotFound(NotFound):
    message = _("Service API method not found: %(detail)s")


class CellTimeout(NotFound):
    message = _("Timeout waiting for response from cell")


class CellMaxHopCountReached(NovaException):
    message = _("Cell message has reached maximum hop count: %(hop_count)s")


class NoCellsAvailable(NovaException):
    message = _("No cells available matching scheduling criteria.")


class CellError(NovaException):
    message = _("Exception received during cell processing: %(exc_name)s.")


class InstanceUnknownCell(NotFound):
    message = _("Cell is not known for instance %(instance_uuid)s")


class SchedulerHostFilterNotFound(NotFound):
    message = _("Scheduler Host Filter %(filter_name)s could not be found.")


class InstanceMetadataNotFound(NotFound):
    message = _("Instance %(instance_uuid)s has no metadata with "
                "key %(metadata_key)s.")


class InstanceSystemMetadataNotFound(NotFound):
    message = _("Instance %(instance_uuid)s has no system metadata with "
                "key %(metadata_key)s.")


class InstanceTypeExtraSpecsNotFound(NotFound):
    message = _("Instance Type %(instance_type_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class FileNotFound(NotFound):
    message = _("File %(file_path)s could not be found.")


class NoFilesFound(NotFound):
    message = _("Zero files could be found.")


class SwitchNotFoundForNetworkAdapter(NotFound):
    message = _("Virtual switch associated with the "
                "network adapter %(adapter)s not found.")


class NetworkAdapterNotFound(NotFound):
    message = _("Network adapter %(adapter)s could not be found.")


class ClassNotFound(NotFound):
    message = _("Class %(class_name)s could not be found: %(exception)s")


class NotAllowed(NovaException):
    message = _("Action not allowed.")


class ImageRotationNotAllowed(NovaException):
    message = _("Rotation is not allowed for snapshots")


class RotationRequiredForBackup(NovaException):
    message = _("Rotation param is required for backup image_type")


class KeyPairExists(Duplicate):
    message = _("Key pair %(key_name)s already exists.")


class InstanceExists(Duplicate):
    message = _("Instance %(name)s already exists.")


class InstanceTypeExists(Duplicate):
    message = _("Instance Type with name %(name)s already exists.")


class InstanceTypeIdExists(Duplicate):
    message = _("Instance Type with ID %(flavor_id)s already exists.")


class FlavorAccessExists(Duplicate):
    message = _("Flavor access alreay exists for flavor %(flavor_id)s "
                "and project %(project_id)s combination.")


class InvalidSharedStorage(NovaException):
    message = _("%(path)s is not on shared storage: %(reason)s")


class InvalidLocalStorage(NovaException):
    message = _("%(path)s is not on local storage: %(reason)s")


class MigrationError(NovaException):
    message = _("Migration error") + ": %(reason)s"


class MigrationPreCheckError(MigrationError):
    message = _("Migration pre-check error") + ": %(reason)s"


class MalformedRequestBody(NovaException):
    message = _("Malformed message body: %(reason)s")


# NOTE(johannes): NotFound should only be used when a 404 error is
# appropriate to be returned
class ConfigNotFound(NovaException):
    message = _("Could not find config at %(path)s")


class PasteAppNotFound(NovaException):
    message = _("Could not load paste app '%(name)s' from %(path)s")


class CannotResizeToSameFlavor(NovaException):
    message = _("When resizing, instances must change flavor!")


class ResizeError(NovaException):
    message = _("Resize error: %(reason)s")


class InstanceTypeMemoryTooSmall(NovaException):
    message = _("Instance type's memory is too small for requested image.")


class InstanceTypeDiskTooSmall(NovaException):
    message = _("Instance type's disk is too small for requested image.")


class InsufficientFreeMemory(NovaException):
    message = _("Insufficient free memory on compute node to start %(uuid)s.")


class CouldNotFetchMetrics(NovaException):
    message = _("Could not fetch bandwidth/cpu/disk metrics for this host.")


class NoValidHost(NovaException):
    message = _("No valid host was found. %(reason)s")


class QuotaError(NovaException):
    message = _("Quota exceeded") + ": code=%(code)s"
    code = 413
    headers = {'Retry-After': 0}
    safe = True


class TooManyInstances(QuotaError):
    message = _("Quota exceeded for %(overs)s: Requested %(req)s,"
                " but already used %(used)d of %(allowed)d %(resource)s")


class FloatingIpLimitExceeded(QuotaError):
    message = _("Maximum number of floating ips exceeded")


class FixedIpLimitExceeded(QuotaError):
    message = _("Maximum number of fixed ips exceeded")


class MetadataLimitExceeded(QuotaError):
    message = _("Maximum number of metadata items exceeds %(allowed)d")


class OnsetFileLimitExceeded(QuotaError):
    message = _("Personality file limit exceeded")


class OnsetFilePathLimitExceeded(QuotaError):
    message = _("Personality file path too long")


class OnsetFileContentLimitExceeded(QuotaError):
    message = _("Personality file content too long")


class KeypairLimitExceeded(QuotaError):
    message = _("Maximum number of key pairs exceeded")


class SecurityGroupLimitExceeded(QuotaError):
    message = _("Maximum number of security groups or rules exceeded")


class AggregateError(NovaException):
    message = _("Aggregate %(aggregate_id)s: action '%(action)s' "
                "caused an error: %(reason)s.")


class AggregateNotFound(NotFound):
    message = _("Aggregate %(aggregate_id)s could not be found.")


class AggregateNameExists(Duplicate):
    message = _("Aggregate %(aggregate_name)s already exists.")


class AggregateHostNotFound(NotFound):
    message = _("Aggregate %(aggregate_id)s has no host %(host)s.")


class AggregateMetadataNotFound(NotFound):
    message = _("Aggregate %(aggregate_id)s has no metadata with "
                "key %(metadata_key)s.")


class AggregateHostExists(Duplicate):
    message = _("Aggregate %(aggregate_id)s already has host %(host)s.")


class InstanceTypeCreateFailed(NovaException):
    message = _("Unable to create instance type")


class InstancePasswordSetFailed(NovaException):
    message = _("Failed to set admin password on %(instance)s "
                "because %(reason)s")
    safe = True


class DuplicateVlan(Duplicate):
    message = _("Detected existing vlan with id %(vlan)d")


class CidrConflict(NovaException):
    message = _("There was a conflict when trying to complete your request.")
    code = 409


class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")


class InstanceInfoCacheNotFound(NotFound):
    message = _("Info cache for instance %(instance_uuid)s could not be "
                "found.")


class NodeNotFound(NotFound):
    message = _("Node %(node_id)s could not be found.")


class NodeNotFoundByUUID(NotFound):
    message = _("Node with UUID %(node_uuid)s could not be found.")


class MarkerNotFound(NotFound):
    message = _("Marker %(marker)s could not be found.")


class InvalidInstanceIDMalformed(Invalid):
    message = _("Invalid id: %(val)s (expecting \"i-...\").")


class CouldNotFetchImage(NovaException):
    message = _("Could not fetch image %(image_id)s")


class CouldNotUploadImage(NovaException):
    message = _("Could not upload image %(image_id)s")


class TaskAlreadyRunning(NovaException):
    message = _("Task %(task_name)s is already running on host %(host)s")


class TaskNotRunning(NovaException):
    message = _("Task %(task_name)s is not running on host %(host)s")


class InstanceIsLocked(InstanceInvalidState):
    message = _("Instance %(instance_uuid)s is locked")


class ConfigDriveMountFailed(NovaException):
    message = _("Could not mount vfat config drive. %(operation)s failed. "
                "Error: %(error)s")


class ConfigDriveUnknownFormat(NovaException):
    message = _("Unknown config drive format %(format)s. Select one of "
                "iso9660 or vfat.")


class InterfaceAttachFailed(Invalid):
    message = _("Failed to attach network adapter device to %(instance)s")


class InterfaceDetachFailed(Invalid):
    message = _("Failed to detach network adapter device from  %(instance)s")


class InstanceUserDataTooLarge(NovaException):
    message = _("User data too large. User data must be no larger than "
                "%(maxsize)s bytes once base64 encoded. Your data is "
                "%(length)d bytes")


class InstanceUserDataMalformed(NovaException):
    message = _("User data needs to be valid base 64.")


class UnexpectedTaskStateError(NovaException):
    message = _("unexpected task state: expecting %(expected)s but "
                "the actual state is %(actual)s")


class InstanceActionNotFound(NovaException):
    message = _("Action for request_id %(request_id)s on instance"
                " %(instance_uuid)s not found")


class InstanceActionEventNotFound(NovaException):
    message = _("Event %(event)s not found for action id %(action_id)s")


class UnexpectedVMStateError(NovaException):
    message = _("unexpected VM state: expecting %(expected)s but "
                "the actual state is %(actual)s")


class CryptoCAFileNotFound(FileNotFound):
    message = _("The CA file for %(project)s could not be found")


class CryptoCRLFileNotFound(FileNotFound):
    message = _("The CRL file for %(project)s could not be found")


class InstanceRecreateNotSupported(Invalid):
    message = _('Instance recreate is not implemented by this virt driver.')


class ServiceGroupUnavailable(NovaException):
    message = _("The service from servicegroup driver %(driver) is "
                "temporarily unavailable.")


class DBNotAllowed(NovaException):
    message = _('%(binary)s attempted direct database access which is '
                'not allowed by policy')


class UnsupportedVirtType(Invalid):
    message = _("Virtualization type '%(virt)s' is not supported by "
                "this compute driver")


class UnsupportedHardware(Invalid):
    message = _("Requested hardware '%(model)s' is not supported by "
                "the '%(virt)s' virt driver")


class Base64Exception(NovaException):
    message = _("Invalid Base 64 data for file %(path)s")


class BuildAbortException(NovaException):
    message = _("Build of instance %(instance_uuid)s aborted: %(reason)s")


class RescheduledException(NovaException):
    message = _("Build of instance %(instance_uuid)s was re-scheduled: "
                "%(reason)s")


class ShadowTableExists(NovaException):
    message = _("Shadow table with name %(name)s already exists.")


class InstanceFaultRollback(NovaException):
    def __init__(self, inner_exception=None):
        message = _("Instance rollback performed due to: %s")
        self.inner_exception = inner_exception
        super(InstanceFaultRollback, self).__init__(message % inner_exception)


class UnsupportedObjectError(NovaException):
    message = _('Unsupported object type %(objtype)s')


class OrphanedObjectError(NovaException):
    message = _('Cannot call %(method)s on orphaned %(objtype)s object')


class IncompatibleObjectVersion(NovaException):
    message = _('Version %(objver)s of %(objname)s is not supported')
