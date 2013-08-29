# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Red Hat, Inc.
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

"""
A temporary helper which emulates oslo.messaging.Notifier.

This helper method allows us to do the tedious porting to the new Notifier API
as a standalone commit so that the commit which switches us to oslo.messaging
is smaller and easier to review. This file will be removed as part of that
commit.
"""

from oslo.config import cfg

from nova.openstack.common.notifier import api as notifier_api

CONF = cfg.CONF


class Notifier(object):

    def __init__(self, publisher_id):
        super(Notifier, self).__init__()
        self.publisher_id = publisher_id

    _marker = object()

    def prepare(self, publisher_id=_marker):
        ret = self.__class__(self.publisher_id)
        if publisher_id is not self._marker:
            ret.publisher_id = publisher_id
        return ret

    def _notify(self, ctxt, event_type, payload, priority):
        notifier_api.notify(ctxt,
                            self.publisher_id,
                            event_type,
                            priority,
                            payload)

    def debug(self, ctxt, event_type, payload):
        self._notify(ctxt, event_type, payload, 'DEBUG')

    def info(self, ctxt, event_type, payload):
        self._notify(ctxt, event_type, payload, 'INFO')

    def warn(self, ctxt, event_type, payload):
        self._notify(ctxt, event_type, payload, 'WARN')

    def error(self, ctxt, event_type, payload):
        self._notify(ctxt, event_type, payload, 'ERROR')

    def critical(self, ctxt, event_type, payload):
        self._notify(ctxt, event_type, payload, 'CRITICAL')


def get_notifier(service=None, host=None, publisher_id=None):
    if not publisher_id:
        publisher_id = "%s.%s" % (service, host or CONF.host)
    return Notifier(publisher_id)
