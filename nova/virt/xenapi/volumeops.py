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


class VolumeOps(object):
    def __init__(self, session):
        self._session = session

    @defer.inlineCallbacks
    def attach_volume(self, instance_name, device_path, mountpoint):
        # NOTE: No Resource Pool concept so far
        logging.debug("Attach_volume: %s, %s, %s",
                      instance_name, device_path, mountpoint)
        volume_info = _parse_volume_info(device_path, mountpoint)
        # Create the iSCSI SR, and the PDB through which hosts access SRs.
        # But first, retrieve target info, like Host, IQN, LUN and SCSIID
        target = yield self._get_target(volume_info)
        label = 'SR-%s' % volume_info['volumeId']
        description = 'Attached-to:%s' % instance_name
        # Create SR and check the physical space available for the VDI allocation 
        sr_ref = yield self._create_sr(target, label, description)
        disk_size = int(target['size'])
        #disk_size = yield self._get_sr_available_space(sr_ref)
        # Create VDI  and attach VBD to VM
        vm_ref = yield self._lookup(instance_name)
        logging.debug("Mounting disk of: %s GB", (disk_size / (1024*1024*1024.0)))
        try:
            vdi_ref = yield self._create_vdi(sr_ref, disk_size,
                                             'user', volume_info['volumeId'], '',
                                             False, False)
        except Exception, exc:
            logging.warn(exc)
            yield self._destroy_sr(sr_ref)
            raise Exception('Unable to create VDI on SR %s for instance %s'
                            % (sr_ref,
                            instance_name))
        else:
            try:
                userdevice = 2  # FIXME: this depends on the numbers of attached disks 
                vbd_ref = yield self._create_vbd(vm_ref, vdi_ref, userdevice, False, True, False)
            except Exception, exc:
                logging.warn(exc)
                yield self._destroy_sr(sr_ref)
                raise Exception('Unable to create VBD on SR %s for instance %s'
                            % (sr_ref,
                            instance_name))
            else:
                try:
                    raise Exception('') 
                    task = yield self._call_xenapi('Async.VBD.plug', vbd_ref)
                    yield self._wait_for_task(task)
                except Exception, exc:
                    logging.warn(exc)
                    yield self._destroy_sr(sr_ref)
                    raise Exception('Unable to attach volume to instance %s' % instance_name)
                
        yield True

    @defer.inlineCallbacks
    def detach_volume(self, instance_name, mountpoint):
        logging.debug("Detach_volume: %s, %s, %s", instance_name, mountpoint)
        # Detach VBD from VM
        # Forget SR/PDB info associated with host
        # TODO: can we avoid destroying the SR every time we detach?
        yield True