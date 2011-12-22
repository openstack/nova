# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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
"""Support for mounting images with the loop device"""

from nova import utils
from nova.virt.disk import mount


class Mount(mount.Mount):
    """loop back support for raw images."""
    mode = 'loop'

    def get_dev(self):
        out, err = utils.trycmd('losetup', '--find', '--show', self.image,
                                run_as_root=True)
        if err:
            self.error = _('Could not attach image to loopback: %s') % err
            return False

        self.device = out.strip()
        self.linked = True
        return True

    def unget_dev(self):
        if not self.linked:
            return
        utils.execute('losetup', '--detach', self.device, run_as_root=True)
        self.linked = False
