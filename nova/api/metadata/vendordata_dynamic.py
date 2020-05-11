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

import sys

from keystoneauth1 import exceptions as ks_exceptions
from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.api.metadata import vendordata
import nova.conf

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)

_SESSION = None
_ADMIN_AUTH = None


def _load_ks_session(conf):
    """Load session.

    This is either an authenticated session or a requests session, depending on
    what's configured.
    """
    global _ADMIN_AUTH
    global _SESSION

    if not _ADMIN_AUTH:
        _ADMIN_AUTH = ks_loading.load_auth_from_conf_options(
            conf, nova.conf.vendordata.vendordata_group.name)

    if not _ADMIN_AUTH:
        LOG.warning('Passing insecure dynamic vendordata requests '
                    'because of missing or incorrect service account '
                    'configuration.')

    if not _SESSION:
        _SESSION = ks_loading.load_session_from_conf_options(
            conf, nova.conf.vendordata.vendordata_group.name,
            auth=_ADMIN_AUTH)

    return _SESSION


class DynamicVendorData(vendordata.VendorDataDriver):
    def __init__(self, context=None, instance=None, address=None,
                 network_info=None):
        # NOTE(mikal): address and network_info are unused, but can't be
        # removed / renamed as this interface is shared with the static
        # JSON plugin.
        self.context = context
        self.instance = instance
        # We only create the session if we make a request.
        self.session = None

    def _do_request(self, service_name, url):
        if self.session is None:
            self.session = _load_ks_session(CONF)
        try:
            body = {'project-id': self.instance.project_id,
                    'instance-id': self.instance.uuid,
                    'image-id': self.instance.image_ref,
                    'user-data': self.instance.user_data,
                    'hostname': self.instance.hostname,
                    'metadata': self.instance.metadata,
                    'boot-roles': self.instance.system_metadata.get(
                                      'boot_roles', '')}
            headers = {'Content-Type': 'application/json',
                       'Accept': 'application/json',
                       'User-Agent': 'openstack-nova-vendordata'}

            # SSL verification
            verify = url.startswith('https://')

            if verify and CONF.api.vendordata_dynamic_ssl_certfile:
                verify = CONF.api.vendordata_dynamic_ssl_certfile

            timeout = (CONF.api.vendordata_dynamic_connect_timeout,
                       CONF.api.vendordata_dynamic_read_timeout)

            res = self.session.request(url, 'POST', data=jsonutils.dumps(body),
                                       verify=verify, headers=headers,
                                       timeout=timeout)
            if res and res.text:
                # TODO(mikal): Use the Cache-Control response header to do some
                # sensible form of caching here.
                return jsonutils.loads(res.text)

            return {}

        except (TypeError, ValueError,
                ks_exceptions.connection.ConnectionError,
                ks_exceptions.http.HttpError) as e:
            LOG.warning('Error from dynamic vendordata service '
                        '%(service_name)s at %(url)s: %(error)s',
                        {'service_name': service_name,
                         'url': url,
                         'error': e},
                        instance=self.instance)
            if CONF.api.vendordata_dynamic_failure_fatal:
                raise e.with_traceback(sys.exc_info()[2])

            return {}

    def get(self):
        j = {}

        for target in CONF.api.vendordata_dynamic_targets:
            # NOTE(mikal): a target is composed of the following:
            #    name@url
            # where name is the name to use in the metadata handed to
            # instances, and url is the URL to fetch it from
            if target.find('@') == -1:
                LOG.warning('Vendordata target %(target)s lacks a name. '
                            'Skipping',
                            {'target': target}, instance=self.instance)
                continue

            tokens = target.split('@')
            name = tokens[0]
            url = '@'.join(tokens[1:])

            if name in j:
                LOG.warning('Vendordata already contains an entry named '
                            '%(target)s. Skipping',
                            {'target': target}, instance=self.instance)
                continue

            j[name] = self._do_request(name, url)

        return j
