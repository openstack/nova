# Copyright (c) 2015 Umea University
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

import copy

from oslo.config import cfg

from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.network import linux_net
from nova.network import model as network_model
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import utils
from nova.virt.libvirt import designer
from nova.virt.libvirt import vif as libvirt_vif

LOG = logging.getLogger(__name__)


neutron_opts = [
    # TODO(Luis Tomas) temporary hack until Neutron can pass over the
    # name of the bridge mappings it is configured with
    cfg.StrOpt('ovs_bridge_mappings',
               default='br-enp4s0d1',
               help='Name of bridge mappings used by Open vSwitch',
               deprecated_group='DEFAULT')
]

CONF = cfg.CONF
# neutron_opts options in the DEFAULT group were deprecated in Juno
CONF.register_opts(neutron_opts, 'neutron')


class LibvirtCOLOVIFDriver(libvirt_vif.LibvirtGenericVIFDriver):

    def __init__(self, get_connection):
        super(LibvirtCOLOVIFDriver, self).__init__(get_connection)

    def get_ext_bridge_name(self):
        # needs to be updated
        return CONF.neutron.ovs_bridge_mappings

    def get_colo_br_name(self, iface_id):
        return ("cqbr" + iface_id)[:network_model.NIC_NAME_LEN]

    def get_colo_veth_pair_names(self, iface_id):
        return (("cqvb%s" % iface_id)[:network_model.NIC_NAME_LEN],
                ("cqvo%s" % iface_id)[:network_model.NIC_NAME_LEN])

    def get_colo_forward(self, vif):
        return vif['network'].get('colo_forward', None)

    def get_colo_failover(self, vif):
        return vif['network'].get('colo_failover', None)

    def get_config_bridge(self, instance, vif, image_meta,
                          inst_type, virt_type):
        conf = super(LibvirtCOLOVIFDriver, self).get_config_bridge(instance,
                                                                   vif,
                                                                   image_meta,
                                                                   inst_type,
                                                                   virt_type)

        designer.set_vif_colo_config(conf, self.get_colo_forward(vif),
                                     self.get_colo_failover(vif))

        return conf

    def get_config_ovs_bridge(self, instance, vif, image_meta, inst_type,
                              virt_type):
        raise NotImplementedError()

    def get_config_ovs_hybrid(self, instance, vif, image_meta,
                              inst_type, virt_type):
        _vif = copy.deepcopy(vif)
        _vif['network']['bridge'] = self.get_br_name(vif['id'])

        if utils.ft_enabled(instance):
            colo_forward, _ = self.get_colo_veth_pair_names(vif['id'])
            _vif['network']['colo_forward'] = colo_forward

            if utils.ft_secondary(instance):
                _vif['network']['colo_failover'] = _vif['network']['bridge']
                _vif['network']['bridge'] = self.get_colo_br_name(vif['id'])

        return self.get_config_bridge(instance, _vif, image_meta,
                                      inst_type, virt_type)

    def get_config_ivs_hybrid(self, instance, vif, image_meta, inst_type,
                              virt_type):
        raise NotImplementedError()

    def get_config_ivs_ethernet(self, instance, vif, image_meta, inst_type,
                                virt_type):
        raise NotImplementedError()

    def get_config_802qbg(self, instance, vif, image_meta, inst_type,
                          virt_type):
        raise NotImplementedError()

    def get_config_802qbh(self, instance, vif, image_meta, inst_type,
                          virt_type):
        raise NotImplementedError()

    def get_config_hw_veb(self, instance, vif, image_meta, inst_type,
                          virt_type):
        raise NotImplementedError()

    def get_config_iovisor(self, instance, vif, image_meta, inst_type,
                           virt_type):
        raise NotImplementedError()

    def get_config_midonet(self, instance, vif, image_meta, inst_type,
                           virt_type):
        raise NotImplementedError()

    def get_config_mlnx_direct(self, instance, vif, image_meta, inst_type,
                               virt_type):
        raise NotImplementedError()

    def plug_bridge(self, instance, vif):
        raise NotImplementedError()

    def plug_ovs_bridge(self, instance, vif):
        raise NotImplementedError()

    def plug_ovs_hybrid_colo(self, instance, vif):
        """Plug using hybrid stragegy

        Create the extra veth and bridge devices needed for enabling
        COLO fault tolerance support
        """
        iface_id = self.get_ovs_interfaceid(vif)
        colo_v1_name, colo_v2_name = self.get_colo_veth_pair_names(vif['id'])

        ft_secondary = utils.ft_secondary(instance)
        if ft_secondary:
            colo_br_name = self.get_colo_br_name(vif['id'])

            if not linux_net.device_exists(colo_br_name):
                utils.execute('brctl', 'addbr', colo_br_name, run_as_root=True)
                utils.execute('brctl', 'setfd', colo_br_name, 0,
                              run_as_root=True)
                utils.execute('brctl', 'stp', colo_br_name, 'off',
                              run_as_root=True)
                utils.execute('tee',
                              ('/sys/class/net/%s/bridge/multicast_snooping' %
                               colo_br_name),
                              process_input='0',
                              run_as_root=True,
                              check_exit_code=[0, 1])

                utils.execute('ip', 'link', 'set', colo_br_name, 'up',
                              run_as_root=True)

        if not linux_net.device_exists(colo_v2_name):
            linux_net._create_veth_pair(colo_v1_name, colo_v2_name)
            if ft_secondary:
                utils.execute('brctl', 'addif', colo_br_name,
                              colo_v1_name, run_as_root=True)

            colo_vlan_id = instance.system_metadata['colo_vlan_id']
            linux_net.create_ovs_vif_port_colo(self.get_ext_bridge_name(),
                                               colo_v2_name, colo_vlan_id)

    def plug_ovs_hybrid(self, instance, vif):
        super(LibvirtCOLOVIFDriver, self).plug_ovs_hybrid(instance, vif)

        if utils.ft_enabled(instance):
            self.plug_ovs_hybrid_colo(instance, vif)

    def plug_ivs_ethernet(self, instance, vif):
        raise NotImplementedError()

    def plug_ivs_hybrid(self, instance, vif):
        raise NotImplementedError()

    def plug_mlnx_direct(self, instance, vif):
        raise NotImplementedError()

    def plug_802qbg(self, instance, vif):
        raise NotImplementedError()

    def plug_802qbh(self, instance, vif):
        raise NotImplementedError()

    def plug_hw_veb(self, instance, vif):
        raise NotImplementedError()

    def plug_midonet(self, instance, vif):
        raise NotImplementedError()

    def plug_iovisor(self, instance, vif):
        raise NotImplementedError()

    def unplug_bridge(self, instance, vif):
        raise NotImplementedError()

    def unplug_ovs_bridge(self, instance, vif):
        raise NotImplementedError()

    def unplug_ovs_hybrid_colo(self, instance, vif):
        """UnPlug using hybrid strategy

        Extra unpluging actions needed for COLO integration.
        Unkook extra port from OVS, unkook extra port from bridge,
        delete extra bridge, and delete both extra veth devices.
        Extra actions for the secondary VM with regards to the primary.
        """
        try:
            colo_v1_name, colo_v2_name = self.get_colo_veth_pair_names(
                                                  vif['id'])

            if utils.ft_secondary(instance):
                colo_br_name = self.get_colo_br_name(vif['id'])

                if linux_net.device_exists(colo_br_name):
                    utils.execute('brctl', 'delif', colo_br_name, colo_v1_name,
                                  run_as_root=True)
                    utils.execute('ip', 'link', 'set', colo_br_name, 'down',
                                  run_as_root=True)
                    utils.execute('brctl', 'delbr', colo_br_name,
                                  run_as_root=True)

            linux_net.delete_ovs_vif_port(self.get_ext_bridge_name(),
                                          colo_v2_name)
        except processutils.ProcessExecutionError:
            LOG.exception(_LE("Failed while unplugging vif"),
                          instance=instance)

    def unplug_ovs_hybrid(self, instance, vif):
        super(LibvirtCOLOVIFDriver, self).unplug_ovs_hybrid(instance, vif)

        if utils.ft_enabled(instance):
            self.unplug_ovs_hybrid_colo(instance, vif)

    def unplug_ivs_ethernet(self, instance, vif):
        raise NotImplementedError()

    def unplug_ivs_hybrid(self, instance, vif):
        raise NotImplementedError()

    def unplug_mlnx_direct(self, instance, vif):
        raise NotImplementedError()

    def unplug_802qbg(self, instance, vif):
        raise NotImplementedError()

    def unplug_802qbh(self, instance, vif):
        raise NotImplementedError()

    def unplug_hw_veb(self, instance, vif):
        raise NotImplementedError()

    def unplug_midonet(self, instance, vif):
        raise NotImplementedError()

    def unplug_iovisor(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_ovs(self, instance, vif):
        if self.get_firewall_required(vif) or vif.is_hybrid_plug_enabled():
            self.unplug_ovs_hybrid_colo(instance, vif)
        else:
            raise NotImplementedError()

    def cleanup_colo_plug_ivs(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_mlnx_direct(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_802qbg(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_802qbh(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_hw_veb(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_midonet(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug_iovisor(self, instance, vif):
        raise NotImplementedError()

    def cleanup_colo_plug(self, instance, vif):
        """ Cleans up the extra plugs needed for COLO integration

        This function is call when a failover is triggered and (only) the
        extra veth and bridge devices need to be unplugged
        """

        vif_type = vif['type']

        if vif_type is None:
            raise exception.NovaException(
                _("vif_type parameter must be present "
                  "for this vif_driver implementation"))
        vif_slug = self._normalize_vif_type(vif_type)
        func = getattr(self, 'cleanup_colo_plug_%s' % vif_slug, None)
        if not func:
            raise exception.NovaException(
                _("Unexpected vif_type=%s") % vif_type)

        func(instance, vif)

    # TODO(ORBIT): Temporary
    def colo_generate_proxy_script(self, instance, vif, path):
        tapdev = self.get_vif_devname(vif)
        with open("/opt/qemu/scripts/colo-proxy-script.sh") as f:
            qemu_script = f.read()

        qemu_script = qemu_script.replace("virt_if=$4",
                                          "virt_if=\"" + tapdev + "\"", 1)

        with open(path, "w+") as f:
            f.write(qemu_script)

        import os
        os.chmod(path, 0755)
