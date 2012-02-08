# Copyright 2011 OpenStack LLC.
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


import nova.context

from nova import flags
from nova.openstack.common import cfg
from nova import rpc


notification_topic_opt = cfg.ListOpt('notification_topics',
        default=['notifications', ],
        help='AMQP topic used for Nova notifications')

FLAGS = flags.FLAGS
FLAGS.register_opt(notification_topic_opt)


def notify(message):
    """Sends a notification to the RabbitMQ"""
    context = nova.context.get_admin_context()
    priority = message.get('priority',
                           FLAGS.default_notification_level)
    priority = priority.lower()
    for topic in FLAGS.notification_topics:
        topic = '%s.%s' % (topic, priority)
        try:
            rpc.notify(context, topic, message)
        except Exception, e:
            LOG.exception(_("Could not send notification to %(topic)s. "
                            "Payload=%(message)s" % locals()))
