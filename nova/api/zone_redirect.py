# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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
#    under the License.import datetime

"""Reroutes calls to child zones on ZoneRouteException's."""

import httplib
import re
import webob
import webob.dec
import webob.exc
import urlparse
import urllib

from nova import exception
from nova import log as logging
from nova import wsgi
from nova.scheduler import api

import novaclient.client as client
import novaclient.exceptions as osexceptions

try:
    import json
except ImportError:
    import simplejson as json


LOG = logging.getLogger('server')


class RequestForwarder(api.ChildZoneHelper):

    def __init__(self, resource, method, body):
        self.resource = resource
        self.method = method
        self.body = body
    
    def process(self, client, zone):
        api_url = zone.api_url
        LOG.debug(_("Zone redirect to: %(api_url)s, " % locals()))
        try:
            if self.method == 'GET':
                response, body = client.get(self.resource, body=self.body)
            elif self.method == 'POST':
                response, body = client.post(self.resource, body=self.body)
            elif self.method == 'PUT':
                response, body = client.put(self.resource, body=self.body)
            elif self.method == 'DELETE':
                response, body = client.delete(self.resource, body=self.body)
        except osexceptions.OpenStackException, e:
            LOG.info(_("Zone returned error: %s ('%s', '%s')"),
                                e.code, e.message, e.details)
            res = webob.Response()
            res.status = "404"
            return res

        status = response.status
        LOG.debug(_("Zone %(api_url)s response: "
                                "%(response)s [%(status)s]/ %(body)s") %
                                    locals())
        res = webob.Response()
        res.status = response['status']
        res.content_type = response['content-type']
        res.body = json.dumps(body)
        return res


class ZoneRedirectMiddleware(wsgi.Middleware):
    """Catches Zone Routing exceptions and delegates the call
       to child zones."""

    @webob.dec.wsgify
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except exception.ZoneRouteException as e:
            if not e.zones:
                exc = webob.exc.HTTPInternalServerError(explanation=
                                        _("No zones to reroute to."))
                return faults.Fault(exc)

            # Todo(sandy): This only works for OpenStack API currently.
            # Needs to be broken out into a driver. 
            scheme, netloc, path, query, frag = \
                                    urlparse.urlsplit(req.path_qs)
            query = urlparse.parse_qsl(query)
            query = [(key, value) for key, value in query if key != 'fresh']
            query = urllib.urlencode(query)
            url = urlparse.urlunsplit((scheme, netloc, path, query, frag))

            m = re.search('/v\d+\.\d+/(.+)', url)
            resource = m.group(1)

            forwarder = RequestForwarder(resource, req.method, req.body)
            for result in forwarder.start(e.zones):
                # Todo(sandy): We need to aggregate multiple successes.
                if result.status_int == 200:
                    return result

            LOG.debug(_("Zone Redirect Middleware returning 404 ..."))
            res = webob.Response()
            res.status = "404"
            return res
