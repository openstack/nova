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


EVENT_APPLIANCE = 0x1
EVENT_LIBRARY = 0x2
EVENT_WARNING = 0x3
EVENT_TRACE = 0x4


class GuestFS(object):
    SUPPORT_CLOSE_ON_EXIT = True
    SUPPORT_RETURN_DICT = True
    CAN_SET_OWNERSHIP = True

    def __init__(self, **kwargs):
        if not self.SUPPORT_CLOSE_ON_EXIT and 'close_on_exit' in kwargs:
            raise TypeError('close_on_exit')
        if not self.SUPPORT_RETURN_DICT and 'python_return_dict' in kwargs:
            raise TypeError('python_return_dict')

        self._python_return_dict = kwargs.get('python_return_dict', False)
        self.kwargs = kwargs
        self.drives = []
        self.running = False
        self.closed = False
        self.mounts = []
        self.files = {}
        self.auginit = False
        self.root_mounted = False
        self.backend_settings = None
        self.trace_enabled = False
        self.verbose_enabled = False
        self.event_callback = None

    def launch(self):
        self.running = True

    def shutdown(self):
        self.running = False
        self.mounts = []
        self.drives = []

    def set_backend_settings(self, settings):
        self.backend_settings = settings

    def close(self):
        self.closed = True

    def add_drive_opts(self, file, *args, **kwargs):
        if file == "/some/fail/file":
            raise RuntimeError("%s: No such file or directory", file)

        self.drives.append((file, kwargs))

    def add_drive(self, file, format=None, *args, **kwargs):
        self.add_drive_opts(file, format=None, *args, **kwargs)

    def inspect_os(self):
        return ["/dev/guestvgf/lv_root"]

    def inspect_get_mountpoints(self, dev):
        mountpoints = [("/home", "/dev/mapper/guestvgf-lv_home"),
                       ("/", "/dev/mapper/guestvgf-lv_root"),
                       ("/boot", "/dev/vda1")]

        if self.SUPPORT_RETURN_DICT and self._python_return_dict:
            return dict(mountpoints)
        else:
            return mountpoints

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

        if ((cfgpath.startswith("/files/etc/passwd") or
                cfgpath.startswith("/files/etc/group")) and not
                self.CAN_SET_OWNERSHIP):
            raise RuntimeError("Node not found %s", cfgpath)

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

    def set_trace(self, enabled):
        self.trace_enabled = enabled

    def set_verbose(self, enabled):
        self.verbose_enabled = enabled

    def set_event_callback(self, func, events):
        self.event_callback = (func, events)

    def vfs_type(self, dev):
        return 'ext3'
