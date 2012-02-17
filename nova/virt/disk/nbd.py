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
"""Support for mounting images with qemu-nbd"""

import os
import time

from nova import flags
from nova.openstack.common import cfg
from nova import utils
from nova.virt.disk import mount


nbd_opts = [
    cfg.IntOpt('timeout_nbd',
               default=10,
               help='time to wait for a NBD device coming up'),
    cfg.IntOpt('max_nbd_devices',
               default=16,
               help='maximum number of possible nbd devices'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(nbd_opts)


class Mount(mount.Mount):
    """qemu-nbd support disk images."""
    mode = 'nbd'

    # NOTE(padraig): There are three issues with this nbd device handling
    #  1. max_nbd_devices should be inferred (#861504)
    #  2. We assume nothing else on the system uses nbd devices
    #  3. Multiple workers on a system can race against each other
    # A patch has been proposed in Nov 2011, to add add a -f option to
    # qemu-nbd, akin to losetup -f. One could test for this by running qemu-nbd
    # with just the -f option, where it will fail if not supported, or if there
    # are no free devices. Note that patch currently hardcodes 16 devices.
    # We might be able to alleviate problem 2. by scanning /proc/partitions
    # like the aformentioned patch does.
    _DEVICES = ['/dev/nbd%s' % i for i in range(FLAGS.max_nbd_devices)]

    def _allocate_nbd(self):
        if not os.path.exists("/sys/block/nbd0"):
            self.error = _('nbd unavailable: module not loaded')
            return None
        while True:
            if not self._DEVICES:
                # really want to log this info, not raise
                self.error = _('No free nbd devices')
                return None
            device = self._DEVICES.pop()
            if not os.path.exists("/sys/block/%s/pid" %
                                  os.path.basename(device)):
                break
        return device

    def _free_nbd(self, device):
        self._DEVICES.append(device)

    def get_dev(self):
        device = self._allocate_nbd()
        if not device:
            return False
        _out, err = utils.trycmd('qemu-nbd', '-c', device, self.image,
                                 run_as_root=True)
        if err:
            self.error = _('qemu-nbd error: %s') % err
            self._free_nbd(device)
            return False

        # NOTE(vish): this forks into another process, so give it a chance
        #             to set up before continuing
        for _i in range(FLAGS.timeout_nbd):
            if os.path.exists("/sys/block/%s/pid" % os.path.basename(device)):
                self.device = device
                break
            time.sleep(1)
        else:
            self.error = _('nbd device %s did not show up') % device
            self._free_nbd(device)
            return False

        self.linked = True
        return True

    def unget_dev(self):
        if not self.linked:
            return
        utils.execute('qemu-nbd', '-d', self.device, run_as_root=True)
        self._free_nbd(self.device)
        self.linked = False
        self.device = None
