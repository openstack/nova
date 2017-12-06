# Copyright 2015, 2018 IBM Corp.
#
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

from nova import exception
from nova.i18n import _
from nova.virt.powervm.volume import fcvscsi


def build_volume_driver(adapter, instance, conn_info, stg_ftsk=None):
    drv_type = conn_info.get('driver_volume_type')
    if drv_type != 'fibre_channel':
        reason = _("Invalid connection type of %s") % drv_type
        raise exception.InvalidVolume(reason=reason)
    return fcvscsi.FCVscsiVolumeAdapter(adapter, instance, conn_info,
                                        stg_ftsk=stg_ftsk)
