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

import io
import os

from nova.virt.libvirt import utils as libvirt_utils


files = {'console.log': b''}
disk_sizes = {}
disk_backing_files = {}
disk_type = "qcow2"

RESIZE_SNAPSHOT_NAME = libvirt_utils.RESIZE_SNAPSHOT_NAME


def create_image(disk_format, path, size):
    pass


def create_cow_image(backing_file, path):
    pass


def create_ploop_image(disk_format, path, size, fs_type):
    pass


def get_disk_size(path, format=None):
    return 0


def get_disk_backing_file(path, basename=True, format=None):
    backing_file = disk_backing_files.get(path, None)
    if backing_file and basename:
        backing_file = os.path.basename(backing_file)

    return backing_file


def get_disk_type_from_path(path):
    if disk_type in ('raw', 'qcow2'):
        return None
    return disk_type


def copy_image(src, dest, host=None, receive=False,
               on_execute=None, on_completion=None,
               compression=True):
    pass


def resize2fs(path):
    pass


def create_lvm_image(vg, lv, size, sparse=False):
    pass


def volume_group_free_space(vg):
    pass


def remove_logical_volumes(*paths):
    pass


def write_to_file(path, contents, umask=None):
    pass


def chown(path, owner):
    pass


def update_mtime(path):
    pass


def extract_snapshot(disk_path, source_fmt, out_path, dest_fmt):
    files[out_path] = b''


class File(object):
    def __init__(self, path, mode=None):
        if path in files:
            self.fp = io.BytesIO(files[path])
        else:
            self.fp = io.BytesIO(files[os.path.split(path)[-1]])

    def __enter__(self):
        return self.fp

    def __exit__(self, *args):
        return

    def close(self, *args, **kwargs):
        self.fp.close()


def file_open(path, mode=None):
    return File(path, mode)


def find_disk(virt_dom):
    if disk_type == 'lvm':
        return ("/dev/nova-vg/lv", "raw")
    elif disk_type in ['raw', 'qcow2']:
        return ("filename", disk_type)
    else:
        return ("unknown_type_disk", None)


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


def fetch_image(context, target, image_id, max_size=0):
    pass


def fetch_raw_image(context, target, image_id, max_size=0):
    pass


def get_instance_path(instance, relative=False):
    return libvirt_utils.get_instance_path(instance, relative=relative)


def get_instance_path_at_destination(instance, migrate_data=None):
    return libvirt_utils.get_instance_path_at_destination(instance,
                                                          migrate_data)


def pick_disk_driver_name(hypervisor_version, is_block_dev=False):
    return "qemu"


def is_valid_hostname(name):
    return True


def chown_for_id_maps(path, id_maps):
    pass


def get_arch(image_meta):
    return libvirt_utils.get_arch(image_meta)


def last_bytes(file_like_object, num):
    return libvirt_utils.last_bytes(file_like_object, num)
