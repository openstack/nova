# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat Inc.
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
# iBoot Power Driver

from nova import context as nova_context
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.virt.baremetal import baremetal_states
from nova.virt.baremetal import base

iboot = importutils.try_import('iboot')


LOG = logging.getLogger(__name__)


class IBootManager(base.PowerManager):
    """iBoot Power Driver for Baremetal Nova Compute

    This PowerManager class provides a mechanism for controlling power state
    via an iBoot capable device (tested with an iBoot G2).

    Requires installation of python-iboot:

        https://github.com/darkip/python-iboot

    """
    def __init__(self, **kwargs):
        node = kwargs.pop('node', {})
        addr_relay = str(node['pm_address']).split(',')

        if len(addr_relay) > 1:
            try:
                self.relay_id = int(addr_relay[1])
            except ValueError:
                msg = _("iboot PDU relay ID must be an integer.")
                raise exception.InvalidParameterValue(msg)
        else:
            self.relay_id = 1

        addr_port = addr_relay[0].split(':')
        self.address = addr_port[0]
        if len(addr_port) > 1:
            try:
                self.port = int(addr_port[1])
            except ValueError:
                msg = _("iboot PDU port must be an integer.")
                raise exception.InvalidParameterValue(msg)
        else:
            self.port = 9100

        self.user = str(node['pm_user'])
        self.password = str(node['pm_password'])
        instance = kwargs.pop('instance', {})
        self.node_name = instance.get('hostname', "")
        context = nova_context.get_admin_context()
        self.state = None
        self.conn = None

    def _create_connection(self):
        if not self.conn:
            self.conn = iboot.iBootInterface(self.address, self.user,
                                             self.password, port=self.port,
                                             num_relays=self.relay_id)
        return self.conn

    def _switch(self, relay_id, enabled):
        return self.conn.switch(relay_id, enabled)

    def _get_relay(self, relay_id):
        return self.conn.get_relays()[relay_id - 1]

    def activate_node(self):
        LOG.info(_("activate_node name %s"), self.node_name)
        self._create_connection()
        self._switch(self.relay_id, True)

        if self.is_power_on():
            self.state = baremetal_states.ACTIVE
        else:
            self.state = baremetal_states.ERROR

        return self.state

    def reboot_node(self):
        LOG.info(_("reboot_node: %s"), self.node_name)
        self._create_connection()
        self._switch(self.relay_id, False)
        self._switch(self.relay_id, True)

        if self.is_power_on():
            self.state = baremetal_states.ACTIVE
        else:
            self.state = baremetal_states.ERROR

        return self.state

    def deactivate_node(self):
        LOG.info(_("deactivate_node name %s"), self.node_name)
        self._create_connection()
        if self.is_power_on():
            self._switch(self.relay_id, False)

        if self.is_power_on():
            self.state = baremetal_states.ERROR
        else:
            self.state = baremetal_states.DELETED

        return self.state

    def is_power_on(self):
        LOG.debug(_("Checking if %s is running"), self.node_name)
        self._create_connection()
        return self._get_relay(self.relay_id)
