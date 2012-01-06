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
import sys

import novaclient.exceptions
import webob.exc

from nova import log as logging

LOG = logging.getLogger('nova.exception')


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=0, title="", explanation=""):
        self.code = code
        self.title = title
        self.explanation = explanation
        super(ConvertedException, self).__init__()


def novaclient_converter(f):
    """Convert novaclient ClientException HTTP codes to webob exceptions.
    Has to be the outer-most decorator.
    """
    def new_f(*args, **kwargs):
        try:
            ret = f(*args, **kwargs)
            return ret
        except novaclient.exceptions.ClientException, e:
            raise ConvertedException(e.code, e.message, e.details)
    return new_f


class ProcessExecutionError(IOError):
    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout
        self.cmd = cmd
        self.description = description

        if description is None:
            description = _('Unexpected error while running command.')
        if exit_code is None:
            exit_code = '-'
        message = _('%(description)s\nCommand: %(cmd)s\n'
                    'Exit code: %(exit_code)s\nStdout: %(stdout)r\n'
                    'Stderr: %(stderr)r') % locals()
        IOError.__init__(self, message)


class Error(Exception):
    def __init__(self, message=None):
        super(Error, self).__init__(message)


class ApiError(Error):
    def __init__(self, message='Unknown', code=None):
        self.msg = message
        self.code = code
        if code:
            outstr = '%s: %s' % (code, message)
        else:
            outstr = '%s' % message
        super(ApiError, self).__init__(outstr)


class DBError(Error):
    """Wraps an implementation specific exception."""
    def __init__(self, inner_exception=None):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(str(inner_exception))


def wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception, e:
            LOG.exception(_('DB exception wrapped.'))
            raise DBError(e)
    _wrap.func_name = f.func_name
    return _wrap


def wrap_exception(notifier=None, publisher_id=None, event_type=None,
                   level=None):
    """This decorator wraps a method to catch any exceptions that may
    get thrown. It logs the exception as well as optionally sending
    it to the notification system.
    """
    # TODO(sandy): Find a way to import nova.notifier.api so we don't have
    # to pass it in as a parameter. Otherwise we get a cyclic import of
    # nova.notifier.api -> nova.utils -> nova.exception :(
    # TODO(johannes): Also, it would be nice to use
    # utils.save_and_reraise_exception() without an import loop
    def inner(f):
        def wrapped(*args, **kw):
            try:
                return f(*args, **kw)
            except Exception, e:
                # Save exception since it can be clobbered during processing
                # below before we can re-raise
                exc_info = sys.exc_info()

                if notifier:
                    payload = dict(args=args, exception=e)
                    payload.update(kw)

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

                    notifier.notify(publisher_id, temp_type, temp_level,
                                    payload)

                # re-raise original exception since it may have been clobbered
                raise exc_info[0], exc_info[1], exc_info[2]

        return functools.wraps(f)(wrapped)
    return inner


