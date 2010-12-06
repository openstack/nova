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


"""
It captures all the inner details of Nova classes and avoid their exposure
to the implementation of the XenAPI module. One benefit of this, is to avoid
sprawl of code changes
"""

import re
import string

from nova import db
from nova import flags
from nova import context
from nova import process

from twisted.internet import defer

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

flags.DEFINE_string('xenapi_connection_url',
                    None,
                    'URL for connection to XenServer/Xen Cloud Platform.'
                    ' Required if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_username',
                    'root',
                    'Username for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_password',
                    None,
                    'Password for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_float('xenapi_task_poll_interval',
                   0.5,
                   'The interval used for polling of remote tasks '
                   '(Async.VM.start, etc).  Used only if '
                   'connection_type=xenapi.')
flags.DEFINE_string('target_host',
                    None,
                    'iSCSI Target Host')
flags.DEFINE_string('target_port',
                    '3260',
                    'iSCSI Target Port, 3260 Default')
flags.DEFINE_string('iqn_prefix',
                    'iqn.2010-10.org.openstack',
                    'IQN Prefix')


class Configuration(object):
    """ Wraps Configuration details into common class """
    def __init__(self):
        self._flags = flags.FLAGS

    @property
    def xenapi_connection_url(self):
        """ Return the connection url """
        return self._flags.xenapi_connection_url

    @property
    def xenapi_connection_username(self):
        """ Return the username used for the connection """
        return self._flags.xenapi_connection_username

    @property
    def xenapi_connection_password(self):
        """ Return the password used for the connection """
        return self._flags.xenapi_connection_password

    @property
    def xenapi_task_poll_interval(self):
        """ Return the poll interval for the connection """
        return self._flags.xenapi_task_poll_interval

    @property
    def target_host(self):
        return self._flags.target_host

    @property
    def target_port(self):
        return self._flags.target_port

    @property
    def iqn_prefix(self):
        return self._flags.iqn_prefix


config = Configuration()


class Instance(object):
    """ Wraps up instance specifics """

    @classmethod
    def get_name(cls, instance):
        """ The name of the instance """
        return instance.name

    @classmethod
    def get_type(cls, instance):
        """ The type of the instance """
        return instance_types.INSTANCE_TYPES[instance.instance_type]

    @classmethod
    def get_project(cls, instance):
        """ The project the instance belongs """
        return AuthManager().get_project(instance.project_id)

    @classmethod
    def get_project_id(cls, instance):
        """ The id of the project the instance belongs """
        return instance.project_id

    @classmethod
    def get_image_id(cls, instance):
        """ The instance's image id """
        return instance.image_id

    @classmethod
    def get_kernel_id(cls, instance):
        """ The instance's kernel id """
        return instance.kernel_id

    @classmethod
    def get_ramdisk_id(cls, instance):
        """ The instance's ramdisk id """
        return instance.ramdisk_id

    @classmethod
    def get_network(cls, instance):
        """ The network the instance is connected to """
        # TODO: is ge_admin_context the right context to retrieve?
        return db.project_get_network(context.get_admin_context(),
                                      instance.project_id)

    @classmethod
    def get_mac(cls, instance):
        """ The instance's MAC address """
        return instance.mac_address

    @classmethod
    def get_user(cls, instance):
        """ The owner of the instance """
        return AuthManager().get_user(instance.user_id)


class Network(object):
    """ Wraps up network specifics """

    @classmethod
    def get_bridge(cls, network):
        """ the bridge for the network """
        return network.bridge


class Image(object):
    """ Wraps up image specifics """

    @classmethod
    def get_url(cls, image):
        """ the url to get the image from """
        return images.image_url(image)


class User(object):
    """ Wraps up user specifics """

    @classmethod
    def get_access(cls, user, project):
        """ access key """
        return AuthManager().get_access_key(user, project)

    @classmethod
    def get_secret(cls, user):
        """ access secret """
        return user.secret


class Volume(object):
    """ Wraps up volume specifics """

    @classmethod
    @defer.inlineCallbacks
    def parse_volume_info(cls, device_path, mountpoint):
        """
        Parse device_path and mountpoint as they can be used by XenAPI.
        In particular, the mountpoint (e.g. /dev/sdc) must be translated
        into a numeric literal.
        FIXME: As for device_path, currently cannot be used as it is,
        because it does not contain target information. As for interim
        solution, target details are passed either via Flags or obtained
        by iscsiadm. Long-term solution is to add a few more fields to the
        db in the iscsi_target table with the necessary info and modify
        the iscsi driver to set them.
        """
        device_number = Volume.mountpoint_to_number(mountpoint)
        volume_id = Volume.get_volume_id(device_path)
        (iscsi_name, iscsi_portal) = yield Volume.get_target(volume_id)
        target_host = Volume.get_target_host(iscsi_portal)
        target_port = Volume.get_target_port(iscsi_portal)
        target_iqn = Volume.get_iqn(iscsi_name, volume_id)

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
        defer.returnValue(volume_info)

    @classmethod
    def mountpoint_to_number(cls, mountpoint):
        """ Translate a mountpoint like /dev/sdc into a numberic """
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
    def get_volume_id(cls, n):
        """ Retrieve the volume id from device_path """
        # n must contain at least the volume_id
        # /vol- is for remote volumes
        # -vol- is for local volumes
        # see compute/manager->setup_compute_volume
        volume_id = n[n.find('/vol-') + 1:]
        if volume_id == n:
            volume_id = n[n.find('-vol-') + 1:].replace('--', '-')
        return volume_id

    @classmethod
    def get_target_host(cls, n):
        """ Retrieve target host """
        if n:
            return n[0:n.find(':')]
        elif n is None or config.target_host:
            return config.target_host

    @classmethod
    def get_target_port(cls, n):
        """ Retrieve target port """
        if n:
            return n[n.find(':') + 1:]
        elif  n is None or config.target_port:
            return config.target_port

    @classmethod
    def get_iqn(cls, n, id):
        """ Retrieve target IQN """
        if n:
            return n
        elif n is None or config.iqn_prefix:
            volume_id = Volume.get_volume_id(id)
            return '%s:%s' % (config.iqn_prefix, volume_id)

    @classmethod
    @defer.inlineCallbacks
    def get_target(self, volume_id):
        """
        Gets iscsi name and portal from volume name and host.
        For this method to work the following are needed:
        1) volume_ref['host'] must resolve to something rather than loopback
        2) ietd must bind only to the address as resolved above
        If any of the two conditions are not met, fall back on Flags.
        """
        volume_ref = db.volume_get_by_ec2_id(context.get_admin_context(),
                                             volume_id)

        (r, _e) = yield process.simple_execute("sudo iscsiadm -m discovery -t "
                                         "sendtargets -p %s" %
                                         volume_ref['host'])
        if len(_e) == 0:
            for target in r.splitlines():
                if volume_id in target:
                    (location, _sep, iscsi_name) = target.partition(" ")
                    break
            iscsi_portal = location.split(",")[0]
            defer.returnValue((iscsi_name, iscsi_portal))
        else:
            defer.returnValue((None, None))
