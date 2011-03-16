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

import novaclient.client as client
import novaclient.exceptions as osexceptions

try:
    import json
except ImportError:
    import simplejson as json


LOG = logging.getLogger('server')


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
            for zone in e.zones:
                url = zone.api_url
                LOG.info(_("Zone redirect to:[url:%(api_url)s, "
                                                "username:%(username)s]"
                            % dict(api_url=zone.api_url,
                                            username=zone.username)))

                nova = client.OpenStackClient(zone.username, zone.password,
                                                    zone.api_url)
                nova.authenticate()
                new_req = req.copy()

                scheme, netloc, path, query, frag = \
                                        urlparse.urlsplit(new_req.path_qs)
                query = urlparse.parse_qsl(query)
                query = [(key, value) for key, value in query if key != 'fresh']
                query = urllib.urlencode(query)
                url = urlparse.urlunsplit((scheme, netloc, path, query, frag))

                m = re.search('/(v\d+\.\d+)/(.+)', url)
                version = m.group(1)
                resource = m.group(2)

                #LOG.info(_("New Request Data: %s"), new_req.body)
                #LOG.info(_("New Request Path: %s"), resource)
                try:
                    if req.method == 'GET':
                        response, body = nova.get(resource, body=new_req.body)
                    elif req.method == 'POST':
                        response, body = nova.post(resource, body=new_req.body)
                    elif req.method == 'PUT':
                        response, body = nova.put(resource, body=new_req.body)
                    elif req.method == 'DELETE':
                        response, body = nova.delete(resource,
                                                            body=new_req.body)
                except osexceptions.OpenStackException, e:
                    LOG.info(_("Zone returned error: %s ('%s', '%s')"),
                                        e.code, e.message, e.details)
                    continue

                LOG.info(_("Zone Response: %s [%s]/ %s"), response,
                                                        response.status, body)
                if response.status == 200:
                    res = webob.Response()
                    res.status = response['status']
                    res.content_type = response['content-type']
                    res.body = json.dumps(body)
                    return res

            LOG.info(_("Returning 404 ..."))
            res = webob.Response()
            res.status = "404"
            return res
