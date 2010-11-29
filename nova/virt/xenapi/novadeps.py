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
