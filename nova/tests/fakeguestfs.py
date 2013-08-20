# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2012 Red Hat, Inc
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


class GuestFS(object):

    def __init__(self):
        self.drives = []
        self.running = False
        self.closed = False
        self.mounts = []
        self.files = {}
        self.auginit = False
        self.attach_method = 'libvirt'
        self.root_mounted = False

    def launch(self):
        self.running = True

    def shutdown(self):
        self.running = False
        self.mounts = []
        self.drives = []

    def close(self):
        self.closed = True

    def add_drive_opts(self, file, *args, **kwargs):
        self.drives.append((file, kwargs['format']))

    def get_attach_method(self):
        return self.attach_method

    def set_attach_method(self, attach_method):
        self.attach_method = attach_method

    def inspect_os(self):
        return ["/dev/guestvgf/lv_root"]

    def inspect_get_mountpoints(self, dev):
        return [["/home", "/dev/mapper/guestvgf-lv_home"],
                ["/", "/dev/mapper/guestvgf-lv_root"],
                ["/boot", "/dev/vda1"]]

    def mount_options(self, options, device, mntpoint):
        if mntpoint == "/":
            self.root_mounted = True
        else:
            if not self.root_mounted:
                raise RuntimeError(
                    "mount: %s: No such file or directory" % mntpoint)
        self.mounts.append((options, device, mntpoint))

    def mkdir_p(self, path):
        if path not in self.files:
            self.files[path] = {
                "isdir": True,
                "gid": 100,
                "uid": 100,
                "mode": 0o700
                }

    def read_file(self, path):
        if path not in self.files:
            self.files[path] = {
                "isdir": False,
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0o700
                }

        return self.files[path]["content"]

    def write(self, path, content):
        if path not in self.files:
            self.files[path] = {
                "isdir": False,
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0o700
                }

        self.files[path]["content"] = content

    def write_append(self, path, content):
        if path not in self.files:
            self.files[path] = {
                "isdir": False,
                "content": "Hello World",
                "gid": 100,
                "uid": 100,
                "mode": 0o700
                }

        self.files[path]["content"] = self.files[path]["content"] + content

    def stat(self, path):
        if path not in self.files:
            raise RuntimeError("No such file: " + path)

        return self.files[path]["mode"]

    def chown(self, uid, gid, path):
        if path not in self.files:
            raise RuntimeError("No such file: " + path)

        if uid != -1:
            self.files[path]["uid"] = uid
        if gid != -1:
            self.files[path]["gid"] = gid

    def chmod(self, mode, path):
        if path not in self.files:
            raise RuntimeError("No such file: " + path)

        self.files[path]["mode"] = mode

    def aug_init(self, root, flags):
        self.auginit = True

    def aug_close(self):
        self.auginit = False

    def aug_get(self, cfgpath):
        if not self.auginit:
            raise RuntimeError("Augeus not initialized")

        if cfgpath == "/files/etc/passwd/root/uid":
            return 0
        elif cfgpath == "/files/etc/passwd/fred/uid":
            return 105
        elif cfgpath == "/files/etc/passwd/joe/uid":
            return 110
        elif cfgpath == "/files/etc/group/root/gid":
            return 0
        elif cfgpath == "/files/etc/group/users/gid":
            return 500
        elif cfgpath == "/files/etc/group/admins/gid":
            return 600
        raise RuntimeError("Unknown path %s", cfgpath)
