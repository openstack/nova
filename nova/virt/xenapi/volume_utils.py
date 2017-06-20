# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2013 OpenStack Foundation
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
import uuid

from eventlet import greenthread
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_utils import strutils
from oslo_utils import versionutils
import six

import nova.conf
from nova import exception
from nova.i18n import _


CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

# Namespace for SRs so we can reliably generate a UUID
# Generated from uuid.uuid5(uuid.UUID(int=0), 'volume_utils-SR_UUID')
SR_NAMESPACE = uuid.UUID("3cca4135-a809-5bb3-af62-275fbfe87178")


def parse_sr_info(connection_data, description=''):
    params = {}
    if 'sr_uuid' not in connection_data:
        params = _parse_volume_info(connection_data)
        sr_identity = "%s/%s/%s" % (params['target'], params['port'],
                                    params['targetIQN'])
        # PY2 can only support taking an ascii string to uuid5
        if six.PY2 and isinstance(sr_identity, six.text_type):
            sr_identity = sr_identity.encode('utf-8')
        sr_uuid = str(uuid.uuid5(SR_NAMESPACE, sr_identity))
    else:
        sr_uuid = connection_data['sr_uuid']
        for k in connection_data.get('introduce_sr_keys', {}):
            params[k] = connection_data[k]

    label = connection_data.pop('name_label',
                                'tempSR-%s' % sr_uuid)
    params['name_description'] = connection_data.get('name_description',
                                                     description)

    return (sr_uuid, label, params)


def _parse_volume_info(connection_data):
    """Parse device_path and mountpoint as they can be used by XenAPI.
    In particular, the mountpoint (e.g. /dev/sdc) must be translated
    into a numeric literal.
    """
    volume_id = connection_data['volume_id']
    target_portal = connection_data['target_portal']
    target_host = _get_target_host(target_portal)
    target_port = _get_target_port(target_portal)
    target_iqn = connection_data['target_iqn']

    log_params = {
        "vol_id": volume_id,
        "host": target_host,
        "port": target_port,
        "iqn": target_iqn
    }
    LOG.debug('(vol_id,host,port,iqn): '
              '(%(vol_id)s,%(host)s,%(port)s,%(iqn)s)', log_params)

    if (volume_id is None or
        target_host is None or
            target_iqn is None):
        raise exception.StorageError(
                reason=_('Unable to obtain target information %s') %
                        strutils.mask_password(connection_data))
    volume_info = {}
    volume_info['id'] = volume_id
    volume_info['target'] = target_host
    volume_info['port'] = target_port
    volume_info['targetIQN'] = target_iqn
    if ('auth_method' in connection_data and
            connection_data['auth_method'] == 'CHAP'):
        volume_info['chapuser'] = connection_data['auth_username']
        volume_info['chappassword'] = connection_data['auth_password']

    return volume_info


def _get_target_host(iscsi_string):
    """Retrieve target host."""
    if iscsi_string:
        host = iscsi_string.split(':')[0]
        if len(host) > 0:
            return host
    return CONF.xenserver.target_host


def _get_target_port(iscsi_string):
    """Retrieve target port."""
    if iscsi_string and ':' in iscsi_string:
        return iscsi_string.split(':')[1]

    return CONF.xenserver.target_port


def introduce_sr(session, sr_uuid, label, params):
    LOG.debug('Introducing SR %s', label)

    sr_type, sr_desc = _handle_sr_params(params)

    if _requires_backend_kind(session.product_version) and sr_type == 'iscsi':
        params['backend-kind'] = 'vbd'

    sr_ref = session.call_xenapi('SR.introduce', sr_uuid, label, sr_desc,
            sr_type, '', False, params)

    LOG.debug('Creating PBD for SR')
    pbd_ref = _create_pbd(session, sr_ref, params)

    LOG.debug('Plugging SR')
    session.call_xenapi("PBD.plug", pbd_ref)

    session.call_xenapi("SR.scan", sr_ref)
    return sr_ref


def _requires_backend_kind(version):
    # Fix for Bug #1502929
    version_as_string = '.'.join(str(v) for v in version)
    return (versionutils.is_compatible('6.5', version_as_string))


def _handle_sr_params(params):
    if 'id' in params:
        del params['id']

    sr_type = params.pop('sr_type', 'iscsi')
    sr_desc = params.pop('name_description', '')
    return sr_type, sr_desc


