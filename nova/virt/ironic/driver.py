# coding=utf-8
#
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
import logging as py_logging

from ironicclient import exc as ironic_exception
from oslo.config import cfg
import six

from nova.compute import arch
from nova.compute import power_state
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LW
from nova.objects import flavor as flavor_obj
from nova.objects import instance as instance_obj
from nova.openstack.common import excutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.virt import driver as virt_driver
from nova.virt import firewall
from nova.virt.ironic import client_wrapper
from nova.virt.ironic import ironic_states
from nova.virt.ironic import patcher


LOG = logging.getLogger(__name__)

opts = [
    cfg.IntOpt('api_version',
               default=1,
               help='Version of Ironic API service endpoint.'),
    cfg.StrOpt('api_endpoint',
               help='URL for Ironic API endpoint.'),
    cfg.StrOpt('admin_username',
               help='Ironic keystone admin name'),
    cfg.StrOpt('admin_password',
               help='Ironic keystone admin password.'),
    cfg.StrOpt('admin_auth_token',
               help='Ironic keystone auth token.'),
    cfg.StrOpt('admin_url',
               help='Keystone public API endpoint.'),
    cfg.StrOpt('client_log_level',
               help='Log level override for ironicclient. Set this in '
                    'order to override the global "default_log_levels", '
                    '"verbose", and "debug" settings.'),
    cfg.StrOpt('admin_tenant_name',
               help='Ironic keystone tenant name.'),
    cfg.IntOpt('api_max_retries',
               default=60,
               help=('How many retries when a request does conflict.')),
    cfg.IntOpt('api_retry_interval',
               default=2,
               help=('How often to retry in seconds when a request '
                     'does conflict')),
    ]

ironic_group = cfg.OptGroup(name='ironic',
                            title='Ironic Options')

CONF = cfg.CONF
CONF.register_group(ironic_group)
CONF.register_opts(opts, ironic_group)

_POWER_STATE_MAP = {
    ironic_states.POWER_ON: power_state.RUNNING,
    ironic_states.NOSTATE: power_state.NOSTATE,
    ironic_states.POWER_OFF: power_state.SHUTDOWN,
}


def map_power_state(state):
    try:
        return _POWER_STATE_MAP[state]
    except KeyError:
        LOG.warning(_LW("Power state %s not found."), state)
        return power_state.NOSTATE


def _validate_instance_and_node(icli, instance):
    """Get the node associated with the instance.

    Check with the Ironic service that this instance is associated with a
    node, and return the node.
    """
    try:
        # TODO(mrda): Bug ID 1365228 icli should be renamed ironicclient
        # throughout
        return icli.call("node.get_by_instance_uuid", instance['uuid'])
    except ironic_exception.NotFound:
        raise exception.InstanceNotFound(instance_id=instance['uuid'])


def _get_nodes_supported_instances(cpu_arch=None):
    """Return supported instances for a node."""
    if not cpu_arch:
        return []
    return [(cpu_arch, 'baremetal', 'baremetal')]


def _log_ironic_polling(what, node, instance):
    prov_state = (None if node.provision_state is None else
                  '"%s"' % node.provision_state)
    tgt_prov_state = (None if node.target_provision_state is None else
                      '"%s"' % node.target_provision_state)
    LOG.debug('Still waiting for ironic node %(node)s to %(what)s: '
              'provision_state=%(prov_state)s, '
              'target_provision_state=%(tgt_prov_state)s',
              dict(what=what,
                   node=node.uuid,
                   prov_state=prov_state,
                   tgt_prov_state=tgt_prov_state),
              instance=instance)


