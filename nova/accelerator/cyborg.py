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
    ARQ_URL = "/accelerator_requests"

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

    def _create_arqs(self, dp_name):
        data = {"device_profile_name": dp_name}
        resp, err_msg = self._call_cyborg(self._client.post,
             self.ARQ_URL, json=data)

        if err_msg:
            raise exception.AcceleratorRequestOpFailed(
                op=_('create'), msg=err_msg)

        return resp.json().get('arqs')

    def create_arqs_and_match_resource_providers(self, dp_name, rg_rp_map):
        """Create ARQs, match them with request groups and thereby
          determine their corresponding RPs.

        :param dp_name: Device profile name
        :param rg_rp_map: Request group - Resource Provider map
            {requester_id: [resource_provider_uuid]}
        :returns:
            [arq], with each ARQ associated with an RP
        :raises: DeviceProfileError, AcceleratorRequestOpFailed
        """
        LOG.info('Creating ARQs for device profile %s', dp_name)
        arqs = self._create_arqs(dp_name)
        if not arqs or len(arqs) == 0:
            msg = _('device profile name %s') % dp_name
            raise exception.AcceleratorRequestOpFailed(op=_('create'), msg=msg)
        for arq in arqs:
            dp_group_id = arq['device_profile_group_id']
            arq['device_rp_uuid'] = None
            requester_id = (
                get_device_profile_group_requester_id(dp_group_id))
            arq['device_rp_uuid'] = rg_rp_map[requester_id][0]
        return arqs

    def bind_arqs(self, bindings):
        """Initiate Cyborg bindings.

           Handles RFC 6902-compliant JSON patching, sparing
           calling Nova code from those details.

           :param bindings:
               { "$arq_uuid": {
                     "hostname": STRING
                     "device_rp_uuid": UUID
                     "instance_uuid": UUID
                  },
                  ...
                }
           :returns: nothing
           :raises: AcceleratorRequestOpFailed
        """
        LOG.info('Binding ARQs.')
        # Create a JSON patch in RFC 6902 format
        patch_list = {}
        for arq_uuid, binding in bindings.items():
            patch = [{"path": "/" + field,
                      "op": "add",
                      "value": value
                     } for field, value in binding.items()]
            patch_list[arq_uuid] = patch

        resp, err_msg = self._call_cyborg(self._client.patch,
             self.ARQ_URL, json=patch_list)
        if err_msg:
            msg = _(' Binding failed for ARQ UUIDs: ')
            err_msg = err_msg + msg + ','.join(bindings.keys())
            raise exception.AcceleratorRequestOpFailed(
                op=_('bind'), msg=err_msg)

    def get_arqs_for_instance(self, instance_uuid, only_resolved=False):
        """Get ARQs for the instance.

           :param instance_uuid: Instance UUID
           :param only_resolved: flag to return only resolved ARQs
           :returns: List of ARQs for the instance:
               if only_resolved: only those ARQs which have completed binding
               else: all ARQs
            The format of the returned data structure is as below:
               [
                {'uuid': $arq_uuid,
                 'device_profile_name': $dp_name,
                 'device_profile_group_id': $dp_request_group_index,
                 'state': 'Bound',
                 'device_rp_uuid': $resource_provider_uuid,
                 'hostname': $host_nodename,
                 'instance_uuid': $instance_uuid,
                 'attach_handle_info': {  # PCI bdf
                     'bus': '0c', 'device': '0',
                     'domain': '0000', 'function': '0'},
                 'attach_handle_type': 'PCI'
                      # or 'TEST_PCI' for Cyborg fake driver
                }
               ]
           :raises: AcceleratorRequestOpFailed
        """
        query = {"instance": instance_uuid}
        resp, err_msg = self._call_cyborg(self._client.get,
            self.ARQ_URL, params=query)

        if err_msg:
            err_msg = err_msg + _(' Instance %s') % instance_uuid
            raise exception.AcceleratorRequestOpFailed(
                op=_('get'), msg=err_msg)

        arqs = resp.json().get('arqs')
        if not arqs:
            err_msg = _('Cyborg returned no accelerator requests for '
                        'instance %s') % instance_uuid
            raise exception.AcceleratorRequestOpFailed(
                op=_('get'), msg=err_msg)

        if only_resolved:
            arqs = [arq for arq in arqs if
                    arq['state'] in ['Bound', 'BindFailed', 'Deleting']]
        return arqs

    def delete_arqs_for_instance(self, instance_uuid):
        """Delete ARQs for instance, after unbinding if needed.

           :param instance_uuid: Instance UUID
           :raises: AcceleratorRequestOpFailed
        """
        # Unbind and delete the ARQs
        params = {"instance": instance_uuid}
        resp, err_msg = self._call_cyborg(self._client.delete,
            self.ARQ_URL, params=params)
        if err_msg:
            msg = err_msg + _(' Instance %s') % instance_uuid
            raise exception.AcceleratorRequestOpFailed(
                op=_('delete'), msg=msg)
