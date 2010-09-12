# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Drivers for volumes
"""

import logging

from twisted.internet import defer

from nova import exception
from nova import flags
from nova import process


FLAGS = flags.FLAGS
flags.DEFINE_string('volume_group', 'nova-volumes',
                    'Name for the VG that will contain exported volumes')
flags.DEFINE_string('aoe_eth_dev', 'eth0',
                    'Which device to export the volumes on')
flags.DEFINE_string('num_shell_tries', 3,
                    'number of times to attempt to run flakey shell commands')


class AOEDriver(object):
    """Executes commands relating to AOE volumes"""
    def __init__(self, execute=process.simple_execute, *args, **kwargs):
        self._execute = execute

    @defer.inlineCallbacks
    def _try_execute(self, command):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                yield self._execute(command)
                defer.returnValue(True)
            except exception.ProcessExecutionError:
                tries = tries + 1
                if tries >= FLAGS.num_shell_tries:
                    raise
                logging.exception("Recovering from a failed execute."
                                  "Try number %s", tries)
                yield self._execute("sleep %s", tries ** 2)


    @defer.inlineCallbacks
    def create_volume(self, volume_name, size):
        """Creates a logical volume"""
        # NOTE(vish): makes sure that the volume group exists
        yield self._execute("vgs %s" % FLAGS.volume_group)
        if int(size) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % size
        yield self._try_execute("sudo lvcreate -L %s -n %s %s" %
                            (sizestr,
                             volume_name,
                             FLAGS.volume_group))

    @defer.inlineCallbacks
    def delete_volume(self, volume_name):
        """Deletes a logical volume"""
        yield self._try_execute("sudo lvremove -f %s/%s" %
                                (FLAGS.volume_group,
                                 volume_name))

    @defer.inlineCallbacks
    def create_export(self, volume_name, shelf_id, blade_id):
        """Creates an export for a logical volume"""
        yield self._try_execute(
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (shelf_id,
                 blade_id,
                 FLAGS.aoe_eth_dev,
                 FLAGS.volume_group,
                 volume_name))

    @defer.inlineCallbacks
    def discover_volume(self, _volume_name):
        """Discover volume on a remote host"""
        yield self._execute("sudo aoe-discover")
        yield self._execute("sudo aoe-stat")

    @defer.inlineCallbacks
    def remove_export(self, _volume_name, shelf_id, blade_id):
        """Removes an export for a logical volume"""
        yield self._try_execute("sudo vblade-persist stop %s %s" %
                                (shelf_id, blade_id))
        yield self._try_execute("sudo vblade-persist destroy %s %s" %
                                (shelf_id, blade_id))

    @defer.inlineCallbacks
    def ensure_exports(self):
        """Runs all existing exports"""
        # NOTE(vish): The standard _try_execute does not work here
        #             because these methods throw errors if other
        #             volumes on this host are in the process of
        #             being created.  The good news is the command
        #             still works for the other volumes, so we
        #             just wait a bit for the current volume to
        #             be ready and ignore any errors.
        yield self._execute("sleep 2")
        yield self._execute("sudo vblade-persist auto all",
                            check_exit_code=False)
        yield self._execute("sudo vblade-persist start all",
                            check_exit_code=False)


class FakeAOEDriver(AOEDriver):
    """Logs calls instead of executing"""
    def __init__(self, *args, **kwargs):
        super(FakeAOEDriver, self).__init__(self.fake_execute)

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command"""
        logging.debug("FAKE AOE: %s", cmd)
