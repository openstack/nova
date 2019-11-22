# Copyright 2015, 2017 IBM Corp.
#
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
import os
import tempfile

from oslo_log import log as logging
from oslo_utils import excutils
from pypowervm import const as pvm_const
from pypowervm.tasks import scsi_mapper as tsk_map
from pypowervm.tasks import storage as tsk_stg
from pypowervm.tasks import vopt as tsk_vopt
from pypowervm import util as pvm_util
from pypowervm.wrappers import storage as pvm_stg
from pypowervm.wrappers import virtual_io_server as pvm_vios
import retrying
from taskflow import task

from nova.api.metadata import base as instance_metadata
from nova.network import model as network_model
from nova.virt import configdrive
from nova.virt.powervm import vm


LOG = logging.getLogger(__name__)

_LLA_SUBNET = "fe80::/64"
# TODO(efried): CONF these (maybe)
_VOPT_VG = 'rootvg'
_VOPT_SIZE_GB = 1


class ConfigDrivePowerVM(object):

    def __init__(self, adapter):
        """Creates the config drive manager for PowerVM.

        :param adapter: The pypowervm adapter to communicate with the system.
        """
        self.adapter = adapter

        # Validate that the virtual optical exists
        self.vios_uuid, self.vg_uuid = tsk_vopt.validate_vopt_repo_exists(
            self.adapter, vopt_media_volume_group=_VOPT_VG,
            vopt_media_rep_size=_VOPT_SIZE_GB)

    @staticmethod
    def _sanitize_network_info(network_info):
        """Will sanitize the network info for the config drive.

        Newer versions of cloud-init look at the vif type information in
        the network info and utilize it to determine what to do.  There are
        a limited number of vif types, and it seems to be built on the idea
        that the neutron vif type is the cloud init vif type (which is not
        quite right).

        This sanitizes the network info that gets passed into the config
        drive to work properly with cloud-inits.
        """
        network_info = copy.deepcopy(network_info)

        # OVS is the only supported vif type. All others (SEA, PowerVM SR-IOV)
        # will default to generic vif.
        for vif in network_info:
            if vif.get('type') != 'ovs':
                LOG.debug('Changing vif type from %(type)s to vif for vif '
                          '%(id)s.', {'type': vif.get('type'),
                                      'id': vif.get('id')})
                vif['type'] = 'vif'
        return network_info

    def _create_cfg_dr_iso(self, instance, injected_files, network_info,
                           iso_path, admin_pass=None):
        """Creates an ISO file that contains the injected files.

        Used for config drive.

        :param instance: The VM instance from OpenStack.
        :param injected_files: A list of file paths that will be injected into
                               the ISO.
        :param network_info: The network_info from the nova spawn method.
        :param iso_path: The absolute file path for the new ISO
        :param admin_pass: Optional password to inject for the VM.
        """
        LOG.info("Creating config drive.", instance=instance)
        extra_md = {}
        if admin_pass is not None:
            extra_md['admin_pass'] = admin_pass

        # Sanitize the vifs for the network config
        network_info = self._sanitize_network_info(network_info)

        inst_md = instance_metadata.InstanceMetadata(instance,
                                                     content=injected_files,
                                                     extra_md=extra_md,
                                                     network_info=network_info)

        with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
            LOG.info("Config drive ISO being built in %s.", iso_path,
                     instance=instance)

            # There may be an OSError exception when create the config drive.
            # If so, retry the operation before raising.
            @retrying.retry(retry_on_exception=lambda exc: isinstance(
                exc, OSError), stop_max_attempt_number=2)
            def _make_cfg_drive(iso_path):
                cdb.make_drive(iso_path)

            try:
                _make_cfg_drive(iso_path)
            except OSError:
                with excutils.save_and_reraise_exception(logger=LOG):
                    LOG.exception("Config drive ISO could not be built",
                                  instance=instance)

    def create_cfg_drv_vopt(self, instance, injected_files, network_info,
                            stg_ftsk, admin_pass=None, mgmt_cna=None):
        """Create the config drive virtual optical and attach to VM.

        :param instance: The VM instance from OpenStack.
        :param injected_files: A list of file paths that will be injected into
                               the ISO.
        :param network_info: The network_info from the nova spawn method.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        :param admin_pass: (Optional) password to inject for the VM.
        :param mgmt_cna: (Optional) The management (RMC) CNA wrapper.
        """
        # If there is a management client network adapter, then we should
        # convert that to a VIF and add it to the network info
        if mgmt_cna is not None:
            network_info = copy.deepcopy(network_info)
            network_info.append(self._mgmt_cna_to_vif(mgmt_cna))

        # Pick a file name for when we upload the media to VIOS
        file_name = pvm_util.sanitize_file_name_for_api(
            instance.uuid.replace('-', ''), prefix='cfg_', suffix='.iso',
            max_len=pvm_const.MaxLen.VOPT_NAME)

        # Create and upload the media
        with tempfile.NamedTemporaryFile(mode='rb') as fh:
            self._create_cfg_dr_iso(instance, injected_files, network_info,
                                    fh.name, admin_pass=admin_pass)
            vopt, f_uuid = tsk_stg.upload_vopt(
                self.adapter, self.vios_uuid, fh, file_name,
                os.path.getsize(fh.name))

        # Define the function to build and add the mapping
        def add_func(vios_w):
            LOG.info("Adding cfg drive mapping to Virtual I/O Server %s.",
                     vios_w.name, instance=instance)
            mapping = tsk_map.build_vscsi_mapping(
                None, vios_w, vm.get_pvm_uuid(instance), vopt)
            return tsk_map.add_map(vios_w, mapping)

        # Add the subtask to create the mapping when the FeedTask runs
        stg_ftsk.wrapper_tasks[self.vios_uuid].add_functor_subtask(add_func)

    def _mgmt_cna_to_vif(self, cna):
        """Converts the mgmt CNA to VIF format for network injection."""
        mac = vm.norm_mac(cna.mac)
        ipv6_link_local = self._mac_to_link_local(mac)

        subnet = network_model.Subnet(
            version=6, cidr=_LLA_SUBNET,
            ips=[network_model.FixedIP(address=ipv6_link_local)])
        network = network_model.Network(id='mgmt', subnets=[subnet],
                                        injected='yes')
        return network_model.VIF(id='mgmt_vif', address=mac,
                                 network=network)

    @staticmethod
    def _mac_to_link_local(mac):
        # Convert the address to IPv6.  The first step is to separate out the
        # mac address
        splits = mac.split(':')

        # Create EUI-64 id per RFC 4291 Appendix A
        splits.insert(3, 'ff')
        splits.insert(4, 'fe')

        # Create modified EUI-64 id via bit flip per RFC 4291 Appendix A
        splits[0] = "%.2x" % (int(splits[0], 16) ^ 0b00000010)

        # Convert to the IPv6 link local format.  The prefix is fe80::.  Join
        # the hexes together at every other digit.
        ll = ['fe80:']
        ll.extend([splits[x] + splits[x + 1]
                   for x in range(0, len(splits), 2)])
        return ':'.join(ll)

    def dlt_vopt(self, instance, stg_ftsk):
        """Deletes the virtual optical and scsi mappings for a VM.

        :param instance: The nova instance whose VOpt(s) are to be removed.
        :param stg_ftsk: A FeedTask. The actions to modify the storage will be
                         added as batched functions onto the FeedTask.
        """
        lpar_uuid = vm.get_pvm_uuid(instance)

        # The matching function for find_maps, remove_maps
        match_func = tsk_map.gen_match_func(pvm_stg.VOptMedia)

        # Add a function to remove the mappings
        stg_ftsk.wrapper_tasks[self.vios_uuid].add_functor_subtask(
            tsk_map.remove_maps, lpar_uuid, match_func=match_func)

        # Find the VOpt device based from the mappings
        media_mappings = tsk_map.find_maps(
            stg_ftsk.get_wrapper(self.vios_uuid).scsi_mappings,
            client_lpar_id=lpar_uuid, match_func=match_func)
        media_elems = [x.backing_storage for x in media_mappings]

        def rm_vopt():
            LOG.info("Removing virtual optical storage.",
                     instance=instance)
            vg_wrap = pvm_stg.VG.get(self.adapter, uuid=self.vg_uuid,
                                     parent_type=pvm_vios.VIOS,
                                     parent_uuid=self.vios_uuid)
            tsk_stg.rm_vg_storage(vg_wrap, vopts=media_elems)

        # Add task to remove the media if it exists
        if media_elems:
            stg_ftsk.add_post_execute(task.FunctorTask(rm_vopt))
