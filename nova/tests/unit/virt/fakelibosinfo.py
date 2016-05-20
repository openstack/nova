# Copyright 2016 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


def match_item(obj, fltr):
    key, val = list(fltr._filter.items())[0]
    if key == 'class':
        key = '_class'
    elif key == 'short-id':
        key = 'short_id'
    return getattr(obj, key, None) == val


class Loader(object):

    def process_default_path(self):
        pass

    def get_db(self):
        return Db()


class Db(object):

    def __init__(self):
        # Generate test devices
        self.devs = []
        self.oslist = None

        net = Device()
        net._class = 'net'
        net.name = 'virtio-net'
        self.devs.append(net)

        net = Device()
        net._class = 'block'
        net.name = 'virtio-block'
        self.devs.append(net)

        devlist = DeviceList()
        devlist.devices = self.devs

        fedora = Os()
        fedora.name = 'Fedora 22'
        fedora.id = 'http://fedoraproject.org/fedora/22'
        fedora.short_id = 'fedora22'
        fedora.dev_list = devlist

        self.oslist = OsList()
        self.oslist.os_list = [fedora]

    def get_os_list(self):
        return self.oslist


class Filter(object):
    def __init__(self):
        self._filter = {}

    @classmethod
    def new(cls):
        return cls()

    def add_constraint(self, flt_key, val):
        self._filter[flt_key] = val


class OsList(object):

    def __init__(self):
        self.os_list = []

    def new_filtered(self, fltr):
        new_list = OsList()
        new_list.os_list = [os for os in self.os_list if match_item(os, fltr)]
        return new_list

    def get_length(self):
        return len(self.os_list)

    def get_nth(self, index):
        return self.os_list[index]


class Os(object):
    def __init__(self):
        self.name = None
        self.short_id = None
        self.id = None
        self.dev_list = None

    def get_all_devices(self, fltr):
        new_list = DeviceList()
        new_list.devices = [dev for dev in self.dev_list.devices
                            if match_item(dev, fltr)]
        return new_list

    def get_name(self):
        return self.name


class DeviceList(object):

    def __init__(self):
        self.devices = []

    def get_length(self):
        return len(self.devices)

    def get_nth(self, index):
        return self.devices[index]


class Device(object):
    def __init__(self):
        self.name = None
        self._class = None

    def get_name(self):
        return self.name
