# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2011 OpenStack Foundation
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

import os
import StringIO

from oslo.config import cfg

from nova.virt.libvirt import utils as libvirt_utils


CONF = cfg.CONF
CONF.import_opt('instances_path', 'nova.compute.manager')


files = {'console.log': True}
disk_sizes = {}
disk_backing_files = {}
disk_type = "qcow2"


def get_iscsi_initiator():
    return "fake.initiator.iqn"


def get_fc_hbas():
    return [{'ClassDevice': 'host1',
             'ClassDevicePath': '/sys/devices/pci0000:00/0000:00:03.0'
                                    '/0000:05:00.2/host1/fc_host/host1',
             'dev_loss_tmo': '30',
             'fabric_name': '0x1000000533f55566',
             'issue_lip': '<store method only>',
             'max_npiv_vports': '255',
             'maxframe_size': '2048 bytes',
             'node_name': '0x200010604b019419',
             'npiv_vports_inuse': '0',
             'port_id': '0x680409',
             'port_name': '0x100010604b019419',
             'port_state': 'Online',
             'port_type': 'NPort (fabric via point-to-point)',
             'speed': '10 Gbit',
             'supported_classes': 'Class 3',
             'supported_speeds': '10 Gbit',
             'symbolic_name': 'Emulex 554M FV4.0.493.0 DV8.3.27',
             'tgtid_bind_type': 'wwpn (World Wide Port Name)',
             'uevent': None,
             'vport_create': '<store method only>',
             'vport_delete': '<store method only>'}]


def get_fc_hbas_info():
    hbas = get_fc_hbas()
    info = [{'port_name': hbas[0]['port_name'].replace('0x', ''),
             'node_name': hbas[0]['node_name'].replace('0x', ''),
             'host_device': hbas[0]['ClassDevice'],
             'device_path': hbas[0]['ClassDevicePath']}]
    return info


def get_fc_wwpns():
    hbas = get_fc_hbas()
    wwpns = []
    for hba in hbas:
        wwpn = hba['port_name'].replace('0x', '')
        wwpns.append(wwpn)

    return wwpns


def get_fc_wwnns():
    hbas = get_fc_hbas()
    wwnns = []
    for hba in hbas:
        wwnn = hba['node_name'].replace('0x', '')
    wwnns.append(wwnn)

    return wwnns


def create_image(disk_format, path, size):
    pass


def create_cow_image(backing_file, path):
    pass


def get_disk_backing_file(path):
    return disk_backing_files.get(path, None)


def get_disk_type(path):
    return disk_type


def copy_image(src, dest):
    pass


def resize2fs(path):
    pass


def create_lvm_image(vg, lv, size, sparse=False):
    pass


def import_rbd_image(path, *args):
    pass


def volume_group_free_space(vg):
    pass


def remove_logical_volumes(*paths):
    pass


def write_to_file(path, contents, umask=None):
    pass


def chown(path, owner):
    pass


def create_snapshot(disk_path, snapshot_name):
    pass


def delete_snapshot(disk_path, snapshot_name):
    pass


def extract_snapshot(disk_path, source_fmt, snapshot_name, out_path, dest_fmt):
    files[out_path] = ''


class File(object):
    def __init__(self, path, mode=None):
        if path in files:
            self.fp = StringIO.StringIO(files[path])
        else:
            self.fp = StringIO.StringIO(files[os.path.split(path)[-1]])

    def __enter__(self):
        return self.fp

    def __exit__(self, *args):
        return

    def close(self, *args, **kwargs):
        self.fp.close()


def file_open(path, mode=None):
    return File(path, mode)


def find_disk(virt_dom):
    return "filename"


def load_file(path):
    if os.path.exists(path):
        with open(path, 'r') as fp:
            return fp.read()
    else:
        return ''


def logical_volume_info(path):
    return {}


def file_delete(path):
    return True


def get_fs_info(path):
    return {'total': 128 * (1024 ** 3),
            'used': 44 * (1024 ** 3),
            'free': 84 * (1024 ** 3)}


def fetch_image(context, target, image_id, user_id, project_id, max_size=0):
    pass


def get_instance_path(instance, forceold=False, relative=False):
    return libvirt_utils.get_instance_path(instance, forceold=forceold,
                                           relative=relative)


def pick_disk_driver_name(hypervisor_version, is_block_dev=False):
    return "qemu"


def list_rbd_volumes(pool):
    fake_volumes = ['875a8070-d0b9-4949-8b31-104d125c9a64.local',
                    '875a8070-d0b9-4949-8b31-104d125c9a64.swap',
                    '875a8070-d0b9-4949-8b31-104d125c9a64',
                    'wrong875a8070-d0b9-4949-8b31-104d125c9a64']
    return fake_volumes


def remove_rbd_volumes(pool, *names):
    pass
