# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Hewlett-Packard Development Company, L.P.
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
#
# Virtual power driver

from oslo.config import cfg

from nova import context as nova_context
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import base
from nova.virt.baremetal import db
import nova.virt.powervm.common as connection

opts = [
    cfg.StrOpt('virtual_power_ssh_host',
               default='',
               help='ip or name to virtual power host'),
    cfg.IntOpt('virtual_power_ssh_port',
               default=22,
               help='Port to use for ssh to virtual power host'),
    cfg.StrOpt('virtual_power_type',
               default='virsh',
               help='base command to use for virtual power(vbox,virsh)'),
    cfg.StrOpt('virtual_power_host_user',
               default='',
               help='user to execute virtual power commands as'),
    cfg.StrOpt('virtual_power_host_pass',
               default='',
               help='password for virtual power host_user'),
    cfg.StrOpt('virtual_power_host_key',
               help='ssh key for virtual power host_user'),

]

baremetal_vp = cfg.OptGroup(name='baremetal',
                            title='Baremetal Options')

CONF = cfg.CONF
CONF.register_group(baremetal_vp)
CONF.register_opts(opts, baremetal_vp)

_conn = None
_vp_cmd = None
_cmds = None

LOG = logging.getLogger(__name__)


def _normalize_mac(mac):
    return mac.replace(':', '').lower()


class VirtualPowerManager(base.PowerManager):
    """Virtual Power Driver for Baremetal Nova Compute

    This PowerManager class provides mechanism for controlling the power state
    of VMs based on their name and MAC address. It uses ssh to connect to the
    VM's host and issue commands.

    Node will be matched based on mac address

    NOTE: for use in dev/test environments only!

    """
    def __init__(self, **kwargs):
        global _conn
        global _cmds

        if _cmds is None:
            LOG.debug("Setting up %s commands." %
                    CONF.baremetal.virtual_power_type)
            _vpc = 'nova.virt.baremetal.virtual_power_driver_settings.%s' % \
                    CONF.baremetal.virtual_power_type
            _cmds = importutils.import_class(_vpc)
        self._vp_cmd = _cmds()
        self.connection_data = _conn
        node = kwargs.pop('node', {})
        instance = kwargs.pop('instance', {})
        self._node_name = instance.get('hostname', "")
        context = nova_context.get_admin_context()
        ifs = db.bm_interface_get_all_by_bm_node_id(context, node['id'])
        self._mac_addresses = [_normalize_mac(i['address']) for i in ifs]
        self._connection = None
        self._matched_name = ''
        self.state = None

    def _get_conn(self):
        if not CONF.baremetal.virtual_power_ssh_host:
            raise exception.NovaException(
                _('virtual_power_ssh_host not defined. Can not Start'))

        if not CONF.baremetal.virtual_power_host_user:
            raise exception.NovaException(
                _('virtual_power_host_user not defined. Can not Start'))

        if not CONF.baremetal.virtual_power_host_pass:
            # it is ok to not have a password if you have a keyfile
            if CONF.baremetal.virtual_power_host_key is None:
                raise exception.NovaException(
                    _('virtual_power_host_pass/key not set. Can not Start'))

        _conn = connection.Connection(
            CONF.baremetal.virtual_power_ssh_host,
            CONF.baremetal.virtual_power_host_user,
            CONF.baremetal.virtual_power_host_pass,
            CONF.baremetal.virtual_power_ssh_port,
            CONF.baremetal.virtual_power_host_key)
        return _conn

    def _set_connection(self):
        if self._connection is None:
            if self.connection_data is None:
                self.connection_data = self._get_conn()

            self._connection = connection.ssh_connect(self.connection_data)

    def _get_full_node_list(self):
        LOG.debug("Getting full node list.")
        cmd = self._vp_cmd.list_cmd
        full_list = self._run_command(cmd)
        return full_list

    def _check_for_node(self):
        LOG.debug("Looking up Name for Mac address %s." % self._mac_addresses)
        self._matched_name = ''
        full_node_list = self._get_full_node_list()

        for node in full_node_list:
            cmd = self._vp_cmd.get_node_macs.replace('{_NodeName_}', node)
            mac_address_list = self._run_command(cmd)

            for mac in mac_address_list:
                if _normalize_mac(mac) in self._mac_addresses:
                    self._matched_name = ('"%s"' % node)
                    break
        return self._matched_name

    def activate_node(self):
        LOG.info("activate_node name %s" % self._node_name)
        if self._check_for_node():
            cmd = self._vp_cmd.start_cmd
            self._run_command(cmd)

        if self.is_power_on():
            self.state = baremetal_states.ACTIVE
        else:
            self.state = baremetal_states.ERROR
        return self.state

    def reboot_node(self):
        LOG.info("reset node: %s" % self._node_name)
        if self._check_for_node():
            cmd = self._vp_cmd.reboot_cmd
            self._run_command(cmd)
        if self.is_power_on():
            self.state = baremetal_states.ACTIVE
        else:
            self.state = baremetal_states.ERROR
        return self.state

    def deactivate_node(self):
        LOG.info("deactivate_node name %s" % self._node_name)
        if self._check_for_node():
            if self.is_power_on():
                cmd = self._vp_cmd.stop_cmd
                self._run_command(cmd)

        if self.is_power_on():
            self.state = baremetal_states.ERROR
        else:
            self.state = baremetal_states.DELETED
        return self.state

    def is_power_on(self):
        LOG.debug("Checking if %s is running" % self._node_name)

        if not self._check_for_node():
            err_msg = _('Node "%(name)s" with MAC address %(mac)s not found.')
            LOG.error(err_msg, {'name': self._node_name,
                                'mac': self._mac_addresses})
            # in our case the _node_name is the the node_id
            raise exception.NodeNotFound(node_id=self._node_name)

        cmd = self._vp_cmd.list_running_cmd
        running_node_list = self._run_command(cmd)

        for node in running_node_list:
            if self._matched_name in node:
                return True
        return False

    def start_console(self):
        pass

    def stop_console(self):
        pass

    def _run_command(self, cmd, check_exit_code=True):
        """Run a remote command using an active ssh connection.

        :param command: String with the command to run.

        If {_NodeName_} is in the command it will get replaced by
        the _matched_name value.

        base_cmd will also get prepended to the command.
        """
        self._set_connection()

        cmd = cmd.replace('{_NodeName_}', self._matched_name)

        cmd = '%s %s' % (self._vp_cmd.base_cmd, cmd)

        try:
            stdout, stderr = processutils.ssh_execute(
                self._connection, cmd, check_exit_code=check_exit_code)
            result = stdout.strip().splitlines()
            LOG.debug('Result for run_command: %s' % result)
        except processutils.ProcessExecutionError:
            result = []
            LOG.exception("Error running command: %s" % cmd)
        return result