def _create_pbd(session, sr_ref, params):
    pbd_rec = {}
    pbd_rec['host'] = session.host_ref
    pbd_rec['SR'] = sr_ref
    pbd_rec['device_config'] = params
    pbd_ref = session.call_xenapi("PBD.create", pbd_rec)
    return pbd_ref


def introduce_vdi(session, sr_ref, vdi_uuid=None, target_lun=None):
    """Introduce VDI in the host."""
    try:
        vdi_ref = _get_vdi_ref(session, sr_ref, vdi_uuid, target_lun)
        if vdi_ref is None:
            greenthread.sleep(CONF.xenserver.introduce_vdi_retry_wait)
            session.call_xenapi("SR.scan", sr_ref)
            vdi_ref = _get_vdi_ref(session, sr_ref, vdi_uuid, target_lun)
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to introduce VDI on SR'))
        raise exception.StorageError(
                reason=_('Unable to introduce VDI on SR %s') % sr_ref)

    if not vdi_ref:
        raise exception.StorageError(
                reason=_('VDI not found on SR %(sr)s (vdi_uuid '
                         '%(vdi_uuid)s, target_lun %(target_lun)s)') %
                            {'sr': sr_ref, 'vdi_uuid': vdi_uuid,
                             'target_lun': target_lun})

    try:
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
        LOG.debug(vdi_rec)
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to get record of VDI'))
        raise exception.StorageError(
                reason=_('Unable to get record of VDI %s on') % vdi_ref)

    if vdi_rec['managed']:
        # We do not need to introduce the vdi
        return vdi_ref

    try:
        return session.call_xenapi("VDI.introduce",
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
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to introduce VDI for SR'))
        raise exception.StorageError(
                reason=_('Unable to introduce VDI for SR %s') % sr_ref)


def _get_vdi_ref(session, sr_ref, vdi_uuid, target_lun):
    if vdi_uuid:
        LOG.debug("vdi_uuid: %s", vdi_uuid)
        return session.call_xenapi("VDI.get_by_uuid", vdi_uuid)
    elif target_lun:
        vdi_refs = session.call_xenapi("SR.get_VDIs", sr_ref)
        for curr_ref in vdi_refs:
            curr_rec = session.call_xenapi("VDI.get_record", curr_ref)
            if ('sm_config' in curr_rec and
                'LUNid' in curr_rec['sm_config'] and
                curr_rec['sm_config']['LUNid'] == str(target_lun)):
                return curr_ref
    else:
        return (session.call_xenapi("SR.get_VDIs", sr_ref))[0]

    return None


def purge_sr(session, sr_ref):
    # Make sure no VBDs are referencing the SR VDIs
    vdi_refs = session.call_xenapi("SR.get_VDIs", sr_ref)
    for vdi_ref in vdi_refs:
        vbd_refs = session.call_xenapi("VDI.get_VBDs", vdi_ref)
        if vbd_refs:
            LOG.warning('Cannot purge SR with referenced VDIs')
            return

    forget_sr(session, sr_ref)


def forget_sr(session, sr_ref):
    """Forgets the storage repository without destroying the VDIs within."""
    LOG.debug('Forgetting SR...')
    _unplug_pbds(session, sr_ref)
    session.call_xenapi("SR.forget", sr_ref)


def _unplug_pbds(session, sr_ref):
    try:
        pbds = session.call_xenapi("SR.get_PBDs", sr_ref)
    except session.XenAPI.Failure as exc:
        LOG.warning('Ignoring exception %(exc)s when getting PBDs'
                    ' for %(sr_ref)s', {'exc': exc, 'sr_ref': sr_ref})
        return

    for pbd in pbds:
        try:
            session.call_xenapi("PBD.unplug", pbd)
        except session.XenAPI.Failure as exc:
            LOG.warning('Ignoring exception %(exc)s when unplugging'
                        ' PBD %(pbd)s', {'exc': exc, 'pbd': pbd})


def get_device_number(mountpoint):
    device_number = _mountpoint_to_number(mountpoint)
    if device_number < 0:
        raise exception.StorageError(
                reason=_('Unable to obtain target information %s') %
                       mountpoint)
    return device_number


def _mountpoint_to_number(mountpoint):
    """Translate a mountpoint like /dev/sdc into a numeric."""
    if mountpoint.startswith('/dev/'):
        mountpoint = mountpoint[5:]
    if re.match('^[hs]d[a-p]$', mountpoint):
        return (ord(mountpoint[2:3]) - ord('a'))
    elif re.match('^x?vd[a-p]$', mountpoint):
        return (ord(mountpoint[-1]) - ord('a'))
    elif re.match('^[0-9]+$', mountpoint):
        return int(mountpoint, 10)
    else:
        LOG.warning('Mountpoint cannot be translated: %s', mountpoint)
        return -1


def find_sr_by_uuid(session, sr_uuid):
    """Return the storage repository given a uuid."""
    try:
        return session.call_xenapi("SR.get_by_uuid", sr_uuid)
    except session.XenAPI.Failure as exc:
        if exc.details[0] == 'UUID_INVALID':
            return None
        raise


def find_sr_from_vbd(session, vbd_ref):
    """Find the SR reference from the VBD reference."""
    try:
        vdi_ref = session.call_xenapi("VBD.get_VDI", vbd_ref)
        sr_ref = session.call_xenapi("VDI.get_SR", vdi_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to find SR from VBD'))
        raise exception.StorageError(
                reason=_('Unable to find SR from VBD %s') % vbd_ref)
    return sr_ref


def find_sr_from_vdi(session, vdi_ref):
    """Find the SR reference from the VDI reference."""
    try:
        sr_ref = session.call_xenapi("VDI.get_SR", vdi_ref)
    except session.XenAPI.Failure:
        LOG.exception(_('Unable to find SR from VDI'))
        raise exception.StorageError(
                reason=_('Unable to find SR from VDI %s') % vdi_ref)
    return sr_ref


def find_vbd_by_number(session, vm_ref, dev_number):
    """Get the VBD reference from the device number."""
    vbd_refs = session.VM.get_VBDs(vm_ref)
    requested_device = str(dev_number)
    if vbd_refs:
        for vbd_ref in vbd_refs:
            try:
                user_device = session.VBD.get_userdevice(vbd_ref)
                if user_device == requested_device:
                    return vbd_ref
            except session.XenAPI.Failure:
                msg = "Error looking up VBD %s for %s" % (vbd_ref, vm_ref)
                LOG.debug(msg, exc_info=True)


def is_booted_from_volume(session, vm_ref):
    """Determine if the root device is a volume."""
    vbd_ref = find_vbd_by_number(session, vm_ref, 0)
    vbd_other_config = session.VBD.get_other_config(vbd_ref)
    if vbd_other_config.get('osvol', False):
        return True
    return False


def _get_vdi_import_path(session, task_ref, vdi_ref, disk_format):
    session_id = session.get_session_id()
    str_fmt = '/import_raw_vdi?session_id={}&task_id={}&vdi={}&format={}'
    return str_fmt.format(session_id, task_ref, vdi_ref, disk_format)


def _stream_to_vdi(conn, vdi_import_path, file_size, file_obj):
    headers = {'Content-Type': 'application/octet-stream',
               'Content-Length': '%s' % file_size}

    CHUNK_SIZE = 16 * 1024
    LOG.debug('Initialising PUT request to %s (Headers: %s)',
              vdi_import_path, headers)
    conn.request('PUT', vdi_import_path, headers=headers)
    remain_size = file_size
    while remain_size >= CHUNK_SIZE:
        trunk = file_obj.read(CHUNK_SIZE)
        remain_size -= CHUNK_SIZE
        conn.send(trunk)
    if remain_size != 0:
        trunk = file_obj.read(remain_size)
        conn.send(trunk)
    resp = conn.getresponse()
    LOG.debug("Connection response status:reason is "
              "%(status)s:%(reason)s",
              {'status': resp.status, 'reason': resp.reason})


def stream_to_vdi(session, instance, disk_format,
                  file_obj, file_size, vdi_ref):

    task_name_label = 'VDI_IMPORT_for_' + instance['name']
    with session.custom_task(task_name_label) as task_ref:
        vdi_import_path = _get_vdi_import_path(session, task_ref, vdi_ref,
                                               disk_format)

        with session.http_connection() as conn:
            try:
                _stream_to_vdi(conn, vdi_import_path, file_size, file_obj)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    LOG.error('Streaming disk to VDI failed with error: %s',
                              e, instance=instance)
