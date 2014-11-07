# Copyright (c) 2014 The Johns Hopkins University/Applied Physics Laboratory
# All Rights Reserved
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

from nova import test
from nova import utils
from nova.virt.libvirt import dmcrypt


class LibvirtDmcryptTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LibvirtDmcryptTestCase, self).setUp()

        self.CIPHER = 'cipher'
        self.KEY_SIZE = 256
        self.NAME = 'disk'
        self.TARGET = dmcrypt.volume_name(self.NAME)
        self.PATH = '/dev/nova-lvm/instance_disk'
        self.KEY = range(0, self.KEY_SIZE)
        self.KEY_STR = ''.join(["%02x" % x for x in range(0, self.KEY_SIZE)])

        self.executes = []
        self.kwargs = {}

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            self.kwargs = kwargs
            return None, None

        def fake_listdir(path):
            return [self.TARGET, '/dev/mapper/disk']

        self.stubs.Set(utils, 'execute', fake_execute)
        self.stubs.Set(os, 'listdir', fake_listdir)

    def test_create_volume(self):
        expected_commands = [('cryptsetup',
               'create',
               self.TARGET,
               self.PATH,
               '--cipher=' + self.CIPHER,
               '--key-size=' + str(self.KEY_SIZE),
               '--key-file=-')]
        dmcrypt.create_volume(self.TARGET, self.PATH, self.CIPHER,
            self.KEY_SIZE, self.KEY)

        self.assertEqual(expected_commands, self.executes)
        self.assertEqual(self.KEY_STR, self.kwargs['process_input'])

    def test_delete_volume(self):
        expected_commands = [('cryptsetup', 'remove', self.TARGET)]
        dmcrypt.delete_volume(self.TARGET)

        self.assertEqual(expected_commands, self.executes)

    def test_list_volumes(self):
        encrypted_volumes = dmcrypt.list_volumes()

        self.assertEqual([self.TARGET], encrypted_volumes)
