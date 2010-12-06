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

from nova import db
from nova import flags
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
