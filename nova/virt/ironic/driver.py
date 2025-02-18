# Copyright 2014 Red Hat, Inc.
# Copyright 2013 Hewlett-Packard Development Company, L.P.
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
A driver wrapping the Ironic API, such that Nova may provision
bare metal resources.
"""

import base64
import gzip
import shutil
import tempfile
import time
from urllib import parse as urlparse

import microversion_parse
from openstack import exceptions as sdk_exc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
from tooz import hashring as hash_ring

from nova.api.metadata import base as instance_metadata
from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova.console import type as console_type
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import external_event as external_event_obj
from nova.objects import fields as obj_fields
from nova import servicegroup
from nova import utils
from nova.virt import configdrive
from nova.virt import driver as virt_driver
from nova.virt import hardware
from nova.virt.ironic import client_wrapper
from nova.virt.ironic import ironic_states
from nova.virt.ironic import patcher
from nova.virt import netutils


ironic = None

LOG = logging.getLogger(__name__)


CONF = nova.conf.CONF

_POWER_STATE_MAP = {
    ironic_states.POWER_ON: power_state.RUNNING,
    ironic_states.NOSTATE: power_state.NOSTATE,
    ironic_states.POWER_OFF: power_state.SHUTDOWN,
}

_UNPROVISION_STATES = (ironic_states.ACTIVE, ironic_states.DEPLOYFAIL,
                       ironic_states.ERROR, ironic_states.DEPLOYWAIT,
                       ironic_states.DEPLOYING, ironic_states.RESCUE,
                       ironic_states.RESCUING, ironic_states.RESCUEWAIT,
                       ironic_states.RESCUEFAIL, ironic_states.UNRESCUING,
                       ironic_states.UNRESCUEFAIL)

_NODE_FIELDS = ('uuid', 'power_state', 'target_power_state', 'provision_state',
                'target_provision_state', 'last_error', 'maintenance',
                'properties', 'instance_uuid', 'traits', 'resource_class')

# Console state checking interval in seconds
_CONSOLE_STATE_CHECKING_INTERVAL = 1

# Number of hash ring partitions per service
# 5 should be fine for most deployments, as an experimental feature.
_HASH_RING_PARTITIONS = 2 ** 5


def map_power_state(state):
    try:
        return _POWER_STATE_MAP[state]
    except KeyError:
        LOG.warning("Power state %s not found.", state)
        return power_state.NOSTATE


def _get_nodes_supported_instances(cpu_arch=None):
    """Return supported instances for a node."""
    if not cpu_arch:
        return []
    return [(cpu_arch,
             obj_fields.HVType.BAREMETAL,
             obj_fields.VMMode.HVM)]


def _log_ironic_polling(what, node, instance):
    power_state = (None if node.power_state is None else
                   '"%s"' % node.power_state)
    tgt_power_state = (None if node.target_power_state is None else
                       '"%s"' % node.target_power_state)
    prov_state = (None if node.provision_state is None else
                  '"%s"' % node.provision_state)
    tgt_prov_state = (None if node.target_provision_state is None else
                      '"%s"' % node.target_provision_state)
    LOG.debug('Still waiting for ironic node %(node)s to %(what)s: '
              'power_state=%(power_state)s, '
              'target_power_state=%(tgt_power_state)s, '
              'provision_state=%(prov_state)s, '
              'target_provision_state=%(tgt_prov_state)s',
              dict(what=what,
                   node=node.uuid,
                   power_state=power_state,
                   tgt_power_state=tgt_power_state,
                   prov_state=prov_state,
                   tgt_prov_state=tgt_prov_state),
              instance=instance)


def _check_peer_list():
    # these configs are mutable; need to check at runtime and init
    if CONF.ironic.conductor_group is not None:
        peer_list = set(CONF.ironic.peer_list)
        if not peer_list:
            LOG.error('FATAL: Peer list is not configured in the '
                      '[ironic]/peer_list option; cannot map '
                      'ironic nodes to compute services.')
            raise exception.InvalidPeerList(host=CONF.host)
        if CONF.host not in peer_list:
            LOG.error('FATAL: Peer list does not contain this '
                      'compute service hostname (%s); add it to '
                      'the [ironic]/peer_list option.', CONF.host)
            raise exception.InvalidPeerList(host=CONF.host)
        if len(peer_list) > 1:
            LOG.warning('Having multiple compute services in your '
                        'peer_list is now deprecated. We recommend moving '
                        'to just a single node in your peer list.')


class IronicDriver(virt_driver.ComputeDriver):
    """Hypervisor driver for Ironic - bare metal provisioning."""

    capabilities = {
        "has_imagecache": False,
        "supports_evacuate": False,
        "supports_migrate_to_same_host": False,
        "supports_attach_interface": True,
        "supports_multiattach": False,
        "supports_trusted_certs": False,
        "supports_pcpus": False,
        "supports_accelerators": False,
        "supports_remote_managed_ports": False,
        "supports_address_space_passthrough": False,
        "supports_address_space_emulated": False,

        # Image type support flags
        "supports_image_type_aki": False,
        "supports_image_type_ami": True,
        "supports_image_type_ari": False,
        "supports_image_type_iso": False,
        "supports_image_type_qcow2": True,
        "supports_image_type_raw": True,
        "supports_image_type_vdi": False,
        "supports_image_type_vhd": False,
        "supports_image_type_vhdx": False,
        "supports_image_type_vmdk": True,
        "supports_image_type_ploop": False,
    }

    # This driver is capable of rebalancing nodes between computes.
    rebalances_nodes = True

    def __init__(self, virtapi, read_only=False):
        super(IronicDriver, self).__init__(virtapi)
        global ironic
        if ironic is None:
            ironic = importutils.import_module('ironicclient')
            # NOTE(deva): work around a lack of symbols in the current version.
            if not hasattr(ironic, 'exc'):
                ironic.exc = importutils.import_module('ironicclient.exc')
            if not hasattr(ironic, 'client'):
                ironic.client = importutils.import_module(
                                                    'ironicclient.client')

        self.node_cache = {}
        self.node_cache_time = 0
        self.servicegroup_api = servicegroup.API()

        self.ironicclient = client_wrapper.IronicClientWrapper()
        self._ironic_connection = None
        self.host = None

    @property
    def ironic_connection(self):
        if self._ironic_connection is None:
            # Ask get_sdk_adapter to raise ServiceUnavailable if the baremetal
            # service isn't ready yet. Consumers of ironic_connection are set
            # up to handle this and raise VirtDriverNotReady as appropriate.
            self._ironic_connection = utils.get_sdk_adapter(
                'baremetal', check_service=True)
        return self._ironic_connection

    def _get_node(self, node_id):
        """Get a node by its UUID.

           Some methods pass in variables named nodename, but are
           actually UUID's.
        """
        node = self.ironic_connection.get_node(node_id, fields=_NODE_FIELDS)
        # TODO(dustinc): Make consumers use the right fields and remove this
        node.uuid = node.id
        node.instance_uuid = node.instance_id
        node.maintenance = node.is_maintenance
        return node

    def _validate_instance_and_node(self, instance):
        """Get the node associated with the instance.

        Check with the Ironic service that this instance is associated with a
        node, and return the node.
        """
        nodes = list(self.ironic_connection.nodes(
            instance_id=instance.uuid, fields=_NODE_FIELDS))
        if not nodes:
            raise exception.InstanceNotFound(instance_id=instance.uuid)
        if len(nodes) > 1:
            # This indicates a programming error so fail.
            raise exception.NovaException(
                _('Ironic returned more than one node for a query '
                  'that can only return zero or one: %s') % nodes)

        node = nodes[0]
        # TODO(dustinc): Make consumers use the right fields and remove
        if hasattr(node, "id"):
            node.uuid = node.id
        if hasattr(node, "instance_id"):
            node.instance_uuid = node.instance_id
        if hasattr(node, "is_maintenance"):
            node.maintenance = node.is_maintenance
        return node

    def _node_resources_unavailable(self, node_obj):
        """Determine whether the node's resources are in an acceptable state.

        Determines whether the node's resources should be presented
        to Nova for use based on the current power, provision and maintenance
        state. This is called after _node_resources_used, so any node that
        is not used and not in AVAILABLE should be considered in a 'bad' state,
        and unavailable for scheduling. Returns True if unacceptable.
        """
        bad_power_states = [
            ironic_states.ERROR, ironic_states.NOSTATE]
        # keep NOSTATE around for compatibility
        good_provision_states = [
            ironic_states.AVAILABLE, ironic_states.NOSTATE]
        return (node_obj.maintenance or
                node_obj.power_state in bad_power_states or
                node_obj.provision_state not in good_provision_states)

    def _node_resources_used(self, node_obj):
        """Determine whether the node's resources are currently used.

        Determines whether the node's resources should be considered used
        or not. A node is used when it is either in the process of putting
        a new instance on the node, has an instance on the node, or is in
        the process of cleaning up from a deleted instance. Returns True if
        used.

        If we report resources as consumed for a node that does not have an
        instance on it, the resource tracker will notice there's no instances
        consuming resources and try to correct us. So only nodes with an
        instance attached should report as consumed here.
        """
        return node_obj.instance_uuid is not None

    def _parse_node_properties(self, node):
        """Helper method to parse the node's properties."""
        properties = {}

        for prop in ('cpus', 'memory_mb', 'local_gb'):
            try:
                properties[prop] = int(node.properties.get(prop, 0))
            except (TypeError, ValueError):
                LOG.warning('Node %(uuid)s has a malformed "%(prop)s". '
                            'It should be an integer.',
                            {'uuid': node.uuid, 'prop': prop})
                properties[prop] = 0

        raw_cpu_arch = node.properties.get('cpu_arch', None)
        try:
            cpu_arch = obj_fields.Architecture.canonicalize(raw_cpu_arch)
        except exception.InvalidArchitectureName:
            cpu_arch = None
        if not cpu_arch:
            LOG.warning("cpu_arch not defined for node '%s'", node.uuid)

        properties['cpu_arch'] = cpu_arch
        properties['raw_cpu_arch'] = raw_cpu_arch
        properties['capabilities'] = node.properties.get('capabilities')
        return properties

    def _node_resource(self, node):
        """Helper method to create resource dict from node stats."""
        properties = self._parse_node_properties(node)

        raw_cpu_arch = properties['raw_cpu_arch']
        cpu_arch = properties['cpu_arch']

        nodes_extra_specs = {}

        # NOTE(deva): In Havana and Icehouse, the flavor was required to link
        # to an arch-specific deploy kernel and ramdisk pair, and so the flavor
        # also had to have extra_specs['cpu_arch'], which was matched against
        # the ironic node.properties['cpu_arch'].
        # With Juno, the deploy image(s) may be referenced directly by the
        # node.driver_info, and a flavor no longer needs to contain any of
        # these three extra specs, though the cpu_arch may still be used
        # in a heterogeneous environment, if so desired.
        # NOTE(dprince): we use the raw cpu_arch here because extra_specs
        # filters aren't canonicalized
        nodes_extra_specs['cpu_arch'] = raw_cpu_arch

        # NOTE(gilliard): To assist with more precise scheduling, if the
        # node.properties contains a key 'capabilities', we expect the value
        # to be of the form "k1:v1,k2:v2,etc.." which we add directly as
        # key/value pairs into the node_extra_specs to be used by the
        # ComputeCapabilitiesFilter
        capabilities = properties['capabilities']
        if capabilities:
            for capability in str(capabilities).split(','):
                parts = capability.split(':')
                if len(parts) == 2 and parts[0] and parts[1]:
                    nodes_extra_specs[parts[0].strip()] = parts[1]
                else:
                    LOG.warning("Ignoring malformed capability '%s'. "
                                "Format should be 'key:val'.", capability)

        vcpus = vcpus_used = 0
        memory_mb = memory_mb_used = 0
        local_gb = local_gb_used = 0

        dic = {
            'uuid': str(node.uuid),
            'hypervisor_hostname': str(node.uuid),
            'hypervisor_type': self._get_hypervisor_type(),
            'hypervisor_version': self._get_hypervisor_version(),
            'resource_class': node.resource_class,
            # The Ironic driver manages multiple hosts, so there are
            # likely many different CPU models in use. As such it is
            # impossible to provide any meaningful info on the CPU
            # model of the "host"
            'cpu_info': None,
            'vcpus': vcpus,
            'vcpus_used': vcpus_used,
            'local_gb': local_gb,
            'local_gb_used': local_gb_used,
            'disk_available_least': local_gb - local_gb_used,
            'memory_mb': memory_mb,
            'memory_mb_used': memory_mb_used,
            'supported_instances': _get_nodes_supported_instances(cpu_arch),
            'stats': nodes_extra_specs,
            'numa_topology': None,
        }
        return dic

    def _set_instance_id(self, node, instance):
        try:
            # NOTE(TheJulia): Assert an instance ID to lock the node
            # from other deployment attempts while configuration is
            # being set.
            self.ironic_connection.update_node(node, retry_on_conflict=False,
                                               instance_id=instance.uuid)
        except sdk_exc.SDKException:
            msg = (_("Failed to reserve node %(node)s "
                     "when provisioning the instance %(instance)s")
                   % {'node': node.id, 'instance': instance.uuid})
            LOG.error(msg)
            raise exception.InstanceDeployFailure(msg)

    def prepare_for_spawn(self, instance):
        LOG.debug('Preparing to spawn instance %s.', instance.uuid)
        node_uuid = instance.get('node')
        if not node_uuid:
            raise ironic.exc.BadRequest(
                _("Ironic node uuid not supplied to "
                  "driver for instance %s.") % instance.uuid)
        node = self._get_node(node_uuid)

        # Its possible this node has just moved from deleting
        # to cleaning. Placement will update the inventory
        # as all reserved, but this instance might have got here
        # before that happened, but after the previous allocation
        # got deleted. We trigger a re-schedule to another node.
        if (self._node_resources_used(node) or
                self._node_resources_unavailable(node)):
            msg = "Chosen ironic node %s is not available" % node_uuid
            LOG.info(msg, instance=instance)
            raise exception.ComputeResourcesUnavailable(reason=msg)

        self._set_instance_id(node, instance)

    def failed_spawn_cleanup(self, instance):
        LOG.debug('Failed spawn cleanup called for instance',
                  instance=instance)
        try:
            node = self._validate_instance_and_node(instance)
        except exception.InstanceNotFound:
            LOG.warning('Attempt to clean-up from failed spawn of '
                        'instance %s failed due to no instance_uuid '
                        'present on the node.', instance.uuid)
            return
        self._cleanup_deploy(node, instance)

    def _add_instance_info_to_node(self, node, instance, image_meta, flavor,
                                   preserve_ephemeral=None,
                                   block_device_info=None):

        root_bdm = block_device.get_root_bdm(
            virt_driver.block_device_info_get_mapping(block_device_info))
        boot_from_volume = root_bdm is not None
        patch = patcher.create(node).get_deploy_patch(instance,
                                                      image_meta,
                                                      flavor,
                                                      preserve_ephemeral,
                                                      boot_from_volume)

        try:
            # FIXME(lucasagomes): The "retry_on_conflict" parameter was added
            # to basically causes the deployment to fail faster in case the
            # node picked by the scheduler is already associated with another
            # instance due bug #1341420.
            self.ironicclient.call('node.update', node.uuid, patch,
                                   retry_on_conflict=False)
        except ironic.exc.BadRequest:
            msg = (_("Failed to add deploy parameters on node %(node)s "
                     "when provisioning the instance %(instance)s")
                   % {'node': node.uuid, 'instance': instance.uuid})
            LOG.error(msg)
            raise exception.InstanceDeployFailure(msg)

    def _remove_instance_info_from_node(self, node, instance):
        patch = [{'path': '/instance_info', 'op': 'remove'},
                 {'path': '/instance_uuid', 'op': 'remove'}]
        try:
            self.ironicclient.call('node.update', node.uuid, patch)
        except ironic.exc.BadRequest as e:
            LOG.warning("Failed to remove deploy parameters from node "
                        "%(node)s when unprovisioning the instance "
                        "%(instance)s: %(reason)s",
                        {'node': node.uuid, 'instance': instance.uuid,
                         'reason': str(e)})

    def _add_volume_target_info(self, context, instance, block_device_info):
        bdms = virt_driver.block_device_info_get_mapping(block_device_info)

        for bdm in bdms:
            if not bdm.is_volume:
                continue

            connection_info = jsonutils.loads(bdm._bdm_obj.connection_info)
            target_properties = connection_info['data']
            driver_volume_type = connection_info['driver_volume_type']

            try:
                self.ironicclient.call('volume_target.create',
                                       node_uuid=instance.node,
                                       volume_type=driver_volume_type,
                                       properties=target_properties,
                                       boot_index=bdm._bdm_obj.boot_index,
                                       volume_id=bdm._bdm_obj.volume_id)
            except (ironic.exc.BadRequest, ironic.exc.Conflict):
                msg = (_("Failed to add volume target information of "
                         "volume %(volume)s on node %(node)s when "
                         "provisioning the instance")
                       % {'volume': bdm._bdm_obj.volume_id,
                          'node': instance.node})
                LOG.error(msg, instance=instance)
                raise exception.InstanceDeployFailure(msg)

    def _cleanup_volume_target_info(self, instance):
        targets = self.ironicclient.call('node.list_volume_targets',
                                         instance.node, detail=True)
        for target in targets:
            volume_target_id = target.uuid
            try:
                self.ironicclient.call('volume_target.delete',
                                       volume_target_id)
            except ironic.exc.NotFound:
                LOG.debug("Volume target information %(target)s of volume "
                          "%(volume)s is already removed from node %(node)s",
                          {'target': volume_target_id,
                           'volume': target.volume_id,
                           'node': instance.node},
                          instance=instance)
            except ironic.exc.ClientException as e:
                LOG.warning("Failed to remove volume target information "
                            "%(target)s of volume %(volume)s from node "
                            "%(node)s when unprovisioning the instance: "
                            "%(reason)s",
                            {'target': volume_target_id,
                             'volume': target.volume_id,
                             'node': instance.node,
                             'reason': e},
                            instance=instance)

    def _cleanup_deploy(self, node, instance, network_info=None,
                        remove_instance_info=True):
        self._cleanup_volume_target_info(instance)
        self._unplug_vifs(node, instance, network_info)
        if remove_instance_info:
            self._remove_instance_info_from_node(node, instance)

    def _wait_for_available(self, instance, node):
        """Wait for the node to be marked as ACTIVE in Ironic."""
        abort_ironic_states = (ironic_states.DEPLOYWAIT,
                               ironic_states.DEPLOYING,
                               ironic_states.ACTIVE,
                               ironic_states.ERROR,
                               ironic_states.CLEANFAIL)
        instance.refresh()
        if (instance.task_state == task_states.DELETING or
            instance.vm_state in (vm_states.ERROR, vm_states.DELETED)):
            raise exception.InstanceDeployFailure(
                _("Instance %s provisioning was aborted") % instance.uuid)

        if node.provision_state == ironic_states.AVAILABLE:
            # job is done
            LOG.debug("Ironic node %(node)s is now AVAILABLE",
                      dict(node=node.uuid), instance=instance)
            raise loopingcall.LoopingCallDone()

        if (node.target_provision_state in abort_ironic_states or
            node.provision_state in abort_ironic_states):
            # ironic is already doing something unexpected with the instance
            raise exception.InstanceNotFound(instance_id=instance.uuid)

        _log_ironic_polling('become AVAILABLE', node, instance)

    def _wait_for_active(self, instance):
        """Wait for the node to be marked as ACTIVE in Ironic."""
        instance.refresh()
        # Ignore REBUILD_SPAWNING when rebuilding from ERROR state.
        if (instance.task_state != task_states.REBUILD_SPAWNING and
                (instance.task_state == task_states.DELETING or
                 instance.vm_state in (vm_states.ERROR, vm_states.DELETED))):
            raise exception.InstanceDeployFailure(
                _("Instance %s provisioning was aborted") % instance.uuid)

        node = self._validate_instance_and_node(instance)
        if node.provision_state == ironic_states.ACTIVE:
            # job is done
            LOG.debug("Ironic node %(node)s is now ACTIVE",
                      dict(node=node.uuid), instance=instance)
            raise loopingcall.LoopingCallDone()

        if node.target_provision_state in (ironic_states.DELETED,
                                           ironic_states.AVAILABLE):
            # ironic is trying to delete it now
            raise exception.InstanceNotFound(instance_id=instance.uuid)

        if node.provision_state in (ironic_states.NOSTATE,
                                    ironic_states.AVAILABLE):
            # ironic already deleted it
            raise exception.InstanceNotFound(instance_id=instance.uuid)

        if node.provision_state == ironic_states.DEPLOYFAIL:
            # ironic failed to deploy
            msg = (_("Failed to provision instance %(inst)s: %(reason)s")
                   % {'inst': instance.uuid, 'reason': node.last_error})
            raise exception.InstanceDeployFailure(msg)

        _log_ironic_polling('become ACTIVE', node, instance)

    def _wait_for_power_state(self, instance, message):
        """Wait for the node to complete a power state change."""
        node = self._validate_instance_and_node(instance)

        if node.target_power_state == ironic_states.NOSTATE:
            raise loopingcall.LoopingCallDone()

        _log_ironic_polling(message, node, instance)

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function.

        :param host: the hostname of the compute host.

        """
        self.host = host
        self._refresh_hash_ring(nova_context.get_admin_context())

    def _get_hypervisor_type(self):
        """Get hypervisor type."""
        return 'ironic'

    def _get_hypervisor_version(self):
        """Returns the version of the Ironic API service endpoint."""
        return client_wrapper.IRONIC_API_VERSION[0]

    def instance_exists(self, instance):
        """Checks the existence of an instance.

        Checks the existence of an instance. This is an override of the
        base method for efficiency.

        :param instance: The instance object.
        :returns: True if the instance exists. False if not.

        """
        try:
            self._validate_instance_and_node(instance)
            return True
        except exception.InstanceNotFound:
            return False

    def _get_node_list(self, return_generator=False, **kwargs):
        """Helper function to return a list or generator of nodes.

        :param return_generator: If True, returns a generator of nodes. This
          generator will only have SDK attribute names.
        :returns: a list or generator of raw nodes from ironic
        :raises: VirtDriverNotReady
        """
        try:
            # NOTE(dustinc): The generator returned by the SDK can only be
            # interated once. Since there are cases where it needs to be
            # iterated more than once, we should return it as a list. In the
            # future it may be worth refactoring these other usages so it can
            # be returned as a generator.
            node_generator = self.ironic_connection.nodes(**kwargs)
        except sdk_exc.InvalidResourceQuery as e:
            LOG.error("Invalid parameters in the provided search query."
                      "Error: %s", str(e))
            raise exception.VirtDriverNotReady()
        except Exception as e:
            LOG.error("An unknown error has occurred when trying to get the "
                      "list of nodes from the Ironic inventory. Error: %s",
                      str(e))
            raise exception.VirtDriverNotReady()
        if return_generator:
            return node_generator
        else:
            node_list = []
            # TODO(dustinc): Update all usages to use SDK attributes then stop
            #  copying values to PythonClient attributes.
            for node in node_generator:
                # NOTE(dustinc): There are usages that filter out these fields
                #  which forces us to check for the attributes.
                if hasattr(node, "id"):
                    node.uuid = node.id
                if hasattr(node, "instance_id"):
                    node.instance_uuid = node.instance_id
                if hasattr(node, "is_maintenance"):
                    node.maintenance = node.is_maintenance
                node_list.append(node)
            return node_list

    def list_instances(self):
        """Return the names of all the instances provisioned.

        :returns: a list of instance names.
        :raises: VirtDriverNotReady

        """
        conductor_group = CONF.ironic.conductor_group
        kwargs = {'associated': True, 'fields': ['instance_uuid']}
        if conductor_group is not None:
            kwargs['conductor_group'] = conductor_group
        uuids = [node.instance_uuid for node in self._get_node_list(**kwargs)]
        filters = {'uuid': uuids}
        context = nova_context.get_admin_context()
        instances = objects.InstanceList.get_by_filters(context,
                                                        filters,
                                                        expected_attrs=[
                                                            'name',
                                                            'host'],
                                                        use_slave=True)

        if CONF.ironic.update_host:
            for instance in instances:
                if instance.host != self.host:
                    instance.host = self.host
                    instance.save()

        return [obj.name for obj in instances]

    def list_instance_uuids(self):
        """Return the IDs of all the instances provisioned.

        :returns: a list of instance IDs.
        :raises: VirtDriverNotReady

        """
        # NOTE(dustinc): The SDK returns an object with instance_id,
        #  but the Ironic API expects instance_uuid in query.
        return [node.instance_id for node in self._get_node_list(
            return_generator=True, associated=True, fields=['instance_uuid'])]

    def node_is_available(self, nodename):
        """Confirms a Nova hypervisor node exists in the Ironic inventory.

        :param nodename: The UUID of the node. Parameter is called nodename
                         even though it is a UUID to keep method signature
                         the same as inherited class.
        :returns: True if the node exists, False if not.

        """
        # NOTE(comstud): We can cheat and use caching here. This method
        # just needs to return True for nodes that exist. It doesn't
        # matter if the data is stale. Sure, it's possible that removing
        # node from Ironic will cause this method to return True until
        # the next call to 'get_available_nodes', but there shouldn't
        # be much harm. There's already somewhat of a race.
        if not self.node_cache:
            # Empty cache, try to populate it.
            self._refresh_cache()

        # nodename is the ironic node's UUID.
        if nodename in self.node_cache:
            return True

        # NOTE(comstud): Fallback and check Ironic. This case should be
        # rare.
        try:
            # nodename is the ironic node's UUID.
            self._get_node(nodename)
            return True
        except sdk_exc.ResourceNotFound:
            return False

    def _refresh_hash_ring(self, ctxt):
        peer_list = None
        # NOTE(jroll) if this is set, we need to limit the set of other
        # compute services in the hash ring to hosts that are currently up
        # and specified in the peer_list config option, as there's no way
        # to check which conductor_group other compute services are using.
        if CONF.ironic.conductor_group is not None:
            try:
                # NOTE(jroll) first we need to make sure the Ironic API can
                # filter by conductor_group. If it cannot, limiting to
                # peer_list could end up with a node being managed by multiple
                # compute services.
                self._can_send_version(min_version='1.46')

                peer_list = set(CONF.ironic.peer_list)
                # these configs are mutable; need to check at runtime and init.
                # luckily, we run this method from init_host.
                _check_peer_list()
                LOG.debug('Limiting peer list to %s', peer_list)
            except exception.IronicAPIVersionNotAvailable:
                pass

        # TODO(jroll) optimize this to limit to the peer_list
        service_list = objects.ServiceList.get_all_computes_by_hv_type(
            ctxt, self._get_hypervisor_type())
        services = set()
        for svc in service_list:
            # NOTE(jroll) if peer_list is None, we aren't partitioning by
            # conductor group, so we check all compute services for liveness.
            # if we have a peer_list, don't check liveness for compute
            # services that aren't in the list.
            if peer_list is None or svc.host in peer_list:
                is_up = self.servicegroup_api.service_is_up(svc)
                if is_up:
                    services.add(svc.host.lower())
        # NOTE(jroll): always make sure this service is in the list, because
        # only services that have something registered in the compute_nodes
        # table will be here so far, and we might be brand new.
        services.add(CONF.host.lower())

        if len(services) > 1:
            LOG.warning('Having multiple compute services in your '
                        'deployment, for a single conductor group, '
                        'is now deprecated. We recommend moving '
                        'to just a single ironic nova compute service.')

        self.hash_ring = hash_ring.HashRing(services,
                                            partitions=_HASH_RING_PARTITIONS)
        LOG.debug('Hash ring members are %s', services)

    def _refresh_cache(self):
        ctxt = nova_context.get_admin_context()
        self._refresh_hash_ring(ctxt)
        node_cache = {}

        def _get_node_list(**kwargs):
            # NOTE(TheJulia): This call can take a substantial amount
            # of time as it may be attempting to retrieve thousands of
            # baremetal nodes. Depending on the version of Ironic,
            # this can be as long as 2-10 seconds per every thousand
            # nodes, and this call may retrieve all nodes in a deployment,
            # depending on if any filter parameters are applied.
            return self._get_node_list(fields=_NODE_FIELDS, **kwargs)

        # NOTE(jroll) if conductor_group is set, we need to limit nodes that
        # can be managed to nodes that have a matching conductor_group
        # attribute. If the API isn't new enough to support conductor groups,
        # we fall back to managing all nodes. If it is new enough, we can
        # filter it in the API.
        conductor_group = CONF.ironic.conductor_group
        if conductor_group is not None:
            try:
                self._can_send_version(min_version='1.46')
                nodes = _get_node_list(conductor_group=conductor_group)
                LOG.debug('Limiting manageable ironic nodes to conductor '
                          'group %s', conductor_group)
            except exception.IronicAPIVersionNotAvailable:
                LOG.error('Required Ironic API version 1.46 is not '
                          'available to filter nodes by conductor group. '
                          'All nodes will be eligible to be managed by '
                          'this compute service.')
                nodes = _get_node_list()
        else:
            nodes = _get_node_list()

        # NOTE(saga): As _get_node_list() will take a long
        # time to return in large clusters we need to call it before
        # get_uuids_by_host() method. Otherwise the instances list we get from
        # get_uuids_by_host() method will become stale.
        # A stale instances list can cause a node that is managed by this
        # compute host to be excluded in error and cause the compute node
        # to be orphaned and associated resource provider to be deleted.
        instances = objects.InstanceList.get_uuids_by_host(ctxt, CONF.host)

        for node in nodes:
            # NOTE(jroll): we always manage the nodes for instances we manage
            if node.instance_uuid in instances:
                node_cache[node.uuid] = node

            # NOTE(jroll): check if the node matches us in the hash ring, and
            # does not have an instance_uuid (which would imply the node has
            # an instance managed by another compute service).
            # Note that this means nodes with an instance that was deleted in
            # nova while the service was down, and not yet reaped, will not be
            # reported until the periodic task cleans it up.
            elif (node.instance_uuid is None and
                  CONF.host.lower() in
                  self.hash_ring.get_nodes(node.uuid.encode('utf-8'))):
                node_cache[node.uuid] = node

        self.node_cache = node_cache
        self.node_cache_time = time.time()

    def get_available_nodes(self, refresh=False):
        """Returns the UUIDs of Ironic nodes managed by this compute service.

        We use consistent hashing to distribute Ironic nodes between all
        available compute services. The subset of nodes managed by a given
        compute service is determined by the following rules:

        * any node with an instance managed by the compute service
        * any node that is mapped to the compute service on the hash ring
        * no nodes with instances managed by another compute service

        The ring is rebalanced as nova-compute services are brought up and
        down. Note that this rebalance does not happen at the same time for
        all compute services, so a node may be managed by multiple compute
        services for a small amount of time.

        :param refresh: Boolean value; If True run update first. Ignored by
                        this driver.
        :returns: a list of UUIDs

        """
        # NOTE(jroll) we refresh the cache every time this is called
        #             because it needs to happen in the resource tracker
        #             periodic task. This task doesn't pass refresh=True,
        #             unfortunately.
        self._refresh_cache()

        node_uuids = list(self.node_cache.keys())
        LOG.debug("Returning %(num_nodes)s available node(s)",
                  dict(num_nodes=len(node_uuids)))

        return node_uuids

    def get_nodenames_by_uuid(self, refresh=False):
        nodes = self.get_available_nodes(refresh=refresh)
        # We use the uuid for compute_node.uuid and
        # compute_node.hypervisor_hostname, so the dict keys and values are
        # the same.
        return dict(zip(nodes, nodes))

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update a ProviderTree object with current resource provider and
        inventory information.

        :param nova.compute.provider_tree.ProviderTree provider_tree:
            A nova.compute.provider_tree.ProviderTree object representing all
            the providers in the tree associated with the compute node, and any
            sharing providers (those with the ``MISC_SHARES_VIA_AGGREGATE``
            trait) associated via aggregate with any of those providers (but
            not *their* tree- or aggregate-associated providers), as currently
            known by placement.
        :param nodename:
            String name of the compute node (i.e.
            ComputeNode.hypervisor_hostname) for which the caller is requesting
            updated provider information.
        :param allocations:
            Dict of allocation data of the form:
              { $CONSUMER_UUID: {
                    # The shape of each "allocations" dict below is identical
                    # to the return from GET /allocations/{consumer_uuid}
                    "allocations": {
                        $RP_UUID: {
                            "generation": $RP_GEN,
                            "resources": {
                                $RESOURCE_CLASS: $AMOUNT,
                                ...
                            },
                        },
                        ...
                    },
                    "project_id": $PROJ_ID,
                    "user_id": $USER_ID,
                    "consumer_generation": $CONSUMER_GEN,
                },
                ...
              }
            If None, and the method determines that any inventory needs to be
            moved (from one provider to another and/or to a different resource
            class), the ReshapeNeeded exception must be raised. Otherwise, this
            dict must be edited in place to indicate the desired final state of
            allocations.
        :raises ReshapeNeeded: If allocations is None and any inventory needs
            to be moved from one provider to another and/or to a different
            resource class.
        """
        # nodename is the ironic node's UUID.
        node = self._node_from_cache(nodename)

        reserved = False
        if self._node_resources_unavailable(node):
            # Operators might mark a node as in maintainance,
            # even when an instance is on the node,
            # either way lets mark this as reserved
            reserved = True

        if (self._node_resources_used(node) and
            not CONF.workarounds.skip_reserve_in_use_ironic_nodes):
            # Make resources as reserved once we have
            # and instance here.
            # When the allocation is deleted, most likely
            # automatic clean will start, so we keep the node
            # reserved until it becomes available again.
            # In the case without automatic clean, once
            # the allocation is removed in placement it
            # also stays as reserved until we notice on
            # the next periodic its actually available.
            reserved = True

        info = self._node_resource(node)
        result = {}

        rc_name = info.get('resource_class')
        if rc_name is None:
            raise exception.NoResourceClass(node=nodename)

        norm_name = utils.normalize_rc_name(rc_name)
        if norm_name is not None:
            result[norm_name] = {
                'total': 1,
                'reserved': int(reserved),
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
            }

        provider_tree.update_inventory(nodename, result)
        # TODO(efried): *Unset* (remove_traits) if "owned" by ironic virt but
        # not set on the node object, and *set* (add_traits) only those both
        # owned by ironic virt and set on the node object.
        provider_tree.update_traits(nodename, node.traits)

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename: the UUID of the node.
        :returns: a dictionary describing resources.

        """
        # NOTE(comstud): We can cheat and use caching here. This method is
        # only called from a periodic task and right after the above
        # get_available_nodes() call is called.
        if not self.node_cache:
            # Well, it's also called from init_host(), so if we have empty
            # cache, let's try to populate it.
            self._refresh_cache()

        # nodename is the ironic node's UUID.
        node = self._node_from_cache(nodename)
        return self._node_resource(node)

    def _node_from_cache(self, node_uuid):
        """Returns a node from the cache, retrieving the node from Ironic API
        if the node doesn't yet exist in the cache.
        """
        # NOTE(vdrok): node_cache might also be modified during instance
        # _unprovision call, hence this function is synchronized
        @utils.synchronized('ironic-node-%s' % node_uuid)
        def _sync_node_from_cache():
            cache_age = time.time() - self.node_cache_time
            if node_uuid in self.node_cache:
                LOG.debug("Using cache for node %(node)s, age: %(age)s",
                          {'node': node_uuid, 'age': cache_age})
                return self.node_cache[node_uuid]
            else:
                LOG.debug("Node %(node)s not found in cache, age: %(age)s",
                          {'node': node_uuid, 'age': cache_age})
                node = self._get_node(node_uuid)
                self.node_cache[node_uuid] = node
                return node
        return _sync_node_from_cache()

    def get_info(self, instance, use_cache=True):
        """Get the current state and resource usage for this instance.

        If the instance is not found this method returns (a dictionary
        with) NOSTATE and all resources == 0.

        :param instance: the instance object.
        :param use_cache: boolean to indicate if the driver should be allowed
                          to use cached data to return instance status.
                          If false, pull fresh data from ironic.
        :returns: an InstanceInfo object
        """

        def _fetch_from_ironic(self, instance):
            try:
                node = self._validate_instance_and_node(instance)
                return hardware.InstanceInfo(
                    state=map_power_state(node.power_state))
            except exception.InstanceNotFound:
                return hardware.InstanceInfo(
                    state=map_power_state(ironic_states.NOSTATE))

        if not use_cache:
            return _fetch_from_ironic(self, instance)

        # we should already have a cache for our nodes, refreshed on every
        # RT loop. but if we don't have a cache, generate it.
        if not self.node_cache:
            self._refresh_cache()

        for node in self.node_cache.values():
            if instance.uuid == node.instance_uuid:
                break
        else:
            # if we can't find the instance, fall back to ironic
            return _fetch_from_ironic(self, instance)

        return hardware.InstanceInfo(state=map_power_state(node.power_state))

    def _get_network_metadata(self, node, network_info):
        """Gets a more complete representation of the instance network info.

        This data is exposed as network_data.json in the metadata service and
        the config drive.

        :param node: The node object.
        :param network_info: Instance network information.
        """
        base_metadata = netutils.get_network_metadata(network_info)

        # TODO(vdrok): change to doing a single "detailed vif list" call,
        # when added to ironic API, response to that will contain all
        # necessary information. Then we will be able to avoid looking at
        # internal_info/extra fields.
        ports = self.ironicclient.call("node.list_ports",
                                       node.uuid, detail=True)
        portgroups = self.ironicclient.call("portgroup.list", node=node.uuid,
                                            detail=True)
        vif_id_to_objects = {'ports': {}, 'portgroups': {}}
        for collection, name in ((ports, 'ports'), (portgroups, 'portgroups')):
            for p in collection:
                vif_id = (p.internal_info.get('tenant_vif_port_id') or
                          p.extra.get('vif_port_id'))
                if vif_id:
                    vif_id_to_objects[name][vif_id] = p

        additional_links = []
        for link in base_metadata['links']:
            vif_id = link['vif_id']
            if vif_id in vif_id_to_objects['portgroups']:
                pg = vif_id_to_objects['portgroups'][vif_id]
                pg_ports = [p for p in ports if p.portgroup_uuid == pg.uuid]
                link.update({'type': 'bond', 'bond_mode': pg.mode,
                             'bond_links': []})
                # If address is set on the portgroup, an (ironic) vif-attach
                # call has already updated neutron with the port address;
                # reflect it here. Otherwise, an address generated by neutron
                # will be used instead (code is elsewhere to handle this case).
                if pg.address:
                    link.update({'ethernet_mac_address': pg.address})
                for prop in pg.properties:
                    # These properties are the bonding driver options described
                    # at https://www.kernel.org/doc/Documentation/networking/bonding.txt  # noqa
                    # cloud-init checks the same way, parameter name has to
                    # start with bond
                    key = prop if prop.startswith('bond') else 'bond_%s' % prop
                    link[key] = pg.properties[prop]
                for port in pg_ports:
                    # This won't cause any duplicates to be added. A port
                    # cannot be in more than one port group for the same
                    # node.
                    additional_links.append({
                        'id': port.uuid,
                        'type': 'phy', 'ethernet_mac_address': port.address,
                    })
                    link['bond_links'].append(port.uuid)
            elif vif_id in vif_id_to_objects['ports']:
                p = vif_id_to_objects['ports'][vif_id]
                # Ironic updates neutron port's address during attachment
                link.update({'ethernet_mac_address': p.address,
                             'type': 'phy'})

        base_metadata['links'].extend(additional_links)
        return base_metadata

    def _generate_configdrive(self, context, instance, node, network_info,
                              extra_md=None, files=None):
        """Generate a config drive.

        :param instance: The instance object.
        :param node: The node object.
        :param network_info: Instance network information.
        :param extra_md: Optional, extra metadata to be added to the
                         configdrive.
        :param files: Optional, a list of paths to files to be added to
                      the configdrive.

        """
        if not extra_md:
            extra_md = {}

        i_meta = instance_metadata.InstanceMetadata(instance,
            content=files, extra_md=extra_md, network_info=network_info,
            network_metadata=self._get_network_metadata(node, network_info))

        with tempfile.NamedTemporaryFile() as uncompressed:
            with configdrive.ConfigDriveBuilder(instance_md=i_meta) as cdb:
                cdb.make_drive(uncompressed.name)

            with tempfile.NamedTemporaryFile() as compressed:
                # compress config drive
                with gzip.GzipFile(fileobj=compressed, mode='wb') as gzipped:
                    uncompressed.seek(0)
                    shutil.copyfileobj(uncompressed, gzipped)

                # base64 encode config drive
                compressed.seek(0)
                return base64.b64encode(compressed.read())

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
        """Deploy an instance.

        :param context: The security context.
        :param instance: The instance object.
        :param image_meta: Image dict returned by nova.image.glance
            that defines the image from which to boot this instance.
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in
            instance.
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
                            Ignored by this driver.
        :param network_info: Instance network information.
        :param block_device_info: Instance block device
            information.
        :param arqs: Accelerator requests for this instance.
        :param power_on: True if the instance should be powered on, False
                         otherwise
        """
        LOG.debug('Spawn called for instance', instance=instance)

        # The compute manager is meant to know the node uuid, so missing uuid
        # is a significant issue. It may mean we've been passed the wrong data.
        node_uuid = instance.get('node')
        if not node_uuid:
            raise ironic.exc.BadRequest(
                _("Ironic node uuid not supplied to "
                  "driver for instance %s.") % instance.uuid)

        node = self._get_node(node_uuid)
        flavor = instance.flavor

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_available,
                                                     instance, node)
        try:
            timer.start(interval=CONF.ironic.api_retry_interval).wait()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error deploying instance %(instance)s on "
                          "baremetal node %(node)s.",
                          {'instance': instance.uuid,
                           'node': node_uuid})

        self._add_instance_info_to_node(node, instance, image_meta, flavor,
                                        block_device_info=block_device_info)

        try:
            self._add_volume_target_info(context, instance, block_device_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error preparing deploy for instance "
                          "on baremetal node %(node)s.",
                          {'node': node_uuid},
                          instance=instance)
                self._cleanup_deploy(node, instance, network_info)

        # NOTE(Shrews): The default ephemeral device needs to be set for
        # services (like cloud-init) that depend on it being returned by the
        # metadata server. Addresses bug https://launchpad.net/bugs/1324286.
        if flavor.ephemeral_gb:
            instance.default_ephemeral_device = '/dev/sda1'
            instance.save()

        # validate we are ready to do the deploy
        validate_chk = self.ironicclient.call("node.validate", node_uuid)
        if (not validate_chk.deploy.get('result') or
                not validate_chk.power.get('result') or
                not validate_chk.storage.get('result')):
            # something is wrong. undo what we have done
            self._cleanup_deploy(node, instance, network_info)
            raise exception.ValidationError(_(
                "Ironic node: %(id)s failed to validate."
                " (deploy: %(deploy)s, power: %(power)s,"
                " storage: %(storage)s)")
                % {'id': node.uuid,
                   'deploy': validate_chk.deploy,
                   'power': validate_chk.power,
                   'storage': validate_chk.storage})

        # Config drive
        configdrive_value = None
        if configdrive.required_by(instance):
            extra_md = {}
            if admin_password:
                extra_md['admin_pass'] = admin_password

            try:
                configdrive_value = self._generate_configdrive(
                    context, instance, node, network_info, extra_md=extra_md,
                    files=injected_files)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    msg = "Failed to build configdrive: %s" % str(e)
                    LOG.error(msg, instance=instance)
                    self._cleanup_deploy(node, instance, network_info)

            LOG.info("Config drive for instance %(instance)s on "
                     "baremetal node %(node)s created.",
                     {'instance': instance['uuid'], 'node': node_uuid})

        # trigger the node deploy
        try:
            self.ironicclient.call("node.set_provision_state", node_uuid,
                                   ironic_states.ACTIVE,
                                   configdrive=configdrive_value)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to request Ironic to provision instance "
                          "%(inst)s: %(reason)s",
                          {'inst': instance.uuid,
                           'reason': str(e)})
                self._cleanup_deploy(node, instance, network_info)

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_active,
                                                     instance)
        try:
            timer.start(interval=CONF.ironic.api_retry_interval).wait()
            LOG.info('Successfully provisioned Ironic node %s',
                     node.uuid, instance=instance)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error deploying instance %(instance)s on "
                          "baremetal node %(node)s.",
                          {'instance': instance.uuid,
                           'node': node_uuid})

    def _unprovision(self, instance, node):
        """This method is called from destroy() to unprovision
        already provisioned node after required checks.
        """
        try:
            self.ironicclient.call("node.set_provision_state", node.uuid,
                                   "deleted")
        except Exception as e:
            # if the node is already in a deprovisioned state, continue
            # This should be fixed in Ironic.
            # TODO(deva): This exception should be added to
            #             python-ironicclient and matched directly,
            #             rather than via __name__.
            if getattr(e, '__name__', None) != 'InstanceDeployFailure':
                raise

        # using a dict because this is modified in the local method
        data = {'tries': 0}

        def _wait_for_provision_state():
            try:
                node = self._validate_instance_and_node(instance)
            except exception.InstanceNotFound:
                LOG.debug("Instance already removed from Ironic",
                          instance=instance)
                raise loopingcall.LoopingCallDone()
            if node.provision_state in (ironic_states.NOSTATE,
                                        ironic_states.CLEANING,
                                        ironic_states.CLEANWAIT,
                                        ironic_states.CLEANFAIL,
                                        ironic_states.AVAILABLE):
                # From a user standpoint, the node is unprovisioned. If a node
                # gets into CLEANFAIL state, it must be fixed in Ironic, but we
                # can consider the instance unprovisioned.
                LOG.debug("Ironic node %(node)s is in state %(state)s, "
                          "instance is now unprovisioned.",
                          dict(node=node.uuid, state=node.provision_state),
                          instance=instance)
                raise loopingcall.LoopingCallDone()

            if data['tries'] >= CONF.ironic.api_max_retries + 1:
                msg = (_("Error destroying the instance on node %(node)s. "
                         "Provision state still '%(state)s'.")
                       % {'state': node.provision_state,
                          'node': node.uuid})
                LOG.error(msg)
                raise exception.NovaException(msg)
            else:
                data['tries'] += 1

            _log_ironic_polling('unprovision', node, instance)

        # wait for the state transition to finish
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_provision_state)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()

        # NOTE(vdrok): synchronize this function so that get_available_resource
        # has up-to-date view of node_cache.
        @utils.synchronized('ironic-node-%s' % node.uuid)
        def _sync_remove_cache_entry():
            # NOTE(vdrok): Force the cache update, so that
            # update_usages resource tracker call that will happen next
            # has the up-to-date node view.
            self.node_cache.pop(node.uuid, None)
            LOG.debug('Removed node %(uuid)s from node cache.',
                      {'uuid': node.uuid})
        _sync_remove_cache_entry()

    def destroy(self, context, instance, network_info,
                block_device_info=None, destroy_disks=True,
                destroy_secrets=True):
        """Destroy the specified instance, if it can be found.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information.
        :param block_device_info: Instance block device
            information. Ignored by this driver.
        :param destroy_disks: Indicates if disks should be
            destroyed. Ignored by this driver.
        :param destroy_secrets: Indicates if secrets should be
            destroyed. Ignored by this driver.
        """
        LOG.debug('Destroy called for instance', instance=instance)
        try:
            node = self._validate_instance_and_node(instance)
        except exception.InstanceNotFound:
            LOG.warning("Destroy called on non-existing instance %s.",
                        instance.uuid)
            # NOTE(deva): if nova.compute.ComputeManager._delete_instance()
            #             is called on a non-existing instance, the only way
            #             to delete it is to return from this method
            #             without raising any exceptions.
            return

        try:
            if node.provision_state in _UNPROVISION_STATES:
                self._unprovision(instance, node)
            else:
                # NOTE(hshiina): if spawn() fails before ironic starts
                #                provisioning, instance information should be
                #                removed from ironic node.
                self._remove_instance_info_from_node(node, instance)
        finally:
            # NOTE(mgoddard): We don't need to remove instance info at this
            # point since we will have already done it. The destroy will only
            # succeed if this method returns without error, so we will end up
            # removing the instance info eventually.
            self._cleanup_deploy(node, instance, network_info,
                                 remove_instance_info=False)

        LOG.info('Successfully unprovisioned Ironic node %s',
                 node.uuid, instance=instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):
        """Reboot the specified instance.

        NOTE: Unlike the libvirt driver, this method does not delete
              and recreate the instance; it preserves local state.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param reboot_type: Either a HARD or SOFT reboot.
        :param block_device_info: Info pertaining to attached volumes.
            Ignored by this driver.
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered. Ignored by this driver.
        :param accel_info: List of accelerator request dicts. The exact
            data struct is doc'd in nova/virt/driver.py::spawn().
        """
        LOG.debug('Reboot(type %s) called for instance',
                  reboot_type, instance=instance)
        node = self._validate_instance_and_node(instance)

        hard = True
        if reboot_type == 'SOFT':
            try:
                self.ironicclient.call("node.set_power_state", node.uuid,
                                       'reboot', soft=True)
                hard = False
            except ironic.exc.BadRequest as exc:
                LOG.info('Soft reboot is not supported by ironic hardware '
                         'driver. Falling back to hard reboot: %s',
                         exc,
                         instance=instance)

        if hard:
            self.ironicclient.call("node.set_power_state", node.uuid, 'reboot')

        timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_power_state, instance, 'reboot')
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully rebooted(type %(type)s) Ironic node %(node)s',
                 {'type': ('HARD' if hard else 'SOFT'),
                  'node': node.uuid},
                 instance=instance)

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance.

        NOTE: Unlike the libvirt driver, this method does not delete
              and recreate the instance; it preserves local state.

        :param instance: The instance object.
        :param timeout: time to wait for node to shutdown. If it is set,
            soft power off is attempted before hard power off.
        :param retry_interval: How often to signal node while waiting
            for it to shutdown. Ignored by this driver. Retrying depends on
            Ironic hardware driver.
        """
        LOG.debug('Power off called for instance', instance=instance)
        node = self._validate_instance_and_node(instance)

        if timeout:
            try:
                self.ironicclient.call("node.set_power_state", node.uuid,
                                       'off', soft=True, timeout=timeout)

                timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_power_state, instance, 'soft power off')
                timer.start(interval=CONF.ironic.api_retry_interval).wait()
                node = self._validate_instance_and_node(instance)
                if node.power_state == ironic_states.POWER_OFF:
                    LOG.info('Successfully soft powered off Ironic node %s',
                             node.uuid, instance=instance)
                    return
                LOG.info("Failed to soft power off instance "
                         "%(instance)s on baremetal node %(node)s "
                         "within the required timeout %(timeout)d "
                         "seconds due to error: %(reason)s. "
                         "Attempting hard power off.",
                         {'instance': instance.uuid,
                          'timeout': timeout,
                          'node': node.uuid,
                          'reason': node.last_error},
                         instance=instance)
            except ironic.exc.ClientException as e:
                LOG.info("Failed to soft power off instance "
                         "%(instance)s on baremetal node %(node)s "
                         "due to error: %(reason)s. "
                         "Attempting hard power off.",
                         {'instance': instance.uuid,
                          'node': node.uuid,
                          'reason': e},
                         instance=instance)

        self.ironicclient.call("node.set_power_state", node.uuid, 'off')
        timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_power_state, instance, 'power off')
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully hard powered off Ironic node %s',
                 node.uuid, instance=instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        """Power on the specified instance.

        NOTE: Unlike the libvirt driver, this method does not delete
              and recreate the instance; it preserves local state.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param block_device_info: Instance block device
            information. Ignored by this driver.
        :param accel_info: List of accelerator requests for this instance.
                           Ignored by this driver.
        """
        LOG.debug('Power on called for instance', instance=instance)
        node = self._validate_instance_and_node(instance)
        self.ironicclient.call("node.set_power_state", node.uuid, 'on')

        timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_power_state, instance, 'power on')
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully powered on Ironic node %s',
                 node.uuid, instance=instance)

    def power_update_event(self, instance, target_power_state):
        """Update power, vm and task states of the specified instance in
        the nova DB.
        """
        LOG.info('Power update called for instance with '
                 'target power state %s.', target_power_state,
                 instance=instance)
        if target_power_state == external_event_obj.POWER_ON:
            instance.power_state = power_state.RUNNING
            instance.vm_state = vm_states.ACTIVE
            instance.task_state = None
            expected_task_state = task_states.POWERING_ON
        else:
            # It's POWER_OFF
            instance.power_state = power_state.SHUTDOWN
            instance.vm_state = vm_states.STOPPED
            instance.task_state = None
            expected_task_state = task_states.POWERING_OFF
        instance.save(expected_task_state=expected_task_state)

    def trigger_crash_dump(self, instance):
        """Trigger crash dump mechanism on the given instance.

        Stalling instances can be triggered to dump the crash data. How the
        guest OS reacts in details, depends on the configuration of it.

        :param instance: The instance where the crash dump should be triggered.

        :return: None
        """
        LOG.debug('Trigger crash dump called for instance', instance=instance)
        node = self._validate_instance_and_node(instance)

        self.ironicclient.call("node.inject_nmi", node.uuid)

        LOG.info('Successfully triggered crash dump into Ironic node %s',
                 node.uuid, instance=instance)

    def _plug_vif(self, node, port_id):
        last_attempt = 5
        for attempt in range(0, last_attempt + 1):
            try:
                self.ironicclient.call("node.vif_attach", node.uuid,
                                       port_id, retry_on_conflict=False)
            except ironic.exc.BadRequest as e:
                # NOTE(danms): If we race with ironic startup, there
                # will be no ironic-conductor running, which will
                # give us a failure to do this plug operation. So,
                # be graceful in that case and wait/retry.
                # NOTE(mdbooth): This will be fixed in ironic by
                # change I2c21baae. This will ensure ironic returns a 503 here,
                # which will cause ironicclient to automatically retry for us.
                # We can remove this workaround once we are confident that we
                # are only running against ironic containing this fix.
                if 'No conductor' in str(e) and attempt < last_attempt:
                    LOG.warning('No ironic conductor is running; '
                                'waiting...')
                    time.sleep(10)
                    continue

                msg = (_("Cannot attach VIF %(vif)s to the node %(node)s "
                         "due to error: %(err)s") % {
                             'vif': port_id,
                             'node': node.uuid, 'err': e})
                LOG.error(msg)
                raise exception.VirtualInterfacePlugException(msg)
            except ironic.exc.Conflict:
                # NOTE (vsaienko) Return since the VIF is already attached.
                return

            # Success, so don't retry
            return

    def _plug_vifs(self, node, instance, network_info):
        # NOTE(PhilDay): Accessing network_info will block if the thread
        # it wraps hasn't finished, so do this ahead of time so that we
        # don't block while holding the logging lock.
        network_info_str = str(network_info)
        LOG.debug("plug: instance_uuid=%(uuid)s vif=%(network_info)s",
                  {'uuid': instance.uuid,
                   'network_info': network_info_str})
        for vif in network_info:
            port_id = str(vif['id'])
            self._plug_vif(node, port_id)

    def _unplug_vifs(self, node, instance, network_info):
        # NOTE(PhilDay): Accessing network_info will block if the thread
        # it wraps hasn't finished, so do this ahead of time so that we
        # don't block while holding the logging lock.
        network_info_str = str(network_info)
        LOG.debug("unplug: instance_uuid=%(uuid)s vif=%(network_info)s",
                  {'uuid': instance.uuid,
                   'network_info': network_info_str})
        if not network_info:
            return
        for vif in network_info:
            port_id = str(vif['id'])
            try:
                self.ironicclient.call("node.vif_detach", node.uuid,
                                       port_id)
            except ironic.exc.BadRequest:
                LOG.debug("VIF %(vif)s isn't attached to Ironic node %(node)s",
                          {'vif': port_id, 'node': node.uuid})

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks.

        This method is present for compatability. Any call will result
        in a DEBUG log entry being generated, and will otherwise be
        ignored, as Ironic manages VIF attachments through a node
        lifecycle. Please see ``attach_interface``, which is the
        proper and current method to utilize.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        LOG.debug('VIF plug called for instance %(instance)s on node '
                  '%(node)s, however Ironic manages VIF attachments '
                  'for nodes.',
                  {'instance': instance.uuid,
                   'node': instance.node})

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        # instance.node is the ironic node's UUID.
        node = self._get_node(instance.node)
        self._unplug_vifs(node, instance, network_info)

    def attach_interface(self, context, instance, image_meta, vif):
        """Use hotplug to add a network interface to a running instance.
        The counter action to this is :func:`detach_interface`.

        :param context: The request context.
        :param nova.objects.instance.Instance instance:
            The instance which will get an additional network interface.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to attach.
        :raise nova.exception.NovaException: If the attach fails.
        :returns: None
        """
        # NOTE(vdrok): instance info cache gets updated by the network-changed
        # event from neutron or by _heal_instance_info_cache periodic task. In
        # both cases, this is done asynchronously, so the cache may not be up
        # to date immediately after attachment.
        node = self._get_node(instance.node)
        self._plug_vifs(node, instance, [vif])

    def detach_interface(self, context, instance, vif):
        """Use hotunplug to remove a network interface from a running instance.
        The counter action to this is :func:`attach_interface`.

        :param context: The request context.
        :param nova.objects.instance.Instance instance:
            The instance which gets a network interface removed.
        :param nova.network.model.VIF vif:
            The object which has the information about the interface to detach.
        :raise nova.exception.NovaException: If the detach fails.
        :returns: None
        """
        # NOTE(vdrok): instance info cache gets updated by the network-changed
        # event from neutron or by _heal_instance_info_cache periodic task. In
        # both cases, this is done asynchronously, so the cache may not be up
        # to date immediately after detachment.
        self.unplug_vifs(instance, [vif])

    def rebuild(self, context, instance, image_meta, injected_files,
                admin_password, allocations, bdms, detach_block_devices,
                attach_block_devices, network_info=None,
                evacuate=False, block_device_info=None,
                preserve_ephemeral=False, accel_uuids=None,
                reimage_boot_volume=False):
        """Rebuild/redeploy an instance.

        This version of rebuild() allows for supporting the option to
        preserve the ephemeral partition. We cannot call spawn() from
        here because it will attempt to set the instance_uuid value
        again, which is not allowed by the Ironic API. It also requires
        the instance to not have an 'active' provision state, but we
        cannot safely change that. Given that, we implement only the
        portions of spawn() we need within rebuild().

        :param context: The security context.
        :param instance: The instance object.
        :param image_meta: Image object returned by nova.image.glance
            that defines the image from which to boot this instance. Ignored
            by this driver.
        :param injected_files: User files to inject into instance.
        :param admin_password: Administrator password to set in
            instance. Ignored by this driver.
        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
                            Ignored by this driver.
        :param bdms: block-device-mappings to use for rebuild. Ignored
            by this driver.
        :param detach_block_devices: function to detach block devices. See
            nova.compute.manager.ComputeManager:_rebuild_default_impl for
            usage. Ignored by this driver.
        :param attach_block_devices: function to attach block devices. See
            nova.compute.manager.ComputeManager:_rebuild_default_impl for
            usage. Ignored by this driver.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param evacuate: Boolean value; if True the instance is
            recreated on a new hypervisor - all the cleanup of old state is
            skipped. Ignored by this driver.
        :param block_device_info: Instance block device
            information. Ignored by this driver.
        :param preserve_ephemeral: Boolean value; if True the ephemeral
            must be preserved on rebuild.
        :param accel_uuids: Accelerator UUIDs. Ignored by this driver.
        :param reimage_boot_volume: Re-image the volume backed instance.
        """
        if reimage_boot_volume:
            raise exception.NovaException(
                _("Ironic doesn't support rebuilding volume backed "
                  "instances."))

        LOG.debug('Rebuild called for instance', instance=instance)

        instance.task_state = task_states.REBUILD_SPAWNING
        instance.save(expected_task_state=[task_states.REBUILDING])

        node_uuid = instance.node
        node = self._get_node(node_uuid)

        self._add_instance_info_to_node(node, instance, image_meta,
                                        instance.flavor, preserve_ephemeral)

        # Config drive
        configdrive_value = None
        if configdrive.required_by(instance):
            extra_md = {}
            if admin_password:
                extra_md['admin_pass'] = admin_password

            try:
                configdrive_value = self._generate_configdrive(
                    context, instance, node, network_info, extra_md=extra_md,
                    files=injected_files)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    msg = "Failed to build configdrive: %s" % str(e)
                    LOG.error(msg, instance=instance)
                    raise exception.InstanceDeployFailure(msg)

            LOG.info("Config drive for instance %(instance)s on "
                     "baremetal node %(node)s created.",
                     {'instance': instance['uuid'], 'node': node_uuid})

        # Trigger the node rebuild/redeploy.
        try:
            self.ironicclient.call("node.set_provision_state",
                              node_uuid, ironic_states.REBUILD,
                              configdrive=configdrive_value)
        except (exception.NovaException,         # Retry failed
                ironic.exc.InternalServerError,  # Validations
                ironic.exc.BadRequest) as e:     # Maintenance
            msg = (_("Failed to request Ironic to rebuild instance "
                     "%(inst)s: %(reason)s") % {'inst': instance.uuid,
                                                'reason': str(e)})
            raise exception.InstanceDeployFailure(msg)

        # Although the target provision state is REBUILD, it will actually go
        # to ACTIVE once the redeploy is finished.
        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_active,
                                                     instance)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Instance was successfully rebuilt', instance=instance)

    def network_binding_host_id(self, context, instance):
        """Get host ID to associate with network ports.

        This defines the binding:host_id parameter to the port-create calls for
        Neutron. If using the neutron network interface (separate networks for
        the control plane and tenants), return None here to indicate that the
        port should not yet be bound; Ironic will make a port-update call to
        Neutron later to tell Neutron to bind the port.

        NOTE: the late binding is important for security. If an ML2 mechanism
        manages to connect the tenant network to the baremetal machine before
        deployment is done (e.g. port-create time), then the tenant potentially
        has access to the deploy agent, which may contain firmware blobs or
        secrets. ML2 mechanisms may be able to connect the port without the
        switchport info that comes from ironic, if they store that switchport
        info for some reason. As such, we should *never* pass binding:host_id
        in the port-create call when using the 'neutron' network_interface,
        because a null binding:host_id indicates to Neutron that it should
        not connect the port yet.

        :param context:  request context
        :param instance: nova.objects.instance.Instance that the network
                         ports will be associated with
        :returns: None
        """
        # NOTE(vsaienko) Ironic will set binding:host_id later with port-update
        # call when updating mac address or setting binding:profile
        # to tell Neutron to bind the port.
        return None

    def _get_node_console_with_reset(self, instance):
        """Acquire console information for an instance.

        If the console is enabled, the console will be re-enabled
        before returning.

        :param instance: nova instance
        :return: a dictionary with below values
            { 'node': ironic node
              'console_info': node console info }
        :raise ConsoleNotAvailable: if console is unavailable
            for the instance
        """
        node = self._validate_instance_and_node(instance)
        node_uuid = node.uuid

        def _get_console():
            """Request ironicclient to acquire node console."""
            try:
                return self.ironicclient.call('node.get_console', node_uuid)
            except (exception.NovaException,  # Retry failed
                    ironic.exc.InternalServerError,  # Validations
                    ironic.exc.BadRequest) as e:  # Maintenance
                LOG.error('Failed to acquire console information for '
                          'instance %(inst)s: %(reason)s',
                          {'inst': instance.uuid, 'reason': e})
                raise exception.ConsoleNotAvailable()

        def _wait_state(state):
            """Wait for the expected console mode to be set on node."""
            console = _get_console()
            if console['console_enabled'] == state:
                raise loopingcall.LoopingCallDone(retvalue=console)

            _log_ironic_polling('set console mode', node, instance)

            # Return False to start backing off
            return False

        def _enable_console(mode):
            """Request ironicclient to enable/disable node console."""
            try:
                self.ironicclient.call('node.set_console_mode', node_uuid,
                                       mode)
            except (exception.NovaException,  # Retry failed
                    ironic.exc.InternalServerError,  # Validations
                    ironic.exc.BadRequest) as e:  # Maintenance
                LOG.error('Failed to set console mode to "%(mode)s" '
                          'for instance %(inst)s: %(reason)s',
                          {'mode': mode,
                           'inst': instance.uuid,
                           'reason': e})
                raise exception.ConsoleNotAvailable()

            # Waiting for the console state to change (disabled/enabled)
            try:
                timer = loopingcall.BackOffLoopingCall(_wait_state, state=mode)
                return timer.start(
                    starting_interval=_CONSOLE_STATE_CHECKING_INTERVAL,
                    timeout=CONF.ironic.serial_console_state_timeout,
                    jitter=0.5).wait()
            except loopingcall.LoopingCallTimeOut:
                LOG.error('Timeout while waiting for console mode to be '
                          'set to "%(mode)s" on node %(node)s',
                          {'mode': mode,
                           'node': node_uuid})
                raise exception.ConsoleNotAvailable()

        # Acquire the console
        console = _get_console()

        # NOTE: Resetting console is a workaround to force acquiring
        # console when it has already been acquired by another user/operator.
        # IPMI serial console does not support multi session, so
        # resetting console will deactivate any active one without
        # warning the operator.
        if console['console_enabled']:
            try:
                # Disable console
                _enable_console(False)
                # Then re-enable it
                console = _enable_console(True)
            except exception.ConsoleNotAvailable:
                # NOTE: We try to do recover on failure.
                # But if recover fails, the console may remain in
                # "disabled" state and cause any new connection
                # will be refused.
                console = _enable_console(True)

        if console['console_enabled']:
            return {'node': node,
                    'console_info': console['console_info']}
        else:
            LOG.debug('Console is disabled for instance %s',
                      instance.uuid)
            raise exception.ConsoleNotAvailable()

    def get_serial_console(self, context, instance):
        """Acquire serial console information.

        :param context: request context
        :param instance: nova instance
        :return: ConsoleSerial object
        :raise ConsoleTypeUnavailable: if serial console is unavailable
            for the instance
        """
        LOG.debug('Getting serial console', instance=instance)
        try:
            result = self._get_node_console_with_reset(instance)
        except exception.ConsoleNotAvailable:
            raise exception.ConsoleTypeUnavailable(console_type='serial')

        node = result['node']
        console_info = result['console_info']

        if console_info["type"] not in ("socat", "shellinabox", "kvm"):
            LOG.warning('Console type "%(type)s" (of ironic node '
                        '%(node)s) does not support Nova serial console',
                        {'type': console_info["type"],
                         'node': node.uuid},
                        instance=instance)
            raise exception.ConsoleTypeUnavailable(
                console_type=console_info["type"])

        # Parse and check the console url
        url = urlparse.urlparse(console_info["url"])
        try:
            scheme = url.scheme
            hostname = url.hostname
            port = url.port
            path = url.path
            if url.query:
                path += "?"
                path += url.query
            if url.fragment:
                path += "#"
                path += url.fragment
            if not (scheme and hostname):
                raise AssertionError()
        except (ValueError, AssertionError):
            LOG.error('Invalid Socat or Shellinabox console URL "%(url)s" '
                      '(ironic node %(node)s)',
                      {'url': console_info["url"],
                       'node': node.uuid},
                      instance=instance)
            raise exception.ConsoleTypeUnavailable(
                console_type=console_info["type"])

        if scheme == "tcp":
            return console_type.ConsoleSerial(host=hostname,
                                              port=port)
        elif scheme == "http":
            return console_type.ConsoleSerial(host=hostname,
                                              port=port or 80,
                                              internal_access_path=path)
        elif scheme == "https":
            return console_type.ConsoleSerial(host=hostname,
                                              port=port or 443,
                                              internal_access_path=path)
        else:
            LOG.warning('Socat serial console only supports "tcp". '
                        'Shellinabox and KVM only http and https. '
                        'This URL is "%(url)s" (ironic node %(node)s).',
                        {'url': console_info["url"],
                         'node': node.uuid},
                        instance=instance)
            raise exception.ConsoleTypeUnavailable(
                console_type=console_info["type"])

    def prepare_networks_before_block_device_mapping(self, instance,
                                                     network_info):
        """Prepare networks before the block devices are mapped to instance.

        Plug VIFs before block device preparation. In case where storage
        network is managed by neutron and a MAC address is specified as a
        volume connector to a node, we can get the IP address assigned to
        the connector. An IP address of volume connector may be required by
        some volume backend drivers. For getting the IP address, VIFs need to
        be plugged before block device preparation so that a VIF is assigned to
        a MAC address.
        """

        try:
            node = self._get_node(instance.node)
            self._plug_vifs(node, instance, network_info)

        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error preparing deploy for instance "
                          "%(instance)s on baremetal node %(node)s.",
                          {'instance': instance.uuid,
                           'node': instance.node},
                          instance=instance)

    def clean_networks_preparation(self, instance, network_info):
        """Clean networks preparation when block device mapping is failed.

        Unplug VIFs when block device preparation is failed.
        """

        try:
            self.unplug_vifs(instance, network_info)
        except Exception as e:
            LOG.warning('Error detaching VIF from node %(node)s '
                        'after deploy failed; %(reason)s',
                        {'node': instance.node,
                         'reason': str(e)},
                        instance=instance)

    def get_volume_connector(self, instance):
        """Get connector information for the instance for attaching to volumes.

        Connector information is a dictionary representing the hardware
        information that will be making the connection. This information
        consists of properties for protocols supported by the hardware.
        If the hardware supports iSCSI protocol, iSCSI initiator IQN is
        included as follows::

            {
                'ip': ip,
                'initiator': initiator,
                'host': hostname
            }

        An IP address is set if a volume connector with type ip is assigned to
        a node. An IP address is also set if a node has a volume connector with
        type mac. An IP address is got from a VIF attached to an ironic port
        or portgroup with the MAC address. Otherwise, an IP address of one
        of VIFs is used.

        :param instance: nova instance
        :return: A connector information dictionary
        """
        node = self.ironicclient.call("node.get", instance.node)
        properties = self._parse_node_properties(node)
        connectors = self.ironicclient.call("node.list_volume_connectors",
                                            instance.node, detail=True)
        values = {}
        for conn in connectors:
            values.setdefault(conn.type, []).append(conn.connector_id)
        props = {}

        ip = self._get_volume_connector_ip(instance, node, values)
        if ip:
            LOG.debug('Volume connector IP address for node %(node)s is '
                      '%(ip)s.',
                      {'node': node.uuid, 'ip': ip},
                      instance=instance)
            props['ip'] = props['host'] = ip
        if values.get('iqn'):
            props['initiator'] = values['iqn'][0]
        if values.get('wwpn'):
            props['wwpns'] = values['wwpn']
        if values.get('wwnn'):
            props['wwnns'] = values['wwnn']
        props['platform'] = properties.get('cpu_arch')
        props['os_type'] = 'baremetal'

        # NOTE(TheJulia): The host field is important to cinder connectors
        # as it is used in some drivers for logging purposes, and we presently
        # only otherwise set it when an IP address is used.
        if 'host' not in props:
            props['host'] = instance.hostname
        # Eventually it would be nice to be able to do multipath, but for now
        # we should at least set the value to False.
        props['multipath'] = False
        return props

    def _get_volume_connector_ip(self, instance, node, values):
        if values.get('ip'):
            LOG.debug('Node %s has an IP address for volume connector',
                      node.uuid, instance=instance)
            return values['ip'][0]

        vif_id = self._get_vif_from_macs(node, values.get('mac', []), instance)

        # retrieve VIF and get the IP address
        nw_info = instance.get_network_info()
        if vif_id:
            fixed_ips = [ip for vif in nw_info if vif['id'] == vif_id
                         for ip in vif.fixed_ips()]
        else:
            fixed_ips = [ip for vif in nw_info for ip in vif.fixed_ips()]
        fixed_ips_v4 = [ip for ip in fixed_ips if ip['version'] == 4]
        if fixed_ips_v4:
            return fixed_ips_v4[0]['address']
        elif fixed_ips:
            return fixed_ips[0]['address']
        return None

    def _get_vif_from_macs(self, node, macs, instance):
        """Get a VIF from specified MACs.

        Retrieve ports and portgroups which have specified MAC addresses and
        return a UUID of a VIF attached to a port or a portgroup found first.

        :param node: The node object.
        :param mac: A list of MAC addresses of volume connectors.
        :param instance: nova instance, used for logging.
        :return: A UUID of a VIF assigned to one of the MAC addresses.
        """
        for mac in macs:
            for method in ['portgroup.list', 'port.list']:
                ports = self.ironicclient.call(method,
                                               node=node.uuid,
                                               address=mac,
                                               detail=True)
                for p in ports:
                    vif_id = (p.internal_info.get('tenant_vif_port_id') or
                              p.extra.get('vif_port_id'))
                    if vif_id:
                        LOG.debug('VIF %(vif)s for volume connector is '
                                  'retrieved with MAC %(mac)s of node '
                                  '%(node)s',
                                  {'vif': vif_id,
                                   'mac': mac,
                                   'node': node.uuid},
                                  instance=instance)
                        return vif_id
        return None

    def _can_send_version(self, min_version=None, max_version=None):
        """Validate if the supplied version is available in the API."""
        # NOTE(TheJulia): This will effectively just be a pass if no
        # version negotiation has occured, since there is no way for
        # us to know without explicitly otherwise requesting that
        # back-end negotiation occurs. This is a capability that is
        # present in python-ironicclient, however it may not be needed
        # in this case.
        if self.ironicclient.is_api_version_negotiated:
            current_api_version = self.ironicclient.current_api_version
            if (min_version and
                    microversion_parse.parse_version_string(
                        current_api_version) <
                    microversion_parse.parse_version_string(
                        min_version)):
                raise exception.IronicAPIVersionNotAvailable(
                    version=min_version)
            if (max_version and
                    microversion_parse.parse_version_string(
                        current_api_version) >
                    microversion_parse.parse_version_string(
                        max_version)):
                raise exception.IronicAPIVersionNotAvailable(
                    version=max_version)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password, block_device_info):
        """Rescue the specified instance.

        :param nova.context.RequestContext context:
            The context for the rescue.
        :param nova.objects.instance.Instance instance:
            The instance being rescued.
        :param nova.network.model.NetworkInfo network_info:
            Necessary network information for the rescue. Ignored by this
            driver.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance. Ignored by this driver.
        :param rescue_password: new root password to set for rescue.
        :param dict block_device_info:
            The block device mapping of the instance.
        :raise InstanceRescueFailure if rescue fails.
        """
        LOG.debug('Rescue called for instance', instance=instance)

        node_uuid = instance.node

        def _wait_for_rescue():
            try:
                node = self._validate_instance_and_node(instance)
            except exception.InstanceNotFound as e:
                raise exception.InstanceRescueFailure(reason=str(e))

            if node.provision_state == ironic_states.RESCUE:
                raise loopingcall.LoopingCallDone()

            if node.provision_state == ironic_states.RESCUEFAIL:
                raise exception.InstanceRescueFailure(
                          reason=node.last_error)

        try:
            self.ironicclient.call("node.set_provision_state",
                                   node_uuid, ironic_states.RESCUE,
                                   rescue_password=rescue_password)
        except Exception as e:
            raise exception.InstanceRescueFailure(reason=str(e))

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_rescue)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully rescued Ironic node %(node)s',
                 {'node': node_uuid}, instance=instance)

    def unrescue(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ):
        """Unrescue the specified instance.

        :param context: security context
        :param instance: nova.objects.instance.Instance
        """
        LOG.debug('Unrescue called for instance', instance=instance)

        node_uuid = instance.node

        def _wait_for_unrescue():
            try:
                node = self._validate_instance_and_node(instance)
            except exception.InstanceNotFound as e:
                raise exception.InstanceUnRescueFailure(reason=str(e))

            if node.provision_state == ironic_states.ACTIVE:
                raise loopingcall.LoopingCallDone()

            if node.provision_state == ironic_states.UNRESCUEFAIL:
                raise exception.InstanceUnRescueFailure(
                          reason=node.last_error)

        try:
            self.ironicclient.call("node.set_provision_state",
                                   node_uuid, ironic_states.UNRESCUE)
        except Exception as e:
            raise exception.InstanceUnRescueFailure(reason=str(e))

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_unrescue)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully unrescued Ironic node %(node)s',
                 {'node': node_uuid}, instance=instance)

    def manages_network_binding_host_id(self):
        """IronicDriver manages port bindings for baremetal instances.
        """
        return True
