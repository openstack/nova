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

import uuid

from nova import flags
from nova import utils


FLAGS = flags.FLAGS

flags.DEFINE_string('default_notification_level', 'INFO',
                    'Default notification level for outgoing notifications')

WARN = 'WARN'
INFO = 'INFO'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'
DEBUG = 'DEBUG'

log_levels = (DEBUG, WARN, INFO, ERROR, CRITICAL)


class BadPriorityException(Exception):
    pass


def publisher_id(service, host=None):
    if not host:
        host = FLAGS.host
    return "%s.%s" % (service, host)


def msgkeys(event_type, instance_id, level, publisher_id):
    return dict(event_type=event_type, instance_id=instance_id, 
                notification_level=level, publisher_id=publisher_id)


def safe_notify(publisher_id, event_type, priority, payload):
    try:
        notify(publisher_id, event_type, notification_level, payload)
    exception Exception, e:
        LOG.exception(_("Problem '%(e)' attempting to "
                        "send to notification system." % locals()))


def instance_safe_notify(publisher_id, event_type, priority, instance_id,
                    extra_payload=None):
    payload = dict(instance_id = instance_id)
    if extra_payload:
        payload.extend(extra_payload)
    safe_notify(publisher_id, event_type, priority, payload)


def exception_to_notification(self, ex):
    required = ['instance_id', 'publisher_id', 'notification_level',
                'event_type']
    for key in required:
        if not (hasattr(ex, key) and ex.key):
            return  # Doesn't have everything we need. Skip it.
    instance_id = ex.instance_id
    publisher_id = ex.publisher_id
    notification_level = ex.notification_level
    event_type = ex.event_type
    instance_safe_notify(publisher_id, event_type, priority, instance_id)

def notify(publisher_id, event_type, priority, payload):
    """
    Sends a notification using the specified driver

    Notify parameters:

    publisher_id - the source worker_type.host of the message
    event_type - the literal type of event (ex. Instance Creation)
    priority - patterned after the enumeration of Python logging levels in
               the set (DEBUG, WARN, INFO, ERROR, CRITICAL)
    payload - A python dictionary of attributes

    Outgoing message format includes the above parameters, and appends the
    following:

    message_id - a UUID representing the id for this notification
    timestamp - the GMT timestamp the notification was sent at

    The composite message will be constructed as a dictionary of the above
    attributes, which will then be sent via the transport mechanism defined
    by the driver.

    Message example:

    {'message_id': str(uuid.uuid4()),
     'publisher_id': 'compute.host1',
     'timestamp': utils.utcnow(),
     'priority': 'WARN',
     'event_type': 'compute.create_instance',
     'payload': {'instance_id': 12, ... }}

    """
    if priority not in log_levels:
        raise BadPriorityException(
                 _('%s not in valid priorities' % priority))
    driver = utils.import_object(FLAGS.notification_driver)
    msg = dict(message_id=str(uuid.uuid4()),
                   publisher_id=publisher_id,
                   event_type=event_type,
                   priority=priority,
                   payload=payload,
                   timestamp=str(utils.utcnow()))
    driver.notify(msg)
