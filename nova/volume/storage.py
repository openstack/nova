# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Nova Storage manages creating, attaching, detaching, and
destroying persistent storage volumes, ala EBS.
Currently uses Ata-over-Ethernet.
"""

import glob
import logging
import random
import socket
import subprocess
import time

from nova import vendor
from tornado import ioloop
from twisted.internet import defer

from nova import datastore
from nova import exception
from nova import flags
from nova import rpc
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('storage_dev', '/dev/sdb',
                    'Physical device to use for volumes')
flags.DEFINE_string('volume_group', 'nova-volumes',
                    'Name for the VG that will contain exported volumes')
flags.DEFINE_string('aoe_eth_dev', 'eth0',
                    'Which device to export the volumes on')
flags.DEFINE_string('storage_name',
                    socket.gethostname(),
                    'name of this node')
flags.DEFINE_integer('shelf_id',
                    utils.last_octet(utils.get_my_ip()),
                    'AoE shelf_id for this node')
flags.DEFINE_string('storage_availability_zone',
                    'nova',
                    'availability zone of this node')
flags.DEFINE_boolean('fake_storage', False,
                     'Should we make real storage volumes to attach?')

class BlockStore(object):
    def __init__(self):
        super(BlockStore, self).__init__()
        self.volume_class = Volume
        if FLAGS.fake_storage:
            self.volume_class = FakeVolume
        self._init_volume_group()
        self.keeper = datastore.Keeper('storage-')

    def report_state(self):
        #TODO: aggregate the state of the system
        pass

    def create_volume(self, size, user_id):
        """
        Creates an exported volume (fake or real),
        restarts exports to make it available.
        Volume at this point has size, owner, and zone.
        """
        logging.debug("Creating volume of size: %s" % (size))
        vol = self.volume_class.create(size, user_id)
        self.keeper.set_add('volumes', vol['volume_id'])
        self._restart_exports()
        return vol['volume_id']

    def get_volume(self, volume_id):
        """ Returns a redis-backed volume object """
        if self.keeper.set_is_member('volumes', volume_id):
            return self.volume_class(volume_id=volume_id)
        raise exception.Error("Volume does not exist")

    def by_project(self, project):
        """ returns a list of volume objects for a project """
        # TODO(termie): I don't understand why this is doing a range
        #for volume_id in datastore.Redis.instance().lrange("project:%s:volumes" %
                                    #project, 0, -1):
        for volume_id in datastore['project:%s:volumes' % project]:
            yield self.volume_class(volume_id=volume_id)

    def by_node(self, node_id):
        """ returns a list of volumes for a node """
        for volume in self.all:
            if volume['node_name'] == node_id:
                yield volume

    @property
    def all(self):
        """ returns a list of all volumes """
        for volume_id in self.keeper['volumes']:
            yield self.volume_class(volume_id=volume_id)


    def delete_volume(self, volume_id):
        logging.debug("Deleting volume with id of: %s" % (volume_id))
        vol = self.get_volume(volume_id)
        vol.destroy()
        self.keeper.set_remove('volumes', vol['volume_id'])
        return True

    def attach_volume(self, volume_id, instance_id, mountpoint):
        self.volume_class(volume_id).attach(instance_id, mountpoint)

    def detach_volume(self, volume_id):
        self.volume_class(volume_id).detach()

    def loop_volumes(self):
        volumes = subprocess.Popen(["sudo", "lvs", "--noheadings"], stdout=subprocess.PIPE).communicate()[0].split("\n")
        for lv in volumes:
            if len(lv.split(" ")) > 1:
                yield lv.split(" ")[2]

    def _restart_exports(self):
        if FLAGS.fake_storage:
            return
        utils.runthis("Setting exports to auto: %s", "sudo vblade-persist auto all")
        utils.runthis("Starting all exports: %s", "sudo vblade-persist start all")
        utils.runthis("Discovering AOE devices: %s", "sudo aoe-discover")

    def _init_volume_group(self):
        if FLAGS.fake_storage:
            return
        utils.runthis("PVCreate returned: %s", "sudo pvcreate %s" % (FLAGS.storage_dev))
        utils.runthis("VGCreate returned: %s", "sudo vgcreate %s %s" % (FLAGS.volume_group, FLAGS.storage_dev))


class FakeBlockStore(BlockStore):
    def __init__(self):
        super(FakeBlockStore, self).__init__()

    def loop_volumes(self):
        return self.volumes

    def _init_volume_group(self):
        pass

    def _restart_exports(self):
        pass


class Volume(datastore.RedisModel):

    object_type = 'volume'

    def __init__(self, volume_id=None):
        self.volume_id = volume_id
        super(Volume, self).__init__(object_id=volume_id)

    @classmethod
    def create(cls, size, user_id):
        volume_id = utils.generate_uid('vol')
        vol = cls(volume_id=volume_id)
        #TODO(vish): do we really need to store the volume id as .object_id .volume_id and ['volume_id']?
        vol['volume_id'] = volume_id
        vol['node_name'] = FLAGS.storage_name
        vol['size'] = size
        vol['user_id'] = user_id
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol["instance_id"] = 'none'
        vol["mountpoint"] = 'none'
        vol["create_time"] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        vol["attachment_set"] = ''
        vol.create_lv()
        vol.setup_export()
        vol['status'] = "available"
        vol.save()
        return vol

    def attach(self, instance_id, mountpoint):
        self['instance_id'] = instance_id
        self['mountpoint'] = mountpoint
        self['status'] = "attached"
        self.save()

    def detach(self):
        self['instance_id'] = None
        self['mountpoint'] = None
        self['status'] = "available"
        self.save()

    def destroy(self):
        try:
            self._remove_export()
        except:
            pass
        self._delete_lv()
        super(Volume, self).destroy()

    def create_lv(self):
        if str(self['size']) == '0':
            sizestr = '100M'
        else:
            sizestr = '%sG' % self['size']
        utils.runthis("Creating LV: %s", "sudo lvcreate -L %s -n %s %s" % (sizestr, self.volume_id, FLAGS.volume_group))

    def _delete_lv(self):
        utils.runthis("Removing LV: %s", "sudo lvremove -f %s/%s" % (FLAGS.volume_group, self.volume_id))

    def setup_export(self):
        (shelf_id, blade_id) = get_next_aoe_numbers()
        self['aoe_device'] = "e%s.%s" % (shelf_id, blade_id)
        self.save()
        utils.runthis("Creating AOE export: %s",
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (shelf_id, blade_id, FLAGS.aoe_eth_dev, FLAGS.volume_group, self.volume_id))

    def _remove_export(self):
        utils.runthis("Destroyed AOE export: %s", "sudo vblade-persist stop %s %s" % (self.aoe_device[1], self.aoe_device[3]))
        utils.runthis("Destroyed AOE export: %s", "sudo vblade-persist destroy %s %s" % (self.aoe_device[1], self.aoe_device[3]))


class FakeVolume(Volume):
    def create_lv(self):
        pass

    def setup_export(self):
        # TODO(???): This may not be good enough?
        self['aoe_device'] = 'e%s.%s' % (FLAGS.shelf_id,
                                      ''.join([random.choice('0123456789') for x in xrange(3)]))
        self.save()

    def _remove_export(self):
        pass

    def _delete_lv(self):
        pass

def get_next_aoe_numbers():
    aoes = subprocess.Popen("sudo ls -1 /var/lib/vblade-persist/vblades/", shell=True, stdout=subprocess.PIPE).communicate()[0]
    last_aoe = aoes.strip().split("\n")[-1]
    if last_aoe == '':
        last_aoe = 'e0.0'
    logging.debug("Last aoe is %s" % (last_aoe))
    blade_id = last_aoe.rpartition(".")[2]
    shelf_id = FLAGS.shelf_id
    blade_id = int(blade_id) + 1
    return (shelf_id, blade_id)
