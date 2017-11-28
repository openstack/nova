# Copyright (c) 2012 Intel, Inc.
# Copyright (c) 2011-2012 OpenStack Foundation
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
Filter to add support for Trusted Computing Pools (EXPERIMENTAL).

Filter that only schedules tasks on a host if the integrity (trust)
of that host matches the trust requested in the ``extra_specs`` for the
flavor.  The ``extra_specs`` will contain a key/value pair where the
key is ``trust``.  The value of this pair (``trusted``/``untrusted``) must
match the integrity of that host (obtained from the Attestation
service) before the task can be scheduled on that host.

Note that the parameters to control access to the Attestation Service
are in the ``nova.conf`` file in a separate ``trust`` section.  For example,
the config file will look something like:

    [DEFAULT]
    debug=True
    ...
    [trust]
    server=attester.mynetwork.com

Details on the specific parameters can be found in the file
``trust_attest.py``.

Details on setting up and using an Attestation Service can be found at
the Open Attestation project at:

    https://github.com/OpenAttestation/OpenAttestation
"""

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_serialization import jsonutils
from oslo_utils import timeutils
import requests

import nova.conf
from nova import context
from nova.i18n import _LW
from nova import objects
from nova.scheduler import filters

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class AttestationService(object):
    # Provide access wrapper to attestation server to get integrity report.

    def __init__(self):
        self.api_url = CONF.trusted_computing.attestation_api_url
        self.host = CONF.trusted_computing.attestation_server
        self.port = CONF.trusted_computing.attestation_port
        self.auth_blob = CONF.trusted_computing.attestation_auth_blob
        self.key_file = None
        self.cert_file = None
        self.ca_file = CONF.trusted_computing.attestation_server_ca_file
        self.request_count = 100
        # If the CA file is not provided, let's check the cert if verification
        # asked
        self.verify = (not CONF.trusted_computing.attestation_insecure_ssl
                       and self.ca_file or True)
        self.cert = (self.cert_file, self.key_file)

    def _do_request(self, method, action_url, body, headers):
        # Connects to the server and issues a request.
        # :returns: result data
        # :raises: IOError if the request fails

        action_url = "https://%s:%d%s/%s" % (self.host, self.port,
                                             self.api_url, action_url)
        try:
            res = requests.request(method, action_url, data=body,
                                   headers=headers, cert=self.cert,
                                   verify=self.verify)
            status_code = res.status_code
            if status_code in (requests.codes.OK,
                               requests.codes.CREATED,
                               requests.codes.ACCEPTED,
                               requests.codes.NO_CONTENT):
                try:
                    return requests.codes.OK, jsonutils.loads(res.text)
                except (TypeError, ValueError):
                    return requests.codes.OK, res.text
            return status_code, None

        except requests.exceptions.RequestException:
            return IOError, None

    def _request(self, cmd, subcmd, hosts):
        body = {}
        body['count'] = len(hosts)
        body['hosts'] = hosts
        cooked = jsonutils.dumps(body)
        headers = {}
        headers['content-type'] = 'application/json'
        headers['Accept'] = 'application/json'
        if self.auth_blob:
            headers['x-auth-blob'] = self.auth_blob
        status, res = self._do_request(cmd, subcmd, cooked, headers)
        return status, res

    def do_attestation(self, hosts):
        """Attests compute nodes through OAT service.

        :param hosts: hosts list to be attested
        :returns: dictionary for trust level and validate time
        """
        result = None

        status, data = self._request("POST", "PollHosts", hosts)
        if data is not None:
            result = data.get('hosts')

        return result


class ComputeAttestationCache(object):
    """Cache for compute node attestation

    Cache compute node's trust level for sometime,
    if the cache is out of date, poll OAT service to flush the
    cache.

    OAT service may have cache also. OAT service's cache valid time
    should be set shorter than trusted filter's cache valid time.
    """

    def __init__(self):
        self.attestservice = AttestationService()
        self.compute_nodes = {}
        admin = context.get_admin_context()

        # Fetch compute node list to initialize the compute_nodes,
        # so that we don't need poll OAT service one by one for each
        # host in the first round that scheduler invokes us.
        computes = objects.ComputeNodeList.get_all(admin)
        for compute in computes:
            host = compute.hypervisor_hostname
            self._init_cache_entry(host)

    def _cache_valid(self, host):
        cachevalid = False
        if host in self.compute_nodes:
            node_stats = self.compute_nodes.get(host)
            if not timeutils.is_older_than(
                             node_stats['vtime'],
                             CONF.trusted_computing.attestation_auth_timeout):
                cachevalid = True
        return cachevalid

    def _init_cache_entry(self, host):
        self.compute_nodes[host] = {
            'trust_lvl': 'unknown',
            'vtime': timeutils.normalize_time(
                        timeutils.parse_isotime("1970-01-01T00:00:00Z"))}

    def _invalidate_caches(self):
        for host in self.compute_nodes:
            self._init_cache_entry(host)

    def _update_cache_entry(self, state):
        entry = {}

        host = state['host_name']
        entry['trust_lvl'] = state['trust_lvl']

        try:
            # Normalize as naive object to interoperate with utcnow().
            entry['vtime'] = timeutils.normalize_time(
                            timeutils.parse_isotime(state['vtime']))
        except ValueError:
            try:
                # Mt. Wilson does not necessarily return an ISO8601 formatted
                # `vtime`, so we should try to parse it as a string formatted
                # datetime.
                vtime = timeutils.parse_strtime(state['vtime'], fmt="%c")
                entry['vtime'] = timeutils.normalize_time(vtime)
            except ValueError:
                # Mark the system as un-trusted if get invalid vtime.
                entry['trust_lvl'] = 'unknown'
                entry['vtime'] = timeutils.utcnow()

        self.compute_nodes[host] = entry

    def _update_cache(self):
        self._invalidate_caches()
        states = self.attestservice.do_attestation(
            list(self.compute_nodes.keys()))
        if states is None:
            return
        for state in states:
            self._update_cache_entry(state)

    def get_host_attestation(self, host):
        """Check host's trust level."""
        if host not in self.compute_nodes:
            self._init_cache_entry(host)
        if not self._cache_valid(host):
            self._update_cache()
        level = self.compute_nodes.get(host).get('trust_lvl')
        return level


class ComputeAttestation(object):
    def __init__(self):
        self.caches = ComputeAttestationCache()

    def is_trusted(self, host, trust):
        level = self.caches.get_host_attestation(host)
        return trust == level


class TrustedFilter(filters.BaseHostFilter):
    """Trusted filter to support Trusted Compute Pools."""

    RUN_ON_REBUILD = False

    def __init__(self):
        self.compute_attestation = ComputeAttestation()
        msg = _LW('The TrustedFilter is deprecated as it has been marked '
                  'experimental for some time with no tests. It will be '
                  'removed in the 17.0.0 Queens release.')
        versionutils.report_deprecated_feature(LOG, msg)

    # The hosts the instances are running on doesn't change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, spec_obj):
        instance_type = spec_obj.flavor
        extra = (instance_type.extra_specs
                 if 'extra_specs' in instance_type else {})
        trust = extra.get('trust:trusted_host')
        host = host_state.nodename
        if trust:
            return self.compute_attestation.is_trusted(host, trust)
        return True
