# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import os

from nova.api.openstack.compute.views import versions as compute_views


def get_view_builder(req):
    base_url = req.application_url
    return ViewBuilder(base_url)


class ViewBuilder(compute_views.ViewBuilder):
    def generate_href(self, path=None):
        """Create an url that refers to a specific version_number."""
        version_number = 'v1'
        if path:
            path = path.strip('/')
            return os.path.join(self.base_url, version_number, path)
        else:
            return os.path.join(self.base_url, version_number) + '/'
