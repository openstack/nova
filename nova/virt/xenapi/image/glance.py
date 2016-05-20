# Copyright 2013 OpenStack Foundation
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

import functools
import sys

from oslo_log import log as logging
import six

from nova.compute import utils as compute_utils
import nova.conf
from nova import exception
from nova.image import glance
from nova import utils
from nova.virt.xenapi import vm_utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class GlanceStore(object):
    def _call_glance_plugin(self, context, instance, session, fn, params):
        glance_api_servers = glance.get_api_servers()

        def pick_glance(kwargs):
            server = next(glance_api_servers)
            kwargs['endpoint'] = server
            # NOTE(sdague): is the return significant here at all?
            return server

        def retry_cb(context, instance, exc=None):
            if exc:
                exc_info = sys.exc_info()
                LOG.debug(six.text_type(exc), exc_info=exc_info)
                compute_utils.add_instance_fault_from_exc(
                    context, instance, exc, exc_info)

        cb = functools.partial(retry_cb, context, instance)

        return session.call_plugin_serialized_with_retry(
            'glance', fn, CONF.glance.num_retries, pick_glance, cb, **params)

    def _make_params(self, context, session, image_id):
        return {'image_id': image_id,
                'sr_path': vm_utils.get_sr_path(session),
                'extra_headers': glance.generate_identity_headers(context)}

    def download_image(self, context, session, instance, image_id):
        params = self._make_params(context, session, image_id)
        params['uuid_stack'] = vm_utils._make_uuid_stack()

        try:
            vdis = self._call_glance_plugin(context, instance, session,
                                            'download_vhd2', params)
        except exception.PluginRetriesExceeded:
            raise exception.CouldNotFetchImage(image_id=image_id)

        return vdis

    def upload_image(self, context, session, instance, image_id, vdi_uuids):
        params = self._make_params(context, session, image_id)
        params['vdi_uuids'] = vdi_uuids

        props = params['properties'] = {}
        props['auto_disk_config'] = instance['auto_disk_config']
        props['os_type'] = instance.get('os_type', None) or (
                CONF.xenserver.default_os_type)

        compression_level = vm_utils.get_compression_level()
        if compression_level:
            props['xenapi_image_compression_level'] = compression_level

        auto_disk_config = utils.get_auto_disk_config_from_instance(instance)
        if utils.is_auto_disk_config_disabled(auto_disk_config):
            props["auto_disk_config"] = "disabled"

        try:
            self._call_glance_plugin(context, instance, session,
                                     'upload_vhd2', params)
        except exception.PluginRetriesExceeded:
            raise exception.CouldNotUploadImage(image_id=image_id)
