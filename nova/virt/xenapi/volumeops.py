# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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
Management class for Storage-related functions (attach, detach, etc).
"""
import logging

from twisted.internet import defer

from volume_utils import VolumeHelper
from vm_utils import VMHelper

from novadeps import Volume


class VolumeOps(object):
    def __init__(self, session):
        self._session = session

    @defer.inlineCallbacks
    def attach_volume(self, instance_name, device_path, mountpoint):
        # Before we start, check that the VM exists
        vm_ref = yield VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise Exception('Instance %s does not exist' % instance_name)
        # NOTE: No Resource Pool concept so far
        logging.debug("Attach_volume: %s, %s, %s",
                      instance_name, device_path, mountpoint)
        # Create the iSCSI SR, and the PDB through which hosts access SRs.
        # But first, retrieve target info, like Host, IQN, LUN and SCSIID
        vol_rec = Volume.parse_volume_info(device_path, mountpoint)
        label = 'SR-%s' % vol_rec['volumeId']
        description = 'Disk-for:%s' % instance_name
        # Create SR
        sr_ref = yield VolumeHelper.create_iscsi_storage(self._session,
                                                         vol_rec['targetHost'],
                                                         vol_rec['targetPort'],
                                                         vol_rec['targeIQN'],
                                                         '',  # no CHAP auth
                                                         '',
                                                         label,
                                                         description)
        # Introduce VDI  and attach VBD to VM
        try:
            vdi_ref = yield VolumeHelper.introduce_vdi(self._session, sr_ref)
        except Exception, exc:
            logging.warn(exc)
            yield VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
            raise Exception('Unable to create VDI on SR %s for instance %s'
                            % (sr_ref,
                            instance_name))
        else:
            try:
                vbd_ref = yield VMHelper.create_vbd(self._session,
                                                    vm_ref, vdi_ref,
                                                    vol_rec['deviceNumber'],
                                                    False)
            except Exception, exc:
                logging.warn(exc)
                yield VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
                raise Exception('Unable to create VBD on SR %s for instance %s'
                            % (sr_ref,
                            instance_name))
            else:
                try:
                    #raise Exception('')
                    task = yield self._session.call_xenapi('Async.VBD.plug',
                                                           vbd_ref)
                    yield self._session.wait_for_task(task)
                except Exception, exc:
                    logging.warn(exc)
                    yield VolumeHelper.destroy_iscsi_storage(self._session,
                                                             sr_ref)
                    raise Exception('Unable to attach volume to instance %s' %
                                    instance_name)
        yield True

    @defer.inlineCallbacks
    def detach_volume(self, instance_name, mountpoint):
        # Before we start, check that the VM exists
        vm_ref = yield VMHelper.lookup(self._session, instance_name)
        if vm_ref is None:
            raise Exception('Instance %s does not exist' % instance_name)
        # Detach VBD from VM
        logging.debug("Detach_volume: %s, %s", instance_name, mountpoint)
        device_number = Volume.mountpoint_to_number(mountpoint)
        try:
            vbd_ref = yield VMHelper.find_vbd_by_number(self._session,
                                                        vm_ref, device_number)
        except Exception, exc:
            logging.warn(exc)
            raise Exception('Unable to locate volume %s' % mountpoint)
        else:
            try:
                sr_ref = yield VolumeHelper.find_sr_from_vbd(self._session,
                                                             vbd_ref)
                yield VMHelper.unplug_vbd(self._session, vbd_ref)
            except Exception, exc:
                logging.warn(exc)
                raise Exception('Unable to detach volume %s' % mountpoint)
            try:
                yield VMHelper.destroy_vbd(self._session, vbd_ref)
            except Exception, exc:
                    logging.warn(exc)
        # Forget SR
        yield VolumeHelper.destroy_iscsi_storage(self._session, sr_ref)
        yield True
