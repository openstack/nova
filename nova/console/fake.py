# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

"""Fake ConsoleProxy driver for tests."""

from nova import exception


class FakeConsoleProxy(object):
    """Fake ConsoleProxy driver."""

    @property
    def console_type(self):
        return 'fake'

    def setup_console(self, context, console):
        """Sets up actual proxies."""
        pass

    def teardown_console(self, context, console):
        """Tears down actual proxies."""
        pass

    def init_host(self):
        """Start up any config'ed consoles on start."""
        pass

    def generate_password(self, length=8):
        """Returns random console password."""
        return 'fakepass'

    def get_port(self, context):
        """Get available port for consoles that need one."""
        return 5999

    def fix_pool_password(self, password):
        """Trim password to length, and any other massaging."""
        return password

    def fix_console_password(self, password):
        """Trim password to length, and any other massaging."""
        return password
