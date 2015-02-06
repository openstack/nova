# Copyright 2011 OpenStack Foundation
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

from oslo_config import cfg

from nova.api.openstack import extensions as base_extensions
from nova.openstack.common import log as logging

ext_opts = [
    cfg.MultiStrOpt('osapi_compute_extension',
                    default=[
                      'nova.api.openstack.compute.contrib.standard_extensions'
                      ],
                    help='osapi compute extension to load'),
]
CONF = cfg.CONF
CONF.register_opts(ext_opts)

LOG = logging.getLogger(__name__)


class ExtensionManager(base_extensions.ExtensionManager):
    def __init__(self):
        self.cls_list = CONF.osapi_compute_extension
        self.extensions = {}
        self.sorted_ext_list = []
        self._load_extensions()
