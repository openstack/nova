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

import re
import string
import logging

from twisted.internet import defer

from nova import db
from nova import context
from nova import flags
from nova import process
from nova import utils

FLAGS = flags.FLAGS
XenAPI = None


class StorageError(Exception):
    """ To raise errors related to SR, VDI, PBD, and VBD commands """
    def __init__(self, message=None):
        super(StorageError, self).__init__(message)


class VolumeHelper():
    """
    The class that wraps the helper methods together.
    """
    def __init__(self):
        return

    @classmethod
    def late_import(cls):
        """
        Load XenAPI module in for helper class
        """
        global XenAPI
        if XenAPI is None:
            XenAPI = __import__('XenAPI')

    @classmethod
    @utils.deferredToThread
    def create_iscsi_storage(cls, session, info, label, description):
        """
        Create an iSCSI storage repository that will be used to mount
        the volume for the specified instance
        """
        return VolumeHelper.create_iscsi_storage_blocking(session, info,
                                                          label,
                                                          description)

    @classmethod
    def create_iscsi_storage_blocking(cls, session, info, label, description):
        """ Synchronous create_iscsi_storage """
        sr_ref = session.get_xenapi().SR.get_by_name_label(label)
        if len(sr_ref) == 0:
            logging.debug('Introducing %s...', label)
            record = {}
            if 'chapuser' in info and 'chappassword' in info:
                record = {'target': info['targetHost'],
                          'port': info['targetPort'],
                          'targetIQN': info['targeIQN'],
                          'chapuser': info['chapuser'],
                          'chappassword': info['chappassword']
                          }
            else:
                record = {'target': info['targetHost'],
                          'port': info['targetPort'],
                          'targetIQN': info['targeIQN']
                          }
            try:
                sr_ref = session.get_xenapi().SR.create(
                    session.get_xenapi_host(),
                    record,
                    '0', label, description, 'iscsi', '', False, {})
                logging.debug('Introduced %s as %s.', label, sr_ref)
                return sr_ref
            except XenAPI.Failure, exc:
                logging.warn(exc)
                raise StorageError('Unable to create Storage Repository')
        else:
            return sr_ref[0]

    @classmethod
    @defer.inlineCallbacks
    def find_sr_from_vbd(cls, session, vbd_ref):
        """ Find the SR reference from the VBD reference """
        try:
            vdi_ref = yield session.get_xenapi().VBD.get_VDI(vbd_ref)
            sr_ref = yield session.get_xenapi().VDI.get_SR(vdi_ref)
        except XenAPI.Failure, exc:
            logging.warn(exc)
            raise StorageError('Unable to find SR from VBD %s' % vbd_ref)
        defer.returnValue(sr_ref)

    @classmethod
    @utils.deferredToThread
    def destroy_iscsi_storage(cls, session, sr_ref):
        """ Forget the SR whilst preserving the state of the disk """
        VolumeHelper.destroy_iscsi_storage_blocking(session, sr_ref)

    @classmethod
    def destroy_iscsi_storage_blocking(cls, session, sr_ref):
        """ Synchronous destroy_iscsi_storage """
        logging.debug("Forgetting SR %s ... ", sr_ref)
        pbds = []
        try:
            pbds = session.get_xenapi().SR.get_PBDs(sr_ref)
        except XenAPI.Failure, exc:
            logging.warn('Ignoring exception %s when getting PBDs for %s',
                         exc, sr_ref)
        for pbd in pbds:
            try:
                session.get_xenapi().PBD.unplug(pbd)
            except XenAPI.Failure, exc:
                logging.warn('Ignoring exception %s when unplugging PBD %s',
                             exc, pbd)
        try:
            session.get_xenapi().SR.forget(sr_ref)
            logging.debug("Forgetting SR %s done.", sr_ref)
        except XenAPI.Failure, exc:
            logging.warn('Ignoring exception %s when forgetting SR %s',
                         exc, sr_ref)

    @classmethod
    @utils.deferredToThread
    def introduce_vdi(cls, session, sr_ref):
        """ Introduce VDI in the host """
        return VolumeHelper.introduce_vdi_blocking(session, sr_ref)

    @classmethod
    def introduce_vdi_blocking(cls, session, sr_ref):
        """ Synchronous introduce_vdi """
        try:
            vdis = session.get_xenapi().SR.get_VDIs(sr_ref)
        except XenAPI.Failure, exc:
            logging.warn(exc)
            raise StorageError('Unable to introduce VDI on SR %s' % sr_ref)
        try:
            vdi_rec = session.get_xenapi().VDI.get_record(vdis[0])
        except XenAPI.Failure, exc:
            logging.warn(exc)
            raise StorageError('Unable to get record of VDI %s on' % vdis[0])
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
    @defer.inlineCallbacks
    def parse_volume_info(cls, device_path, mountpoint):
        """
        Parse device_path and mountpoint as they can be used by XenAPI.
        In particular, the mountpoint (e.g. /dev/sdc) must be translated
        into a numeric literal.
        FIXME(armando):
        As for device_path, currently cannot be used as it is,
        because it does not contain target information. As for interim
        solution, target details are passed either via Flags or obtained
        by iscsiadm. Long-term solution is to add a few more fields to the
        db in the iscsi_target table with the necessary info and modify
        the iscsi driver to set them.
        """
        device_number = VolumeHelper.mountpoint_to_number(mountpoint)
        volume_id = _get_volume_id(device_path)
        (iscsi_name, iscsi_portal) = yield _get_target(volume_id)
        target_host = _get_target_host(iscsi_portal)
        target_port = _get_target_port(iscsi_portal)
        target_iqn = _get_iqn(iscsi_name, volume_id)
        logging.debug('(vol_id,number,host,port,iqn): (%s,%s,%s,%s)',
                      volume_id,
                      target_host,
                      target_port,
                      target_iqn)
        if (device_number < 0) or \
            (volume_id is None) or \
            (target_host is None) or \
            (target_iqn is None):
            raise StorageError('Unable to obtain target information %s, %s' %
                            (device_path, mountpoint))
        volume_info = {}
        volume_info['deviceNumber'] = device_number
        volume_info['volumeId'] = volume_id
        volume_info['targetHost'] = target_host
        volume_info['targetPort'] = target_port
        volume_info['targeIQN'] = target_iqn
        defer.returnValue(volume_info)

    @classmethod
    def mountpoint_to_number(cls, mountpoint):
        """ Translate a mountpoint like /dev/sdc into a numberic """
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


