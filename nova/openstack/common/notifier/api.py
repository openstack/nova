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

import socket
import uuid

from oslo.config import cfg

from nova.openstack.common import context
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)

notifier_opts = [
    cfg.MultiStrOpt('notification_driver',
                    default=[],
                    help='Driver or drivers to handle sending notifications'),
    cfg.StrOpt('default_notification_level',
               default='INFO',
               help='Default notification level for outgoing notifications'),
    cfg.StrOpt('default_publisher_id',
               default=None,
               help='Default publisher_id for outgoing notifications'),
]

CONF = cfg.CONF
CONF.register_opts(notifier_opts)

WARN = 'WARN'
INFO = 'INFO'
ERROR = 'ERROR'
CRITICAL = 'CRITICAL'
DEBUG = 'DEBUG'

log_levels = (DEBUG, WARN, INFO, ERROR, CRITICAL)


class BadPriorityException(Exception):
    pass


def notify_decorator(name, fn):
    """Decorator for notify which is used from utils.monkey_patch().

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

        ctxt = context.get_context_from_function_and_args(fn, args, kwarg)
        notify(ctxt,
               CONF.default_publisher_id or socket.gethostname(),
               name,
               CONF.default_notification_level,
               body)
        return fn(*args, **kwarg)
    return wrapped_func


def publisher_id(service, host=None):
    if not host:
        try:
            host = CONF.host
        except AttributeError:
            host = CONF.default_publisher_id or socket.gethostname()
    return "%s.%s" % (service, host)


def notify(context, publisher_id, event_type, priority, payload):
    """Sends a notification using the specified driver

    :param publisher_id: the source worker_type.host of the message
    :param event_type:   the literal type of event (ex. Instance Creation)
    :param priority:     patterned after the enumeration of Python logging
                         levels in the set (DEBUG, WARN, INFO, ERROR, CRITICAL)
    :param payload:       A python dictionary of attributes

    Outgoing message format includes the above parameters, and appends the
    following:

    message_id
      a UUID representing the id for this notification

    timestamp
      the GMT timestamp the notification was sent at

    The composite message will be constructed as a dictionary of the above
    attributes, which will then be sent via the transport mechanism defined
    by the driver.

    Message example::

        {'message_id': str(uuid.uuid4()),
         'publisher_id': 'compute.host1',
         'timestamp': timeutils.utcnow(),
         'priority': 'WARN',
         'event_type': 'compute.create_instance',
         'payload': {'instance_id': 12, ... }}

    """
    if priority not in log_levels:
        raise BadPriorityException(
            _('%s not in valid priorities') % priority)

    # Ensure everything is JSON serializable.
    payload = jsonutils.to_primitive(payload, convert_instances=True)

    msg = dict(message_id=str(uuid.uuid4()),
               publisher_id=publisher_id,
               event_type=event_type,
               priority=priority,
               payload=payload,
               timestamp=str(timeutils.utcnow()))

    for driver in _get_drivers():
        try:
            driver.notify(context, msg)
        except Exception as e:
            LOG.exception(_("Problem '%(e)s' attempting to "
                            "send to notification system. "
                            "Payload=%(payload)s")
                          % dict(e=e, payload=payload))


_drivers = None


def _get_drivers():
    """Instantiate, cache, and return drivers based on the CONF."""
    global _drivers
    if _drivers is None:
        _drivers = {}
        for notification_driver in CONF.notification_driver:
            try:
                driver = importutils.import_module(notification_driver)
                _drivers[notification_driver] = driver
            except ImportError:
                LOG.exception(_("Failed to load notifier %s. "
                                "These notifications will not be sent.") %
                              notification_driver)
    return _drivers.values()


def _reset_drivers():
    """Used by unit tests to reset the drivers."""
    global _drivers
    _drivers = None
