# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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

import base64
from xml.etree import ElementTree

from nova import flags

FLAGS = flags.FLAGS


def generate_user_data(vsa, volumes):
    SubElement = ElementTree.SubElement

    e_vsa = ElementTree.Element("vsa")

    e_vsa_detail = SubElement(e_vsa, "id")
    e_vsa_detail.text = str(vsa['id'])
    e_vsa_detail = SubElement(e_vsa, "name")
    e_vsa_detail.text = vsa['display_name']
    e_vsa_detail = SubElement(e_vsa, "description")
    e_vsa_detail.text = vsa['display_description']
    e_vsa_detail = SubElement(e_vsa, "vc_count")
    e_vsa_detail.text = str(vsa['vc_count'])

    e_vsa_detail = SubElement(e_vsa, "auth_user")
    e_vsa_detail.text = FLAGS.vsa_ec2_user_id
    e_vsa_detail = SubElement(e_vsa, "auth_access_key")
    e_vsa_detail.text = FLAGS.vsa_ec2_access_key

    e_volumes = SubElement(e_vsa, "volumes")
    for volume in volumes:

        loc = volume['provider_location']
        if loc is None:
            ip = ''
            iscsi_iqn = ''
            iscsi_portal = ''
        else:
            (iscsi_target, _sep, iscsi_iqn) = loc.partition(" ")
            (ip, iscsi_portal) = iscsi_target.split(":", 1)

        e_vol = SubElement(e_volumes, "volume")
        e_vol_detail = SubElement(e_vol, "id")
        e_vol_detail.text = str(volume['id'])
        e_vol_detail = SubElement(e_vol, "name")
        e_vol_detail.text = volume['name']
        e_vol_detail = SubElement(e_vol, "display_name")
        e_vol_detail.text = volume['display_name']
        e_vol_detail = SubElement(e_vol, "size_gb")
        e_vol_detail.text = str(volume['size'])
        e_vol_detail = SubElement(e_vol, "status")
        e_vol_detail.text = volume['status']
        e_vol_detail = SubElement(e_vol, "ip")
        e_vol_detail.text = ip
        e_vol_detail = SubElement(e_vol, "iscsi_iqn")
        e_vol_detail.text = iscsi_iqn
        e_vol_detail = SubElement(e_vol, "iscsi_portal")
        e_vol_detail.text = iscsi_portal
        e_vol_detail = SubElement(e_vol, "lun")
        e_vol_detail.text = '0'
        e_vol_detail = SubElement(e_vol, "sn_host")
        e_vol_detail.text = volume['host']

    _xml = ElementTree.tostring(e_vsa)
    return base64.b64encode(_xml)
