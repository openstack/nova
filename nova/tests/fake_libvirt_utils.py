# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright (c) 2011 OpenStack LLC
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


files = {'console.log': True}
disk_sizes = {}
disk_backing_files = {}
disk_type = "qcow2"


def get_iscsi_initiator():
    return "fake.initiator.iqn"


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


def fetch_image(context, target, image_id, user_id, project_id):
    pass
