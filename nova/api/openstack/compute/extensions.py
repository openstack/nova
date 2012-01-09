# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova.api.openstack import extensions as base_extensions
from nova import flags
from nova import log as logging


LOG = logging.getLogger('nova.api.openstack.compute.extensions')
FLAGS = flags.FLAGS


class ExtensionManager(base_extensions.ExtensionManager):
    def __new__(cls):
        if cls._ext_mgr is None:
            LOG.audit(_('Initializing extension manager.'))

            cls._ext_mgr = super(ExtensionManager, cls).__new__(cls)

            cls.cls_list = FLAGS.osapi_compute_extension
            cls._ext_mgr.extensions = {}
            cls._ext_mgr._load_extensions()

        return cls._ext_mgr


class ExtensionMiddleware(base_extensions.ExtensionMiddleware):
    def __init__(self, application, ext_mgr=None):
        if not ext_mgr:
            ext_mgr = ExtensionManager()
        super(ExtensionMiddleware, self).__init__(application, ext_mgr)
