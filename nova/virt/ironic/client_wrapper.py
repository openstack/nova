# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

from keystoneauth1 import discover as ks_disc
from keystoneauth1 import loading as ks_loading
from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova import exception
from nova.i18n import _
from nova import utils


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF

ironic = None

IRONIC_GROUP = nova.conf.ironic.ironic_group

# The API version required by the Ironic driver
IRONIC_API_VERSION = (1, 38)
# NOTE(TheJulia): This version should ALWAYS be the _last_ release
# supported version of the API version used by nova. If a feature
# needs 1.38 to be negotiated to operate properly, then the version
# above should be updated, and this version should only be changed
# once a cycle to the API version desired for features merging in
# that cycle.
PRIOR_IRONIC_API_VERSION = (1, 37)


class IronicClientWrapper(object):
    """Ironic client wrapper class that encapsulates authentication logic."""

    def __init__(self):
        """Initialise the IronicClientWrapper for use.

        Initialise IronicClientWrapper by loading ironicclient
        dynamically so that ironicclient is not a dependency for
        Nova.
        """
        global ironic
        if ironic is None:
            ironic = importutils.import_module('ironicclient')
            # NOTE(deva): work around a lack of symbols in the current version.
            if not hasattr(ironic, 'exc'):
                ironic.exc = importutils.import_module('ironicclient.exc')
            if not hasattr(ironic, 'client'):
                ironic.client = importutils.import_module(
                                                    'ironicclient.client')
        self._cached_client = None

    def _get_auth_plugin(self):
        """Load an auth plugin from CONF options."""
        # If an auth plugin name is defined in `auth_type` option of [ironic]
        # group, register its options and load it.
        auth_plugin = ks_loading.load_auth_from_conf_options(CONF,
                                                             IRONIC_GROUP.name)

        return auth_plugin

    def _get_client(self, retry_on_conflict=True):
        max_retries = CONF.ironic.api_max_retries if retry_on_conflict else 1
        retry_interval = (CONF.ironic.api_retry_interval
                          if retry_on_conflict else 0)

        # If we've already constructed a valid, authed client, just return
        # that.
        if retry_on_conflict and self._cached_client is not None:
            return self._cached_client

        auth_plugin = self._get_auth_plugin()

        sess = ks_loading.load_session_from_conf_options(CONF,
                                                         IRONIC_GROUP.name,
                                                         auth=auth_plugin)

        # Retries for Conflict exception
        kwargs = {}
        kwargs['max_retries'] = max_retries
        kwargs['retry_interval'] = retry_interval
        # NOTE(TheJulia): The ability for a list of available versions to be
        # accepted was added in python-ironicclient 2.2.0. The highest
        # available version will be utilized by the client for the lifetime
        # of the client.
        kwargs['os_ironic_api_version'] = [
            '%d.%d' % IRONIC_API_VERSION, '%d.%d' % PRIOR_IRONIC_API_VERSION]

        ironic_conf = CONF[IRONIC_GROUP.name]
        # valid_interfaces is a list. ironicclient passes this kwarg through to
        # ksa, which is set up to handle 'interface' as either a list or a
        # single value.
        kwargs['interface'] = ironic_conf.valid_interfaces

        # NOTE(clenimar/efried): by default, the endpoint is taken from the
        # service catalog. Use `endpoint_override` if you want to override it.
        if CONF.ironic.api_endpoint:
            # NOTE(efried): `api_endpoint` still overrides service catalog and
            # `endpoint_override` conf options. This will be removed in a
            # future release.
            ironic_url = CONF.ironic.api_endpoint
        else:
            try:
                ksa_adap = utils.get_ksa_adapter(
                    nova.conf.ironic.DEFAULT_SERVICE_TYPE,
                    ksa_auth=auth_plugin, ksa_session=sess,
                    min_version=IRONIC_API_VERSION,
                    max_version=(IRONIC_API_VERSION[0], ks_disc.LATEST))
                ironic_url = ksa_adap.get_endpoint()
            except exception.ServiceNotFound:
                # NOTE(efried): No reason to believe service catalog lookup
                # won't also fail in ironic client init, but this way will
                # yield the expected exception/behavior.
                ironic_url = None

        try:
            cli = ironic.client.get_client(IRONIC_API_VERSION[0],
                                           ironic_url=ironic_url,
                                           session=sess, **kwargs)
            # Cache the client so we don't have to reconstruct and
            # reauthenticate it every time we need it.
            if retry_on_conflict:
                self._cached_client = cli

        except ironic.exc.Unauthorized:
            msg = _("Unable to authenticate Ironic client.")
            LOG.error(msg)
            raise exception.NovaException(msg)

        return cli

    def _multi_getattr(self, obj, attr):
        """Support nested attribute path for getattr().

        :param obj: Root object.
        :param attr: Path of final attribute to get. E.g., "a.b.c.d"

        :returns: The value of the final named attribute.
        :raises: AttributeError will be raised if the path is invalid.
        """
        for attribute in attr.split("."):
            obj = getattr(obj, attribute)
        return obj

    def call(self, method, *args, **kwargs):
        """Call an Ironic client method and retry on stale token.

        :param method: Name of the client method to call as a string.
        :param args: Client method arguments.
        :param kwargs: Client method keyword arguments.
        :param retry_on_conflict: Boolean value. Whether the request should be
                                  retried in case of a conflict error
                                  (HTTP 409) or not. If retry_on_conflict is
                                  False the cached instance of the client
                                  won't be used. Defaults to True.
        """
        retry_on_conflict = kwargs.pop('retry_on_conflict', True)

        # authentication retry for token expiration is handled in keystone
        # session, other retries are handled by ironicclient starting with
        # 0.8.0
        client = self._get_client(retry_on_conflict=retry_on_conflict)
        return self._multi_getattr(client, method)(*args, **kwargs)

    @property
    def current_api_version(self):
        """Value representing the negotiated API client version.

        This value represents the current negotiated API version that
        is being utilized by the client to permit the caller to make
        decisions based upon that version.

        :returns: The highest available negotiatable version or None
                  if a version has not yet been negotiated by the underlying
                  client library.
        """
        return self._get_client().current_api_version

    @property
    def is_api_version_negotiated(self):
        """Boolean to indicate if the client version has been negotiated.

        :returns: True if the underlying client library has completed API
                  version negotiation. Otherwise the value returned is
                  False.
        """
        return self._get_client().is_api_version_negotiated
