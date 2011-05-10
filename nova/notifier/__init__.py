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

import datetime
import json

from nova import flags
from nova import utils

FLAGS = flags.FLAGS

flags.DEFINE_string('default_notification_level', 'info',
                    'Default notification level for outgoing notifications')

WARN = 'WARN'
INFO = 'INFO'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'
DEBUG = 'DEBUG'

log_levels = (DEBUG, WARN, INFO, ERROR, CRITICAL)

class BadPriorityException(Exception):
    pass

def notify(event_name, publisher_id, event_type, priority, payload):
    """
    Sends a notification using the specified driver

    Message format is as follows:

    publisher_id - the source worker_type.host of the message
    timestamp - the GMT timestamp the notification was sent at
    event_type - the literal type of event (ex. Instance Creation)
    priority - patterned after the enumeration of Python logging levels in
               the set (DEBUG, WARN, INFO, ERROR, CRITICAL)
    payload - A python dictionary of attributes

    The payload will be constructed as a dictionary of the above attributes,
    and converted into a JSON dump, which will then be sent via the transport
    mechanism defined by the driver.

    Message example:

    { 'publisher_id': 'compute.host1',
      'timestamp': '2011-05-09 22:00:14.621831',
      'priority': 'WARN',
      'event_type': 'compute.create_instance',
      'payload': {'instance_id': 12, ... }}

    """
    if priority not in log_levels:
        raise BadPriorityException('%s not in valid priorities' % priority)
    driver = utils.import_class(FLAGS.notification_driver)()
    message = dict(publisher_id=publisher_id,
                   event_type=event_type,
                   priority=priority,
                   payload=payload,
                   time=str(datetime.datetime.utcnow()))
    driver.notify(json.dumps(message))
