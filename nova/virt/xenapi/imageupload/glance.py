# Copyright 2013 OpenStack, LLC
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

from oslo.config import cfg

from nova.image import glance
import nova.openstack.common.log as logging
from nova.virt.xenapi import vm_utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF


class GlanceStore(object):

    def upload_image(self, context, session, instance, vdi_uuids, image_id):
        """Requests that the Glance plugin bundle the specified VDIs and
        push them into Glance using the specified human-friendly name.
        """
        # NOTE(sirp): Currently we only support uploading images as VHD, there
        # is no RAW equivalent (yet)
        LOG.debug(_("Asking xapi to upload to glance %(vdi_uuids)s as"
                    " ID %(image_id)s"), locals(), instance=instance)

        glance_api_servers = glance.get_api_servers()
        glance_host, glance_port, glance_use_ssl = glance_api_servers.next()

        properties = {
            'auto_disk_config': instance['auto_disk_config'],
            'os_type': instance['os_type'] or CONF.default_os_type,
        }

        params = {'vdi_uuids': vdi_uuids,
                  'image_id': image_id,
                  'glance_host': glance_host,
                  'glance_port': glance_port,
                  'glance_use_ssl': glance_use_ssl,
                  'sr_path': vm_utils.get_sr_path(session),
                  'auth_token': getattr(context, 'auth_token', None),
                  'properties': properties}

        session.call_plugin_serialized('glance', 'upload_vhd', **params)
