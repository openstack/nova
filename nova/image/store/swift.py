# Copyright 2012 OpenStack, LLC
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

import urllib

from nova.image.store import base
from nova.openstack.common import cfg
import nova.openstack.common.log as logging

LOG = logging.getLogger(__name__)

swift_opts = [
    cfg.StrOpt("swift_store_auth_version",
               default="2"),
    cfg.StrOpt("swift_store_auth_address",
               default="http://localhost:5000/v2.0/"),
    cfg.StrOpt("swift_store_user",
               default="tenant:user"),
    cfg.StrOpt("swift_store_key",
               default="openstack"),
    cfg.StrOpt("swift_store_container",
               default="glance"),
    cfg.BoolOpt("swift_store_create_container_on_put",
                default=True),
    cfg.IntOpt("swift_store_large_object_size",
               default=5 * 1024),
    cfg.IntOpt("swift_store_large_object_chunk_size",
               default=4 * 1024),
    cfg.BoolOpt("swift_enable_snet",
                default=False),
    cfg.StrOpt("swift_store_region",
                default=None),
    cfg.BoolOpt("swift_store_multitenant",
                default=False)
]

CONF = cfg.CONF

CONF.register_opts(swift_opts)


class SwiftStore(base.Store):

    def get_store_name(self):
        return "swift"

    def get_location(self, image_id):
        auth_or_store_url = CONF.swift_store_auth_address
        scheme = 'swift+https'

        if auth_or_store_url.startswith('http://'):
            scheme = 'swift+http'
            auth_or_store_url = auth_or_store_url[len('http://'):]
        elif auth_or_store_url.startswith('https://'):
            auth_or_store_url = auth_or_store_url[len('https://'):]

        credstring = self._get_credstring()
        auth_or_store_url = auth_or_store_url.strip('/')
        container = CONF.swift_store_container.strip('/')
        obj = str(image_id).strip('/')

        return '%s://%s%s/%s/%s' % (scheme, credstring, auth_or_store_url,
                                    container, obj)

    def _get_credstring(self):
        if CONF.swift_store_user and CONF.swift_store_key:
            user = urllib.quote(CONF.swift_store_user)
            key = urllib.quote(CONF.swift_store_key)
            return '%s:%s@' % (user, key)
        return ''
