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

from oslo_log import log as logging
import six

import webob.exc
from webob import util as woutil

from nova.i18n import _, _LE

LOG = logging.getLogger(__name__)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code, title="", explanation=""):
        self.code = code
        # There is a strict rule about constructing status line for HTTP:
        # '...Status-Line, consisting of the protocol version followed by a
        # numeric status code and its associated textual phrase, with each
        # element separated by SP characters'
        # (http://www.faqs.org/rfcs/rfc2616.html)
        # 'code' and 'title' can not be empty because they correspond
        # to numeric status code and its associated text
        if title:
            self.title = title
        else:
            try:
                self.title = woutil.status_reasons[self.code]
            except KeyError:
                msg = _LE("Improper or unknown HTTP status code used: %d")
                LOG.error(msg, code)
                self.title = woutil.status_generic_reasons[self.code // 100]
        self.explanation = explanation
        super(ConvertedException, self).__init__()


class NovaException(Exception):
    """Base Nova Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.

    """
    msg_fmt = _("An unknown exception occurred.")
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

        try:
            if not message:
                message = self.msg_fmt % kwargs
            else:
                message = six.text_type(message)
        except Exception:
            # NOTE(melwitt): This is done in a separate method so it can be
            # monkey-patched during testing to make it a hard failure.
            self._log_exception()
            message = self.msg_fmt

        self.message = message
        super(NovaException, self).__init__(message)

    def _log_exception(self):
        # kwargs doesn't match a variable in the message
        # log the issue and the kwargs
        LOG.exception(_LE('Exception in string format operation'))
        for name, value in self.kwargs.items():
            LOG.error("%s: %s" % (name, value))  # noqa

    def format_message(self):
        # NOTE(mrodden): use the first argument to the python Exception object
        # which should be our full NovaException message, (see __init__)
        return self.args[0]

    def __repr__(self):
        dict_repr = self.__dict__
        dict_repr['class'] = self.__class__.__name__
        return str(dict_repr)


class EncryptionFailure(NovaException):
    msg_fmt = _("Failed to encrypt text: %(reason)s")


class DecryptionFailure(NovaException):
    msg_fmt = _("Failed to decrypt text: %(reason)s")


class RevokeCertFailure(NovaException):
    msg_fmt = _("Failed to revoke certificate for %(project_id)s")


class VirtualInterfaceCreateException(NovaException):
    msg_fmt = _("Virtual Interface creation failed")


class VirtualInterfaceMacAddressException(NovaException):
    msg_fmt = _("Creation of virtual interface with "
                "unique mac address failed")


class VirtualInterfacePlugException(NovaException):
    msg_fmt = _("Virtual interface plugin failed")


class VirtualInterfaceUnplugException(NovaException):
    msg_fmt = _("Failed to unplug virtual interface: %(reason)s")


class GlanceConnectionFailed(NovaException):
    msg_fmt = _("Connection to glance host %(server)s failed: "
        "%(reason)s")


class CinderConnectionFailed(NovaException):
    msg_fmt = _("Connection to cinder host failed: %(reason)s")


class UnsupportedCinderAPIVersion(NovaException):
    msg_fmt = _('Nova does not support Cinder API version %(version)s')


class CinderAPIVersionNotAvailable(NovaException):
    """Used to indicate that a requested Cinder API version, generally a
    microversion, is not available.
    """
    msg_fmt = _('Cinder API version %(version)s is not available.')


class Forbidden(NovaException):
    msg_fmt = _("Forbidden")
    code = 403


class AdminRequired(Forbidden):
    msg_fmt = _("User does not have admin privileges")


class PolicyNotAuthorized(Forbidden):
    msg_fmt = _("Policy doesn't allow %(action)s to be performed.")


class ImageNotActive(NovaException):
    # NOTE(jruzicka): IncorrectState is used for volumes only in EC2,
    # but it still seems like the most appropriate option.
    msg_fmt = _("Image %(image_id)s is not active.")


class ImageNotAuthorized(NovaException):
    msg_fmt = _("Not authorized for image %(image_id)s.")


class Invalid(NovaException):
    msg_fmt = _("Bad Request - Invalid Parameters")
    code = 400


class InvalidConfiguration(Invalid):
    msg_fmt = _("Configuration is Invalid.")


class InvalidBDM(Invalid):
    msg_fmt = _("Block Device Mapping is Invalid.")


class InvalidBDMSnapshot(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "failed to get snapshot %(id)s.")


class InvalidBDMVolume(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "failed to get volume %(id)s.")


class InvalidBDMImage(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "failed to get image %(id)s.")


class InvalidBDMBootSequence(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "Boot sequence for the instance "
                "and image/block device mapping "
                "combination is not valid.")


class InvalidBDMLocalsLimit(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "You specified more local devices than the "
                "limit allows")


class InvalidBDMEphemeralSize(InvalidBDM):
    msg_fmt = _("Ephemeral disks requested are larger than "
                "the instance type allows. If no size is given "
                "in one block device mapping, flavor ephemeral "
                "size will be used.")


class InvalidBDMSwapSize(InvalidBDM):
    msg_fmt = _("Swap drive requested is larger than instance type allows.")


class InvalidBDMFormat(InvalidBDM):
    msg_fmt = _("Block Device Mapping is Invalid: "
                "%(details)s")


class InvalidBDMForLegacy(InvalidBDM):
    msg_fmt = _("Block Device Mapping cannot "
                "be converted to legacy format. ")


class InvalidBDMVolumeNotBootable(InvalidBDM):
    msg_fmt = _("Block Device %(id)s is not bootable.")


class TooManyDiskDevices(InvalidBDM):
    msg_fmt = _('The maximum allowed number of disk devices (%(maximum)d) to '
                'attach to a single instance has been exceeded.')
    code = 403


class InvalidBDMDiskBus(InvalidBDM):
    msg_fmr = _("Block Device Mapping is invalid: The provided disk bus "
                "%(disk_bus)s is not valid.")


class InvalidAttribute(Invalid):
    msg_fmt = _("Attribute not supported: %(attr)s")


class ValidationError(Invalid):
    msg_fmt = "%(detail)s"


class VolumeAttachFailed(Invalid):
    msg_fmt = _("Volume %(volume_id)s could not be attached. "
                "Reason: %(reason)s")


class VolumeDetachFailed(Invalid):
    msg_fmt = _("Volume %(volume_id)s could not be detached. "
                "Reason: %(reason)s")


class MultiattachNotSupportedByVirtDriver(NovaException):
    # This exception indicates the compute hosting the instance does not
    # support multiattach volumes. This should generally be considered a
    # 409 HTTPConflict error in the API since we expect all virt drivers to
    # eventually support multiattach volumes.
    msg_fmt = _("Volume %(volume_id)s has 'multiattach' set, "
                "which is not supported for this instance.")
    code = 409


class MultiattachNotSupportedOldMicroversion(Invalid):
    msg_fmt = _('Multiattach volumes are only supported starting with '
                'compute API version 2.60.')


class VolumeTypeSupportNotYetAvailable(NovaException):
    # This exception indicates the deployment is not yet new enough to support
    # volume type, so a 409 HTTPConflict response is generally used
    # for handling this in the API.
    msg_fmt = _("Volume type support is not yet available.")
    code = 409


class MultiattachToShelvedNotSupported(Invalid):
    msg_fmt = _("Attaching multiattach volumes is not supported for "
                "shelved-offloaded instances.")


class MultiattachSwapVolumeNotSupported(Invalid):
    msg_fmt = _('Swapping multi-attach volumes with more than one read/write '
                'attachment is not supported.')


class VolumeNotCreated(NovaException):
    msg_fmt = _("Volume %(volume_id)s did not finish being created"
                " even after we waited %(seconds)s seconds or %(attempts)s"
                " attempts. And its status is %(volume_status)s.")


class ExtendVolumeNotSupported(Invalid):
    msg_fmt = _("Volume size extension is not supported by the hypervisor.")


class VolumeEncryptionNotSupported(Invalid):
    msg_fmt = _("Volume encryption is not supported for %(volume_type)s "
                "volume %(volume_id)s")


class VolumeTaggedAttachNotSupported(Invalid):
    msg_fmt = _("Tagged volume attachment is not supported for this server "
                "instance.")


class VolumeTaggedAttachToShelvedNotSupported(VolumeTaggedAttachNotSupported):
    msg_fmt = _("Tagged volume attachment is not supported for "
                "shelved-offloaded instances.")


class NetworkInterfaceTaggedAttachNotSupported(Invalid):
    msg_fmt = _("Tagged network interface attachment is not supported for "
                "this server instance.")


class InvalidKeypair(Invalid):
    msg_fmt = _("Keypair data is invalid: %(reason)s")


class InvalidRequest(Invalid):
    msg_fmt = _("The request is invalid.")


class InvalidInput(Invalid):
    msg_fmt = _("Invalid input received: %(reason)s")


class InvalidVolume(Invalid):
    msg_fmt = _("Invalid volume: %(reason)s")


class InvalidVolumeAccessMode(Invalid):
    msg_fmt = _("Invalid volume access mode: %(access_mode)s")


class StaleVolumeMount(InvalidVolume):
    msg_fmt = _("The volume mount at %(mount_path)s is unusable.")


class InvalidMetadata(Invalid):
    msg_fmt = _("Invalid metadata: %(reason)s")


class InvalidMetadataSize(Invalid):
    msg_fmt = _("Invalid metadata size: %(reason)s")


class InvalidPortRange(Invalid):
    msg_fmt = _("Invalid port range %(from_port)s:%(to_port)s. %(msg)s")


class InvalidIpProtocol(Invalid):
    msg_fmt = _("Invalid IP protocol %(protocol)s.")


class InvalidContentType(Invalid):
    msg_fmt = _("Invalid content type %(content_type)s.")


class InvalidAPIVersionString(Invalid):
    msg_fmt = _("API Version String %(version)s is of invalid format. Must "
                "be of format MajorNum.MinorNum.")


class VersionNotFoundForAPIMethod(Invalid):
    msg_fmt = _("API version %(version)s is not supported on this method.")


class InvalidGlobalAPIVersion(Invalid):
    msg_fmt = _("Version %(req_ver)s is not supported by the API. Minimum "
                "is %(min_ver)s and maximum is %(max_ver)s.")


class ApiVersionsIntersect(Invalid):
    msg_fmt = _("Version of %(name)s %(min_ver)s %(max_ver)s intersects "
                "with another versions.")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    msg_fmt = "%(err)s"


class InvalidAggregateAction(Invalid):
    msg_fmt = _("Unacceptable parameters.")
    code = 400


class InvalidAggregateActionAdd(InvalidAggregateAction):
    msg_fmt = _("Cannot add host to aggregate "
                "%(aggregate_id)s. Reason: %(reason)s.")


class InvalidAggregateActionDelete(InvalidAggregateAction):
    msg_fmt = _("Cannot remove host from aggregate "
                "%(aggregate_id)s. Reason: %(reason)s.")


class InvalidAggregateActionUpdate(InvalidAggregateAction):
    msg_fmt = _("Cannot update aggregate "
                "%(aggregate_id)s. Reason: %(reason)s.")


class InvalidAggregateActionUpdateMeta(InvalidAggregateAction):
    msg_fmt = _("Cannot update metadata of aggregate "
                "%(aggregate_id)s. Reason: %(reason)s.")


class InvalidSortKey(Invalid):
    msg_fmt = _("Sort key supplied was not valid.")


class InvalidStrTime(Invalid):
    msg_fmt = _("Invalid datetime string: %(reason)s")


class InvalidNUMANodesNumber(Invalid):
    msg_fmt = _("The property 'numa_nodes' cannot be '%(nodes)s'. "
                "It must be a number greater than 0")


class InvalidName(Invalid):
    msg_fmt = _("An invalid 'name' value was provided. "
                "The name must be: %(reason)s")


class InstanceInvalidState(Invalid):
    msg_fmt = _("Instance %(instance_uuid)s in %(attr)s %(state)s. Cannot "
                "%(method)s while the instance is in this state.")


class InstanceNotRunning(Invalid):
    msg_fmt = _("Instance %(instance_id)s is not running.")


class InstanceNotInRescueMode(Invalid):
    msg_fmt = _("Instance %(instance_id)s is not in rescue mode")


class InstanceNotRescuable(Invalid):
    msg_fmt = _("Instance %(instance_id)s cannot be rescued: %(reason)s")


class InstanceNotReady(Invalid):
    msg_fmt = _("Instance %(instance_id)s is not ready")


class InstanceSuspendFailure(Invalid):
    msg_fmt = _("Failed to suspend instance: %(reason)s")


class InstanceResumeFailure(Invalid):
    msg_fmt = _("Failed to resume instance: %(reason)s")


class InstancePowerOnFailure(Invalid):
    msg_fmt = _("Failed to power on instance: %(reason)s")


class InstancePowerOffFailure(Invalid):
    msg_fmt = _("Failed to power off instance: %(reason)s")


class InstanceRebootFailure(Invalid):
    msg_fmt = _("Failed to reboot instance: %(reason)s")


class InstanceTerminationFailure(Invalid):
    msg_fmt = _("Failed to terminate instance: %(reason)s")


class InstanceDeployFailure(Invalid):
    msg_fmt = _("Failed to deploy instance: %(reason)s")


class MultiplePortsNotApplicable(Invalid):
    msg_fmt = _("Failed to launch instances: %(reason)s")


class InvalidFixedIpAndMaxCountRequest(Invalid):
    msg_fmt = _("Failed to launch instances: %(reason)s")


class ServiceUnavailable(Invalid):
    msg_fmt = _("Service is unavailable at this time.")


class ServiceNotUnique(Invalid):
    msg_fmt = _("More than one possible service found.")


class ComputeResourcesUnavailable(ServiceUnavailable):
    msg_fmt = _("Insufficient compute resources: %(reason)s.")


class HypervisorUnavailable(NovaException):
    msg_fmt = _("Connection to the hypervisor is broken on host")


class ComputeServiceUnavailable(ServiceUnavailable):
    msg_fmt = _("Compute service of %(host)s is unavailable at this time.")


class ComputeServiceInUse(NovaException):
    msg_fmt = _("Compute service of %(host)s is still in use.")


class UnableToMigrateToSelf(Invalid):
    msg_fmt = _("Unable to migrate instance (%(instance_id)s) "
                "to current host (%(host)s).")


class OperationNotSupportedForSEV(NovaException):
    msg_fmt = _("Operation '%(operation)s' not supported for SEV-enabled "
                "instance (%(instance_uuid)s).")
    code = 409


class InvalidHypervisorType(Invalid):
    msg_fmt = _("The supplied hypervisor type of is invalid.")


class HypervisorTooOld(Invalid):
    msg_fmt = _("This compute node's hypervisor is older than the minimum "
                "supported version: %(version)s.")


class DestinationHypervisorTooOld(Invalid):
    msg_fmt = _("The instance requires a newer hypervisor version than "
                "has been provided.")


class ServiceTooOld(Invalid):
    msg_fmt = _("This service is older (v%(thisver)i) than the minimum "
                "(v%(minver)i) version of the rest of the deployment. "
                "Unable to continue.")


class DestinationDiskExists(Invalid):
    msg_fmt = _("The supplied disk path (%(path)s) already exists, "
                "it is expected not to exist.")


class InvalidDevicePath(Invalid):
    msg_fmt = _("The supplied device path (%(path)s) is invalid.")


class DevicePathInUse(Invalid):
    msg_fmt = _("The supplied device path (%(path)s) is in use.")
    code = 409


class InvalidCPUInfo(Invalid):
    msg_fmt = _("Unacceptable CPU info: %(reason)s")


class InvalidIpAddressError(Invalid):
    msg_fmt = _("%(address)s is not a valid IP v4/6 address.")


class InvalidVLANTag(Invalid):
    msg_fmt = _("VLAN tag is not appropriate for the port group "
                "%(bridge)s. Expected VLAN tag is %(tag)s, "
                "but the one associated with the port group is %(pgroup)s.")


class InvalidVLANPortGroup(Invalid):
    msg_fmt = _("vSwitch which contains the port group %(bridge)s is "
                "not associated with the desired physical adapter. "
                "Expected vSwitch is %(expected)s, but the one associated "
                "is %(actual)s.")


class InvalidDiskFormat(Invalid):
    msg_fmt = _("Disk format %(disk_format)s is not acceptable")


class InvalidDiskInfo(Invalid):
    msg_fmt = _("Disk info file is invalid: %(reason)s")


class DiskInfoReadWriteFail(Invalid):
    msg_fmt = _("Failed to read or write disk info file: %(reason)s")


class ImageUnacceptable(Invalid):
    msg_fmt = _("Image %(image_id)s is unacceptable: %(reason)s")


class ImageBadRequest(Invalid):
    msg_fmt = _("Request of image %(image_id)s got BadRequest response: "
                "%(response)s")


class InstanceUnacceptable(Invalid):
    msg_fmt = _("Instance %(instance_id)s is unacceptable: %(reason)s")


class InvalidUUID(Invalid):
    msg_fmt = _("Expected a uuid but received %(uuid)s.")


class InvalidID(Invalid):
    msg_fmt = _("Invalid ID received %(id)s.")


class ConstraintNotMet(NovaException):
    msg_fmt = _("Constraint not met.")
    code = 412


class NotFound(NovaException):
    msg_fmt = _("Resource could not be found.")
    code = 404


class AgentBuildNotFound(NotFound):
    msg_fmt = _("No agent-build associated with id %(id)s.")


class AgentBuildExists(NovaException):
    msg_fmt = _("Agent-build with hypervisor %(hypervisor)s os %(os)s "
                "architecture %(architecture)s exists.")


class VolumeAttachmentNotFound(NotFound):
    msg_fmt = _("Volume attachment %(attachment_id)s could not be found.")


class VolumeNotFound(NotFound):
    msg_fmt = _("Volume %(volume_id)s could not be found.")


class VolumeTypeNotFound(NotFound):
    msg_fmt = _("Volume type %(id_or_name)s could not be found.")


class UndefinedRootBDM(NovaException):
    msg_fmt = _("Undefined Block Device Mapping root: BlockDeviceMappingList "
                "contains Block Device Mappings from multiple instances.")


class BDMNotFound(NotFound):
    msg_fmt = _("No Block Device Mapping with id %(id)s.")


class VolumeBDMNotFound(NotFound):
    msg_fmt = _("No volume Block Device Mapping with id %(volume_id)s.")


class VolumeBDMIsMultiAttach(Invalid):
    msg_fmt = _("Block Device Mapping %(volume_id)s is a multi-attach volume"
                " and is not valid for this operation.")


class VolumeBDMPathNotFound(VolumeBDMNotFound):
    msg_fmt = _("No volume Block Device Mapping at path: %(path)s")


class DeviceDetachFailed(NovaException):
    msg_fmt = _("Device detach failed for %(device)s: %(reason)s")


class DeviceNotFound(NotFound):
    msg_fmt = _("Device '%(device)s' not found.")


class SnapshotNotFound(NotFound):
    msg_fmt = _("Snapshot %(snapshot_id)s could not be found.")


class DiskNotFound(NotFound):
    msg_fmt = _("No disk at %(location)s")


class VolumeDriverNotFound(NotFound):
    msg_fmt = _("Could not find a handler for %(driver_type)s volume.")


class InvalidImageRef(Invalid):
    msg_fmt = _("Invalid image href %(image_href)s.")


class AutoDiskConfigDisabledByImage(Invalid):
    msg_fmt = _("Requested image %(image)s "
                "has automatic disk resize disabled.")


class ImageNotFound(NotFound):
    msg_fmt = _("Image %(image_id)s could not be found.")


class ImageDeleteConflict(NovaException):
    msg_fmt = _("Conflict deleting image. Reason: %(reason)s.")


class ImageHandlerUnsupported(NovaException):
    msg_fmt = _("Error: unsupported image handler %(image_handler)s.")


class PreserveEphemeralNotSupported(Invalid):
    msg_fmt = _("The current driver does not support "
                "preserving ephemeral partitions.")


class ProjectNotFound(NotFound):
    msg_fmt = _("Project %(project_id)s could not be found.")


class StorageRepositoryNotFound(NotFound):
    msg_fmt = _("Cannot find SR to read/write VDI.")


class InstanceMappingNotFound(NotFound):
    msg_fmt = _("Instance %(uuid)s has no mapping to a cell.")


class NetworkDhcpReleaseFailed(NovaException):
    msg_fmt = _("Failed to release IP %(address)s with MAC %(mac_address)s")


class NetworkInUse(NovaException):
    msg_fmt = _("Network %(network_id)s is still in use.")


class NetworkSetHostFailed(NovaException):
    msg_fmt = _("Network set host failed for network %(network_id)s.")


class NetworkNotCreated(Invalid):
    msg_fmt = _("%(req)s is required to create a network.")


class LabelTooLong(Invalid):
    msg_fmt = _("Maximum allowed length for 'label' is 255.")


class InvalidIntValue(Invalid):
    msg_fmt = _("%(key)s must be an integer.")


class InvalidCidr(Invalid):
    msg_fmt = _("%(cidr)s is not a valid IP network.")


class InvalidAddress(Invalid):
    msg_fmt = _("%(address)s is not a valid IP address.")


class AddressOutOfRange(Invalid):
    msg_fmt = _("%(address)s is not within %(cidr)s.")


class DuplicateVlan(NovaException):
    msg_fmt = _("Detected existing vlan with id %(vlan)d")
    code = 409


class CidrConflict(NovaException):
    msg_fmt = _('Requested cidr (%(cidr)s) conflicts '
                'with existing cidr (%(other)s)')
    code = 409


class NetworkHasProject(NetworkInUse):
    msg_fmt = _('Network must be disassociated from project '
                '%(project_id)s before it can be deleted.')


class NetworkNotFound(NotFound):
    msg_fmt = _("Network %(network_id)s could not be found.")


class PortNotFound(NotFound):
    msg_fmt = _("Port id %(port_id)s could not be found.")


class NetworkNotFoundForBridge(NetworkNotFound):
    msg_fmt = _("Network could not be found for bridge %(bridge)s")


class NetworkNotFoundForUUID(NetworkNotFound):
    msg_fmt = _("Network could not be found for uuid %(uuid)s")


class NetworkNotFoundForCidr(NetworkNotFound):
    msg_fmt = _("Network could not be found with cidr %(cidr)s.")


class NetworkNotFoundForInstance(NetworkNotFound):
    msg_fmt = _("Network could not be found for instance %(instance_id)s.")


class NoNetworksFound(NotFound):
    msg_fmt = _("No networks defined.")


class NoMoreNetworks(NovaException):
    msg_fmt = _("No more available networks.")


class NetworkNotFoundForProject(NetworkNotFound):
    msg_fmt = _("Either network uuid %(network_uuid)s is not present or "
                "is not assigned to the project %(project_id)s.")


class NetworkAmbiguous(Invalid):
    msg_fmt = _("More than one possible network found. Specify "
                "network ID(s) to select which one(s) to connect to.")


class UnableToAutoAllocateNetwork(Invalid):
    msg_fmt = _('Unable to automatically allocate a network for project '
                '%(project_id)s')


class NetworkRequiresSubnet(Invalid):
    msg_fmt = _("Network %(network_uuid)s requires a subnet in order to boot"
                " instances on.")


class ExternalNetworkAttachForbidden(Forbidden):
    msg_fmt = _("It is not allowed to create an interface on "
                "external network %(network_uuid)s")


class NetworkMissingPhysicalNetwork(NovaException):
    msg_fmt = _("Physical network is missing for network %(network_uuid)s")


class VifDetailsMissingVhostuserSockPath(Invalid):
    msg_fmt = _("vhostuser_sock_path not present in vif_details"
                " for vif %(vif_id)s")


class VifDetailsMissingMacvtapParameters(Invalid):
    msg_fmt = _("Parameters %(missing_params)s not present in"
                " vif_details for vif %(vif_id)s. Check your Neutron"
                " configuration to validate that the macvtap parameters are"
                " correct.")


class OVSConfigurationFailure(NovaException):
    msg_fmt = _("OVS configuration failed with: %(inner_exception)s.")


class DatastoreNotFound(NotFound):
    msg_fmt = _("Could not find the datastore reference(s) which the VM uses.")


class PortInUse(Invalid):
    msg_fmt = _("Port %(port_id)s is still in use.")


class PortRequiresFixedIP(Invalid):
    msg_fmt = _("Port %(port_id)s requires a FixedIP in order to be used.")


class PortNotUsable(Invalid):
    msg_fmt = _("Port %(port_id)s not usable for instance %(instance)s.")


class PortNotUsableDNS(Invalid):
    msg_fmt = _("Port %(port_id)s not usable for instance %(instance)s. "
                "Value %(value)s assigned to dns_name attribute does not "
                "match instance's hostname %(hostname)s")


class PortNotFree(Invalid):
    msg_fmt = _("No free port available for instance %(instance)s.")


class PortBindingFailed(Invalid):
    msg_fmt = _("Binding failed for port %(port_id)s, please check neutron "
                "logs for more information.")


class PortBindingDeletionFailed(NovaException):
    msg_fmt = _("Failed to delete binding for port %(port_id)s and host "
                "%(host)s.")


class PortBindingActivationFailed(NovaException):
    msg_fmt = _("Failed to activate binding for port %(port_id)s and host "
                "%(host)s.")


class PortUpdateFailed(Invalid):
    msg_fmt = _("Port update failed for port %(port_id)s: %(reason)s")


class AttachSRIOVPortNotSupported(Invalid):
    msg_fmt = _('Attaching SR-IOV port %(port_id)s to server '
                '%(instance_uuid)s is not supported. SR-IOV ports must be '
                'specified during server creation.')


class FixedIpExists(NovaException):
    msg_fmt = _("Fixed IP %(address)s already exists.")


class FixedIpNotFound(NotFound):
    msg_fmt = _("No fixed IP associated with id %(id)s.")


class FixedIpNotFoundForAddress(FixedIpNotFound):
    msg_fmt = _("Fixed IP not found for address %(address)s.")


class FixedIpNotFoundForInstance(FixedIpNotFound):
    msg_fmt = _("Instance %(instance_uuid)s has zero fixed IPs.")


class FixedIpNotFoundForNetworkHost(FixedIpNotFound):
    msg_fmt = _("Network host %(host)s has zero fixed IPs "
                "in network %(network_id)s.")


class FixedIpNotFoundForSpecificInstance(FixedIpNotFound):
    msg_fmt = _("Instance %(instance_uuid)s doesn't have fixed IP '%(ip)s'.")


class FixedIpNotFoundForNetwork(FixedIpNotFound):
    msg_fmt = _("Fixed IP address (%(address)s) does not exist in "
                "network (%(network_uuid)s).")


class FixedIpAssociateFailed(NovaException):
    msg_fmt = _("Fixed IP associate failed for network: %(net)s.")


class FixedIpAlreadyInUse(NovaException):
    msg_fmt = _("Fixed IP address %(address)s is already in use on instance "
                "%(instance_uuid)s.")


class FixedIpAssociatedWithMultipleInstances(NovaException):
    msg_fmt = _("More than one instance is associated with fixed IP address "
                "'%(address)s'.")


class FixedIpInvalid(Invalid):
    msg_fmt = _("Fixed IP address %(address)s is invalid.")


class FixedIpInvalidOnHost(Invalid):
    msg_fmt = _("The fixed IP associated with port %(port_id)s is not "
                "compatible with the host.")


class NoMoreFixedIps(NovaException):
    msg_fmt = _("No fixed IP addresses available for network: %(net)s")


class NoFixedIpsDefined(NotFound):
    msg_fmt = _("Zero fixed IPs could be found.")


class FloatingIpExists(NovaException):
    msg_fmt = _("Floating IP %(address)s already exists.")


class FloatingIpNotFound(NotFound):
    msg_fmt = _("Floating IP not found for ID %(id)s.")


class FloatingIpDNSExists(Invalid):
    msg_fmt = _("The DNS entry %(name)s already exists in domain %(domain)s.")


class FloatingIpNotFoundForAddress(FloatingIpNotFound):
    msg_fmt = _("Floating IP not found for address %(address)s.")


class FloatingIpNotFoundForHost(FloatingIpNotFound):
    msg_fmt = _("Floating IP not found for host %(host)s.")


class FloatingIpMultipleFoundForAddress(NovaException):
    msg_fmt = _("Multiple floating IPs are found for address %(address)s.")


class FloatingIpPoolNotFound(NotFound):
    msg_fmt = _("Floating IP pool not found.")
    safe = True


class NoMoreFloatingIps(FloatingIpNotFound):
    msg_fmt = _("Zero floating IPs available.")
    safe = True


class FloatingIpAssociated(NovaException):
    msg_fmt = _("Floating IP %(address)s is associated.")


class FloatingIpNotAssociated(NovaException):
    msg_fmt = _("Floating IP %(address)s is not associated.")


class NoFloatingIpsDefined(NotFound):
    msg_fmt = _("Zero floating IPs exist.")


class NoFloatingIpInterface(NotFound):
    msg_fmt = _("Interface %(interface)s not found.")


class FloatingIpAllocateFailed(NovaException):
    msg_fmt = _("Floating IP allocate failed.")


class FloatingIpAssociateFailed(NovaException):
    msg_fmt = _("Floating IP %(address)s association has failed.")


class FloatingIpBadRequest(Invalid):
    msg_fmt = _("The floating IP request failed with a BadRequest")


class CannotDisassociateAutoAssignedFloatingIP(NovaException):
    msg_fmt = _("Cannot disassociate auto assigned floating IP")


class KeypairNotFound(NotFound):
    msg_fmt = _("Keypair %(name)s not found for user %(user_id)s")


class ServiceNotFound(NotFound):
    msg_fmt = _("Service %(service_id)s could not be found.")


class ConfGroupForServiceTypeNotFound(ServiceNotFound):
    msg_fmt = _("No conf group name could be found for service type "
                "%(stype)s.")


class ServiceBinaryExists(NovaException):
    msg_fmt = _("Service with host %(host)s binary %(binary)s exists.")


class ServiceTopicExists(NovaException):
    msg_fmt = _("Service with host %(host)s topic %(topic)s exists.")


class HostNotFound(NotFound):
    msg_fmt = _("Host %(host)s could not be found.")


class ComputeHostNotFound(HostNotFound):
    msg_fmt = _("Compute host %(host)s could not be found.")


class HostBinaryNotFound(NotFound):
    msg_fmt = _("Could not find binary %(binary)s on host %(host)s.")


class InvalidReservationExpiration(Invalid):
    msg_fmt = _("Invalid reservation expiration %(expire)s.")


class InvalidQuotaValue(Invalid):
    msg_fmt = _("Change would make usage less than 0 for the following "
                "resources: %(unders)s")


class InvalidQuotaMethodUsage(Invalid):
    msg_fmt = _("Wrong quota method %(method)s used on resource %(res)s")


class QuotaNotFound(NotFound):
    msg_fmt = _("Quota could not be found")


class QuotaExists(NovaException):
    msg_fmt = _("Quota exists for project %(project_id)s, "
                "resource %(resource)s")


class QuotaResourceUnknown(QuotaNotFound):
    msg_fmt = _("Unknown quota resources %(unknown)s.")


class ProjectUserQuotaNotFound(QuotaNotFound):
    msg_fmt = _("Quota for user %(user_id)s in project %(project_id)s "
                "could not be found.")


class ProjectQuotaNotFound(QuotaNotFound):
    msg_fmt = _("Quota for project %(project_id)s could not be found.")


class QuotaClassNotFound(QuotaNotFound):
    msg_fmt = _("Quota class %(class_name)s could not be found.")


class QuotaClassExists(NovaException):
    msg_fmt = _("Quota class %(class_name)s exists for resource %(resource)s")


class QuotaUsageNotFound(QuotaNotFound):
    msg_fmt = _("Quota usage for project %(project_id)s could not be found.")


class QuotaUsageRefreshNotAllowed(Invalid):
    msg_fmt = _("Quota usage refresh of resource %(resource)s for project "
                "%(project_id)s, user %(user_id)s, is not allowed. "
                "The allowed resources are %(syncable)s.")


class ReservationNotFound(QuotaNotFound):
    msg_fmt = _("Quota reservation %(uuid)s could not be found.")


class OverQuota(NovaException):
    msg_fmt = _("Quota exceeded for resources: %(overs)s")


class SecurityGroupNotFound(NotFound):
    msg_fmt = _("Security group %(security_group_id)s not found.")


class SecurityGroupNotFoundForProject(SecurityGroupNotFound):
    msg_fmt = _("Security group %(security_group_id)s not found "
                "for project %(project_id)s.")


class SecurityGroupNotFoundForRule(SecurityGroupNotFound):
    msg_fmt = _("Security group with rule %(rule_id)s not found.")


class SecurityGroupExists(Invalid):
    msg_fmt = _("Security group %(security_group_name)s already exists "
                "for project %(project_id)s.")


class SecurityGroupExistsForInstance(Invalid):
    msg_fmt = _("Security group %(security_group_id)s is already associated"
                " with the instance %(instance_id)s")


class SecurityGroupNotExistsForInstance(Invalid):
    msg_fmt = _("Security group %(security_group_id)s is not associated with"
                " the instance %(instance_id)s")


class SecurityGroupDefaultRuleNotFound(Invalid):
    msg_fmt = _("Security group default rule (%rule_id)s not found.")


class SecurityGroupCannotBeApplied(Invalid):
    msg_fmt = _("Network requires port_security_enabled and subnet associated"
                " in order to apply security groups.")


class NoUniqueMatch(NovaException):
    msg_fmt = _("No Unique Match Found.")
    code = 409


class NoActiveMigrationForInstance(NotFound):
    msg_fmt = _("Active live migration for instance %(instance_id)s not found")


class MigrationNotFound(NotFound):
    msg_fmt = _("Migration %(migration_id)s could not be found.")


class MigrationNotFoundByStatus(MigrationNotFound):
    msg_fmt = _("Migration not found for instance %(instance_id)s "
                "with status %(status)s.")


class MigrationNotFoundForInstance(MigrationNotFound):
    msg_fmt = _("Migration %(migration_id)s not found for instance "
                "%(instance_id)s")


class InvalidMigrationState(Invalid):
    msg_fmt = _("Migration %(migration_id)s state of instance "
                "%(instance_uuid)s is %(state)s. Cannot %(method)s while the "
                "migration is in this state.")


class AbortQueuedLiveMigrationNotYetSupported(NovaException):
    msg_fmt = _("Aborting live migration %(migration_id)s with status "
                "%(status)s is not yet supported for this instance.")
    code = 409


class ConsoleLogOutputException(NovaException):
    msg_fmt = _("Console log output could not be retrieved for instance "
                "%(instance_id)s. Reason: %(reason)s")


class ConsolePoolExists(NovaException):
    msg_fmt = _("Console pool with host %(host)s, console_type "
                "%(console_type)s and compute_host %(compute_host)s "
                "already exists.")


class ConsolePoolNotFoundForHostType(NotFound):
    msg_fmt = _("Console pool of type %(console_type)s "
                "for compute host %(compute_host)s "
                "on proxy host %(host)s not found.")


class ConsoleNotFound(NotFound):
    msg_fmt = _("Console %(console_id)s could not be found.")


class ConsoleNotFoundForInstance(ConsoleNotFound):
    msg_fmt = _("Console for instance %(instance_uuid)s could not be found.")


class ConsoleNotAvailable(NotFound):
    msg_fmt = _("Guest does not have a console available.")


class ConsoleNotFoundInPoolForInstance(ConsoleNotFound):
    msg_fmt = _("Console for instance %(instance_uuid)s "
                "in pool %(pool_id)s could not be found.")


class ConsoleTypeInvalid(Invalid):
    msg_fmt = _("Invalid console type %(console_type)s")


class ConsoleTypeUnavailable(Invalid):
    msg_fmt = _("Unavailable console type %(console_type)s.")


class ConsolePortRangeExhausted(NovaException):
    msg_fmt = _("The console port range %(min_port)d-%(max_port)d is "
                "exhausted.")


class FlavorNotFound(NotFound):
    msg_fmt = _("Flavor %(flavor_id)s could not be found.")


class FlavorNotFoundByName(FlavorNotFound):
    msg_fmt = _("Flavor with name %(flavor_name)s could not be found.")


class FlavorAccessNotFound(NotFound):
    msg_fmt = _("Flavor access not found for %(flavor_id)s / "
                "%(project_id)s combination.")


class FlavorExtraSpecUpdateCreateFailed(NovaException):
    msg_fmt = _("Flavor %(id)s extra spec cannot be updated or created "
                "after %(retries)d retries.")


class CellTimeout(NotFound):
    msg_fmt = _("Timeout waiting for response from cell")


class SchedulerHostFilterNotFound(NotFound):
    msg_fmt = _("Scheduler Host Filter %(filter_name)s could not be found.")


class FlavorExtraSpecsNotFound(NotFound):
    msg_fmt = _("Flavor %(flavor_id)s has no extra specs with "
                "key %(extra_specs_key)s.")


class ComputeHostMetricNotFound(NotFound):
    msg_fmt = _("Metric %(name)s could not be found on the compute "
                "host node %(host)s.%(node)s.")


class FileNotFound(NotFound):
    msg_fmt = _("File %(file_path)s could not be found.")


class SwitchNotFoundForNetworkAdapter(NotFound):
    msg_fmt = _("Virtual switch associated with the "
                "network adapter %(adapter)s not found.")


class NetworkAdapterNotFound(NotFound):
    msg_fmt = _("Network adapter %(adapter)s could not be found.")


class ClassNotFound(NotFound):
    msg_fmt = _("Class %(class_name)s could not be found: %(exception)s")


class InstanceTagNotFound(NotFound):
    msg_fmt = _("Instance %(instance_id)s has no tag '%(tag)s'")


class KeyPairExists(NovaException):
    msg_fmt = _("Key pair '%(key_name)s' already exists.")


class InstanceExists(NovaException):
    msg_fmt = _("Instance %(name)s already exists.")


class FlavorExists(NovaException):
    msg_fmt = _("Flavor with name %(name)s already exists.")


class FlavorIdExists(NovaException):
    msg_fmt = _("Flavor with ID %(flavor_id)s already exists.")


class FlavorAccessExists(NovaException):
    msg_fmt = _("Flavor access already exists for flavor %(flavor_id)s "
                "and project %(project_id)s combination.")


class InvalidSharedStorage(NovaException):
    msg_fmt = _("%(path)s is not on shared storage: %(reason)s")


class InvalidLocalStorage(NovaException):
    msg_fmt = _("%(path)s is not on local storage: %(reason)s")


class StorageError(NovaException):
    msg_fmt = _("Storage error: %(reason)s")


class MigrationError(NovaException):
    msg_fmt = _("Migration error: %(reason)s")


class MigrationPreCheckError(MigrationError):
    msg_fmt = _("Migration pre-check error: %(reason)s")


class MigrationSchedulerRPCError(MigrationError):
    msg_fmt = _("Migration select destinations error: %(reason)s")


class RPCPinnedToOldVersion(NovaException):
    msg_fmt = _("RPC is pinned to old version")


class MalformedRequestBody(NovaException):
    msg_fmt = _("Malformed message body: %(reason)s")


# NOTE(johannes): NotFound should only be used when a 404 error is
# appropriate to be returned
class ConfigNotFound(NovaException):
    msg_fmt = _("Could not find config at %(path)s")


class PasteAppNotFound(NovaException):
    msg_fmt = _("Could not load paste app '%(name)s' from %(path)s")


class CannotResizeToSameFlavor(NovaException):
    msg_fmt = _("When resizing, instances must change flavor!")


class ResizeError(NovaException):
    msg_fmt = _("Resize error: %(reason)s")


class CannotResizeDisk(NovaException):
    msg_fmt = _("Server disk was unable to be resized because: %(reason)s")


class FlavorMemoryTooSmall(NovaException):
    msg_fmt = _("Flavor's memory is too small for requested image.")


class FlavorDiskTooSmall(NovaException):
    msg_fmt = _("The created instance's disk would be too small.")


class FlavorDiskSmallerThanImage(FlavorDiskTooSmall):
    msg_fmt = _("Flavor's disk is too small for requested image. Flavor disk "
                "is %(flavor_size)i bytes, image is %(image_size)i bytes.")


class FlavorDiskSmallerThanMinDisk(FlavorDiskTooSmall):
    msg_fmt = _("Flavor's disk is smaller than the minimum size specified in "
                "image metadata. Flavor disk is %(flavor_size)i bytes, "
                "minimum size is %(image_min_disk)i bytes.")


class VolumeSmallerThanMinDisk(FlavorDiskTooSmall):
    msg_fmt = _("Volume is smaller than the minimum size specified in image "
                "metadata. Volume size is %(volume_size)i bytes, minimum "
                "size is %(image_min_disk)i bytes.")


class BootFromVolumeRequiredForZeroDiskFlavor(Forbidden):
    msg_fmt = _("Only volume-backed servers are allowed for flavors with "
                "zero disk.")


class InsufficientFreeMemory(NovaException):
    msg_fmt = _("Insufficient free memory on compute node to start %(uuid)s.")


class NoValidHost(NovaException):
    msg_fmt = _("No valid host was found. %(reason)s")


class RequestFilterFailed(NovaException):
    msg_fmt = _("Scheduling failed: %(reason)s")


class MaxRetriesExceeded(NoValidHost):
    msg_fmt = _("Exceeded maximum number of retries. %(reason)s")


class QuotaError(NovaException):
    msg_fmt = _("Quota exceeded: code=%(code)s")
    # NOTE(cyeoh): 413 should only be used for the ec2 API
    # The error status code for out of quota for the nova api should be
    # 403 Forbidden.
    code = 413
    safe = True


class TooManyInstances(QuotaError):
    msg_fmt = _("Quota exceeded for %(overs)s: Requested %(req)s,"
                " but already used %(used)s of %(allowed)s %(overs)s")


class FloatingIpLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of floating IPs exceeded")


class FixedIpLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of fixed IPs exceeded")


class MetadataLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of metadata items exceeds %(allowed)d")


class OnsetFileLimitExceeded(QuotaError):
    msg_fmt = _("Personality file limit exceeded")


class OnsetFilePathLimitExceeded(OnsetFileLimitExceeded):
    msg_fmt = _("Personality file path exceeds maximum %(allowed)s")


class OnsetFileContentLimitExceeded(OnsetFileLimitExceeded):
    msg_fmt = _("Personality file content exceeds maximum %(allowed)s")


class KeypairLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of key pairs exceeded")


class SecurityGroupLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of security groups or rules exceeded")


class PortLimitExceeded(QuotaError):
    msg_fmt = _("Maximum number of ports exceeded")


class AggregateError(NovaException):
    msg_fmt = _("Aggregate %(aggregate_id)s: action '%(action)s' "
                "caused an error: %(reason)s.")


class AggregateNotFound(NotFound):
    msg_fmt = _("Aggregate %(aggregate_id)s could not be found.")


class AggregateNameExists(NovaException):
    msg_fmt = _("Aggregate %(aggregate_name)s already exists.")


class AggregateHostNotFound(NotFound):
    msg_fmt = _("Aggregate %(aggregate_id)s has no host %(host)s.")


class AggregateMetadataNotFound(NotFound):
    msg_fmt = _("Aggregate %(aggregate_id)s has no metadata with "
                "key %(metadata_key)s.")


class AggregateHostExists(NovaException):
    msg_fmt = _("Aggregate %(aggregate_id)s already has host %(host)s.")


class InstancePasswordSetFailed(NovaException):
    msg_fmt = _("Failed to set admin password on %(instance)s "
                "because %(reason)s")
    safe = True


class InstanceNotFound(NotFound):
    msg_fmt = _("Instance %(instance_id)s could not be found.")


class InstanceInfoCacheNotFound(NotFound):
    msg_fmt = _("Info cache for instance %(instance_uuid)s could not be "
                "found.")


class MarkerNotFound(NotFound):
    msg_fmt = _("Marker %(marker)s could not be found.")


class CouldNotFetchImage(NovaException):
    msg_fmt = _("Could not fetch image %(image_id)s")


class CouldNotUploadImage(NovaException):
    msg_fmt = _("Could not upload image %(image_id)s")


class TaskAlreadyRunning(NovaException):
    msg_fmt = _("Task %(task_name)s is already running on host %(host)s")


class TaskNotRunning(NovaException):
    msg_fmt = _("Task %(task_name)s is not running on host %(host)s")


class InstanceIsLocked(InstanceInvalidState):
    msg_fmt = _("Instance %(instance_uuid)s is locked")


class ConfigDriveInvalidValue(Invalid):
    msg_fmt = _("Invalid value for Config Drive option: %(option)s")


class ConfigDriveUnsupportedFormat(Invalid):
    msg_fmt = _("Config drive format '%(format)s' is not supported.")


class ConfigDriveMountFailed(NovaException):
    msg_fmt = _("Could not mount vfat config drive. %(operation)s failed. "
                "Error: %(error)s")


class ConfigDriveUnknownFormat(NovaException):
    msg_fmt = _("Unknown config drive format %(format)s. Select one of "
                "iso9660 or vfat.")


class ConfigDriveNotFound(NotFound):
    msg_fmt = _("Instance %(instance_uuid)s requires config drive, but it "
                "does not exist.")


class InterfaceAttachFailed(NovaException):
    msg_fmt = _("Failed to attach network adapter device to "
                "%(instance_uuid)s")


class InterfaceAttachFailedNoNetwork(Invalid):
    msg_fmt = _("No specific network was requested and none are available "
                "for project '%(project_id)s'.")


class InterfaceDetachFailed(Invalid):
    msg_fmt = _("Failed to detach network adapter device from "
                "%(instance_uuid)s")


class InstanceUserDataMalformed(NovaException):
    msg_fmt = _("User data needs to be valid base 64.")


class InstanceUpdateConflict(NovaException):
    msg_fmt = _("Conflict updating instance %(instance_uuid)s. "
                "Expected: %(expected)s. Actual: %(actual)s")


class UnknownInstanceUpdateConflict(InstanceUpdateConflict):
    msg_fmt = _("Conflict updating instance %(instance_uuid)s, but we were "
                "unable to determine the cause")


class UnexpectedTaskStateError(InstanceUpdateConflict):
    pass


class UnexpectedDeletingTaskStateError(UnexpectedTaskStateError):
    pass


class InstanceActionNotFound(NovaException):
    msg_fmt = _("Action for request_id %(request_id)s on instance"
                " %(instance_uuid)s not found")


class InstanceActionEventNotFound(NovaException):
    msg_fmt = _("Event %(event)s not found for action id %(action_id)s")


class CryptoCAFileNotFound(FileNotFound):
    msg_fmt = _("The CA file for %(project)s could not be found")


class CryptoCRLFileNotFound(FileNotFound):
    msg_fmt = _("The CRL file for %(project)s could not be found")


class InstanceEvacuateNotSupported(Invalid):
    msg_fmt = _('Instance evacuate is not supported.')


class DBNotAllowed(NovaException):
    msg_fmt = _('%(binary)s attempted direct database access which is '
                'not allowed by policy')


class UnsupportedVirtType(Invalid):
    msg_fmt = _("Virtualization type '%(virt)s' is not supported by "
                "this compute driver")


class UnsupportedHardware(Invalid):
    msg_fmt = _("Requested hardware '%(model)s' is not supported by "
                "the '%(virt)s' virt driver")


class Base64Exception(NovaException):
    msg_fmt = _("Invalid Base 64 data for file %(path)s")


class BuildAbortException(NovaException):
    msg_fmt = _("Build of instance %(instance_uuid)s aborted: %(reason)s")


class RescheduledException(NovaException):
    msg_fmt = _("Build of instance %(instance_uuid)s was re-scheduled: "
                "%(reason)s")


class ShadowTableExists(NovaException):
    msg_fmt = _("Shadow table with name %(name)s already exists.")


class InstanceFaultRollback(NovaException):
    def __init__(self, inner_exception=None):
        message = _("Instance rollback performed due to: %s")
        self.inner_exception = inner_exception
        super(InstanceFaultRollback, self).__init__(message % inner_exception)


class OrphanedObjectError(NovaException):
    msg_fmt = _('Cannot call %(method)s on orphaned %(objtype)s object')


class ObjectActionError(NovaException):
    msg_fmt = _('Object action %(action)s failed because: %(reason)s')


class AgentError(NovaException):
    msg_fmt = _('Error during following call to agent: %(method)s')


class AgentTimeout(AgentError):
    msg_fmt = _('Unable to contact guest agent. '
                'The following call timed out: %(method)s')


class AgentNotImplemented(AgentError):
    msg_fmt = _('Agent does not support the call: %(method)s')


class InstanceGroupNotFound(NotFound):
    msg_fmt = _("Instance group %(group_uuid)s could not be found.")


class InstanceGroupIdExists(NovaException):
    msg_fmt = _("Instance group %(group_uuid)s already exists.")


class InstanceGroupMemberNotFound(NotFound):
    msg_fmt = _("Instance group %(group_uuid)s has no member with "
                "id %(instance_id)s.")


class InstanceGroupSaveException(NovaException):
    msg_fmt = _("%(field)s should not be part of the updates.")


class ResourceMonitorError(NovaException):
    msg_fmt = _("Error when creating resource monitor: %(monitor)s")


class PciDeviceWrongAddressFormat(NovaException):
    msg_fmt = _("The PCI address %(address)s has an incorrect format.")


class PciDeviceInvalidDeviceName(NovaException):
    msg_fmt = _("Invalid PCI Whitelist: "
                "The PCI whitelist can specify devname or address,"
                " but not both")


class PciDeviceNotFoundById(NotFound):
    msg_fmt = _("PCI device %(id)s not found")


class PciDeviceNotFound(NotFound):
    msg_fmt = _("PCI Device %(node_id)s:%(address)s not found.")


class PciDeviceInvalidStatus(Invalid):
    msg_fmt = _(
        "PCI device %(compute_node_id)s:%(address)s is %(status)s "
        "instead of %(hopestatus)s")


class PciDeviceVFInvalidStatus(Invalid):
    msg_fmt = _(
        "Not all Virtual Functions of PF %(compute_node_id)s:%(address)s "
        "are free.")


class PciDevicePFInvalidStatus(Invalid):
    msg_fmt = _(
        "Physical Function %(compute_node_id)s:%(address)s, related to VF"
        " %(compute_node_id)s:%(vf_address)s is %(status)s "
        "instead of %(hopestatus)s")


class PciDeviceInvalidOwner(Invalid):
    msg_fmt = _(
        "PCI device %(compute_node_id)s:%(address)s is owned by %(owner)s "
        "instead of %(hopeowner)s")


class PciDeviceRequestFailed(NovaException):
    msg_fmt = _(
        "PCI device request %(requests)s failed")


class PciDevicePoolEmpty(NovaException):
    msg_fmt = _(
        "Attempt to consume PCI device %(compute_node_id)s:%(address)s "
        "from empty pool")


class PciInvalidAlias(Invalid):
    msg_fmt = _("Invalid PCI alias definition: %(reason)s")


class PciRequestAliasNotDefined(NovaException):
    msg_fmt = _("PCI alias %(alias)s is not defined")


class PciConfigInvalidWhitelist(Invalid):
    msg_fmt = _("Invalid PCI devices Whitelist config: %(reason)s")


class PciRequestFromVIFNotFound(NotFound):
    msg_fmt = _("Failed to locate PCI request associated with the given VIF "
                "PCI address: %(pci_slot)s on compute node: %(node_id)s")


# Cannot be templated, msg needs to be constructed when raised.
class InternalError(NovaException):
    """Generic hypervisor errors.

    Consider subclassing this to provide more specific exceptions.
    """
    msg_fmt = "%(err)s"


class PciDevicePrepareFailed(NovaException):
    msg_fmt = _("Failed to prepare PCI device %(id)s for instance "
                "%(instance_uuid)s: %(reason)s")


class PciDeviceDetachFailed(NovaException):
    msg_fmt = _("Failed to detach PCI device %(dev)s: %(reason)s")


class PciDeviceUnsupportedHypervisor(NovaException):
    msg_fmt = _("%(type)s hypervisor does not support PCI devices")


class KeyManagerError(NovaException):
    msg_fmt = _("Key manager error: %(reason)s")


class VolumesNotRemoved(Invalid):
    msg_fmt = _("Failed to remove volume(s): (%(reason)s)")


class VolumeRebaseFailed(NovaException):
    msg_fmt = _("Volume rebase failed: %(reason)s")


class InvalidVideoMode(Invalid):
    msg_fmt = _("Provided video model (%(model)s) is not supported.")


class RngDeviceNotExist(Invalid):
    msg_fmt = _("The provided RNG device path: (%(path)s) is not "
                "present on the host.")


class RequestedVRamTooHigh(NovaException):
    msg_fmt = _("The requested amount of video memory %(req_vram)d is higher "
                "than the maximum allowed by flavor %(max_vram)d.")


class SecurityProxyNegotiationFailed(NovaException):
    msg_fmt = _("Failed to negotiate security type with server: %(reason)s")


class RFBAuthHandshakeFailed(NovaException):
    msg_fmt = _("Failed to complete auth handshake: %(reason)s")


class RFBAuthNoAvailableScheme(NovaException):
    msg_fmt = _("No matching auth scheme: allowed types: '%(allowed_types)s', "
                "desired types: '%(desired_types)s'")


class InvalidWatchdogAction(Invalid):
    msg_fmt = _("Provided watchdog action (%(action)s) is not supported.")


class LiveMigrationNotSubmitted(NovaException):
    msg_fmt = _("Failed to submit live migration %(migration_uuid)s for "
                "instance %(instance_uuid)s for processing.")


class SelectionObjectsWithOldRPCVersionNotSupported(NovaException):
    msg_fmt = _("Requests for Selection objects with alternates are not "
                "supported in select_destinations() before RPC version 4.5; "
                "version %(version)s requested.")


class LiveMigrationURINotAvailable(NovaException):
    msg_fmt = _('No live migration URI configured and no default available '
                'for "%(virt_type)s" hypervisor virtualization type.')


class UnshelveException(NovaException):
    msg_fmt = _("Error during unshelve instance %(instance_id)s: %(reason)s")


class MismatchVolumeAZException(Invalid):
    msg_fmt = _("The availability zone between the server and its attached "
                "volumes do not match: %(reason)s.")
    code = 409


class UnshelveInstanceInvalidState(InstanceInvalidState):
    msg_fmt = _('Specifying an availability zone when unshelving server '
                '%(instance_uuid)s with status "%(state)s" is not supported. '
                'The server status must be SHELVED_OFFLOADED.')
    code = 409


class ImageVCPULimitsRangeExceeded(Invalid):
    msg_fmt = _('Image vCPU topology limits (sockets=%(image_sockets)d, '
                'cores=%(image_cores)d, threads=%(image_threads)d) exceeds '
                'the limits of the flavor (sockets=%(flavor_sockets)d, '
                'cores=%(flavor_cores)d, threads=%(flavor_threads)d)')


class ImageVCPUTopologyRangeExceeded(Invalid):
    msg_fmt = _('Image vCPU topology (sockets=%(image_sockets)d, '
                'cores=%(image_cores)d, threads=%(image_threads)d) exceeds '
                'the limits of the flavor or image (sockets=%(max_sockets)d, '
                'cores=%(max_cores)d, threads=%(max_threads)d)')


class ImageVCPULimitsRangeImpossible(Invalid):
    msg_fmt = _("Requested vCPU limits %(sockets)d:%(cores)d:%(threads)d "
                "are impossible to satisfy for vcpus count %(vcpus)d")


class InvalidArchitectureName(Invalid):
    msg_fmt = _("Architecture name '%(arch)s' is not recognised")


class ImageNUMATopologyIncomplete(Invalid):
    msg_fmt = _("CPU and memory allocation must be provided for all "
                "NUMA nodes")


class ImageNUMATopologyForbidden(Forbidden):
    msg_fmt = _("Image property '%(name)s' is not permitted to override "
                "NUMA configuration set against the flavor")


class ImageNUMATopologyRebuildConflict(Invalid):
    msg_fmt = _(
        "An instance's NUMA topology cannot be changed as part of a rebuild. "
        "The image provided is invalid for this instance.")


class ImageNUMATopologyAsymmetric(Invalid):
    msg_fmt = _("Instance CPUs and/or memory cannot be evenly distributed "
                "across instance NUMA nodes. Explicit assignment of CPUs "
                "and memory to nodes is required")


class ImageNUMATopologyCPUOutOfRange(Invalid):
    msg_fmt = _("CPU number %(cpunum)d is larger than max %(cpumax)d")


class ImageNUMATopologyCPUDuplicates(Invalid):
    msg_fmt = _("CPU number %(cpunum)d is assigned to two nodes")


class ImageNUMATopologyCPUsUnassigned(Invalid):
    msg_fmt = _("CPU number %(cpuset)s is not assigned to any node")


class ImageNUMATopologyMemoryOutOfRange(Invalid):
    msg_fmt = _("%(memsize)d MB of memory assigned, but expected "
                "%(memtotal)d MB")


class InvalidHostname(Invalid):
    msg_fmt = _("Invalid characters in hostname '%(hostname)s'")


class NumaTopologyNotFound(NotFound):
    msg_fmt = _("Instance %(instance_uuid)s does not specify a NUMA topology")


class MigrationContextNotFound(NotFound):
    msg_fmt = _("Instance %(instance_uuid)s does not specify a migration "
                "context.")


class SocketPortRangeExhaustedException(NovaException):
    msg_fmt = _("Not able to acquire a free port for %(host)s")


class SocketPortInUseException(NovaException):
    msg_fmt = _("Not able to bind %(host)s:%(port)d, %(error)s")


class ImageSerialPortNumberInvalid(Invalid):
    msg_fmt = _("Number of serial ports specified in flavor is invalid: "
                "expected an integer, got '%(num_ports)s'")


class ImageSerialPortNumberExceedFlavorValue(Invalid):
    msg_fmt = _("Forbidden to exceed flavor value of number of serial "
                "ports passed in image meta.")


class SerialPortNumberLimitExceeded(Invalid):
    msg_fmt = _("Maximum number of serial port exceeds %(allowed)d "
                "for %(virt_type)s")


class InvalidImageConfigDrive(Invalid):
    msg_fmt = _("Image's config drive option '%(config_drive)s' is invalid")


class InvalidHypervisorVirtType(Invalid):
    msg_fmt = _("Hypervisor virtualization type '%(hv_type)s' is not "
                "recognised")


class InvalidMachineType(Invalid):
    msg_fmt = _("Machine type '%(mtype)s' is not compatible with image "
                "%(image_name)s (%(image_id)s): %(reason)s")


class InvalidVirtualMachineMode(Invalid):
    msg_fmt = _("Virtual machine mode '%(vmmode)s' is not recognised")


class InvalidToken(Invalid):
    msg_fmt = _("The token '%(token)s' is invalid or has expired")


class TokenInUse(Invalid):
    msg_fmt = _("The generated token is invalid")


class InvalidConnectionInfo(Invalid):
    msg_fmt = _("Invalid Connection Info")


class InstanceQuiesceNotSupported(Invalid):
    msg_fmt = _('Quiescing is not supported in instance %(instance_id)s')


class InstanceAgentNotEnabled(Invalid):
    msg_fmt = _('Guest agent is not enabled for the instance')
    safe = True


class QemuGuestAgentNotEnabled(InstanceAgentNotEnabled):
    msg_fmt = _('QEMU guest agent is not enabled')


class SetAdminPasswdNotSupported(Invalid):
    msg_fmt = _('Set admin password is not supported')
    safe = True


class MemoryPageSizeInvalid(Invalid):
    msg_fmt = _("Invalid memory page size '%(pagesize)s'")


class MemoryPageSizeForbidden(Invalid):
    msg_fmt = _("Page size %(pagesize)s forbidden against '%(against)s'")


class MemoryPageSizeNotSupported(Invalid):
    msg_fmt = _("Page size %(pagesize)s is not supported by the host.")


class CPUPinningNotSupported(Invalid):
    msg_fmt = _("CPU pinning is not supported by the host: "
                "%(reason)s")


class CPUPinningInvalid(Invalid):
    msg_fmt = _("CPU set to pin %(requested)s must be a subset of "
                "free CPU set %(available)s")


class CPUUnpinningInvalid(Invalid):
    msg_fmt = _("CPU set to unpin %(requested)s must be a subset of "
                "pinned CPU set %(available)s")


class CPUPinningUnknown(Invalid):
    msg_fmt = _("CPU set to pin %(requested)s must be a subset of "
                "known CPU set %(available)s")


class CPUUnpinningUnknown(Invalid):
    msg_fmt = _("CPU set to unpin %(requested)s must be a subset of "
                "known CPU set %(available)s")


class ImageCPUPinningForbidden(Forbidden):
    msg_fmt = _("Image property 'hw_cpu_policy' is not permitted to override "
                "CPU pinning policy set against the flavor")


class ImageCPUThreadPolicyForbidden(Forbidden):
    msg_fmt = _("Image property 'hw_cpu_thread_policy' is not permitted to "
                "override CPU thread pinning policy set against the flavor")


class ImagePMUConflict(Forbidden):
    msg_fmt = _("Image property 'hw_pmu' is not permitted to "
                "override the PMU policy set in the flavor")


class UnsupportedPolicyException(Invalid):
    msg_fmt = _("ServerGroup policy is not supported: %(reason)s")


class CellMappingNotFound(NotFound):
    msg_fmt = _("Cell %(uuid)s has no mapping.")


class NUMATopologyUnsupported(Invalid):
    msg_fmt = _("Host does not support guests with NUMA topology set")


class MemoryPagesUnsupported(Invalid):
    msg_fmt = _("Host does not support guests with custom memory page sizes")


class InvalidImageFormat(Invalid):
    msg_fmt = _("Invalid image format '%(format)s'")


class UnsupportedImageModel(Invalid):
    msg_fmt = _("Image model '%(image)s' is not supported")


class HostMappingNotFound(Invalid):
    msg_fmt = _("Host '%(name)s' is not mapped to any cell")


class HostMappingExists(Invalid):
    msg_fmt = _("Host '%(name)s' mapping already exists")


class RealtimeConfigurationInvalid(Invalid):
    msg_fmt = _("Cannot set realtime policy in a non dedicated "
                "cpu pinning policy")


class CPUThreadPolicyConfigurationInvalid(Invalid):
    msg_fmt = _("Cannot set cpu thread pinning policy in a non dedicated "
                "cpu pinning policy")


class RequestSpecNotFound(NotFound):
    msg_fmt = _("RequestSpec not found for instance %(instance_uuid)s")


class UEFINotSupported(Invalid):
    msg_fmt = _("UEFI is not supported")


class TriggerCrashDumpNotSupported(Invalid):
    msg_fmt = _("Triggering crash dump is not supported")


class UnsupportedHostCPUControlPolicy(Invalid):
    msg_fmt = _("Requested CPU control policy not supported by host")


class LibguestfsCannotReadKernel(Invalid):
    msg_fmt = _("Libguestfs does not have permission to read host kernel.")


class RealtimeMaskNotFoundOrInvalid(Invalid):
    msg_fmt = _("Realtime policy needs vCPU(s) mask configured with at least "
                "1 RT vCPU and 1 ordinary vCPU. See hw:cpu_realtime_mask "
                "or hw_cpu_realtime_mask")


class OsInfoNotFound(NotFound):
    msg_fmt = _("No configuration information found for operating system "
                "%(os_name)s")


class BuildRequestNotFound(NotFound):
    msg_fmt = _("BuildRequest not found for instance %(uuid)s")


class AttachInterfaceNotSupported(Invalid):
    msg_fmt = _("Attaching interfaces is not supported for "
                "instance %(instance_uuid)s.")


class AttachInterfaceWithQoSPolicyNotSupported(AttachInterfaceNotSupported):
    msg_fmt = _("Attaching interfaces with QoS policy is not supported for "
                "instance %(instance_uuid)s.")


class NetworksWithQoSPolicyNotSupported(Invalid):
    msg_fmt = _("Using networks with QoS policy is not supported for "
                "instance %(instance_uuid)s. (Network ID is %(network_id)s)")


class CreateWithPortResourceRequestOldVersion(Invalid):
    msg_fmt = _("Creating servers with ports having resource requests, like a "
                "port with a QoS minimum bandwidth policy, is not supported "
                "until microversion 2.72.")


class InvalidReservedMemoryPagesOption(Invalid):
    msg_fmt = _("The format of the option 'reserved_huge_pages' is invalid. "
                "(found '%(conf)s') Please refer to the nova "
                "config-reference.")


# An exception with this name is used on both sides of the placement/
# nova interaction.
class ResourceProviderInUse(NovaException):
    msg_fmt = _("Resource provider has allocations.")


class ResourceProviderRetrievalFailed(NovaException):
    msg_fmt = _("Failed to get resource provider with UUID %(uuid)s")


class ResourceProviderAggregateRetrievalFailed(NovaException):
    msg_fmt = _("Failed to get aggregates for resource provider with UUID"
                " %(uuid)s")


class ResourceProviderTraitRetrievalFailed(NovaException):
    msg_fmt = _("Failed to get traits for resource provider with UUID"
                " %(uuid)s")


class ResourceProviderCreationFailed(NovaException):
    msg_fmt = _("Failed to create resource provider %(name)s")


class ResourceProviderDeletionFailed(NovaException):
    msg_fmt = _("Failed to delete resource provider %(uuid)s")


class ResourceProviderUpdateFailed(NovaException):
    msg_fmt = _("Failed to update resource provider via URL %(url)s: "
                "%(error)s")


class ResourceProviderNotFound(NotFound):
    msg_fmt = _("No such resource provider %(name_or_uuid)s.")


class ResourceProviderSyncFailed(NovaException):
    msg_fmt = _("Failed to synchronize the placement service with resource "
                "provider information supplied by the compute host.")


class PlacementAPIConnectFailure(NovaException):
    msg_fmt = _("Unable to communicate with the Placement API.")


class PlacementAPIConflict(NovaException):
    """Any 409 error from placement APIs should use (a subclass of) this
    exception.
    """
    msg_fmt = _("A conflict was encountered attempting to invoke the "
                "placement API at URL %(url)s: %(error)s")


class ResourceProviderUpdateConflict(PlacementAPIConflict):
    """A 409 caused by generation mismatch from attempting to update an
    existing provider record or its associated data (aggregates, traits, etc.).
    """
    msg_fmt = _("A conflict was encountered attempting to update resource "
                "provider %(uuid)s (generation %(generation)d): %(error)s")


class InvalidResourceClass(Invalid):
    msg_fmt = _("Resource class '%(resource_class)s' invalid.")


class InvalidResourceAmount(Invalid):
    msg_fmt = _("Resource amounts must be integers. Received '%(amount)s'.")


class InvalidInventory(Invalid):
    msg_fmt = _("Inventory for '%(resource_class)s' on "
                "resource provider '%(resource_provider)s' invalid.")


# An exception with this name is used on both sides of the placement/
# nova interaction.
class InventoryInUse(InvalidInventory):
    pass


class UsagesRetrievalFailed(NovaException):
    msg_fmt = _("Failed to retrieve usages for project '%(project_id)s' and "
                "user '%(user_id)s'.")


class UnsupportedPointerModelRequested(Invalid):
    msg_fmt = _("Pointer model '%(model)s' requested is not supported by "
                "host.")


class NotSupportedWithOption(Invalid):
    msg_fmt = _("%(operation)s is not supported in conjunction with the "
                "current %(option)s setting.  Please refer to the nova "
                "config-reference.")


class Unauthorized(NovaException):
    msg_fmt = _("Not authorized.")
    code = 401


class NeutronAdminCredentialConfigurationInvalid(Invalid):
    msg_fmt = _("Networking client is experiencing an unauthorized exception.")


class InvalidEmulatorThreadsPolicy(Invalid):
    msg_fmt = _("CPU emulator threads option requested is invalid, "
                "given: '%(requested)s', available: '%(available)s'.")


class InvalidCPUAllocationPolicy(Invalid):
    msg_fmt = _("CPU policy requested from '%(source)s' is invalid, "
                "given: '%(requested)s', available: '%(available)s'.")


class InvalidCPUThreadAllocationPolicy(Invalid):
    msg_fmt = _("CPU thread policy requested from '%(source)s' is invalid, "
                "given: '%(requested)s', available: '%(available)s'.")


class BadRequirementEmulatorThreadsPolicy(Invalid):
    msg_fmt = _("An isolated CPU emulator threads option requires a dedicated "
                "CPU policy option.")


class InvalidNetworkNUMAAffinity(Invalid):
    msg_fmt = _("Invalid NUMA network affinity configured: %(reason)s")


class PowerVMAPIFailed(NovaException):
    msg_fmt = _("PowerVM API failed to complete for instance=%(inst_name)s.  "
                "%(reason)s")


class TraitRetrievalFailed(NovaException):
    msg_fmt = _("Failed to retrieve traits from the placement API: %(error)s")


class TraitCreationFailed(NovaException):
    msg_fmt = _("Failed to create trait %(name)s: %(error)s")


class CannotMigrateWithTargetHost(NovaException):
    msg_fmt = _("Cannot migrate with target host. Retry without a host "
                "specified.")


class CannotMigrateToSameHost(NovaException):
    msg_fmt = _("Cannot migrate to the host where the server exists.")


class VirtDriverNotReady(NovaException):
    msg_fmt = _("Virt driver is not ready.")


class InvalidPeerList(NovaException):
    msg_fmt = _("Configured nova-compute peer list for the ironic virt "
                "driver is invalid on host %(host)s")


class InstanceDiskMappingFailed(NovaException):
    msg_fmt = _("Failed to map boot disk of instance %(instance_name)s to "
                "the management partition from any Virtual I/O Server.")


class NewMgmtMappingNotFoundException(NovaException):
    msg_fmt = _("Failed to find newly-created mapping of storage element "
                "%(stg_name)s from Virtual I/O Server %(vios_name)s to the "
                "management partition.")


class NoDiskDiscoveryException(NovaException):
    msg_fmt = _("Having scanned SCSI bus %(bus)x on the management partition, "
                "disk with UDID %(udid)s failed to appear after %(polls)d "
                "polls over %(timeout)d seconds.")


class UniqueDiskDiscoveryException(NovaException):
    msg_fmt = _("Expected to find exactly one disk on the management "
                "partition at %(path_pattern)s; found %(count)d.")


class DeviceDeletionException(NovaException):
    msg_fmt = _("Device %(devpath)s is still present on the management "
                "partition after attempting to delete it. Polled %(polls)d "
                "times over %(timeout)d seconds.")


class OptRequiredIfOtherOptValue(NovaException):
    msg_fmt = _("The %(then_opt)s option is required if %(if_opt)s is "
                "specified as '%(if_value)s'.")


class AllocationCreateFailed(NovaException):
    msg_fmt = _('Failed to create allocations for instance %(instance)s '
                'against resource provider %(provider)s.')


class AllocationUpdateFailed(NovaException):
    msg_fmt = _('Failed to update allocations for consumer %(consumer_uuid)s. '
                'Error: %(error)s')


class AllocationMoveFailed(NovaException):
    msg_fmt = _('Failed to move allocations from consumer %(source_consumer)s '
                'to consumer %(target_consumer)s. '
                'Error: %(error)s')


class AllocationDeleteFailed(NovaException):
    msg_fmt = _('Failed to delete allocations for consumer %(consumer_uuid)s. '
                'Error: %(error)s')


class TooManyComputesForHost(NovaException):
    msg_fmt = _('Unexpected number of compute node records '
                '(%(num_computes)d) found for host %(host)s. There should '
                'only be a one-to-one mapping.')


class CertificateValidationFailed(NovaException):
    msg_fmt = _("Image signature certificate validation failed for "
                "certificate: %(cert_uuid)s. %(reason)s")


class InstanceRescueFailure(NovaException):
    msg_fmt = _("Failed to move instance to rescue mode: %(reason)s")


class InstanceUnRescueFailure(NovaException):
    msg_fmt = _("Failed to unrescue instance: %(reason)s")


class IronicAPIVersionNotAvailable(NovaException):
    msg_fmt = _('Ironic API version %(version)s is not available.')


class ZVMDriverException(NovaException):
    msg_fmt = _("ZVM Driver has error: %(error)s")


class ZVMConnectorError(ZVMDriverException):
    msg_fmt = _("zVM Cloud Connector request failed: %(results)s")

    def __init__(self, message=None, **kwargs):
        """Exception for zVM ConnectorClient calls.

        :param results: The object returned from ZVMConnector.send_request.
        """
        super(ZVMConnectorError, self).__init__(message=message, **kwargs)

        results = kwargs.get('results', {})
        self.overallRC = results.get('overallRC')
        self.rc = results.get('rc')
        self.rs = results.get('rs')
        self.errmsg = results.get('errmsg')


class NoResourceClass(NovaException):
    msg_fmt = _("Resource class not found for Ironic node %(node)s.")


class ResourceProviderAllocationRetrievalFailed(NovaException):
    msg_fmt = _("Failed to retrieve allocations for resource provider "
                "%(rp_uuid)s: %(error)s")


class ConsumerAllocationRetrievalFailed(NovaException):
    msg_fmt = _("Failed to retrieve allocations for consumer "
                "%(consumer_uuid)s: %(error)s")


class ReshapeFailed(NovaException):
    msg_fmt = _("Resource provider inventory and allocation data migration "
                "failed: %(error)s")


class ReshapeNeeded(NovaException):
    msg_fmt = _("Virt driver indicates that provider inventories need to be "
                "moved.")


class FlavorImageConflict(NovaException):
    msg_fmt = _("Conflicting values for %(setting)s found in the flavor "
                "(%(flavor_val)s) and the image (%(image_val)s).")


class MissingDomainCapabilityFeatureException(NovaException):
    msg_fmt = _("Guest config could not be built without domain capabilities "
                "including <%(feature)s> feature.")


class HealPortAllocationException(NovaException):
    msg_fmt = _("Healing port allocation failed.")


class MoreThanOneResourceProviderToHealFrom(HealPortAllocationException):
    msg_fmt = _("More than one matching resource provider %(rp_uuids)s is "
                "available for healing the port allocation for port "
                "%(port_id)s for instance %(instance_uuid)s. This script "
                "does not have enough information to select the proper "
                "resource provider from which to heal.")


class NoResourceProviderToHealFrom(HealPortAllocationException):
    msg_fmt = _("No matching resource provider is "
                "available for healing the port allocation for port "
                "%(port_id)s for instance %(instance_uuid)s. There are no "
                "resource providers with matching traits %(traits)s in the "
                "provider tree of the resource provider %(node_uuid)s ."
                "This probably means that the neutron QoS configuration is "
                "wrong. Consult with "
                "https://docs.openstack.org/neutron/latest/admin/"
                "config-qos-min-bw.html for information on how to configure "
                "neutron. If the configuration is fixed the script can be run "
                "again.")


class UnableToQueryPorts(HealPortAllocationException):
    msg_fmt = _("Unable to query ports for instance %(instance_uuid)s: "
                "%(error)s")


class UnableToUpdatePorts(HealPortAllocationException):
    msg_fmt = _("Unable to update ports with allocations that are about to be "
                "created in placement: %(error)s. The healing of the "
                "instance is aborted. It is safe to try to heal the instance "
                "again.")


class UnableToRollbackPortUpdates(HealPortAllocationException):
    msg_fmt = _("Failed to update neutron ports with allocation keys and the "
                "automatic rollback of the previously successful port updates "
                "also failed: %(error)s. Make sure that the "
                "binding:profile.allocation key of the affected ports "
                "%(port_uuids)s are manually cleaned in neutron according to "
                "document https://docs.openstack.org/nova/latest/cli/"
                "nova-manage.html#placement. If you re-run the script without "
                "the manual fix then the missing allocation for these ports "
                "will not be healed in placement.")


class AssignedResourceNotFound(NovaException):
    msg_fmt = _("Assigned resources not found: %(reason)s")


class PMEMNamespaceConfigInvalid(NovaException):
    msg_fmt = _("The pmem_namespaces configuration is invalid: %(reason)s, "
                "please check your conf file. ")


class GetPMEMNamespaceFailed(NovaException):
    msg_fmt = _("Get PMEM namespaces on host failed: %(reason)s.")


class VPMEMCleanupFailed(NovaException):
    msg_fmt = _("Failed to clean up the vpmem backend device %(dev)s: "
                "%(error)s")
