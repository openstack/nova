# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Intel, Inc.
# Copyright (c) 2011-2012 OpenStack, LLC.
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

"""
Filter to add support for Trusted Computing Pools.

Filter that only schedules tasks on a host if the integrity (trust)
of that host matches the trust requested in the `extra_specs' for the
flavor.  The `extra_specs' will contain a key/value pair where the
key is `trust'.  The value of this pair (`trusted'/`untrusted') must
match the integrity of that host (obtained from the Attestation
service) before the task can be scheduled on that host.

Note that the parameters to control access to the Attestation Service
are in the `nova.conf' file in a separate `trust' section.  For example,
the config file will look something like:

    [DEFAULT]
    verbose=True
    ...
    [trust]
    server=attester.mynetwork.com

Details on the specific parameters can be found in the file `trust_attest.py'.

Details on setting up and using an Attestation Service can be found at
the Open Attestation project at:

    https://github.com/OpenAttestation/OpenAttestation
"""

import httplib
import socket
import ssl

from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.scheduler import filters


LOG = logging.getLogger(__name__)

trusted_opts = [
    cfg.StrOpt('server',
               default=None,
               help='attestation server http'),
    cfg.StrOpt('server_ca_file',
               default=None,
               help='attestation server Cert file for Identity verification'),
    cfg.StrOpt('port',
               default='8443',
               help='attestation server port'),
    cfg.StrOpt('api_url',
               default='/OpenAttestationWebServices/V1.0',
               help='attestation web API URL'),
    cfg.StrOpt('auth_blob',
               default=None,
               help='attestation authorization blob - must change'),
]

FLAGS = flags.FLAGS
trust_group = cfg.OptGroup(name='trusted_computing', title='Trust parameters')
FLAGS.register_group(trust_group)
FLAGS.register_opts(trusted_opts, group='trusted_computing')


class HTTPSClientAuthConnection(httplib.HTTPSConnection):
    """
    Class to make a HTTPS connection, with support for full client-based
    SSL Authentication
    """

    def __init__(self, host, port, key_file, cert_file, ca_file, timeout=None):
        httplib.HTTPSConnection.__init__(self, host,
                                         key_file=key_file,
                                         cert_file=cert_file)
        self.host = host
        self.port = port
        self.key_file = key_file
        self.cert_file = cert_file
        self.ca_file = ca_file
        self.timeout = timeout

    def connect(self):
        """
        Connect to a host on a given (SSL) port.
        If ca_file is pointing somewhere, use it to check Server Certificate.

        Redefined/copied and extended from httplib.py:1105 (Python 2.6.x).
        This is needed to pass cert_reqs=ssl.CERT_REQUIRED as parameter to
        ssl.wrap_socket(), which forces SSL to check server certificate
        against our client certificate.
        """
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = ssl.wrap_socket(sock, self.key_file, self.cert_file,
                                    ca_certs=self.ca_file,
                                    cert_reqs=ssl.CERT_REQUIRED)


class AttestationService(httplib.HTTPSConnection):
    # Provide access wrapper to attestation server to get integrity report.

    def __init__(self):
        self.api_url = FLAGS.trusted_computing.api_url
        self.host = FLAGS.trusted_computing.server
        self.port = FLAGS.trusted_computing.port
        self.auth_blob = FLAGS.trusted_computing.auth_blob
        self.key_file = None
        self.cert_file = None
        self.ca_file = FLAGS.trusted_computing.server_ca_file
        self.request_count = 100

    def _do_request(self, method, action_url, body, headers):
        # Connects to the server and issues a request.
        # :returns: result data
        # :raises: IOError if the request fails

        action_url = "%s/%s" % (self.api_url, action_url)
        try:
            c = HTTPSClientAuthConnection(self.host, self.port,
                                          key_file=self.key_file,
                                          cert_file=self.cert_file,
                                          ca_file=self.ca_file)
            c.request(method, action_url, body, headers)
            res = c.getresponse()
            status_code = res.status
            if status_code in (httplib.OK,
                               httplib.CREATED,
                               httplib.ACCEPTED,
                               httplib.NO_CONTENT):
                return httplib.OK, res
            return status_code, None

        except (socket.error, IOError) as e:
            return IOError, None

    def _request(self, cmd, subcmd, host):
        body = {}
        body['count'] = 1
        body['hosts'] = host
        cooked = jsonutils.dumps(body)
        headers = {}
        headers['content-type'] = 'application/json'
        headers['Accept'] = 'application/json'
        if self.auth_blob:
            headers['x-auth-blob'] = self.auth_blob
        status, res = self._do_request(cmd, subcmd, cooked, headers)
        if status == httplib.OK:
            data = res.read()
            return status, jsonutils.loads(data)
        else:
            return status, None

    def _check_trust(self, data, host):
        for item in data:
            for state in item['hosts']:
                if state['host_name'] == host:
                    return state['trust_lvl']
        return ""

    def do_attestation(self, host):
        state = []
        status, data = self._request("POST", "PollHosts", host)
        if status != httplib.OK:
            return {}
        state.append(data)
        return self._check_trust(state, host)


class TrustedFilter(filters.BaseHostFilter):
    """Trusted filter to support Trusted Compute Pools."""

    def __init__(self):
        self.attestation_service = AttestationService()

    def _is_trusted(self, host, trust):
        level = self.attestation_service.do_attestation(host)
        LOG.debug(_("TCP: trust state of "
                    "%(host)s:%(level)s(%(trust)s)") % locals())
        return trust == level

    def host_passes(self, host_state, filter_properties):
        instance = filter_properties.get('instance_type', {})
        extra = instance.get('extra_specs', {})
        trust = extra.get('trust:trusted_host')
        host = host_state.host
        if trust:
            return self._is_trusted(host, trust)
        return True
