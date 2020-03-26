# Copyright 2019 Intel
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

import six

from oslo_log import log as logging

from keystoneauth1 import exceptions as ks_exc

from nova import exception
from nova.i18n import _
from nova import objects
from nova.scheduler import utils as schedutils
from nova import service_auth
from nova import utils

"""
   Note on object relationships:
   1 device profile (DP) has D >= 1 request groups (just as a flavor
       has many request groups).
   Each DP request group corresponds to exactly 1 numbered request
       group (RG) in the request spec.
   Each numbered RG corresponds to exactly one resource provider (RP).
   A DP request group may request A >= 1 accelerators, and so result
       in the creation of A ARQs.
   Each ARQ corresponds to exactly 1 DP request group.

   A device profile is a dictionary:
   { "name": "mydpname",
     "uuid": <uuid>,
     "groups": [ <device_profile_request_group> ]
   }

   A device profile group is a dictionary too:
    { "resources:CUSTOM_ACCELERATOR_FPGA": "2",
      "resources:CUSTOM_LOCAL_MEMORY": "1",
      "trait:CUSTOM_INTEL_PAC_ARRIA10": "required",
      "trait:CUSTOM_FUNCTION_NAME_FALCON_GZIP_1_1": "required",
       # 0 or more Cyborg properties
      "accel:bitstream_id": "FB021995_BF21_4463_936A_02D49D4DB5E5"
   }

   See cyborg/cyborg/objects/device_profile.py for more details.
"""

LOG = logging.getLogger(__name__)


def get_client(context):
    return _CyborgClient(context)


def get_device_profile_group_requester_id(dp_group_id):
    """Return the value to use in objects.RequestGroup.requester_id.

    The requester_id is used to match device profile groups from
    Cyborg to the request groups in request spec.

    :param dp_group_id: The index of the request group in the device profile.
    """
    req_id = "device_profile_" + str(dp_group_id)
    return req_id


def get_device_profile_request_groups(context, dp_name):
    cyclient = get_client(context)
    return cyclient.get_device_profile_groups(dp_name)


class _CyborgClient(object):
    DEVICE_PROFILE_URL = "/device_profiles"

    def __init__(self, context):
        auth = service_auth.get_auth_plugin(context)
        self._client = utils.get_ksa_adapter('accelerator', ksa_auth=auth)

    def _call_cyborg(self, func, *args, **kwargs):
        resp = err_msg = None
        try:
            resp = func(*args, **kwargs)
            if not resp:
                msg = _('Invalid response from Cyborg: ')
                err_msg = msg + str(resp)
        except ks_exc.ClientException as exc:
            err_msg = _('Could not communicate with Cyborg.')
            LOG.exception('%s: %s', err_msg, six.text_type(exc))

        return resp, err_msg

    def _get_device_profile_list(self, dp_name):
        query = {"name": dp_name}
        err_msg = None

        resp, err_msg = self._call_cyborg(self._client.get,
            self.DEVICE_PROFILE_URL, params=query)

        if err_msg:
            raise exception.DeviceProfileError(name=dp_name, msg=err_msg)

        return resp.json().get('device_profiles')

    def get_device_profile_groups(self, dp_name):
        """Get list of profile group objects from the device profile.

           Cyborg API returns: {"device_profiles": [<device_profile>]}
           See module notes above for further details.

           :param dp_name: string: device profile name
               Expected to be valid, not None or ''.
           :returns: [objects.RequestGroup]
           :raises: DeviceProfileError
        """
        dp_list = self._get_device_profile_list(dp_name)
        if not dp_list:
            msg = _('Expected 1 device profile but got nothing.')
            raise exception.DeviceProfileError(name=dp_name, msg=msg)
        if len(dp_list) != 1:
            err = _('Expected 1 device profile but got %s.') % len(dp_list)
            raise exception.DeviceProfileError(name=dp_name, msg=err)

        dp_groups = dp_list[0]['groups']
        request_groups = []
        for dp_group_id, dp_group in enumerate(dp_groups):
            req_id = get_device_profile_group_requester_id(dp_group_id)
            rg = objects.RequestGroup(requester_id=req_id)
            for key, val in dp_group.items():
                match = schedutils.ResourceRequest.XS_KEYPAT.match(key)
                if not match:
                    continue  # could be 'accel:foo=bar', skip it
                prefix, _ignore, name = match.groups()
                if prefix == schedutils.ResourceRequest.XS_RES_PREFIX:
                    rg.add_resource(rclass=name, amount=val)
                elif prefix == schedutils.ResourceRequest.XS_TRAIT_PREFIX:
                    rg.add_trait(trait_name=name, trait_type=val)
            request_groups.append(rg)
        return request_groups
