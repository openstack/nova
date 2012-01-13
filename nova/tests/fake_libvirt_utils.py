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

import StringIO

files = {}
disk_sizes = {}
disk_backing_files = {}


def create_image(disk_format, path, size):
    pass


def create_cow_image(backing_file, path):
    pass


def get_disk_size(path):
    return disk_sizes.get(path, 1024 * 1024 * 20)


def get_disk_backing_file(path):
    return disk_backing_files.get(path, None)


def copy_image(src, dest):
    pass


def mkfs(fs, path):
    pass


def ensure_tree(path):
    pass


def write_to_file(path, contents, umask=None):
    pass


def chown(path, owner):
    pass


def extract_snapshot(disk_path, source_fmt, snapshot_name, out_path, dest_fmt):
    files[out_path] = ''


class File(object):
    def __init__(self, path, mode=None):
        self.fp = StringIO.StringIO(files[path])

    def __enter__(self):
        return self.fp

    def __exit__(self, *args):
        return


def file_open(path, mode=None):
    return File(path, mode)


def load_file(path):
    return ''


def file_delete(path):
    return True


def get_open_port(start_port, end_port):
    # Return the port in the middle
    return int((start_port + end_port) / 2)


def run_ajaxterm(cmd, token, port):
    pass


def get_fs_info(path):
    return {'total': 128 * (1024 ** 3),
            'used': 44 * (1024 ** 3),
            'free': 84 * (1024 ** 3)}


def fetch_image(context, target, image_id, user_id, project_id,
                 size=None):
    pass
