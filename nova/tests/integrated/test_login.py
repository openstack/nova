# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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


from nova.log import logging
from nova.tests.integrated import integrated_helpers


LOG = logging.getLogger('nova.tests.integrated')


class LoginTest(integrated_helpers._IntegratedTestBase):
    def test_login(self):
        """Simple check - we list flavors - so we know we're logged in."""
        flavors = self.api.get_flavors()
        for flavor in flavors:
            LOG.debug(_("flavor: %s") % flavor)
