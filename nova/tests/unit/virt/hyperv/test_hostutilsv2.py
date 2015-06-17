# Copyright 2015 Cloudbase Solutions Srl
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

import mock

from nova import test
from nova.virt.hyperv import hostutilsv2


class HostUtilsV2TestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V hostutilsv2 class."""

    def setUp(self):
        self._hostutils = hostutilsv2.HostUtilsV2()
        self._hostutils._conn_cimv2 = mock.MagicMock()
        self._hostutils._conn_virt = mock.MagicMock()

        super(HostUtilsV2TestCase, self).setUp()
