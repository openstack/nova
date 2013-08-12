# Copyright 2011 OpenStack Foundation.
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

from oslo.config import cfg

from nova.openstack.common import context as req_context
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging
from nova.openstack.common import rpc

LOG = logging.getLogger(__name__)

notification_topic_opt = cfg.ListOpt(
    'notification_topics', default=['notifications', ],
    help='AMQP topic used for OpenStack notifications')

CONF = cfg.CONF
CONF.register_opt(notification_topic_opt)


def notify(context, message):
    """Sends a notification via RPC."""
    if not context:
        context = req_context.get_admin_context()
    priority = message.get('priority',
                           CONF.default_notification_level)
    priority = priority.lower()
    for topic in CONF.notification_topics:
        topic = '%s.%s' % (topic, priority)
        try:
            rpc.notify(context, topic, message)
        except Exception:
            LOG.exception(_("Could not send notification to %(topic)s. "
                            "Payload=%(message)s"), locals())
