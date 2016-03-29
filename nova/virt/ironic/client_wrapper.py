# coding=utf-8
#
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

import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_utils import importutils

from nova import exception
from nova.i18n import _


LOG = logging.getLogger(__name__)
CONF = cfg.CONF

ironic = None

# The API version required by the Ironic driver
IRONIC_API_VERSION = (1, 8)


class IronicClientWrapper(object):
    """Ironic client wrapper class that encapsulates retry logic."""

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

    def _invalidate_cached_client(self):
        """Tell the wrapper to invalidate the cached ironic-client."""
        self._cached_client = None

    def _get_client(self, retry_on_conflict=True):
        max_retries = CONF.ironic.api_max_retries if retry_on_conflict else 1
        retry_interval = (CONF.ironic.api_retry_interval
                          if retry_on_conflict else 0)

        # If we've already constructed a valid, authed client, just return
        # that.
        if retry_on_conflict and self._cached_client is not None:
            return self._cached_client

        auth_token = CONF.ironic.admin_auth_token
        if auth_token is None:
            kwargs = {'os_username': CONF.ironic.admin_username,
                      'os_password': CONF.ironic.admin_password,
                      'os_auth_url': CONF.ironic.admin_url,
                      'os_tenant_name': CONF.ironic.admin_tenant_name,
                      'os_service_type': 'baremetal',
                      'os_endpoint_type': 'public',
                      'ironic_url': CONF.ironic.api_endpoint}
        else:
            kwargs = {'os_auth_token': auth_token,
                      'ironic_url': CONF.ironic.api_endpoint}

        if CONF.ironic.cafile:
            kwargs['os_cacert'] = CONF.ironic.cafile
            # Set the old option for compat with old clients
            kwargs['ca_file'] = CONF.ironic.cafile

        # Retries for Conflict exception
        kwargs['max_retries'] = max_retries
        kwargs['retry_interval'] = retry_interval
        kwargs['os_ironic_api_version'] = '%d.%d' % IRONIC_API_VERSION
        try:
            cli = ironic.client.get_client(IRONIC_API_VERSION[0], **kwargs)
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
        """Call an Ironic client method and retry on errors.

        :param method: Name of the client method to call as a string.
        :param args: Client method arguments.
        :param kwargs: Client method keyword arguments.
        :param retry_on_conflict: Boolean value. Whether the request should be
                                  retried in case of a conflict error
                                  (HTTP 409) or not. If retry_on_conflict is
                                  False the cached instance of the client
                                  won't be used. Defaults to True.
        :raises: NovaException if all retries failed.
        """
        # TODO(dtantsur): drop these once ironicclient 0.8.0 is out and used in
        # global-requirements.
        retry_excs = (ironic.exc.ServiceUnavailable,
                      ironic.exc.ConnectionRefused)
        retry_on_conflict = kwargs.pop('retry_on_conflict', True)

        # num_attempts should be the times of retry + 1
        # eg. retry==0 just means  run once and no retry
        num_attempts = max(0, CONF.ironic.api_max_retries) + 1

        for attempt in range(1, num_attempts + 1):
            client = self._get_client(retry_on_conflict=retry_on_conflict)

            try:
                return self._multi_getattr(client, method)(*args, **kwargs)
            except ironic.exc.Unauthorized:
                # In this case, the authorization token of the cached
                # ironic-client probably expired. So invalidate the cached
                # client and the next try will start with a fresh one.
                self._invalidate_cached_client()
                LOG.debug("The Ironic client became unauthorized. "
                          "Will attempt to reauthorize and try again.")
            except retry_excs:
                pass

            # We want to perform this logic for all exception cases listed
            # above.
            msg = (_("Error contacting Ironic server for "
                     "'%(method)s'. Attempt %(attempt)d of %(total)d") %
                        {'method': method,
                         'attempt': attempt,
                         'total': num_attempts})
            if attempt == num_attempts:
                LOG.error(msg)
                raise exception.NovaException(msg)
            LOG.warning(msg)
            time.sleep(CONF.ironic.api_retry_interval)
