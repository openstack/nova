# Copyright 2013 Cloudbase Solutions Srl
# Copyright 2013 Pedro Navarro Perez
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

import os_vif
from os_win import utilsfactory

import nova.conf
from nova import exception
from nova.i18n import _
from nova.network import model
from nova.network import os_vif_util

CONF = nova.conf.CONF


class HyperVVIFDriver(object):
    def __init__(self):
        self._netutils = utilsfactory.get_networkutils()

    def plug(self, instance, vif):
        vif_type = vif['type']
        if vif_type == model.VIF_TYPE_HYPERV:
            # neutron takes care of plugging the port
            pass
        elif vif_type == model.VIF_TYPE_OVS:
            vif = os_vif_util.nova_to_osvif_vif(vif)
            instance = os_vif_util.nova_to_osvif_instance(instance)

            # NOTE(claudiub): the vNIC has to be connected to a vSwitch
            # before the ovs port is created.
            self._netutils.connect_vnic_to_vswitch(CONF.hyperv.vswitch_name,
                                                   vif.id)
            os_vif.plug(vif, instance)
        else:
            reason = _("Failed to plug virtual interface: "
                       "unexpected vif_type=%s") % vif_type
            raise exception.VirtualInterfacePlugException(reason)

    def unplug(self, instance, vif):
        vif_type = vif['type']
        if vif_type == model.VIF_TYPE_HYPERV:
            # neutron takes care of unplugging the port
            pass
        elif vif_type == model.VIF_TYPE_OVS:
            vif = os_vif_util.nova_to_osvif_vif(vif)
            instance = os_vif_util.nova_to_osvif_instance(instance)
            os_vif.unplug(vif, instance)
        else:
            reason = _("unexpected vif_type=%s") % vif_type
            raise exception.VirtualInterfaceUnplugException(reason=reason)
