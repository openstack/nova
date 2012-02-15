# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Nexenta Systems, Inc.
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
"""
:mod:`nexenta.jsonrpc` -- Nexenta-specific JSON RPC client
=====================================================================

.. automodule:: nexenta.jsonrpc
.. moduleauthor:: Yuriy Taraday <yorik.sar@gmail.com>
"""

import json
import urllib2

from nova.volume import nexenta
from nova import log as logging

LOG = logging.getLogger("nova.volume.nexenta.jsonrpc")


class NexentaJSONException(nexenta.NexentaException):
    pass


class NexentaJSONProxy(object):
    def __init__(self, url, user, password, auto=False, obj=None, method=None):
        self.url = url
        self.user = user
        self.password = password
        self.auto = auto
        self.obj = obj
        self.method = method

    def __getattr__(self, name):
        if not self.obj:
            obj, method = name, None
        elif not self.method:
            obj, method = self.obj, name
        else:
            obj, method = '%s.%s' % (self.obj, self.method), name
        return NexentaJSONProxy(self.url, self.user, self.password, self.auto,
                                obj, method)

    def __call__(self, *args):
        data = json.dumps({'object': self.obj,
                           'method': self.method,
                           'params': args})
        auth = ('%s:%s' % (self.user, self.password)).encode('base64')[:-1]
        headers = {'Content-Type': 'application/json',
                   'Authorization': 'Basic %s' % (auth,)}
        LOG.debug(_('Sending JSON data: %s'), data)
        request = urllib2.Request(self.url, data, headers)
        response_obj = urllib2.urlopen(request)
        if response_obj.info().status == 'EOF in headers':
            if self.auto and self.url.startswith('http://'):
                LOG.info(_('Auto switching to HTTPS connection to %s'),
                                                                      self.url)
                self.url = 'https' + self.url[4:]
                request = urllib2.Request(self.url, data, headers)
                response_obj = urllib2.urlopen(request)
            else:
                LOG.error(_('No headers in server response'))
                raise NexentaJSONException(_('Bad response from server'))

        response_data = response_obj.read()
        LOG.debug(_('Got response: %s'), response_data)
        response = json.loads(response_data)
        if response.get('error') is not None:
            raise NexentaJSONException(response['error'].get('message', ''))
        else:
            return response.get('result')
