# Service heartbeat driver using Memcached
# Copyright (c) 2013 Akira Yoshiyama <akirayoshiyama at gmail dot com>
#
# This is derived from nova/servicegroup/drivers/db.py.
# Copyright 2012 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import iso8601
from oslo_log import log as logging
from oslo_utils import timeutils

from nova import cache_utils
import nova.conf
from nova.i18n import _, _LI, _LW
from nova.servicegroup import api
from nova.servicegroup.drivers import base


CONF = nova.conf.CONF


LOG = logging.getLogger(__name__)


class MemcachedDriver(base.Driver):

    def __init__(self, *args, **kwargs):
        self.mc = cache_utils.get_memcached_client(
                expiration_time=CONF.service_down_time)

    def join(self, member_id, group_id, service=None):
        """Join the given service with its group."""

        LOG.debug('Memcached_Driver: join new ServiceGroup member '
                  '%(member_id)s to the %(group_id)s group, '
                  'service = %(service)s',
                  {'member_id': member_id,
                   'group_id': group_id,
                   'service': service})
        if service is None:
            raise RuntimeError(_('service is a mandatory argument for '
                                 'Memcached based ServiceGroup driver'))
        report_interval = service.report_interval
        if report_interval:
            service.tg.add_timer_args(
                report_interval, self._report_state, args=[service],
                initial_delay=api.INITIAL_REPORTING_DELAY)

    def is_up(self, service_ref):
        """Moved from nova.utils
        Check whether a service is up based on last heartbeat.
        """
        key = "%(topic)s:%(host)s" % service_ref
        is_up = self.mc.get(str(key)) is not None
        if not is_up:
            LOG.debug('Seems service %s is down', key)

        return is_up

    def updated_time(self, service_ref):
        """Get the updated time from memcache"""
        key = "%(topic)s:%(host)s" % service_ref
        updated_time_in_mc = self.mc.get(str(key))
        updated_time_in_db = service_ref['updated_at']

        if updated_time_in_mc:
            # Change mc time to offset-aware time
            updated_time_in_mc = updated_time_in_mc.replace(tzinfo=iso8601.UTC)
            # If [DEFAULT]/enable_new_services is set to be false, the
            # ``updated_time_in_db`` will be None, in this case, use
            # ``updated_time_in_mc`` instead.
            if (not updated_time_in_db or
                    updated_time_in_db <= updated_time_in_mc):
                return updated_time_in_mc

        return updated_time_in_db

    def _report_state(self, service):
        """Update the state of this service in the datastore."""
        try:
            key = "%(topic)s:%(host)s" % service.service_ref
            # memcached has data expiration time capability.
            # set(..., time=CONF.service_down_time) uses it and
            # reduces key-deleting code.
            self.mc.set(str(key),
                        timeutils.utcnow())

            # TODO(termie): make this pattern be more elegant.
            if getattr(service, 'model_disconnected', False):
                service.model_disconnected = False
                LOG.info(
                    _LI('Recovered connection to memcache server '
                        'for reporting service status.'))

        # TODO(vish): this should probably only catch connection errors
        except Exception:
            if not getattr(service, 'model_disconnected', False):
                service.model_disconnected = True
                LOG.warning(_LW('Lost connection to memcache server '
                             'for reporting service status.'))