class NovaException(Exception):
    """Base Nova Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs
        if not message:
            try:
                message = self.message % kwargs

            except Exception as e:
                # at least get the core message out if something happened
                message = self.message

        super(NovaException, self).__init__(message)


class ImagePaginationFailed(NovaException):
    message = _("Failed to paginate through images from image service")


class VirtualInterfaceCreateException(NovaException):
    message = _("Virtual Interface creation failed")


class VirtualInterfaceMacAddressException(NovaException):
    message = _("5 attempts to create virtual interface"
                "with unique mac address failed")


class NotAuthorized(NovaException):
    message = _("Not authorized.")

    def __init__(self, *args, **kwargs):
        super(NotAuthorized, self).__init__(*args, **kwargs)


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy Doesn't allow %(action)s to be performed.")


class Invalid(NovaException):
    message = _("Unacceptable parameters.")


class InvalidRequest(Invalid):
    message = _("The request is invalid.")


class InvalidSignature(Invalid):
    message = _("Invalid signature %(signature)s for user %(user)s.")


class InvalidInput(Invalid):
    message = _("Invalid input received") + ": %(reason)s"


class InvalidInstanceType(Invalid):
    message = _("Invalid instance type %(instance_type)s.")


class InvalidVolumeType(Invalid):
    message = _("Invalid volume type %(volume_type)s.")


class InvalidPortRange(Invalid):
    message = _("Invalid port range %(from_port)s:%(to_port)s. %(msg)s")


class InvalidIpProtocol(Invalid):
    message = _("Invalid IP protocol %(protocol)s.")


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


class InvalidCidr(Invalid):
    message = _("Invalid cidr %(cidr)s.")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class InstanceInvalidState(Invalid):
    message = _("Instance %(instance_uuid)s in %(attr)s %(state)s. Cannot "
                "%(method)s while the instance is in this state.")


class InstanceNotRunning(Invalid):
    message = _("Instance %(instance_id)s is not running.")


class InstanceNotSuspended(Invalid):
    message = _("Instance %(instance_id)s is not suspended.")


class InstanceNotInRescueMode(Invalid):
    message = _("Instance %(instance_id)s is not in rescue mode")


class InstanceSuspendFailure(Invalid):
    message = _("Failed to suspend instance") + ": %(reason)s"


class InstanceResumeFailure(Invalid):
    message = _("Failed to resume server") + ": %(reason)s."


class InstanceRebootFailure(Invalid):
    message = _("Failed to reboot instance") + ": %(reason)s"


class ServiceUnavailable(Invalid):
    message = _("Service is unavailable at this time.")


class VolumeServiceUnavailable(ServiceUnavailable):
    message = _("Volume service is unavailable at this time.")


class ComputeServiceUnavailable(ServiceUnavailable):
    message = _("Compute service is unavailable at this time.")


class UnableToMigrateToSelf(Invalid):
    message = _("Unable to migrate instance (%(instance_id)s) "
                "to current host (%(host)s).")


class DestinationHostUnavailable(Invalid):
    message = _("Destination compute host is unavailable at this time.")


class SourceHostUnavailable(Invalid):
    message = _("Original compute host is unavailable at this time.")


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
    message = _("Image %(image_id)s is unacceptable") + ": %(reason)s"


class InstanceUnacceptable(Invalid):
    message = _("Instance %(instance_id)s is unacceptable") + ": %(reason)s"


class InvalidEc2Id(Invalid):
    message = _("Ec2 id %(ec2_id)s is unacceptable.")


class NotFound(NovaException):
    message = _("Resource could not be found.")

    def __init__(self, *args, **kwargs):
        super(NotFound, self).__init__(*args, **kwargs)


class FlagNotSet(NotFound):
    message = _("Required flag %(flag)s not set.")


class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class VolumeNotFoundForInstance(VolumeNotFound):
    message = _("Volume not found for instance %(instance_id)s.")


class VolumeMetadataNotFound(NotFound):
    message = _("Volume %(volume_id)s has no metadata with "
                "key %(metadata_key)s.")


class NoVolumeTypesFound(NotFound):
    message = _("Zero volume types found.")


class VolumeTypeNotFound(NotFound):
    message = _("Volume type %(volume_type_id)s could not be found.")


class VolumeTypeNotFoundByName(VolumeTypeNotFound):
    message = _("Volume type with name %(volume_type_name)s "
                "could not be found.")


class VolumeTypeExtraSpecsNotFound(NotFound):
    message = _("Volume Type %(volume_type_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")


class VolumeIsBusy(NovaException):
    message = _("deleting volume %(volume_name)s that has snapshot")


class ISCSITargetNotFoundForVolume(NotFound):
    message = _("No target id found for volume %(volume_id)s.")


class DiskNotFound(NotFound):
    message = _("No disk at %(location)s")


class VolumeDriverNotFound(NotFound):
    message = _("Could not find a handler for %(driver_type)s volume.")


class InvalidImageRef(Invalid):
    message = _("Invalid image href %(image_href)s.")


class ListingImageRefsNotSupported(Invalid):
    message = _("Some images have been stored via hrefs."
        + " This version of the api does not support displaying image hrefs.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class KernelNotFoundForImage(ImageNotFound):
    message = _("Kernel not found for image %(image_id)s.")


class UserNotFound(NotFound):
    message = _("User %(user_id)s could not be found.")


class ProjectNotFound(NotFound):
    message = _("Project %(project_id)s could not be found.")


class ProjectMembershipNotFound(NotFound):
    message = _("User %(user_id)s is not a member of project %(project_id)s.")


class UserRoleNotFound(NotFound):
    message = _("Role %(role_id)s could not be found.")


class StorageRepositoryNotFound(NotFound):
    message = _("Cannot find SR to read/write VDI.")


class NetworkNotCreated(NovaException):
    message = _("%(req)s is required to create a network.")


class NetworkNotFound(NotFound):
    message = _("Network %(network_id)s could not be found.")


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


class NetworkHostNotSet(NovaException):
    message = _("Host is not set to the network (%(network_id)s).")


class DatastoreNotFound(NotFound):
    message = _("Could not find the datastore reference(s) which the VM uses.")


class FixedIpNotFound(NotFound):
    message = _("No fixed IP associated with id %(id)s.")


class FixedIpNotFoundForAddress(FixedIpNotFound):
    message = _("Fixed ip not found for address %(address)s.")


class FixedIpNotFoundForInstance(FixedIpNotFound):
    message = _("Instance %(instance_id)s has zero fixed ips.")


class FixedIpNotFoundForNetworkHost(FixedIpNotFound):
    message = _("Network host %(host)s has zero fixed ips "
                "in network %(network_id)s.")


class FixedIpNotFoundForSpecificInstance(FixedIpNotFound):
    message = _("Instance %(instance_id)s doesn't have fixed ip '%(ip)s'.")


class FixedIpNotFoundForHost(FixedIpNotFound):
    message = _("Host %(host)s has zero fixed ips.")


class FixedIpNotFoundForNetwork(FixedIpNotFound):
    message = _("Fixed IP address (%(address)s) does not exist in "
                "network (%(network_uuid)s).")


class FixedIpAlreadyInUse(NovaException):
    message = _("Fixed IP address %(address)s is already in use.")


class FixedIpInvalid(Invalid):
    message = _("Fixed IP address %(address)s is invalid.")


class NoMoreFixedIps(NovaException):
    message = _("Zero fixed ips available.")


class NoFixedIpsDefined(NotFound):
    message = _("Zero fixed ips could be found.")


class FloatingIpNotFound(NotFound):
    message = _("Floating ip not found for id %(id)s.")


class FloatingIpDNSExists(Invalid):
    message = _("The DNS entry %(name)s already exists in zone %(zone)s.")


class FloatingIpNotFoundForAddress(FloatingIpNotFound):
    message = _("Floating ip not found for address %(address)s.")


class FloatingIpNotFoundForHost(FloatingIpNotFound):
    message = _("Floating ip not found for host %(host)s.")


class NoMoreFloatingIps(FloatingIpNotFound):
    message = _("Zero floating ips available.")


class FloatingIpAssociated(NovaException):
    message = _("Floating ip %(address)s is associated.")


class FloatingIpNotAssociated(NovaException):
    message = _("Floating ip %(address)s is not associated.")


class NoFloatingIpsDefined(NotFound):
    message = _("Zero floating ips exist.")


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


class AuthTokenNotFound(NotFound):
    message = _("Auth token %(token)s could not be found.")


class AccessKeyNotFound(NotFound):
    message = _("Access Key %(access_key)s could not be found.")


class QuotaNotFound(NotFound):
    message = _("Quota could not be found")


class ProjectQuotaNotFound(QuotaNotFound):
    message = _("Quota for project %(project_id)s could not be found.")


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
    message = _("Console for instance %(instance_id)s could not be found.")


class ConsoleNotFoundInPoolForInstance(ConsoleNotFound):
    message = _("Console for instance %(instance_id)s "
                "in pool %(pool_id)s could not be found.")


class NoInstanceTypesFound(NotFound):
    message = _("Zero instance types found.")


class InstanceTypeNotFound(NotFound):
    message = _("Instance type %(instance_type_id)s could not be found.")


class InstanceTypeNotFoundByName(InstanceTypeNotFound):
    message = _("Instance type with name %(instance_type_name)s "
                "could not be found.")


class FlavorNotFound(NotFound):
    message = _("Flavor %(flavor_id)s could not be found.")


class ZoneNotFound(NotFound):
    message = _("Zone %(zone_id)s could not be found.")


class SchedulerHostFilterNotFound(NotFound):
    message = _("Scheduler Host Filter %(filter_name)s could not be found.")


class SchedulerCostFunctionNotFound(NotFound):
    message = _("Scheduler cost function %(cost_fn_str)s could"
                " not be found.")


class SchedulerWeightFlagNotFound(NotFound):
    message = _("Scheduler weight flag not found: %(flag_name)s")


class InstanceMetadataNotFound(NotFound):
    message = _("Instance %(instance_id)s has no metadata with "
                "key %(metadata_key)s.")


class InstanceTypeExtraSpecsNotFound(NotFound):
    message = _("Instance Type %(instance_type_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class LDAPObjectNotFound(NotFound):
    message = _("LDAP object could not be found")


class LDAPUserNotFound(LDAPObjectNotFound):
    message = _("LDAP user %(user_id)s could not be found.")


class LDAPGroupNotFound(LDAPObjectNotFound):
    message = _("LDAP group %(group_id)s could not be found.")


class LDAPGroupMembershipNotFound(NotFound):
    message = _("LDAP user %(user_id)s is not a member of group %(group_id)s.")


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


class GlobalRoleNotAllowed(NotAllowed):
    message = _("Unable to use global role %(role_id)s")


class ImageRotationNotAllowed(NovaException):
    message = _("Rotation is not allowed for snapshots")


class RotationRequiredForBackup(NovaException):
    message = _("Rotation param is required for backup image_type")


#TODO(bcwaldon): EOL this exception!
class Duplicate(NovaException):
    pass


class KeyPairExists(Duplicate):
    message = _("Key pair %(key_name)s already exists.")


class UserExists(Duplicate):
    message = _("User %(user)s already exists.")


class LDAPUserExists(UserExists):
    message = _("LDAP user %(user)s already exists.")


class LDAPGroupExists(Duplicate):
    message = _("LDAP group %(group)s already exists.")


class LDAPMembershipExists(Duplicate):
    message = _("User %(uid)s is already a member of "
                "the group %(group_dn)s")


class ProjectExists(Duplicate):
    message = _("Project %(project)s already exists.")


class InstanceExists(Duplicate):
    message = _("Instance %(name)s already exists.")


class InvalidSharedStorage(NovaException):
    message = _("%(path)s is on shared storage: %(reason)s")


class MigrationError(NovaException):
    message = _("Migration error") + ": %(reason)s"


class MalformedRequestBody(NovaException):
    message = _("Malformed message body: %(reason)s")


class ConfigNotFound(NotFound):
    message = _("Could not find config at %(path)s")


class PasteAppNotFound(NotFound):
    message = _("Could not load paste app '%(name)s' from %(path)s")


class VSANovaAccessParamNotFound(Invalid):
    message = _("Nova access parameters were not specified.")


class VirtualStorageArrayNotFound(NotFound):
    message = _("Virtual Storage Array %(id)d could not be found.")


class VirtualStorageArrayNotFoundByName(NotFound):
    message = _("Virtual Storage Array %(name)s could not be found.")


class CannotResizeToSameSize(NovaException):
    message = _("When resizing, instances must change size!")


class ImageTooLarge(NovaException):
    message = _("Image is larger than instance type allows")


class ZoneRequestError(Error):
    def __init__(self, message=None):
        if message is None:
            message = _("1 or more Zones could not complete the request")
        super(ZoneRequestError, self).__init__(message=message)


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


class WillNotSchedule(NovaException):
    message = _("Host %(host)s is not up or doesn't exist.")


class QuotaError(ApiError):
    """Quota Exceeded."""
    pass
