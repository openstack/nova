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
WSGI middleware for OpenStack Compute API.
"""

from oslo_config import cfg
from oslo_log import log as logging

import nova.api.openstack
from nova.api.openstack.compute import extension_info
from nova.api.openstack.compute.legacy_v2 import consoles as v2_consoles
from nova.api.openstack.compute.legacy_v2 import extensions as v2_extensions
from nova.api.openstack.compute.legacy_v2 import flavors as v2_flavors
from nova.api.openstack.compute.legacy_v2 import image_metadata \
        as v2_image_metadata
from nova.api.openstack.compute.legacy_v2 import images as v2_images
from nova.api.openstack.compute.legacy_v2 import ips as v2_ips
from nova.api.openstack.compute.legacy_v2 import limits as v2_limits
from nova.api.openstack.compute.legacy_v2 import server_metadata \
        as v2_server_metadata
from nova.api.openstack.compute.legacy_v2 import servers as v2_servers
from nova.api.openstack.compute.legacy_v2 import versions \
        as legacy_v2_versions
from nova.i18n import _LW

allow_instance_snapshots_opt = cfg.BoolOpt('allow_instance_snapshots',
        default=True,
        help='Permit instance snapshot operations.')

CONF = cfg.CONF
CONF.register_opt(allow_instance_snapshots_opt)

LOG = logging.getLogger(__name__)


class APIRouter(nova.api.openstack.APIRouter):
    """Routes requests on the OpenStack API to the appropriate controller
    and method.
    """
    ExtensionManager = v2_extensions.ExtensionManager

    def __init__(self, ext_mgr=None, init_only=None):
        LOG.warning(_LW(
            "Deprecated: Starting with the Liberty release, the v2 API was "
            "already deprecated and the v2.1 API is set as the default. Nova "
            "also supports v2.1 API legacy v2 compatible mode for switching "
            "to v2.1 API smoothly. For more information on how to configure "
            "v2.1 API and legacy v2 compatible mode, please refer Nova "
            "api-paste.ini sample file."))
        super(APIRouter, self).__init__(ext_mgr=ext_mgr,
                                        init_only=init_only)

    def _setup_routes(self, mapper, ext_mgr, init_only):
        if init_only is None or 'versions' in init_only:
            self.resources['versions'] = legacy_v2_versions.create_resource()
            mapper.connect("versions", "/",
                        controller=self.resources['versions'],
                        action='show',
                        conditions={"method": ['GET']})

        mapper.redirect("", "/")

        if init_only is None or 'consoles' in init_only:
            self.resources['consoles'] = v2_consoles.create_resource()
            mapper.resource("console", "consoles",
                        controller=self.resources['consoles'],
                        parent_resource=dict(member_name='server',
                        collection_name='servers'))

        if init_only is None or 'consoles' in init_only or \
                'servers' in init_only or 'ips' in init_only:
            self.resources['servers'] = v2_servers.create_resource(ext_mgr)
            mapper.resource("server", "servers",
                            controller=self.resources['servers'],
                            collection={'detail': 'GET'},
                            member={'action': 'POST'})

        if init_only is None or 'ips' in init_only:
            self.resources['ips'] = v2_ips.create_resource()
            mapper.resource("ip", "ips", controller=self.resources['ips'],
                            parent_resource=dict(member_name='server',
                                                 collection_name='servers'))

        if init_only is None or 'images' in init_only:
            self.resources['images'] = v2_images.create_resource()
            mapper.resource("image", "images",
                            controller=self.resources['images'],
                            collection={'detail': 'GET'})

        if init_only is None or 'limits' in init_only:
            self.resources['limits'] = v2_limits.create_resource()
            mapper.resource("limit", "limits",
                            controller=self.resources['limits'])

        if init_only is None or 'flavors' in init_only:
            self.resources['flavors'] = v2_flavors.create_resource()
            mapper.resource("flavor", "flavors",
                            controller=self.resources['flavors'],
                            collection={'detail': 'GET'},
                            member={'action': 'POST'})

        if init_only is None or 'image_metadata' in init_only:
            v2immeta = v2_image_metadata
            self.resources['image_metadata'] = v2immeta.create_resource()
            image_metadata_controller = self.resources['image_metadata']

            mapper.resource("image_meta", "metadata",
                            controller=image_metadata_controller,
                            parent_resource=dict(member_name='image',
                            collection_name='images'))

            mapper.connect("metadata",
                           "/{project_id}/images/{image_id}/metadata",
                           controller=image_metadata_controller,
                           action='update_all',
                           conditions={"method": ['PUT']})

        if init_only is None or 'server_metadata' in init_only:
            self.resources['server_metadata'] = \
                v2_server_metadata.create_resource()
            server_metadata_controller = self.resources['server_metadata']

            mapper.resource("server_meta", "metadata",
                            controller=server_metadata_controller,
                            parent_resource=dict(member_name='server',
                            collection_name='servers'))

            mapper.connect("metadata",
                           "/{project_id}/servers/{server_id}/metadata",
                           controller=server_metadata_controller,
                           action='update_all',
                           conditions={"method": ['PUT']})


class APIRouterV21(nova.api.openstack.APIRouterV21):
    """Routes requests on the OpenStack API to the appropriate controller
    and method.
    """
    def __init__(self, init_only=None):
        self._loaded_extension_info = extension_info.LoadedExtensionInfo()
        super(APIRouterV21, self).__init__(init_only)

    def _register_extension(self, ext):
        return self.loaded_extension_info.register_extension(ext.obj)

    @property
    def loaded_extension_info(self):
        return self._loaded_extension_info
