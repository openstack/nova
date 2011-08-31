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
from nova import log as logging

LOG = logging.getLogger('nova.exception')

FLAGS = flags.FLAGS

flags.DEFINE_string('default_notification_level', 'INFO',
                    'Default notification level for outgoing notifications')
flags.DEFINE_string('default_publisher_id', FLAGS.host,
                    'Default publisher_id for outgoing notifications')


WARN = 'WARN'
INFO = 'INFO'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'
DEBUG = 'DEBUG'

log_levels = (DEBUG, WARN, INFO, ERROR, CRITICAL)


class BadPriorityException(Exception):
    pass


def notify_decorator(name, fn):
    """ decorator for notify which is used from utils.monkey_patch()

        :param name: name of the function
        :param function: - object of the function
        :returns: function -- decorated function

    """
    def wrapped_func(*args, **kwarg):
        body = {}
        body['args'] = []
        body['kwarg'] = {}
        for arg in args:
            body['args'].append(arg)
        for key in kwarg:
            body['kwarg'][key] = kwarg[key]
        notify(FLAGS.default_publisher_id,
                            name,
                            FLAGS.default_notification_level,
                            body)
        return fn(*args, **kwarg)
    return wrapped_func


def publisher_id(service, host=None):
    if not host:
        host = FLAGS.host
    return "%s.%s" % (service, host)


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

    # Ensure everything is JSON serializable.
    payload = utils.to_primitive(payload, convert_instances=True)

    driver = utils.import_object(FLAGS.notification_driver)
    msg = dict(message_id=str(uuid.uuid4()),
                   publisher_id=publisher_id,
                   event_type=event_type,
                   priority=priority,
                   payload=payload,
                   timestamp=str(utils.utcnow()))
    try:
        driver.notify(msg)
    except Exception, e:
        LOG.exception(_("Problem '%(e)s' attempting to "
                        "send to notification system. Payload=%(payload)s" %
                        locals()))
