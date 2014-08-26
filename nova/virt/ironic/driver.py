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

from nova.compute import arch
from nova.compute import power_state
from nova import context as nova_context
from nova import exception
from nova.i18n import _LW
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.virt import driver as virt_driver
from nova.virt import firewall
from nova.virt.ironic import client_wrapper
from nova.virt.ironic import ironic_states


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