class IronicDriver(virt_driver.ComputeDriver):
    """Hypervisor driver for Ironic - bare metal provisioning."""

    capabilities = {"has_imagecache": False,
                    "supports_recreate": False}

    def __init__(self, virtapi, read_only=False):
        super(IronicDriver, self).__init__(virtapi)

        self.firewall_driver = firewall.load_driver(
            default='nova.virt.firewall.NoopFirewallDriver')

        # TODO(mrda): Bug ID 1365230 Logging configurability needs
        # to be addressed
        icli_log_level = CONF.ironic.client_log_level
        if icli_log_level:
            level = py_logging.getLevelName(icli_log_level)
            logger = py_logging.getLogger('ironicclient')
            logger.setLevel(level)

    def _node_resources_unavailable(self, node_obj):
        """Determine whether the node's resources are in an acceptable state.

        Determines whether the node's resources should be presented
        to Nova for use based on the current power and maintenance state.
        Returns True if unacceptable.
        """
        bad_states = [ironic_states.ERROR, ironic_states.NOSTATE]
        return (node_obj.maintenance or
                node_obj.power_state in bad_states)

    def _node_resource(self, node):
        """Helper method to create resource dict from node stats."""
        vcpus = int(node.properties.get('cpus', 0))
        memory_mb = int(node.properties.get('memory_mb', 0))
        local_gb = int(node.properties.get('local_gb', 0))
        try:
            cpu_arch = arch.canonicalize(node.properties.get('cpu_arch', None))
        except exception.InvalidArchitectureName:
            cpu_arch = None
        if not cpu_arch:
            LOG.warn(_LW("cpu_arch not defined for node '%s'"), node.uuid)

        nodes_extra_specs = {}

        # NOTE(deva): In Havana and Icehouse, the flavor was required to link
        # to an arch-specific deploy kernel and ramdisk pair, and so the flavor
        # also had to have extra_specs['cpu_arch'], which was matched against
        # the ironic node.properties['cpu_arch'].
        # With Juno, the deploy image(s) may be referenced directly by the
        # node.driver_info, and a flavor no longer needs to contain any of
        # these three extra specs, though the cpu_arch may still be used
        # in a heterogeneous environment, if so desired.
        nodes_extra_specs['cpu_arch'] = cpu_arch

        # NOTE(gilliard): To assist with more precise scheduling, if the
        # node.properties contains a key 'capabilities', we expect the value
        # to be of the form "k1:v1,k2:v2,etc.." which we add directly as
        # key/value pairs into the node_extra_specs to be used by the
        # ComputeCapabilitiesFilter
        capabilities = node.properties.get('capabilities')
        if capabilities:
            for capability in str(capabilities).split(','):
                parts = capability.split(':')
                if len(parts) == 2 and parts[0] and parts[1]:
                    nodes_extra_specs[parts[0]] = parts[1]
                else:
                    LOG.warn(_LW("Ignoring malformed capability '%s'. "
                                 "Format should be 'key:val'."), capability)

        vcpus_used = 0
        memory_mb_used = 0
        local_gb_used = 0

        if node.instance_uuid:
            # Node has an instance, report all resource as unavailable
            vcpus_used = vcpus
            memory_mb_used = memory_mb
            local_gb_used = local_gb
        elif self._node_resources_unavailable(node):
            # The node's current state is such that it should not present any
            # of its resources to Nova
            vcpus = 0
            memory_mb = 0
            local_gb = 0

        dic = {
            'node': str(node.uuid),
            'hypervisor_hostname': str(node.uuid),
            'hypervisor_type': self._get_hypervisor_type(),
            'hypervisor_version': self._get_hypervisor_version(),
            'cpu_info': 'baremetal cpu',
            'vcpus': vcpus,
            'vcpus_used': vcpus_used,
            'local_gb': local_gb,
            'local_gb_used': local_gb_used,
            'disk_total': local_gb,
            'disk_used': local_gb_used,
            'disk_available': local_gb - local_gb_used,
            'memory_mb': memory_mb,
            'memory_mb_used': memory_mb_used,
            'host_memory_total': memory_mb,
            'host_memory_free': memory_mb - memory_mb_used,
            'supported_instances': jsonutils.dumps(
                _get_nodes_supported_instances(cpu_arch)),
            'stats': jsonutils.dumps(nodes_extra_specs),
            'host': CONF.host,
        }
        dic.update(nodes_extra_specs)
        return dic

    def _start_firewall(self, instance, network_info):
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self.firewall_driver.apply_instance_filter(instance, network_info)

    def _stop_firewall(self, instance, network_info):
        self.firewall_driver.unfilter_instance(instance, network_info)

    def _add_driver_fields(self, node, instance, image_meta, flavor,
                               preserve_ephemeral=None):
        icli = client_wrapper.IronicClientWrapper()
        patch = patcher.create(node).get_deploy_patch(instance,
                                                      image_meta,
                                                      flavor,
                                                      preserve_ephemeral)

        # Associate the node with an instance
        patch.append({'path': '/instance_uuid', 'op': 'add',
                      'value': instance['uuid']})
        try:
            icli.call('node.update', node.uuid, patch)
        except ironic_exception.BadRequest:
            msg = (_("Failed to add deploy parameters on node %(node)s "
                     "when provisioning the instance %(instance)s")
                   % {'node': node.uuid, 'instance': instance['uuid']})
            LOG.error(msg)
            raise exception.InstanceDeployFailure(msg)

    def _cleanup_deploy(self, node, instance, network_info):
        icli = client_wrapper.IronicClientWrapper()
        context = nova_context.get_admin_context()
        flavor = flavor_obj.Flavor.get_by_id(context,
                                             instance['instance_type_id'])
        patch = patcher.create(node).get_cleanup_patch(instance, network_info,
                                                       flavor)

        # Unassociate the node
        patch.append({'op': 'remove', 'path': '/instance_uuid'})
        try:
            icli.call('node.update', node.uuid, patch)
        except ironic_exception.BadRequest:
            LOG.error(_LE("Failed to clean up the parameters on node %(node)s "
                          "when unprovisioning the instance %(instance)s"),
                         {'node': node.uuid, 'instance': instance['uuid']})
            reason = (_("Fail to clean up node %s parameters") % node.uuid)
            raise exception.InstanceTerminationFailure(reason=reason)

        self._unplug_vifs(node, instance, network_info)
        self._stop_firewall(instance, network_info)

    def _wait_for_active(self, icli, instance):
        """Wait for the node to be marked as ACTIVE in Ironic."""
        node = _validate_instance_and_node(icli, instance)
        if node.provision_state == ironic_states.ACTIVE:
            # job is done
            LOG.debug("Ironic node %(node)s is now ACTIVE",
                      dict(node=node.uuid), instance=instance)
            raise loopingcall.LoopingCallDone()

        if node.target_provision_state == ironic_states.DELETED:
            # ironic is trying to delete it now
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        if node.provision_state == ironic_states.NOSTATE:
            # ironic already deleted it
            raise exception.InstanceNotFound(instance_id=instance['uuid'])

        if node.provision_state == ironic_states.DEPLOYFAIL:
            # ironic failed to deploy
            msg = (_("Failed to provision instance %(inst)s: %(reason)s")
                   % {'inst': instance['uuid'], 'reason': node.last_error})
            raise exception.InstanceDeployFailure(msg)

        _log_ironic_polling('become ACTIVE', node, instance)

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function.

        :param host: the hostname of the compute host.

        """
        return

    def _get_hypervisor_type(self):
        """Get hypervisor type."""
        return 'ironic'

    def _get_hypervisor_version(self):
        """Returns the version of the Ironic API service endpoint."""
        return CONF.ironic.api_version

    def instance_exists(self, instance):
        """Checks the existence of an instance.

        Checks the existence of an instance. This is an override of the
        base method for efficiency.

        :param instance: The instance object.
        :returns: True if the instance exists. False if not.

        """
        icli = client_wrapper.IronicClientWrapper()
        try:
            _validate_instance_and_node(icli, instance)
            return True
        except exception.InstanceNotFound:
            return False

    def list_instances(self):
        """Return the names of all the instances provisioned.

        :returns: a list of instance names.

        """
        icli = client_wrapper.IronicClientWrapper()
        node_list = icli.call("node.list", associated=True)
        context = nova_context.get_admin_context()
        return [instance_obj.Instance.get_by_uuid(context,
                                                  i.instance_uuid).name
                for i in node_list]

    def list_instance_uuids(self):
        """Return the UUIDs of all the instances provisioned.

        :returns: a list of instance UUIDs.

        """
        icli = client_wrapper.IronicClientWrapper()
        node_list = icli.call("node.list", associated=True)
        return list(n.instance_uuid for n in node_list)

    def node_is_available(self, nodename):
        """Confirms a Nova hypervisor node exists in the Ironic inventory.

        :param nodename: The UUID of the node.
        :returns: True if the node exists, False if not.

        """
        icli = client_wrapper.IronicClientWrapper()
        try:
            icli.call("node.get", nodename)
            return True
        except ironic_exception.NotFound:
            return False

    def get_available_nodes(self, refresh=False):
        """Returns the UUIDs of all nodes in the Ironic inventory.

        :param refresh: Boolean value; If True run update first. Ignored by
            this driver.
        :returns: a list of UUIDs

        """
        icli = client_wrapper.IronicClientWrapper()
        node_list = icli.call("node.list")
        nodes = [n.uuid for n in node_list]
        LOG.debug("Returning %(num_nodes)s available node(s): %(nodes)s",
                  dict(num_nodes=len(nodes), nodes=nodes))
        return nodes

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename: the UUID of the node.
        :returns: a dictionary describing resources.

        """
        icli = client_wrapper.IronicClientWrapper()
        node = icli.call("node.get", nodename)
        return self._node_resource(node)

    def get_info(self, instance):
        """Get the current state and resource usage for this instance.

        If the instance is not found this method returns (a dictionary
        with) NOSTATE and all resources == 0.

        :param instance: the instance object.
        :returns: a dictionary containing:

            :state: the running state. One of :mod:`nova.compute.power_state`.
            :max_mem:  (int) the maximum memory in KBytes allowed.
            :mem:      (int) the memory in KBytes used by the domain.
            :num_cpu:  (int) the number of CPUs.
            :cpu_time: (int) the CPU time used in nanoseconds. Always 0 for
                             this driver.

        """
        icli = client_wrapper.IronicClientWrapper()
        try:
            node = _validate_instance_and_node(icli, instance)
        except exception.InstanceNotFound:
            return {'state': map_power_state(ironic_states.NOSTATE),
                    'max_mem': 0,
                    'mem': 0,
                    'num_cpu': 0,
                    'cpu_time': 0
                    }

        memory_kib = int(node.properties.get('memory_mb', 0)) * 1024
        if memory_kib == 0:
            LOG.warn(_LW("Warning, memory usage is 0 for "
                         "%(instance)s on baremetal node %(node)s."),
                     {'instance': instance['uuid'],
                      'node': instance['node']})

        num_cpu = node.properties.get('cpus', 0)
        if num_cpu == 0:
            LOG.warn(_LW("Warning, number of cpus is 0 for "
                         "%(instance)s on baremetal node %(node)s."),
                     {'instance': instance['uuid'],
                      'node': instance['node']})

        return {'state': map_power_state(node.power_state),
                'max_mem': memory_kib,
                'mem': memory_kib,
                'num_cpu': num_cpu,
                'cpu_time': 0
                }

    def macs_for_instance(self, instance):
        """List the MAC addresses of an instance.

        List of MAC addresses for the node which this instance is
        associated with.

        :param instance: the instance object.
        :return: None, or a set of MAC ids (e.g. set(['12:34:56:78:90:ab'])).
            None means 'no constraints', a set means 'these and only these
            MAC addresses'.
        """
        icli = client_wrapper.IronicClientWrapper()
        try:
            node = icli.call("node.get", instance['node'])
        except ironic_exception.NotFound:
            return None
        ports = icli.call("node.list_ports", node.uuid)
        return set([p.address for p in ports])

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Deploy an instance.

        :param context: The security context.
        :param instance: The instance object.
        :param image_meta: Image dict returned by nova.image.glance
            that defines the image from which to boot this instance.
        :param injected_files: User files to inject into instance. Ignored
            by this driver.
        :param admin_password: Administrator password to set in
            instance. Ignored by this driver.
        :param network_info: Instance network information.
        :param block_device_info: Instance block device
            information. Ignored by this driver.

        """
        # The compute manager is meant to know the node uuid, so missing uuid
        # is a significant issue. It may mean we've been passed the wrong data.
        node_uuid = instance.get('node')
        if not node_uuid:
            raise ironic_exception.BadRequest(
                _("Ironic node uuid not supplied to "
                  "driver for instance %s.") % instance['uuid'])

        icli = client_wrapper.IronicClientWrapper()
        node = icli.call("node.get", node_uuid)

        flavor = flavor_obj.Flavor.get_by_id(context,
                                             instance['instance_type_id'])

        self._add_driver_fields(node, instance, image_meta, flavor)

        # NOTE(Shrews): The default ephemeral device needs to be set for
        # services (like cloud-init) that depend on it being returned by the
        # metadata server. Addresses bug https://launchpad.net/bugs/1324286.
        if flavor['ephemeral_gb']:
            instance.default_ephemeral_device = '/dev/sda1'
            instance.save()

        # validate we are ready to do the deploy
        validate_chk = icli.call("node.validate", node_uuid)
        if not validate_chk.deploy or not validate_chk.power:
            # something is wrong. undo what we have done
            self._cleanup_deploy(node, instance, network_info)
            raise exception.ValidationError(_(
                "Ironic node: %(id)s failed to validate."
                " (deploy: %(deploy)s, power: %(power)s)")
                % {'id': node.uuid,
                   'deploy': validate_chk.deploy,
                   'power': validate_chk.power})

        # prepare for the deploy
        try:
            self._plug_vifs(node, instance, network_info)
            self._start_firewall(instance, network_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error preparing deploy for instance "
                              "%(instance)s on baremetal node %(node)s."),
                          {'instance': instance['uuid'],
                           'node': node_uuid})
                self._cleanup_deploy(node, instance, network_info)

        # trigger the node deploy
        try:
            icli.call("node.set_provision_state", node_uuid,
                      ironic_states.ACTIVE)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                msg = (_LE("Failed to request Ironic to provision instance "
                           "%(inst)s: %(reason)s"),
                           {'inst': instance['uuid'],
                            'reason': six.text_type(e)})
                LOG.error(msg)
                self._cleanup_deploy(node, instance, network_info)

        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_active,
                                                     icli, instance)
        try:
            timer.start(interval=CONF.ironic.api_retry_interval).wait()
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error deploying instance %(instance)s on "
                              "baremetal node %(node)s."),
                             {'instance': instance['uuid'],
                              'node': node_uuid})
                self.destroy(context, instance, network_info)

    def _unprovision(self, icli, instance, node):
        """This method is called from destroy() to unprovision
        already provisioned node after required checks.
        """
        try:
            icli.call("node.set_provision_state", node.uuid, "deleted")
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
            node = _validate_instance_and_node(icli, instance)
            if not node.provision_state:
                LOG.debug("Ironic node %(node)s is now unprovisioned",
                          dict(node=node.uuid), instance=instance)
                raise loopingcall.LoopingCallDone()

            if data['tries'] >= CONF.ironic.api_max_retries:
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

    def destroy(self, context, instance, network_info,
                block_device_info=None, destroy_disks=True, migrate_data=None):
        """Destroy the specified instance, if it can be found.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information.
        :param block_device_info: Instance block device
            information. Ignored by this driver.
        :param destroy_disks: Indicates if disks should be
            destroyed. Ignored by this driver.
        :param migrate_data: implementation specific params.
            Ignored by this driver.
        """
        icli = client_wrapper.IronicClientWrapper()
        try:
            node = _validate_instance_and_node(icli, instance)
        except exception.InstanceNotFound:
            LOG.warning(_LW("Destroy called on non-existing instance %s."),
                        instance['uuid'])
            # NOTE(deva): if nova.compute.ComputeManager._delete_instance()
            #             is called on a non-existing instance, the only way
            #             to delete it is to return from this method
            #             without raising any exceptions.
            return

        if node.provision_state in (ironic_states.ACTIVE,
                                    ironic_states.DEPLOYFAIL,
                                    ironic_states.ERROR,
                                    ironic_states.DEPLOYWAIT):
            self._unprovision(icli, instance, node)

        self._cleanup_deploy(node, instance, network_info)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot the specified instance.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param reboot_type: Either a HARD or SOFT reboot. Ignored by
            this driver.
        :param block_device_info: Info pertaining to attached volumes.
            Ignored by this driver.
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered. Ignored by this driver.

        """
        icli = client_wrapper.IronicClientWrapper()
        node = _validate_instance_and_node(icli, instance)
        icli.call("node.set_power_state", node.uuid, 'reboot')

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance.

        :param instance: The instance object.
        :param timeout: time to wait for node to shutdown. Ignored by
            this driver.
        :param retry_interval: How often to signal node while waiting
            for it to shutdown. Ignored by this driver.
        """
        icli = client_wrapper.IronicClientWrapper()
        node = _validate_instance_and_node(icli, instance)
        icli.call("node.set_power_state", node.uuid, 'off')

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance.

        :param context: The security context.
        :param instance: The instance object.
        :param network_info: Instance network information. Ignored by
            this driver.
        :param block_device_info: Instance block device
            information. Ignored by this driver.

        """
        icli = client_wrapper.IronicClientWrapper()
        node = _validate_instance_and_node(icli, instance)
        icli.call("node.set_power_state", node.uuid, 'on')

    def get_host_stats(self, refresh=False):
        """Return the currently known stats for all Ironic nodes.

        :param refresh: Boolean value; If True run update first. Ignored by
            this driver.
        :returns: a list of dictionaries; each dictionary contains the
            stats for a node.

        """
        caps = []
        icli = client_wrapper.IronicClientWrapper()
        node_list = icli.call("node.list")
        for node in node_list:
            data = self._node_resource(node)
            caps.append(data)
        return caps

    def _plug_vifs(self, node, instance, network_info):
        # NOTE(PhilDay): Accessing network_info will block if the thread
        # it wraps hasn't finished, so do this ahead of time so that we
        # don't block while holding the logging lock.
        network_info_str = str(network_info)
        LOG.debug("plug: instance_uuid=%(uuid)s vif=%(network_info)s",
                  {'uuid': instance['uuid'],
                   'network_info': network_info_str})
        # start by ensuring the ports are clear
        self._unplug_vifs(node, instance, network_info)

        icli = client_wrapper.IronicClientWrapper()
        ports = icli.call("node.list_ports", node.uuid)

        if len(network_info) > len(ports):
            raise exception.NovaException(_(
                "Ironic node: %(id)s virtual to physical interface count"
                "  missmatch"
                " (Vif count: %(vif_count)d, Pif count: %(pif_count)d)")
                % {'id': node.uuid,
                   'vif_count': len(network_info),
                   'pif_count': len(ports)})

        if len(network_info) > 0:
            # not needed if no vif are defined
            for vif, pif in zip(network_info, ports):
                # attach what neutron needs directly to the port
                port_id = unicode(vif['id'])
                patch = [{'op': 'add',
                          'path': '/extra/vif_port_id',
                          'value': port_id}]
                icli.call("port.update", pif.uuid, patch)

    def _unplug_vifs(self, node, instance, network_info):
        # NOTE(PhilDay): Accessing network_info will block if the thread
        # it wraps hasn't finished, so do this ahead of time so that we
        # don't block while holding the logging lock.
        network_info_str = str(network_info)
        LOG.debug("unplug: instance_uuid=%(uuid)s vif=%(network_info)s",
                  {'uuid': instance['uuid'],
                   'network_info': network_info_str})
        if network_info and len(network_info) > 0:
            icli = client_wrapper.IronicClientWrapper()
            ports = icli.call("node.list_ports", node.uuid)

            # not needed if no vif are defined
            for vif, pif in zip(network_info, ports):
                # we can not attach a dict directly
                patch = [{'op': 'remove', 'path': '/extra/vif_port_id'}]
                try:
                    icli.call("port.update", pif.uuid, patch)
                except ironic_exception.BadRequest:
                    pass

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        icli = client_wrapper.IronicClientWrapper()
        node = icli.call("node.get", instance['node'])
        self._plug_vifs(node, instance, network_info)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks.

        :param instance: The instance object.
        :param network_info: Instance network information.

        """
        icli = client_wrapper.IronicClientWrapper()
        node = icli.call("node.get", instance['node'])
        self._unplug_vifs(node, instance, network_info)
