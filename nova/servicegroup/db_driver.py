# Copyright (c) IBM 2012 Pavel Kravchenco <kpavel at il dot ibm dot com>
#                        Alexey Roytman <roytman at il dot ibm dot com>
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

from nova import context
from nova import db
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova.servicegroup import api
from nova import utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class DbDriver(api.ServiceGroupDriver):

    def join(self, member_id, group_id, service=None):
        """Join the given service with it's group"""

        msg = _('DB_Driver: join new ServiceGroup member %(member_id)s to '
                    'the %(group_id)s group, service = %(service)s')
        LOG.debug(msg, locals())
        if service is None:
            raise RuntimeError(_('service is a mandatory argument for DB based'
                                 ' ServiceGroup driver'))
        report_interval = service.report_interval
        if report_interval:
            pulse = utils.LoopingCall(self._report_state, service)
            pulse.start(interval=report_interval,
                        initial_delay=report_interval)
            return pulse

    def is_up(self, service_ref):
        """Moved from nova.utils
        Check whether a service is up based on last heartbeat.
        """
        last_heartbeat = service_ref['updated_at'] or service_ref['created_at']
        # Timestamps in DB are UTC.
        elapsed = utils.total_seconds(timeutils.utcnow() - last_heartbeat)
        LOG.debug('DB_Driver.is_up last_heartbeat = %(lhb)s elapsed = %(el)s',
                  {'lhb': str(last_heartbeat), 'el': str(elapsed)})
        return abs(elapsed) <= CONF.service_down_time

    def get_all(self, group_id):
        """
        Returns ALL members of the given group
        """
        LOG.debug(_('DB_Driver: get_all members of the %s group') % group_id)
        rs = []
        ctxt = context.get_admin_context()
        for service in db.service_get_all_by_topic(ctxt, group_id):
            if self.is_up(service):
                rs.append(service['host'])
        return rs

    def _report_state(self, service):
        """Update the state of this service in the datastore."""
        ctxt = context.get_admin_context()
        zone = CONF.node_availability_zone
        state_catalog = {}
        try:
            try:
                service_ref = db.service_get(ctxt, service.service_id)
            except exception.NotFound:
                LOG.debug(_('The service database object disappeared, '
                            'Recreating it.'))
                service._create_service_ref(ctxt)
                service_ref = db.service_get(ctxt, service.service_id)

            state_catalog['report_count'] = service_ref['report_count'] + 1
            if zone != service_ref['availability_zone']:
                state_catalog['availability_zone'] = zone

            db.service_update(ctxt,
                             service.service_id, state_catalog)

            # TODO(termie): make this pattern be more elegant.
            if getattr(service, 'model_disconnected', False):
                service.model_disconnected = False
                LOG.error(_('Recovered model server connection!'))

        # TODO(vish): this should probably only catch connection errors
        except Exception:  # pylint: disable=W0702
            if not getattr(service, 'model_disconnected', False):
                service.model_disconnected = True
                LOG.exception(_('model server went away'))