def _get_volume_id(path):
    """ Retrieve the volume id from device_path """
    # n must contain at least the volume_id
    # /vol- is for remote volumes
    # -vol- is for local volumes
    # see compute/manager->setup_compute_volume
    volume_id = path[path.find('/vol-') + 1:]
    if volume_id == path:
        volume_id = path[path.find('-vol-') + 1:].replace('--', '-')
    return volume_id


def _get_target_host(iscsi_string):
    """ Retrieve target host """
    if iscsi_string:
        return iscsi_string[0:iscsi_string.find(':')]
    elif iscsi_string is None or FLAGS.target_host:
        return FLAGS.target_host


def _get_target_port(iscsi_string):
    """ Retrieve target port """
    if iscsi_string:
        return iscsi_string[iscsi_string.find(':') + 1:]
    elif  iscsi_string is None or FLAGS.target_port:
        return FLAGS.target_port


def _get_iqn(iscsi_string, id):
    """ Retrieve target IQN """
    if iscsi_string:
        return iscsi_string
    elif iscsi_string is None or FLAGS.iqn_prefix:
        volume_id = _get_volume_id(id)
        return '%s:%s' % (FLAGS.iqn_prefix, volume_id)


@defer.inlineCallbacks
def _get_target(volume_id):
    """
    Gets iscsi name and portal from volume name and host.
    For this method to work the following are needed:
    1) volume_ref['host'] must resolve to something rather than loopback
    2) ietd must bind only to the address as resolved above
    If any of the two conditions are not met, fall back on Flags.
    """
    volume_ref = db.volume_get_by_ec2_id(context.get_admin_context(),
                                         volume_id)

    (r, _e) = yield process.simple_execute("sudo iscsiadm -m discovery -t "
                                     "sendtargets -p %s" %
                                     volume_ref['host'])
    targets = r.splitlines()
    if len(_e) == 0 and len(targets) == 1:
        for target in targets:
            if volume_id in target:
                (location, _sep, iscsi_name) = target.partition(" ")
                break
        iscsi_portal = location.split(",")[0]
        defer.returnValue((iscsi_name, iscsi_portal))
    else:
        defer.returnValue((None, None))
