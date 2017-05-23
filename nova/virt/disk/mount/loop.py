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
"""Support for mounting images with the loop device."""

from oslo_log import log as logging

from nova.i18n import _
from nova import utils
from nova.virt.disk.mount import api

LOG = logging.getLogger(__name__)


class LoopMount(api.Mount):
    """loop back support for raw images."""
    mode = 'loop'

    def _inner_get_dev(self):
        out, err = utils.trycmd('losetup', '--find', '--show',
                                self.image.path,
                                run_as_root=True)
        if err:
            self.error = _('Could not attach image to loopback: %s') % err
            LOG.info('Loop mount error: %s', self.error)
            self.linked = False
            self.device = None
            return False

        self.device = out.strip()
        LOG.debug("Got loop device %s", self.device)
        self.linked = True
        return True

    def get_dev(self):
        # NOTE(mikal): the retry is required here in case we are low on loop
        # devices. Note however that modern kernels will use more loop devices
        # if they exist. If you're seeing lots of retries, consider adding
        # more devices.
        return self._get_dev_retry_helper()

    def unget_dev(self):
        if not self.linked:
            return

        # NOTE(mikal): On some kernels, losetup -d will intermittently fail,
        # thus leaking a loop device unless the losetup --detach is retried:
        # https://lkml.org/lkml/2012/9/28/62
        LOG.debug("Release loop device %s", self.device)
        utils.execute('losetup', '--detach', self.device, run_as_root=True,
                      attempts=3)
        self.linked = False
        self.device = None
