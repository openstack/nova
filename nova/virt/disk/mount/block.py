# Copyright 2015 Rackspace Hosting, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Support for mounting block device based images directly."""

from nova.virt.disk.mount import api


class BlockMount(api.Mount):
    """Block device backed images do not need to be linked because
       they are already exposed as block devices and can be mounted
       directly.
    """
    mode = 'block'

    def get_dev(self):
        self.device = self.image.path
        self.linked = True
        return True

    def unget_dev(self):
        self.linked = False
        self.device = None
