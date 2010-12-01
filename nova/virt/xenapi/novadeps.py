# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

import re
import string

from nova import db
from nova import flags
from nova import process
from nova import utils
from nova import context

from nova.compute import power_state
from nova.auth.manager import AuthManager
from nova.compute import instance_types
from nova.virt import images

XENAPI_POWER_STATE = {
    'Halted': power_state.SHUTDOWN,
    'Running': power_state.RUNNING,
    'Paused': power_state.PAUSED,
    'Suspended': power_state.SHUTDOWN,  # FIXME
    'Crashed': power_state.CRASHED}

from nova import flags

FLAGS = flags.FLAGS

#FIXME: replace with proper target discovery
flags.DEFINE_string('target_host', None, 'iSCSI Target Host')
flags.DEFINE_string('target_port', '3260', 'iSCSI Target Port, 3260 Default')
flags.DEFINE_string('iqn_prefix', 'iqn.2010-10.org.openstack', 'IQN Prefix')


class Instance(object):

    @classmethod
    def get_name(self, instance):
        return instance.name

    @classmethod
    def get_type(self, instance):
        return instance_types.INSTANCE_TYPES[instance.instance_type]

    @classmethod
    def get_project(self, instance):
        return AuthManager().get_project(instance.project_id)

    @classmethod
    def get_project_id(self, instance):
        return instance.project_id

    @classmethod
    def get_image_id(self, instance):
        return instance.image_id

    @classmethod
    def get_kernel_id(self, instance):
        return instance.kernel_id

    @classmethod
    def get_ramdisk_id(self, instance):
        return instance.ramdisk_id

    @classmethod
    def get_network(self, instance):
        # TODO: is ge_admin_context the right context to retrieve?
        return db.project_get_network(context.get_admin_context(),
                                      instance.project_id)

    @classmethod
    def get_mac(self, instance):
        return instance.mac_address

    @classmethod
    def get_user(self, instance):
        return AuthManager().get_user(instance.user_id)


class Network(object):

    @classmethod
    def get_bridge(self, network):
        return network.bridge


class Image(object):

    @classmethod
    def get_url(self, image):
        return images.image_url(image)


class User(object):

    @classmethod
    def get_access(self, user, project):
        return AuthManager().get_access_key(user, project)

    @classmethod
    def get_secret(self, user):
        return user.secret


class Volume(object):

    @classmethod
    def parse_volume_info(self, device_path, mountpoint):
        # Because XCP/XS want a device number instead of a mountpoint
        device_number = Volume.mountpoint_to_number(mountpoint)
        volume_id = Volume.get_volume_id(device_path)
        target_host = Volume.get_target_host(device_path)
        target_port = Volume.get_target_port(device_path)
        target_iqn = Volume.get_iqn(device_path)

        if (device_number < 0) or \
            (volume_id is None) or \
            (target_host is None) or \
            (target_iqn is None):
            raise Exception('Unable to obtain target information %s, %s' %
                            (device_path, mountpoint))

        volume_info = {}
        volume_info['deviceNumber'] = device_number
        volume_info['volumeId'] = volume_id
        volume_info['targetHost'] = target_host
        volume_info['targetPort'] = target_port
        volume_info['targeIQN'] = target_iqn
        return volume_info

    @classmethod
    def mountpoint_to_number(self, mountpoint):
        if mountpoint.startswith('/dev/'):
            mountpoint = mountpoint[5:]
        if re.match('^[hs]d[a-p]$', mountpoint):
            return (ord(mountpoint[2:3]) - ord('a'))
        elif re.match('^vd[a-p]$', mountpoint):
            return (ord(mountpoint[2:3]) - ord('a'))
        elif re.match('^[0-9]+$', mountpoint):
            return string.atoi(mountpoint, 10)
        else:
            logging.warn('Mountpoint cannot be translated: %s', mountpoint)
            return -1

    @classmethod
    def get_volume_id(self, n):
        # FIXME: n must contain at least the volume_id
        # /vol- is for remote volumes
        # -vol- is for local volumes
        # see compute/manager->setup_compute_volume
        volume_id = n[n.find('/vol-') + 1:]
        if volume_id == n:
            volume_id = n[n.find('-vol-') + 1:].replace('--', '-')
        return volume_id

    @classmethod
    def get_target_host(self, n):
        # FIXME: if n is none fall back on flags
        if n is None or FLAGS.target_host:
            return FLAGS.target_host

    @classmethod
    def get_target_port(self, n):
        # FIXME: if n is none fall back on flags
        return FLAGS.target_port

    @classmethod
    def get_iqn(self, n):
        # FIXME: n must contain at least the volume_id
        volume_id = Volume.get_volume_id(n)
        if n is None or FLAGS.iqn_prefix:
            return '%s:%s' % (FLAGS.iqn_prefix, volume_id)
