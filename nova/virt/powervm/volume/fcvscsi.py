# Copyright 2015, 2018 IBM Corp.
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

from oslo_concurrency import lockutils
from oslo_log import log as logging
from pypowervm import const as pvm_const
from pypowervm.tasks import hdisk
from pypowervm.tasks import partition as pvm_tpar
from pypowervm.tasks import scsi_mapper as tsk_map
from pypowervm.utils import transaction as pvm_tx
from pypowervm.wrappers import storage as pvm_stor
from pypowervm.wrappers import virtual_io_server as pvm_vios
import six
from taskflow import task

from nova import conf as cfg
from nova import exception as exc
from nova.i18n import _
from nova.virt import block_device
from nova.virt.powervm import vm


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

LOCAL_FEED_TASK = 'local_feed_task'
UDID_KEY = 'target_UDID'

# A global variable that will cache the physical WWPNs on the system.
_vscsi_pfc_wwpns = None


@lockutils.synchronized('vscsi_wwpns')
def wwpns(adapter):
    """Builds the WWPNs of the adapters that will connect the ports.

    :return: The list of WWPNs that need to be included in the zone set.
    """
    return pvm_tpar.get_physical_wwpns(adapter, force_refresh=False)


class FCVscsiVolumeAdapter(object):

    def __init__(self, adapter, instance, connection_info, stg_ftsk=None):
        """Initialize the PowerVMVolumeAdapter

        :param adapter: The pypowervm adapter.
        :param instance: The nova instance that the volume should attach to.
        :param connection_info: The volume connection info generated from the
                                BDM. Used to determine how to attach the
                                volume to the VM.
        :param stg_ftsk: (Optional) The pypowervm transaction FeedTask for the
                         I/O Operations.  If provided, the Virtual I/O Server
                         mapping updates will be added to the FeedTask.  This
                         defers the updates to some later point in time.  If
                         the FeedTask is not provided, the updates will be run
                         immediately when the respective method is executed.
        """
        self.adapter = adapter
        self.instance = instance
        self.connection_info = connection_info
        self.vm_uuid = vm.get_pvm_uuid(instance)
        self.reset_stg_ftsk(stg_ftsk=stg_ftsk)
        self._pfc_wwpns = None

    @property
    def volume_id(self):
        """Method to return the volume id.

        Every driver must implement this method if the default impl will
        not work for their data.
        """
        return block_device.get_volume_id(self.connection_info)

    def reset_stg_ftsk(self, stg_ftsk=None):
        """Resets the pypowervm transaction FeedTask to a new value.

        The previous updates from the original FeedTask WILL NOT be migrated
        to this new FeedTask.

        :param stg_ftsk: (Optional) The pypowervm transaction FeedTask for the
                         I/O Operations.  If provided, the Virtual I/O Server
                         mapping updates will be added to the FeedTask.  This
                         defers the updates to some later point in time.  If
                         the FeedTask is not provided, the updates will be run
                         immediately when this method is executed.
        """
        if stg_ftsk is None:
            getter = pvm_vios.VIOS.getter(
                self.adapter, xag=[pvm_const.XAG.VIO_SMAP])
            self.stg_ftsk = pvm_tx.FeedTask(LOCAL_FEED_TASK, getter)
        else:
            self.stg_ftsk = stg_ftsk

    def _set_udid(self, udid):
        """This method will set the hdisk udid in the connection_info.

        :param udid: The hdisk target_udid to be stored in system_metadata
        """
        self.connection_info['data'][UDID_KEY] = udid

    def _get_udid(self):
        """This method will return the hdisk udid stored in connection_info.

        :return: The target_udid associated with the hdisk
        """
        try:
            return self.connection_info['data'][UDID_KEY]
        except (KeyError, ValueError):
            # It's common to lose our specific data in the BDM.  The connection
            # information can be 'refreshed' by operations like live migrate
            # and resize
            LOG.info('Failed to retrieve target_UDID key from BDM for volume '
                     'id %s', self.volume_id, instance=self.instance)
            return None

    def attach_volume(self):
        """Attaches the volume."""

        # Check if the VM is in a state where the attach is acceptable.
        lpar_w = vm.get_instance_wrapper(self.adapter, self.instance)
        capable, reason = lpar_w.can_modify_io()
        if not capable:
            raise exc.VolumeAttachFailed(
                volume_id=self.volume_id, reason=reason)

        # Its about to get weird.  The transaction manager has a list of
        # VIOSes.  We could use those, but they only have SCSI mappings (by
        # design).  They do not have storage (super expensive).
        #
        # We need the storage xag when we are determining which mappings to
        # add to the system.  But we don't want to tie it to the stg_ftsk.  If
        # we do, every retry, every etag gather, etc... takes MUCH longer.
        #
        # So we get the VIOSes with the storage xag here, separately, to save
        # the stg_ftsk from potentially having to run it multiple times.
        attach_ftsk = pvm_tx.FeedTask(
            'attach_volume_to_vio', pvm_vios.VIOS.getter(
                self.adapter, xag=[pvm_const.XAG.VIO_STOR,
                                   pvm_const.XAG.VIO_SMAP]))

        # Find valid hdisks and map to VM.
        attach_ftsk.add_functor_subtask(
            self._attach_volume_to_vio, provides='vio_modified',
            flag_update=False)

        ret = attach_ftsk.execute()

        # Check the number of VIOSes
        vioses_modified = 0
        for result in ret['wrapper_task_rets'].values():
            if result['vio_modified']:
                vioses_modified += 1

        # Validate that a vios was found
        if vioses_modified == 0:
            msg = (_('Failed to discover valid hdisk on any Virtual I/O '
                     'Server for volume %(volume_id)s.') %
                   {'volume_id': self.volume_id})
            ex_args = {'volume_id': self.volume_id, 'reason': msg}
            raise exc.VolumeAttachFailed(**ex_args)

        self.stg_ftsk.execute()

    def _attach_volume_to_vio(self, vios_w):
        """Attempts to attach a volume to a given VIO.

        :param vios_w: The Virtual I/O Server wrapper to attach to.
        :return: True if the volume was attached.  False if the volume was
                 not (could be the Virtual I/O Server does not have
                 connectivity to the hdisk).
        """
        status, device_name, udid = self._discover_volume_on_vios(vios_w)

        if hdisk.good_discovery(status, device_name):
            # Found a hdisk on this Virtual I/O Server.  Add the action to
            # map it to the VM when the stg_ftsk is executed.
            with lockutils.lock(self.volume_id):
                self._add_append_mapping(vios_w.uuid, device_name,
                tag=self.volume_id)

            # Save the UDID for the disk in the connection info.  It is
            # used for the detach.
            self._set_udid(udid)
            LOG.debug('Added deferred task to attach device %(device_name)s '
                      'to vios %(vios_name)s.',
                      {'device_name': device_name, 'vios_name': vios_w.name},
                      instance=self.instance)

            # Valid attachment
            return True

        return False

    def extend_volume(self):
        # The compute node does not need to take any additional steps for the
        # client to see the extended volume.
        pass

    def _discover_volume_on_vios(self, vios_w):
        """Discovers an hdisk on a single vios for the volume.

        :param vios_w: VIOS wrapper to process
        :returns: Status of the volume or None
        :returns: Device name or None
        :returns: UDID or None
        """
        # Get the initiatior WWPNs, targets and Lun for the given VIOS.
        vio_wwpns, t_wwpns, lun = self._get_hdisk_itls(vios_w)

        # Build the ITL map and discover the hdisks on the Virtual I/O
        # Server (if any).
        itls = hdisk.build_itls(vio_wwpns, t_wwpns, lun)
        if len(itls) == 0:
            LOG.debug('No ITLs for VIOS %(vios)s for volume %(volume_id)s.',
                      {'vios': vios_w.name, 'volume_id': self.volume_id},
                      instance=self.instance)
            return None, None, None

        status, device_name, udid = hdisk.discover_hdisk(self.adapter,
                                                         vios_w.uuid, itls)

        if hdisk.good_discovery(status, device_name):
            LOG.info('Discovered %(hdisk)s on vios %(vios)s for volume '
                     '%(volume_id)s. Status code: %(status)s.',
                     {'hdisk': device_name, 'vios': vios_w.name,
                      'volume_id': self.volume_id, 'status': status},
                     instance=self.instance)
        elif status == hdisk.LUAStatus.DEVICE_IN_USE:
            LOG.warning('Discovered device %(dev)s for volume %(volume)s '
                        'on %(vios)s is in use. Error code: %(status)s.',
                        {'dev': device_name, 'volume': self.volume_id,
                         'vios': vios_w.name, 'status': status},
                        instance=self.instance)

        return status, device_name, udid

    def _get_hdisk_itls(self, vios_w):
        """Returns the mapped ITLs for the hdisk for the given VIOS.

        A PowerVM system may have multiple Virtual I/O Servers to virtualize
        the I/O to the virtual machines. Each Virtual I/O server may have their
        own set of initiator WWPNs, target WWPNs and Lun on which hdisk is
        mapped. It will determine and return the ITLs for the given VIOS.

        :param vios_w: A virtual I/O Server wrapper.
        :return: List of the i_wwpns that are part of the vios_w,
        :return: List of the t_wwpns that are part of the vios_w,
        :return: Target lun id of the hdisk for the vios_w.
        """
        it_map = self.connection_info['data']['initiator_target_map']
        i_wwpns = it_map.keys()

        active_wwpns = vios_w.get_active_pfc_wwpns()
        vio_wwpns = [x for x in i_wwpns if x in active_wwpns]

        t_wwpns = []
        for it_key in vio_wwpns:
            t_wwpns.extend(it_map[it_key])
        lun = self.connection_info['data']['target_lun']

        return vio_wwpns, t_wwpns, lun

    def _add_append_mapping(self, vios_uuid, device_name, tag=None):
        """Update the stg_ftsk to append the mapping to the VIOS.

        :param vios_uuid: The UUID of the vios for the pypowervm adapter.
        :param device_name: The The hdisk device name.
        :param tag: String tag to set on the physical volume.
        """
        def add_func(vios_w):
            LOG.info("Adding vSCSI mapping to Physical Volume %(dev)s on "
                     "vios %(vios)s.",
                     {'dev': device_name, 'vios': vios_w.name},
                     instance=self.instance)
            pv = pvm_stor.PV.bld(self.adapter, device_name, tag=tag)
            v_map = tsk_map.build_vscsi_mapping(None, vios_w, self.vm_uuid, pv)
            return tsk_map.add_map(vios_w, v_map)
        self.stg_ftsk.wrapper_tasks[vios_uuid].add_functor_subtask(add_func)

    def detach_volume(self):
        """Detach the volume."""

        # Check if the VM is in a state where the detach is acceptable.
        lpar_w = vm.get_instance_wrapper(self.adapter, self.instance)
        capable, reason = lpar_w.can_modify_io()
        if not capable:
            raise exc.VolumeDetachFailed(
                volume_id=self.volume_id, reason=reason)

        # Run the detach
        try:
            # See logic in attach_volume for why this new FeedTask is here.
            detach_ftsk = pvm_tx.FeedTask(
                'detach_volume_from_vio', pvm_vios.VIOS.getter(
                    self.adapter, xag=[pvm_const.XAG.VIO_STOR,
                                       pvm_const.XAG.VIO_SMAP]))
            # Find hdisks to detach
            detach_ftsk.add_functor_subtask(
                self._detach_vol_for_vio, provides='vio_modified',
                flag_update=False)

            ret = detach_ftsk.execute()

            # Warn if no hdisks detached.
            if not any([result['vio_modified']
                        for result in ret['wrapper_task_rets'].values()]):
                LOG.warning("Detach Volume: Failed to detach the "
                            "volume %(volume_id)s on ANY of the Virtual "
                            "I/O Servers.", {'volume_id': self.volume_id},
                            instance=self.instance)

        except Exception as e:
            LOG.exception('PowerVM error detaching volume from virtual '
                          'machine.', instance=self.instance)
            ex_args = {'volume_id': self.volume_id, 'reason': six.text_type(e)}
            raise exc.VolumeDetachFailed(**ex_args)
        self.stg_ftsk.execute()

    def _detach_vol_for_vio(self, vios_w):
        """Removes the volume from a specific Virtual I/O Server.

        :param vios_w: The VIOS wrapper.
        :return: True if a remove action was done against this VIOS.  False
                 otherwise.
        """
        LOG.debug("Detach volume %(vol)s from vios %(vios)s",
                  dict(vol=self.volume_id, vios=vios_w.name),
                  instance=self.instance)
        device_name = None
        udid = self._get_udid()
        try:
            if udid:
                # This will only work if vios_w has the Storage XAG.
                device_name = vios_w.hdisk_from_uuid(udid)

            if not udid or not device_name:
                # We lost our bdm data. We'll need to discover it.
                status, device_name, udid = self._discover_volume_on_vios(
                    vios_w)

                # Check if the hdisk is in a bad state in the I/O Server.
                # Subsequent scrub code on future deploys will clean this up.
                if not hdisk.good_discovery(status, device_name):
                    LOG.warning(
                        "Detach Volume: The backing hdisk for volume "
                        "%(volume_id)s on Virtual I/O Server %(vios)s is "
                        "not in a valid state.  This may be the result of "
                        "an evacuate.",
                        {'volume_id': self.volume_id, 'vios': vios_w.name},
                        instance=self.instance)
                    return False

        except Exception:
            LOG.exception(
                "Detach Volume: Failed to find disk on Virtual I/O "
                "Server %(vios_name)s for volume %(volume_id)s. Volume "
                "UDID: %(volume_uid)s.",
                {'vios_name': vios_w.name, 'volume_id': self.volume_id,
                 'volume_uid': udid, }, instance=self.instance)
            return False

        # We have found the device name
        LOG.info("Detach Volume: Discovered the device %(hdisk)s "
                 "on Virtual I/O Server %(vios_name)s for volume "
                 "%(volume_id)s.  Volume UDID: %(volume_uid)s.",
                 {'hdisk': device_name, 'vios_name': vios_w.name,
                  'volume_id': self.volume_id, 'volume_uid': udid},
                 instance=self.instance)

        # Add the action to remove the mapping when the stg_ftsk is run.
        partition_id = vm.get_vm_qp(self.adapter, self.vm_uuid,
                                    qprop='PartitionID')

        with lockutils.lock(self.volume_id):
            self._add_remove_mapping(partition_id, vios_w.uuid,
                                     device_name)

            # Add a step to also remove the hdisk
            self._add_remove_hdisk(vios_w, device_name)

        # Found a valid element to remove
        return True

    def _add_remove_mapping(self, vm_uuid, vios_uuid, device_name):
        """Adds a subtask to remove the storage mapping.

        :param vm_uuid: The UUID of the VM instance
        :param vios_uuid: The UUID of the vios for the pypowervm adapter.
        :param device_name: The The hdisk device name.
        """
        def rm_func(vios_w):
            LOG.info("Removing vSCSI mapping from physical volume %(dev)s "
                     "on vios %(vios)s",
                     {'dev': device_name, 'vios': vios_w.name},
                     instance=self.instance)
            removed_maps = tsk_map.remove_maps(
                vios_w, vm_uuid,
                tsk_map.gen_match_func(pvm_stor.PV, names=[device_name]))
            return removed_maps
        self.stg_ftsk.wrapper_tasks[vios_uuid].add_functor_subtask(rm_func)

    def _add_remove_hdisk(self, vio_wrap, device_name):
        """Adds a post-mapping task to remove the hdisk from the VIOS.

        This removal is only done after the mapping updates have completed.

        :param vio_wrap: The Virtual I/O Server wrapper to remove the disk
                         from.
        :param device_name: The hdisk name to remove.
        """
        def rm_hdisk():
            LOG.info("Removing hdisk %(hdisk)s from Virtual I/O Server "
                     "%(vios)s", {'hdisk': device_name, 'vios': vio_wrap.name},
                     instance=self.instance)
            try:
                # Attempt to remove the hDisk
                hdisk.remove_hdisk(self.adapter, CONF.host, device_name,
                                   vio_wrap.uuid)
            except Exception:
                # If there is a failure, log it, but don't stop the process
                LOG.exception("There was an error removing the hdisk "
                              "%(disk)s from Virtual I/O Server %(vios)s.",
                              {'disk': device_name, 'vios': vio_wrap.name},
                              instance=self.instance)

        # Check if there are not multiple mapping for the device
        if not self._check_host_mappings(vio_wrap, device_name):
            name = 'rm_hdisk_%s_%s' % (vio_wrap.name, device_name)
            self.stg_ftsk.add_post_execute(task.FunctorTask(
                rm_hdisk, name=name))
        else:
            LOG.info("hdisk %(disk)s is not removed from Virtual I/O Server "
                     "%(vios)s because it has existing storage mappings",
                     {'disk': device_name, 'vios': vio_wrap.name},
                     instance=self.instance)

    def _check_host_mappings(self, vios_wrap, device_name):
        """Checks if the given hdisk has multiple mappings

        :param vio_wrap: The Virtual I/O Server wrapper to remove the disk
                         from.
        :param device_name: The hdisk name to remove.
        :return: True if there are multiple instances using the given hdisk
        """
        vios_scsi_mappings = next(v.scsi_mappings for v in self.stg_ftsk.feed
                                  if v.uuid == vios_wrap.uuid)
        mappings = tsk_map.find_maps(
            vios_scsi_mappings, None,
            tsk_map.gen_match_func(pvm_stor.PV, names=[device_name]))

        LOG.debug("%(num)d storage mapping(s) found for %(dev)s on VIOS "
                  "%(vios)s", {'num': len(mappings), 'dev': device_name,
                               'vios': vios_wrap.name}, instance=self.instance)
        # The mapping is still present as the task feed removes it later.
        return len(mappings) > 1
