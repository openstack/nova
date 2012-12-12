# vim: tabstop=4 shiftwidth=4 softtabstop=4
# coding=utf-8

# Copyright (c) 2012 NTT DOCOMO, INC.
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

import re

from nova import context as nova_context
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt.baremetal import db as bmdb
from nova.virt import driver
from nova.virt.libvirt import utils as libvirt_utils

opts = [
    cfg.BoolOpt('baremetal_use_unsafe_iscsi',
                 default=False,
                 help='Do not set this out of dev/test environments. '
                      'If a node does not have an fixed PXE IP address, '
                      'volumes are exported with globally opened ACL'),
    cfg.StrOpt('baremetal_iscsi_iqn_prefix',
               default='iqn.2010-10.org.openstack.baremetal',
               help='iSCSI IQN prefix used in baremetal volume connections.'),
    ]

CONF = cfg.CONF
CONF.register_opts(opts)

CONF.import_opt('libvirt_volume_drivers', 'nova.virt.libvirt.driver')

LOG = logging.getLogger(__name__)


def _get_baremetal_node_by_instance_name(virtapi, instance_name):
    context = nova_context.get_admin_context()
    # TODO(deva): optimize this DB query.
    #             I don't think it should be _get_all
    for node in bmdb.bm_node_get_all(context, service_host=CONF.host):
        if not node['instance_uuid']:
            continue
        try:
            inst = virtapi.instance_get_by_uuid(context, node['instance_uuid'])
            if inst['name'] == instance_name:
                return node
        except exception.InstanceNotFound:
            continue

    # raise exception if we found no matching instance
    raise exception.InstanceNotFound(instance_name)


def _create_iscsi_export_tgtadm(path, tid, iqn):
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'target',
                  '--op', 'new',
                  '--tid', tid,
                  '--targetname', iqn,
                  run_as_root=True)
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'logicalunit',
                  '--op', 'new',
                  '--tid', tid,
                  '--lun', '1',
                  '--backing-store', path,
                  run_as_root=True)


def _allow_iscsi_tgtadm(tid, address):
    utils.execute('tgtadm', '--lld', 'iscsi',
                  '--mode', 'target',
                  '--op', 'bind',
                  '--tid', tid,
                  '--initiator-address', address,
                  run_as_root=True)


def _delete_iscsi_export_tgtadm(tid):
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'logicalunit',
                      '--op', 'delete',
                      '--tid', tid,
                      '--lun', '1',
                      run_as_root=True)
    except exception.ProcessExecutionError:
        pass
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'target',
                      '--op', 'delete',
                      '--tid', tid,
                      run_as_root=True)
    except exception.ProcessExecutionError:
        pass
    # Check if the tid is deleted, that is, check the tid no longer exists.
    # If the tid dose not exist, tgtadm returns with exit_code 22.
    # utils.execute() can check the exit_code if check_exit_code parameter is
    # passed. But, regardless of whether check_exit_code contains 0 or not,
    # if the exit_code is 0, the function dose not report errors. So we have to
    # catch a ProcessExecutionError and test its exit_code is 22.
    try:
        utils.execute('tgtadm', '--lld', 'iscsi',
                      '--mode', 'target',
                      '--op', 'show',
                      '--tid', tid,
                      run_as_root=True)
    except exception.ProcessExecutionError as e:
        if e.exit_code == 22:
            # OK, the tid is deleted
            return
        raise
    raise exception.NovaException(_(
            'baremetal driver was unable to delete tid %s') % tid)


def _show_tgtadm():
    out, _ = utils.execute('tgtadm', '--lld', 'iscsi',
                           '--mode', 'target',
                           '--op', 'show',
                           run_as_root=True)
    return out


def _list_backingstore_path():
    out = _show_tgtadm()
    l = []
    for line in out.split('\n'):
        m = re.search(r'Backing store path: (.*)$', line)
        if m:
            if '/' in m.group(1):
                l.append(m.group(1))
    return l


def _get_next_tid():
    out = _show_tgtadm()
    last_tid = 0
    for line in out.split('\n'):
        m = re.search(r'^Target (\d+):', line)
        if m:
            tid = int(m.group(1))
            if last_tid < tid:
                last_tid = tid
    return last_tid + 1


