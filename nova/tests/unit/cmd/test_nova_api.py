# Copyright 2015 HPE, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from nova.cmd import api
from nova import config
from nova import test


# required because otherwise oslo early parse_args dies
@mock.patch.object(config, 'parse_args', new=lambda *args, **kwargs: None)
class TestNovaAPI(test.NoDBTestCase):

    @mock.patch('nova.service.process_launcher')
    def test_with_ec2(self, launcher):
        """Ensure that we don't explode if enabled_apis is wrong.

        If the end user hasn't updated their config, an ec2 entry
        might accidentally kill them in starting up their server. This
        tests that our new safety filter will prevent that.

        The metadata api is excluded because it loads a bunch of the
        network stack, which requires other mocking.
        """
        self.flags(enabled_apis=['ec2', 'osapi_compute'])
        # required because of where the portbind happens, so that we
        # collide on ports.
        self.flags(osapi_compute_listen_port=0)
        api.main()
