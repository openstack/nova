# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack Foundation
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

import sys
from unittest import mock

from nova.api.openstack import wsgi_app
from nova import test
from nova import utils


class TestInitApplication(test.NoDBTestCase):

    @mock.patch('nova.api.openstack.wsgi_app._setup_service', new=mock.Mock())
    @mock.patch('paste.deploy.loadapp', new=mock.Mock())
    def test_init_application_passes_sys_argv_to_config(self):

        with utils.temporary_mutation(sys, argv=mock.sentinel.argv):
            with mock.patch('nova.config.parse_args') as mock_parse_args:
                wsgi_app.init_application('test-app')
                mock_parse_args.assert_called_once_with(
                    mock.sentinel.argv,
                    default_config_files=[
                        '/etc/nova/api-paste.ini', '/etc/nova/nova.conf'])
