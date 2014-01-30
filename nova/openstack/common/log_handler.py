# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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
import logging

from nova.openstack.common import notifier

from oslo.config import cfg


class PublishErrorsHandler(logging.Handler):
    def emit(self, record):
        if ('nova.openstack.common.notifier.log_notifier' in
                cfg.CONF.notification_driver):
            return
        notifier.api.notify(None, 'error.publisher',
                            'error_notification',
                            notifier.api.ERROR,
                            dict(error=record.msg))
