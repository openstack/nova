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

from nova import flags
from nova import process


FLAGS = flags.FLAGS
flags.DEFINE_string('volume_group', 'nova-volumes',
                    'Name for the VG that will contain exported volumes')
flags.DEFINE_string('aoe_eth_dev', 'eth0',
                    'Which device to export the volumes on')


class FakeAOEDriver(object):
    def create_volume(self, volume_id, size):
        logging.debug("Fake AOE: create_volume %s, %s", volume_id, size)

    def delete_volume(self, volume_id):
        logging.debug("Fake AOE: delete_volume %s", volume_id)

    def create_export(self, volume_id, shelf_id, blade_id):
        logging.debug("Fake AOE: create_export %s, %s, %s",
                      volume_id, shelf_id, blade_id)

    def remove_export(self, volume_id, shelf_id, blade_id):
        logging.debug("Fake AOE: remove_export %s, %s, %s",
                      volume_id, shelf_id, blade_id)

    def ensure_exports(self):
        logging.debug("Fake AOE: ensure_export")


class AOEDriver(object):
    def __init__(self, *args, **kwargs):
        super(AOEDriver, self).__init__(*args, **kwargs)

    @defer.inlineCallbacks
    def _ensure_vg(self):
        yield process.simple_execute("vgs | grep %s" % FLAGS.volume_group)

    @defer.inlineCallbacks
    def create_volume(self, volume_id, size):
        self._ensure_vg()
        if int(size) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % size
        yield process.simple_execute(
                "sudo lvcreate -L %s -n %s %s" % (sizestr,
                                                  volume_id,
                                                  FLAGS.volume_group),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def delete_volume(self, volume_id):
        yield process.simple_execute(
                "sudo lvremove -f %s/%s" % (FLAGS.volume_group,
                                            volume_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def create_export(self, volume_id, shelf_id, blade_id):
        yield process.simple_execute(
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (shelf_id,
                 blade_id,
                 FLAGS.aoe_eth_dev,
                 FLAGS.volume_group,
                 volume_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def remove_export(self, _volume_id, shelf_id, blade_id):
        yield process.simple_execute(
                "sudo vblade-persist stop %s %s" % (shelf_id, blade_id),
                terminate_on_stderr=False)
        yield process.simple_execute(
                "sudo vblade-persist destroy %s %s" % (shelf_id, blade_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def ensure_exports(self):
        # NOTE(ja): wait for blades to appear
        yield process.simple_execute("sleep 5")
        yield process.simple_execute("sudo vblade-persist auto all",
                                     check_exit_code=False)
        yield process.simple_execute("sudo vblade-persist start all",
                                     check_exit_code=False)

