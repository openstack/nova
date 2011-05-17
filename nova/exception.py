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

from nova import log as logging


LOG = logging.getLogger('nova.exception')


class ProcessExecutionError(IOError):
    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
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


class BuildInProgress(Error):
    pass


class DBError(Error):
    """Wraps an implementation specific exception."""
    def __init__(self, inner_exception):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(str(inner_exception))


def wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception, e:
            LOG.exception(_('DB exception wrapped.'))
            raise DBError(e)
    return _wrap
    _wrap.func_name = f.func_name


def wrap_exception(f):
    def _wrap(*args, **kw):
        try:
            return f(*args, **kw)
        except Exception, e:
            if not isinstance(e, Error):
                #exc_type, exc_value, exc_traceback = sys.exc_info()
                LOG.exception(_('Uncaught exception'))
                #logging.error(traceback.extract_stack(exc_traceback))
                raise Error(str(e))
            raise
    _wrap.func_name = f.func_name
    return _wrap


class NovaException(Exception):
    """Base Nova Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")

    def __init__(self, **kwargs):
        try:
            self._error_string = self.message % kwargs

        except Exception:
            # at least get the core message out if something happened
            self._error_string = self.message

    def __str__(self):
        return self._error_string


class NotAuthorized(NovaException):
    message = _("Not authorized.")

    def __init__(self, *args, **kwargs):
        super(NotFound, self).__init__(**kwargs)


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class Invalid(NovaException):
    message = _("Unacceptable parameters.")


class InvalidSignature(Invalid):
    message = _("Invalid signature %(signature)s for user %(user)s.")


class InvalidInput(Invalid):
    message = _("Invalid input received") + ": %(reason)s"


class InvalidInstanceType(Invalid):
    message = _("Invalid instance type %(instance_type)s.")


class InvalidPortRange(Invalid):
    message = _("Invalid port range %(from_port)s:%(to_port)s.")


class InvalidIpProtocol(Invalid):
    message = _("Invalid IP protocol %(protocol)s.")


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


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


class SourceHostUnavailable(Invalid):
    message = _("Original compute host is unavailable at this time.")


class InvalidHypervisorType(Invalid):
    message = _("The supplied hypervisor type of is invalid.")


class DestinationHypervisorTooOld(Invalid):
    message = _("The instance requires a newer hypervisor version than "
                "has been provided.")


class InvalidDevicePath(Invalid):
    message = _("The supplied device path (%(path)s) is invalid.")


class InvalidCPUInfo(Invalid):
    message = _("Unacceptable CPU info") + ": %(reason)s"


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
        super(NotFound, self).__init__(**kwargs)


class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class VolumeNotFoundForInstance(VolumeNotFound):
    message = _("Volume not found for instance %(instance_id)s.")


class ExportDeviceNotFoundForVolume(NotFound):
    message = _("No export device found for volume %(volume_id)s.")


class ISCSITargetNotFoundForVolume(NotFound):
    message = _("No target id found for volume %(volume_id)s.")


class DiskNotFound(NotFound):
    message = _("No disk at %(location)s")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class KernelNotFoundForImage(ImageNotFound):
    message = _("Kernel not found for image %(image_id)s.")


class RamdiskNotFoundForImage(ImageNotFound):
    message = _("Ramdisk not found for image %(image_id)s.")


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


class NetworkNotFound(NotFound):
    message = _("Network %(network_id)s could not be found.")


class NetworkNotFoundForBridge(NetworkNotFound):
    message = _("Network could not be found for bridge %(bridge)s")


class NetworkNotFoundForCidr(NetworkNotFound):
    message = _("Network could not be found with cidr %(cidr)s.")


class NetworkNotFoundForInstance(NetworkNotFound):
    message = _("Network could not be found for instance %(instance_id)s.")


class NoNetworksFound(NotFound):
    message = _("No networks defined.")


class DatastoreNotFound(NotFound):
    message = _("Could not find the datastore reference(s) which the VM uses.")


class NoFixedIpsFoundForInstance(NotFound):
    message = _("Instance %(instance_id)s has zero fixed ips.")


class FloatingIpNotFound(NotFound):
    message = _("Floating ip not found for fixed address %(fixed_ip)s.")


class NoFloatingIpsDefined(NotFound):
    message = _("Zero floating ips could be found.")


class NoFloatingIpsDefinedForHost(NoFloatingIpsDefined):
    message = _("Zero floating ips defined for host %(host)s.")


class NoFloatingIpsDefinedForInstance(NoFloatingIpsDefined):
    message = _("Zero floating ips defined for instance %(instance_id)s.")


class KeypairNotFound(NotFound):
    message = _("Keypair %(keypair_name)s not found for user %(user_id)s")


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

# TODO(sirp): move these into the schedule classes since they are internal?
class SchedulerHostFilterDriverNotFound(NotFound):
    message = _("Scheduler Host Filter Driver %(driver_name)s could"
                " not be found.")

class SchedulerCostFunctionNotFound(NotFound):
    message = _("Scheduler cost function %(cost_fn_str)s could"
                " not be found.")

class SchedulerWeightFlagNotFound(NotFound):
    message = _("Scheduler weight flag not found: %(flag_name)s")


class InstanceMetadataNotFound(NotFound):
    message = _("Instance %(instance_id)s has no metadata with "
                "key %(metadata_key)s.")


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
    message = _("Class %(class_name)s could not be found")


class NotAllowed(NovaException):
    message = _("Action not allowed.")


class GlobalRoleNotAllowed(NotAllowed):
    message = _("Unable to use global role %(role_id)s")


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


class MigrationError(NovaException):
    message = _("Migration error") + ": %(reason)s"
