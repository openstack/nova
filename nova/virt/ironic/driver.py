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
from distutils import version
import gzip
import shutil
import tempfile
import time

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import excutils
from oslo_utils import importutils
import six
import six.moves.urllib.parse as urlparse
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
from nova.objects import fields as obj_fields
from nova import rc_fields
from nova import servicegroup
from nova import utils
from nova.virt import configdrive
from nova.virt import driver as virt_driver
from nova.virt import firewall
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


class IronicDriver(virt_driver.ComputeDriver):
    """Hypervisor driver for Ironic - bare metal provisioning."""

    capabilities = {"has_imagecache": False,
                    "supports_evacuate": False,
                    "supports_migrate_to_same_host": False,
                    "supports_attach_interface": True,
                    "supports_multiattach": False,
                    "supports_trusted_certs": False,
                    }

    # Needed for exiting instances to have allocations for custom resource
    # class resources
    # TODO(johngarbutt) we should remove this once the resource class
    # migration has been completed.
    requires_allocation_refresh = True

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

        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')
        self.node_cache = {}
        self.node_cache_time = 0
        self.servicegroup_api = servicegroup.API()

        self.ironicclient = client_wrapper.IronicClientWrapper()

        # This is needed for the instance flavor migration in Pike, and should
        # be removed in Queens. Since this will run several times in the life
        # of the driver, track the instances that have already been migrated.
        self._migrated_instance_uuids = set()

    def _get_node(self, node_uuid):
        """Get a node by its UUID.

           Some methods pass in variables named nodename, but are
           actually UUID's.
        """
        return self.ironicclient.call('node.get', node_uuid,
                                      fields=_NODE_FIELDS)

    def _validate_instance_and_node(self, instance):
        """Get the node associated with the instance.

        Check with the Ironic service that this instance is associated with a
        node, and return the node.
        """
        try:
            return self.ironicclient.call('node.get_by_instance_uuid',
                                          instance.uuid, fields=_NODE_FIELDS)
        except ironic.exc.NotFound:
            raise exception.InstanceNotFound(instance_id=instance.uuid)

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

        vcpus = properties['cpus']
        memory_mb = properties['memory_mb']
        local_gb = properties['local_gb']
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

        vcpus_used = 0
        memory_mb_used = 0
        local_gb_used = 0

        if (self._node_resources_used(node)
                or self._node_resources_unavailable(node)):
            # Node is deployed, or is in a state when deployment can not start.
            # Report all of its resources as in use.
            vcpus_used = vcpus
            memory_mb_used = memory_mb
            local_gb_used = local_gb

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

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _set_instance_uuid(self, node, instance):

        patch = [{'path': '/instance_uuid', 'op': 'add',
                  'value': instance.uuid}]
        try:
            # NOTE(TheJulia): Assert an instance UUID to lock the node
            # from other deployment attempts while configuration is
            # being set.
            self.ironicclient.call('node.update', node.uuid, patch,
                                   retry_on_conflict=False)
        except ironic.exc.BadRequest:
            msg = (_("Failed to reserve node %(node)s "
                     "when provisioning the instance %(instance)s")
                   % {'node': node.uuid, 'instance': instance.uuid})
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
        self._set_instance_uuid(node, instance)

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
                         'reason': six.text_type(e)})

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

    def _cleanup_deploy(self, node, instance, network_info=None):
        self._cleanup_volume_target_info(instance)
        self._unplug_vifs(node, instance, network_info)
        self._stop_firewall(instance, network_info)
        self._remove_instance_info_from_node(node, instance)

    def _wait_for_active(self, instance):
        """Wait for the node to be marked as ACTIVE in Ironic."""
        instance.refresh()
        if (instance.task_state == task_states.DELETING or
            instance.vm_state in (vm_states.ERROR, vm_states.DELETED)):
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
        self._refresh_hash_ring(nova_context.get_admin_context())

    @staticmethod
    def _pike_flavor_migration_for_node(ctx, node_rc, instance_uuid):
        normalized_rc = rc_fields.ResourceClass.normalize_name(node_rc)
        instance = objects.Instance.get_by_uuid(ctx, instance_uuid,
                                                expected_attrs=["flavor"])
        specs = instance.flavor.extra_specs
        resource_key = "resources:%s" % normalized_rc
        if resource_key in specs:
            # The compute must have been restarted, and the instance.flavor
            # has already been migrated
            return False
        specs[resource_key] = "1"
        instance.save()
        return True

    def _pike_flavor_migration(self, node_uuids):
        """This code is needed in Pike to prevent problems where an operator
        has already adjusted their flavors to add the custom resource class to
        extra_specs. Since existing ironic instances will not have this in
        their extra_specs, they will only have allocations against
        VCPU/RAM/disk. By adding just the custom RC to the existing flavor
        extra_specs, the periodic call to update_available_resources() will add
        an allocation against the custom resource class, and prevent placement
        from thinking that that node is available. This code can be removed in
        Queens, and will need to be updated to also alter extra_specs to
        zero-out the old-style standard resource classes of VCPU, MEMORY_MB,
        and DISK_GB.
        """
        ctx = nova_context.get_admin_context()

        for node_uuid in node_uuids:
            node = self._node_from_cache(node_uuid)
            if not node:
                continue
            node_rc = node.resource_class
            if not node_rc:
                LOG.warning("Node %(node)s does not have its resource_class "
                        "set.", {"node": node.uuid})
                continue
            if node.instance_uuid in self._migrated_instance_uuids:
                continue
            self._pike_flavor_migration_for_node(ctx, node_rc,
                                                 node.instance_uuid)
            self._migrated_instance_uuids.add(node.instance_uuid)
            LOG.debug("The flavor extra_specs for Ironic instance %(inst)s "
                      "have been updated for custom resource class '%(rc)s'.",
                      {"inst": node.instance_uuid, "rc": node_rc})
        return

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

    def _get_node_list(self, **kwargs):
        """Helper function to return the list of nodes.

        If unable to connect ironic server, an empty list is returned.

        :returns: a list of raw node from ironic
        :raises: VirtDriverNotReady

        """
        node_list = []
        try:
            node_list = self.ironicclient.call("node.list", **kwargs)
        except exception.NovaException as e:
            LOG.error("Failed to get the list of nodes from the Ironic "
                      "inventory. Error: %s", e)
            raise exception.VirtDriverNotReady()
        except Exception as e:
            LOG.error("An unknown error has occurred when trying to get the "
                      "list of nodes from the Ironic inventory. Error: %s", e)
            raise exception.VirtDriverNotReady()
        return node_list

    def list_instances(self):
        """Return the names of all the instances provisioned.

        :returns: a list of instance names.
        :raises: VirtDriverNotReady

        """
        # NOTE(lucasagomes): limit == 0 is an indicator to continue
        # pagination until there're no more values to be returned.
        node_list = self._get_node_list(associated=True,
                                        fields=['instance_uuid'], limit=0)
        context = nova_context.get_admin_context()
        return [objects.Instance.get_by_uuid(context,
                                             i.instance_uuid).name
                for i in node_list]

    def list_instance_uuids(self):
        """Return the UUIDs of all the instances provisioned.

        :returns: a list of instance UUIDs.
        :raises: VirtDriverNotReady

        """
        # NOTE(lucasagomes): limit == 0 is an indicator to continue
        # pagination until there're no more values to be returned.
        node_list = self._get_node_list(associated=True,
                                        fields=['instance_uuid'], limit=0)
        return list(n.instance_uuid for n in node_list)

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
        except ironic.exc.NotFound:
            return False

    def _refresh_hash_ring(self, ctxt):
        service_list = objects.ServiceList.get_all_computes_by_hv_type(
            ctxt, self._get_hypervisor_type())
        services = set()
        for svc in service_list:
            is_up = self.servicegroup_api.service_is_up(svc)
            if is_up:
                services.add(svc.host)
        # NOTE(jroll): always make sure this service is in the list, because
        # only services that have something registered in the compute_nodes
        # table will be here so far, and we might be brand new.
        services.add(CONF.host)

        self.hash_ring = hash_ring.HashRing(services,
                                            partitions=_HASH_RING_PARTITIONS)

    def _refresh_cache(self):
        # NOTE(lucasagomes): limit == 0 is an indicator to continue
        # pagination until there're no more values to be returned.
        ctxt = nova_context.get_admin_context()
        self._refresh_hash_ring(ctxt)
        instances = objects.InstanceList.get_uuids_by_host(ctxt, CONF.host)
        node_cache = {}

        for node in self._get_node_list(fields=_NODE_FIELDS, limit=0):
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
                  CONF.host in
                  self.hash_ring.get_nodes(node.uuid.encode('utf-8'))):
                node_cache[node.uuid] = node

        self.node_cache = node_cache
        self.node_cache_time = time.time()
        # For Pike, we need to ensure that all instances have their flavor
        # migrated to include the resource_class. Since there could be many,
        # many instances controlled by this host, spawn this asynchronously so
        # as not to block this service.
        node_uuids = [node.uuid for node in self.node_cache.values()
                      if node.instance_uuid and
                      node.instance_uuid not in self._migrated_instance_uuids]
        if node_uuids:
            # No need to run unless something has changed
            utils.spawn_n(self._pike_flavor_migration, node_uuids)

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

    def update_provider_tree(self, provider_tree, nodename):
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
        """
        # nodename is the ironic node's UUID.
        node = self._node_from_cache(nodename)
        reserved = False
        # TODO(jaypipes): Completely remove the reporting of VCPU, MEMORY_MB,
        # and DISK_GB resource classes in early Queens when Ironic nodes will
        # *always* return the custom resource class that represents the
        # baremetal node class in an atomic, singular unit.
        if (not self._node_resources_used(node) and
                self._node_resources_unavailable(node)):
            LOG.debug('Node %(node)s is not ready for a deployment, '
                      'reporting resources as reserved for it. Node\'s '
                      'provision state is %(prov)s, power state is '
                      '%(power)s and maintenance is %(maint)s.',
                      {'node': node.uuid, 'prov': node.provision_state,
                       'power': node.power_state, 'maint': node.maintenance})
            reserved = True

        info = self._node_resource(node)
        result = {}
        # Only report standard resource class inventory if configured to do so.
        # This allows operators to cut-over to ironic custom resource class
        # based scheduled as soon as they have completed the ironic instance
        # flavor data migrations.
        if CONF.workarounds.report_ironic_standard_resource_class_inventory:
            for rc, field in [(rc_fields.ResourceClass.VCPU, 'vcpus'),
                              (rc_fields.ResourceClass.MEMORY_MB, 'memory_mb'),
                              (rc_fields.ResourceClass.DISK_GB, 'local_gb')]:
                # NOTE(dtantsur): any of these fields can be zero starting with
                # the Pike release.
                if info[field]:
                    result[rc] = {
                        'total': info[field],
                        'reserved': info[field] if reserved else 0,
                        'min_unit': 1,
                        'max_unit': info[field],
                        'step_size': 1,
                        'allocation_ratio': 1.0,
                    }

        rc_name = info.get('resource_class')
        if rc_name is not None:
            # TODO(jaypipes): Raise an exception in Queens if Ironic doesn't
            # report a resource class for the node
            norm_name = rc_fields.ResourceClass.normalize_name(rc_name)
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

    def deallocate_networks_on_reschedule(self, instance):
        """Does the driver want networks deallocated on reschedule?

        :param instance: the instance object.
        :returns: Boolean value. If True deallocate networks on reschedule.
        """
        return True

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
            network_metadata=self._get_network_metadata(node, network_info),
            request_context=context)

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
              block_device_info=None):
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
        if (not validate_chk.deploy.get('result')
                or not validate_chk.power.get('result')
                or not validate_chk.storage.get('result')):
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

        # prepare for the deploy
        try:
            self._start_firewall(instance, network_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Error preparing deploy for instance "
                          "%(instance)s on baremetal node %(node)s.",
                          {'instance': instance.uuid,
                           'node': node_uuid})
                self._cleanup_deploy(node, instance, network_info)

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
                    msg = ("Failed to build configdrive: %s" %
                           six.text_type(e))
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
                           'reason': six.text_type(e)})
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
                block_device_info=None, destroy_disks=True):
        """Destroy the specified instance, if it can be found.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information.
        :param block_device_info: Instance block device
            information. Ignored by this driver.
        :param destroy_disks: Indicates if disks should be
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
            self._cleanup_deploy(node, instance, network_info)

        LOG.info('Successfully unprovisioned Ironic node %s',
                 node.uuid, instance=instance)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
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
                 block_device_info=None):
        """Power on the specified instance.

        NOTE: Unlike the libvirt driver, this method does not delete
              and recreate the instance; it preserves local state.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param block_device_info: Instance block device
            information. Ignored by this driver.

        """
        LOG.debug('Power on called for instance', instance=instance)
        node = self._validate_instance_and_node(instance)
        self.ironicclient.call("node.set_power_state", node.uuid, 'on')

        timer = loopingcall.FixedIntervalLoopingCall(
                    self._wait_for_power_state, instance, 'power on')
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully powered on Ironic node %s',
                 node.uuid, instance=instance)

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

    def refresh_security_group_rules(self, security_group_id):
        """Refresh security group rules from data store.

        Invoked when security group rules are updated.

        :param security_group_id: The security group id.

        """
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_instance_security_rules(self, instance):
        """Refresh security group rules from data store.

        Gets called when an instance gets added to or removed from
        the security group the instance is a member of or if the
        group gains or loses a rule.

        :param instance: The instance object.

        """
        self.firewall_driver.refresh_instance_security_rules(instance)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        """Set up filtering rules.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)

    def unfilter_instance(self, instance, network_info):
        """Stop filtering instance.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        self.firewall_driver.unfilter_instance(instance, network_info)

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
                if ('No conductor' in six.text_type(e) and
                        attempt < last_attempt):
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
            port_id = six.text_type(vif['id'])
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
            port_id = six.text_type(vif['id'])
            try:
                self.ironicclient.call("node.vif_detach", node.uuid,
                                       port_id)
            except ironic.exc.BadRequest:
                LOG.debug("VIF %(vif)s isn't attached to Ironic node %(node)s",
                          {'vif': port_id, 'node': node.uuid})

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        # instance.node is the ironic node's UUID.
        node = self._get_node(instance.node)
        self._plug_vifs(node, instance, network_info)

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
        self.plug_vifs(instance, [vif])

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
                preserve_ephemeral=False):
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

        """
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
                    msg = ("Failed to build configdrive: %s" %
                           six.text_type(e))
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
                                                'reason': six.text_type(e)})
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

        if console_info["type"] != "socat":
            LOG.warning('Console type "%(type)s" (of ironic node '
                        '%(node)s) does not support Nova serial console',
                        {'type': console_info["type"],
                         'node': node.uuid},
                        instance=instance)
            raise exception.ConsoleTypeUnavailable(console_type='serial')

        # Parse and check the console url
        url = urlparse.urlparse(console_info["url"])
        try:
            scheme = url.scheme
            hostname = url.hostname
            port = url.port
            if not (scheme and hostname and port):
                raise AssertionError()
        except (ValueError, AssertionError):
            LOG.error('Invalid Socat console URL "%(url)s" '
                      '(ironic node %(node)s)',
                      {'url': console_info["url"],
                       'node': node.uuid},
                      instance=instance)
            raise exception.ConsoleTypeUnavailable(console_type='serial')

        if scheme == "tcp":
            return console_type.ConsoleSerial(host=hostname,
                                              port=port)
        else:
            LOG.warning('Socat serial console only supports "tcp". '
                        'This URL is "%(url)s" (ironic node %(node)s).',
                        {'url': console_info["url"],
                         'node': node.uuid},
                        instance=instance)
            raise exception.ConsoleTypeUnavailable(console_type='serial')

    @property
    def need_legacy_block_device_info(self):
        return False

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
            self.plug_vifs(instance, network_info)
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
                         'reason': six.text_type(e)},
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
        """Validate if the suppplied version is available in the API."""
        # NOTE(TheJulia): This will effectively just be a pass if no
        # version negotiation has occured, since there is no way for
        # us to know without explicitly otherwise requesting that
        # back-end negotiation occurs. This is a capability that is
        # present in python-ironicclient, however it may not be needed
        # in this case.
        if self.ironicclient.is_api_version_negotiated:
            current_api_version = self.ironicclient.current_api_version
            if (min_version and
                    version.StrictVersion(current_api_version) <
                    version.StrictVersion(min_version)):
                raise exception.IronicAPIVersionNotAvailable(
                    version=min_version)
            if (max_version and
                    version.StrictVersion(current_api_version) >
                    version.StrictVersion(max_version)):
                raise exception.IronicAPIVersionNotAvailable(
                    version=max_version)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
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
        :raise InstanceRescueFailure if rescue fails.
        """
        LOG.debug('Rescue called for instance', instance=instance)

        node_uuid = instance.node

        def _wait_for_rescue():
            try:
                node = self._validate_instance_and_node(instance)
            except exception.InstanceNotFound as e:
                raise exception.InstanceRescueFailure(reason=six.text_type(e))

            if node.provision_state == ironic_states.RESCUE:
                raise loopingcall.LoopingCallDone()

            if node.provision_state == ironic_states.RESCUEFAIL:
                raise exception.InstanceRescueFailure(
                          reason=node.last_error)

        try:
            self._can_send_version(min_version='1.38')
            self.ironicclient.call("node.set_provision_state",
                                   node_uuid, ironic_states.RESCUE,
                                   rescue_password=rescue_password)
        except exception.IronicAPIVersionNotAvailable as e:
            LOG.error('Required Ironic API version %(version)s is not '
                      'available for rescuing.',
                      version='1.38', instance=instance)
            raise exception.InstanceRescueFailure(reason=six.text_type(e))
        except Exception as e:
            raise exception.InstanceRescueFailure(reason=six.text_type(e))

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_rescue)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully rescued Ironic node %(node)s',
                 {'node': node_uuid}, instance=instance)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance.

        :param instance: nova.objects.instance.Instance
        :param nova.network.model.NetworkInfo network_info:
            Necessary network information for the unrescue. Ignored by this
            driver.
        """
        LOG.debug('Unrescue called for instance', instance=instance)

        node_uuid = instance.node

        def _wait_for_unrescue():
            try:
                node = self._validate_instance_and_node(instance)
            except exception.InstanceNotFound as e:
                raise exception.InstanceUnRescueFailure(
                          reason=six.text_type(e))

            if node.provision_state == ironic_states.ACTIVE:
                raise loopingcall.LoopingCallDone()

            if node.provision_state == ironic_states.UNRESCUEFAIL:
                raise exception.InstanceUnRescueFailure(
                          reason=node.last_error)

        try:
            self._can_send_version(min_version='1.38')
            self.ironicclient.call("node.set_provision_state",
                                   node_uuid, ironic_states.UNRESCUE)
        except exception.IronicAPIVersionNotAvailable as e:
            LOG.error('Required Ironic API version %(version)s is not '
                       'available for unrescuing.',
                       version='1.38', instance=instance)
            raise exception.InstanceUnRescueFailure(reason=six.text_type(e))
        except Exception as e:
            raise exception.InstanceUnRescueFailure(reason=six.text_type(e))

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_unrescue)
        timer.start(interval=CONF.ironic.api_retry_interval).wait()
        LOG.info('Successfully unrescued Ironic node %(node)s',
                 {'node': node_uuid}, instance=instance)
