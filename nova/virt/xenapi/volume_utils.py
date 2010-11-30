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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

import logging
import re
import string

from twisted.internet import defer

from nova import utils
from nova import flags

FLAGS = flags.FLAGS

#FIXME: replace with proper target discovery
flags.DEFINE_string('target_host', None, 'iSCSI Target Host')
flags.DEFINE_string('target_port', '3260', 'iSCSI Target Port, 3260 Default')
flags.DEFINE_string('iqn_prefix', 'iqn.2010-10.org.openstack', 'IQN Prefix')


class VolumeHelper():
    def __init__(self, session):
        return

    @classmethod
    @utils.deferredToThread
    def create_iscsi_storage(self, session, target, port, target_iqn,
                             username, password, label, description):

        return VolumeHelper.create_iscsi_storage_blocking(session, target,
                                                          port,
                                                          target_iqn,
                                                          username,
                                                          password,
                                                          label,
                                                          description)

    @classmethod
    def create_iscsi_storage_blocking(self, session, target, port, target_iqn,
                                      username, password, label, description):

        sr_ref = session.get_xenapi().SR.get_by_name_label(label)
        if len(sr_ref) == 0:
            logging.debug('Introducing %s...' % label)
            try:
                sr_ref = session.get_xenapi().SR.create(
                    session.get_xenapi_host(),
                    {'target': target,
                     'port': port,
                     'targetIQN': target_iqn
                     # TODO: when/if chap authentication is used
                     #'chapuser': username,
                     #'chappassword': password
                     },
                    '0', label, description, 'iscsi', '', False, {})
                logging.debug('Introduced %s as %s.' % (label, sr_ref))
                return sr_ref
            except Exception, exc:
                logging.warn(exc)
                raise Exception('Unable to create Storage Repository')
        else:
            return sr_ref[0]

    @classmethod
    @defer.inlineCallbacks
    def find_sr_from_vbd(self, session, vbd_ref):
        vdi_ref = yield session.get_xenapi().VBD.get_VDI(vbd_ref)
        sr_ref = yield session.get_xenapi().VDI.get_SR(vdi_ref)
        defer.returnValue(sr_ref)

    @classmethod
    @utils.deferredToThread
    def destroy_iscsi_storage(self, session, sr_ref):
        VolumeHelper.destroy_iscsi_storage_blocking(session, sr_ref)

    @classmethod
    def destroy_iscsi_storage_blocking(self, session, sr_ref):
        logging.debug("Forgetting SR %s ... ", sr_ref)
        pbds = []
        try:
            pbds = session.get_xenapi().SR.get_PBDs(sr_ref)
        except Exception, exc:
            logging.warn('Ignoring exception %s when getting PBDs for %s',
                         exc, sr_ref)
        for pbd in pbds:
            try:
                session.get_xenapi().PBD.unplug(pbd)
            except Exception, exc:
                logging.warn('Ignoring exception %s when unplugging PBD %s',
                             exc, pbd)
        try:
            session.get_xenapi().SR.forget(sr_ref)
            logging.debug("Forgetting SR %s done.", sr_ref)
        except Exception, exc:
            logging.warn('Ignoring exception %s when forgetting SR %s',
                         exc, sr_ref)

    @classmethod
    @utils.deferredToThread
    def introduce_vdi(self, session, sr_ref):
        return VolumeHelper.introduce_vdi_blocking(session, sr_ref)

    @classmethod
    def introduce_vdi_blocking(self, session, sr_ref):
        try:
            vdis = session.get_xenapi().SR.get_VDIs(sr_ref)
        except Exception, exc:
            raise Exception('Unable to introduce VDI on SR %s' % sr_ref)
        try:
            vdi_rec = session.get_xenapi().VDI.get_record(vdis[0])
        except Exception, exc:
            raise Exception('Unable to get record of VDI %s on' % vdis[0])
        else:
            return session.get_xenapi().VDI.introduce(
                vdi_rec['uuid'],
                vdi_rec['name_label'],
                vdi_rec['name_description'],
                vdi_rec['SR'],
                vdi_rec['type'],
                vdi_rec['sharable'],
                vdi_rec['read_only'],
                vdi_rec['other_config'],
                vdi_rec['location'],
                vdi_rec['xenstore_data'],
                vdi_rec['sm_config'])

    @classmethod
    def parse_volume_info(self, device_path, mountpoint):
        # Because XCP/XS want a device number instead of a mountpoint
        device_number = VolumeHelper.mountpoint_to_number(mountpoint)
        volume_id = _get_volume_id(device_path)
        target_host = _get_target_host(device_path)
        target_port = _get_target_port(device_path)
        target_iqn = _get_iqn(device_path)

        if (device_number < 0) or \
            (volume_id is None) or \
            (target_host is None) or \
            (target_iqn is None):
            raise Exception('Unable to obtain target information %s, %s' %
                            (device_path, mountpoint))

        volume_info = {}
        volume_info['deviceNumber'] = device_number
        volume_info['volumeId'] = volume_id
        volume_info['targetHost'] = target_host
        volume_info['targetPort'] = target_port
        volume_info['targeIQN'] = target_iqn
        return volume_info

    @classmethod
    def mountpoint_to_number(self, mountpoint):
        if mountpoint.startswith('/dev/'):
            mountpoint = mountpoint[5:]
        if re.match('^[hs]d[a-p]$', mountpoint):
            return (ord(mountpoint[2:3]) - ord('a'))
        elif re.match('^vd[a-p]$', mountpoint):
            return (ord(mountpoint[2:3]) - ord('a'))
        elif re.match('^[0-9]+$', mountpoint):
            return string.atoi(mountpoint, 10)
        else:
            logging.warn('Mountpoint cannot be translated: %s', mountpoint)
            return -1


def _get_volume_id(n):
    # FIXME: n must contain at least the volume_id
    # /vol- is for remote volumes
    # -vol- is for local volumes
    # see compute/manager->setup_compute_volume
    volume_id = n[n.find('/vol-') + 1:]
    if volume_id == n:
        volume_id = n[n.find('-vol-') + 1:].replace('--', '-')
    return volume_id


def _get_target_host(n):
    # FIXME: if n is none fall back on flags
    if n is None or FLAGS.target_host:
        return FLAGS.target_host


def _get_target_port(n):
    # FIXME: if n is none fall back on flags
    return FLAGS.target_port


def _get_iqn(n):
    # FIXME: n must contain at least the volume_id
    volume_id = _get_volume_id(n)
    if n is None or FLAGS.iqn_prefix:
        return '%s:%s' % (FLAGS.iqn_prefix, volume_id)
