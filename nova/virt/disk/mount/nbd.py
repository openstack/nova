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
"""Support for mounting images with qemu-nbd."""

import os
import random
import re
import time

from oslo_log import log as logging

import nova.conf
from nova.i18n import _
from nova import utils
from nova.virt.disk.mount import api

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

NBD_DEVICE_RE = re.compile('nbd[0-9]+')


class NbdMount(api.Mount):
    """qemu-nbd support disk images."""
    mode = 'nbd'

    def _detect_nbd_devices(self):
        """Detect nbd device files."""
        return filter(NBD_DEVICE_RE.match, os.listdir('/sys/block/'))

    def _find_unused(self, devices):
        for device in devices:
            if not os.path.exists(os.path.join('/sys/block/', device, 'pid')):
                if not os.path.exists('/var/lock/qemu-nbd-%s' % device):
                    return device
                else:
                    LOG.error('NBD error - previous umount did not '
                              'cleanup /var/lock/qemu-nbd-%s.', device)
        LOG.warning('No free nbd devices')
        return None

    def _allocate_nbd(self):
        if not os.path.exists('/sys/block/nbd0'):
            LOG.error('nbd module not loaded')
            self.error = _('nbd unavailable: module not loaded')
            return None

        devices = self._detect_nbd_devices()
        random.shuffle(devices)
        device = self._find_unused(devices)
        if not device:
            # really want to log this info, not raise
            self.error = _('No free nbd devices')
            return None
        return os.path.join('/dev', device)

    @utils.synchronized('nbd-allocation-lock')
    def _inner_get_dev(self):
        device = self._allocate_nbd()
        if not device:
            return False

        # NOTE(mikal): qemu-nbd will return an error if the device file is
        # already in use.
        LOG.debug('Get nbd device %(dev)s for %(imgfile)s',
                  {'dev': device, 'imgfile': self.image.path})
        _out, err = utils.trycmd('qemu-nbd', '-c', device,
                                 self.image.path,
                                 run_as_root=True)
        if err:
            self.error = _('qemu-nbd error: %s') % err
            LOG.info('NBD mount error: %s', self.error)
            return False

        # NOTE(vish): this forks into another process, so give it a chance
        # to set up before continuing
        pidfile = "/sys/block/%s/pid" % os.path.basename(device)
        for _i in range(CONF.timeout_nbd):
            if os.path.exists(pidfile):
                self.device = device
                break
            time.sleep(1)
        else:
            self.error = _('nbd device %s did not show up') % device
            LOG.info('NBD mount error: %s', self.error)

            # Cleanup
            _out, err = utils.trycmd('qemu-nbd', '-d', device,
                                     run_as_root=True)
            if err:
                LOG.warning('Detaching from erroneous nbd device returned '
                            'error: %s', err)
            return False

        self.error = ''
        self.linked = True
        return True

    def get_dev(self):
        """Retry requests for NBD devices."""
        return self._get_dev_retry_helper()

    def unget_dev(self):
        if not self.linked:
            return
        LOG.debug('Release nbd device %s', self.device)
        utils.execute('qemu-nbd', '-d', self.device, run_as_root=True)
        self.linked = False
        self.device = None

    def flush_dev(self):
        """flush NBD block device buffer."""
        # Perform an explicit BLKFLSBUF to support older qemu-nbd(s).
        # Without this flush, when a nbd device gets re-used the
        # qemu-nbd intermittently hangs.
        if self.device:
            utils.execute('blockdev', '--flushbufs',
                          self.device, run_as_root=True)
