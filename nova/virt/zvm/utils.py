# Copyright 2017,2018 IBM Corp.
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

from oslo_log import log as logging
import six
import six.moves.urllib.parse as urlparse
from zvmconnector import connector

from nova import exception


LOG = logging.getLogger(__name__)


class ConnectorClient(object):
    """Request handler to zVM cloud connector"""

    def __init__(self, zcc_url, ca_file=None):
        _url = urlparse.urlparse(zcc_url)

        _ssl_enabled = False

        if _url.scheme == 'https':
            _ssl_enabled = True
        elif ca_file:
            LOG.warning("url is %(url) which is not https "
                        "but ca_file is configured to %(ca_file)s",
                        {'url': zcc_url, 'ca_file': ca_file})

        if _ssl_enabled and ca_file:
            self._conn = connector.ZVMConnector(_url.hostname, _url.port,
                                                ssl_enabled=_ssl_enabled,
                                                verify=ca_file)
        else:
            self._conn = connector.ZVMConnector(_url.hostname, _url.port,
                                                ssl_enabled=_ssl_enabled,
                                                verify=False)

    def call(self, func_name, *args, **kwargs):
        results = self._conn.send_request(func_name, *args, **kwargs)

        if results['overallRC'] != 0:
            LOG.error("zVM Cloud Connector request %(api)s failed with "
               "parameters: %(args)s %(kwargs)s .  Results: %(results)s",
               {'api': func_name, 'args': six.text_type(args),
                'kwargs': six.text_type(kwargs),
                'results': six.text_type(results)})
            raise exception.ZVMConnectorError(results=results)

        return results['output']