def _find_tid(iqn):
    out = _show_tgtadm()
    pattern = r'^Target (\d+): *' + re.escape(iqn)
    for line in out.split('\n'):
        m = re.search(pattern, line)
        if m:
            return int(m.group(1))
    return None


def _get_iqn(instance_name, mountpoint):
    mp = mountpoint.replace('/', '-').strip('-')
    iqn = '%s:%s-%s' % (CONF.baremetal_iscsi_iqn_prefix,
                        instance_name,
                        mp)
    return iqn


class VolumeDriver(object):

    def __init__(self, virtapi):
        super(VolumeDriver, self).__init__()
        self.virtapi = virtapi
        self._initiator = None

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = libvirt_utils.get_iscsi_initiator()
            if not self._initiator:
                LOG.warn(_('Could not determine iscsi initiator name '
                           'for instance %s') % instance)
        return {
            'ip': CONF.my_ip,
            'initiator': self._initiator,
            'host': CONF.host,
        }

    def attach_volume(self, connection_info, instance_name, mountpoint):
        raise NotImplementedError()

    def detach_volume(self, connection_info, instance_name, mountpoint):
        raise NotImplementedError()


class LibvirtVolumeDriver(VolumeDriver):
    """The VolumeDriver deligates to nova.virt.libvirt.volume."""

    def __init__(self, virtapi):
        super(LibvirtVolumeDriver, self).__init__(virtapi)
        self.volume_drivers = {}
        for driver_str in CONF.libvirt_volume_drivers:
            driver_type, _sep, driver = driver_str.partition('=')
            driver_class = importutils.import_class(driver)
            self.volume_drivers[driver_type] = driver_class(self)

    def _volume_driver_method(self, method_name, connection_info,
                             *args, **kwargs):
        driver_type = connection_info.get('driver_volume_type')
        if not driver_type in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        method = getattr(driver, method_name)
        return method(connection_info, *args, **kwargs)

    def attach_volume(self, connection_info, instance_name, mountpoint):
        node = _get_baremetal_node_by_instance_name(self.virtapi,
                                                    instance_name)
        ctx = nova_context.get_admin_context()
        pxe_ip = bmdb.bm_pxe_ip_get_by_bm_node_id(ctx, node['id'])
        if not pxe_ip:
            if not CONF.baremetal_use_unsafe_iscsi:
                raise exception.NovaException(_(
                    'No fixed PXE IP is associated to %s') % instance_name)

        mount_device = mountpoint.rpartition("/")[2]
        self._volume_driver_method('connect_volume',
                                   connection_info,
                                   mount_device)
        device_path = connection_info['data']['device_path']
        iqn = _get_iqn(instance_name, mountpoint)
        tid = _get_next_tid()
        _create_iscsi_export_tgtadm(device_path, tid, iqn)

        if pxe_ip:
            _allow_iscsi_tgtadm(tid, pxe_ip['address'])
        else:
            # NOTE(NTTdocomo): Since nova-compute does not know the
            # instance's initiator ip, it allows any initiators
            # to connect to the volume. This means other bare-metal
            # instances that are not attached the volume can connect
            # to the volume. Do not set CONF.baremetal_use_unsafe_iscsi
            # out of dev/test environments.
            # TODO(NTTdocomo): support CHAP
            _allow_iscsi_tgtadm(tid, 'ALL')

    @exception.wrap_exception()
    def detach_volume(self, connection_info, instance_name, mountpoint):
        mount_device = mountpoint.rpartition("/")[2]
        try:
            iqn = _get_iqn(instance_name, mountpoint)
            tid = _find_tid(iqn)
            if tid is not None:
                _delete_iscsi_export_tgtadm(tid)
            else:
                LOG.warn(_('detach volume could not find tid for %s') % iqn)
        finally:
            self._volume_driver_method('disconnect_volume',
                                       connection_info,
                                       mount_device)

    def get_all_block_devices(self):
        """
        Return all block devices in use on this node.
        """
        return _list_backingstore_path()
