#    Copyright (c) 2012 NTT DOCOMO, INC.
#    Copyright 2011 OpenStack Foundation
#    Copyright 2011 Ilya Alekseyev
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

from nova.cmd import baremetal_manage as bm_man
from nova.tests.virt.baremetal.db import base as bm_db_base


class BareMetalDbCommandsTestCase(bm_db_base.BMDBTestCase):
    def setUp(self):
        super(BareMetalDbCommandsTestCase, self).setUp()
        self.commands = bm_man.BareMetalDbCommands()

    def test_sync_and_version(self):
        self.commands.sync()
        v = self.commands.version()
        self.assertTrue(v > 0)
