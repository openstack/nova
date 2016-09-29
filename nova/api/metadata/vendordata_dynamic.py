# Copyright 2016 Rackspace Australia
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

"""Render vendordata as stored fetched from REST microservices."""

import requests

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.api.metadata import vendordata
import nova.conf
from nova.i18n import _LW

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def generate_identity_headers(context, status='Confirmed'):
    return {
        'X-Auth-Token': getattr(context, 'auth_token', None),
        'X-User-Id': getattr(context, 'user', None),
        'X-Project-Id': getattr(context, 'tenant', None),
        'X-Roles': ','.join(getattr(context, 'roles', [])),
        'X-Identity-Status': status,
    }


class DynamicVendorData(vendordata.VendorDataDriver):
    def __init__(self, context=None, instance=None, address=None,
                 network_info=None):
        # NOTE(mikal): address and network_info are unused, but can't be
        # removed / renamed as this interface is shared with the static
        # JSON plugin.
        self.context = context
        self.instance = instance

    def _do_request(self, service_name, url):
        try:
            body = {'project-id': self.instance.project_id,
                    'instance-id': self.instance.uuid,
                    'image-id': self.instance.image_ref,
                    'user-data': self.instance.user_data,
                    'hostname': self.instance.hostname,
                    'metadata': self.instance.metadata}
            headers = {'Content-Type': 'application/json',
                       'Accept': 'application/json',
                       'User-Agent': 'openstack-nova-vendordata'}

            if self.context:
                headers.update(generate_identity_headers(self.context))

            # SSL verification
            verify = url.startswith('https://')

            if verify and CONF.vendordata_dynamic_ssl_certfile:
                verify = CONF.vendordata_dynamic_ssl_certfile

            timeout = (CONF.vendordata_dynamic_connect_timeout,
                       CONF.vendordata_dynamic_read_timeout)

            res = requests.request('POST', url, data=jsonutils.dumps(body),
                                   headers=headers, verify=verify,
                                   timeout=timeout)
            if res.status_code in (requests.codes.OK,
                                   requests.codes.CREATED,
                                   requests.codes.ACCEPTED):
                # TODO(mikal): Use the Cache-Control response header to do some
                # sensible form of caching here.
                return jsonutils.loads(res.text)

            return {}

        except (TypeError, ValueError, requests.exceptions.RequestException,
                requests.exceptions.SSLError) as e:
            LOG.warning(_LW('Error from dynamic vendordata service '
                            '%(service_name)s at %(url)s: %(error)s'),
                        {'service_name': service_name,
                         'url': url,
                         'error': e},
                        instance=self.instance)
            return {}

    def get(self):
        j = {}

        for target in CONF.vendordata_dynamic_targets:
            # NOTE(mikal): a target is composed of the following:
            #    name@url
            # where name is the name to use in the metadata handed to
            # instances, and url is the URL to fetch it from
            if target.find('@') == -1:
                LOG.warning(_LW('Vendordata target %(target)s lacks a name. '
                                'Skipping'),
                            {'target': target}, instance=self.instance)
                continue

            tokens = target.split('@')
            name = tokens[0]
            url = '@'.join(tokens[1:])

            if name in j:
                LOG.warning(_LW('Vendordata already contains an entry named '
                                '%(target)s. Skipping'),
                            {'target': target}, instance=self.instance)
                continue

            j[name] = self._do_request(name, url)

        return j
