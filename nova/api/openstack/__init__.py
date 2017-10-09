# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
WSGI middleware for OpenStack API controllers.
"""

from oslo_log import log as logging
import routes
import webob.dec
import webob.exc

from nova.api.openstack import wsgi
import nova.conf
from nova.i18n import translate
from nova import utils
from nova import wsgi as base_wsgi


LOG = logging.getLogger(__name__)
CONF = nova.conf.CONF


class FaultWrapper(base_wsgi.Middleware):
    """Calls down the middleware stack, making exceptions into faults."""

    _status_to_type = {}

    @staticmethod
    def status_to_type(status):
        if not FaultWrapper._status_to_type:
            for clazz in utils.walk_class_hierarchy(webob.exc.HTTPError):
                FaultWrapper._status_to_type[clazz.code] = clazz
        return FaultWrapper._status_to_type.get(
                                  status, webob.exc.HTTPInternalServerError)()

    def _error(self, inner, req):
        LOG.exception("Caught error: %s", inner)

        safe = getattr(inner, 'safe', False)
        headers = getattr(inner, 'headers', None)
        status = getattr(inner, 'code', 500)
        if status is None:
            status = 500

        msg_dict = dict(url=req.url, status=status)
        LOG.info("%(url)s returned with HTTP %(status)d", msg_dict)
        outer = self.status_to_type(status)
        if headers:
            outer.headers = headers
        # NOTE(johannes): We leave the explanation empty here on
        # purpose. It could possibly have sensitive information
        # that should not be returned back to the user. See
        # bugs 868360 and 874472
        # NOTE(eglynn): However, it would be over-conservative and
        # inconsistent with the EC2 API to hide every exception,
        # including those that are safe to expose, see bug 1021373
        if safe:
            user_locale = req.best_match_language()
            inner_msg = translate(inner.message, user_locale)
            outer.explanation = '%s: %s' % (inner.__class__.__name__,
                                            inner_msg)

        return wsgi.Fault(outer)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            return self._error(ex, req)


class LegacyV2CompatibleWrapper(base_wsgi.Middleware):

    def _filter_request_headers(self, req):
        """For keeping same behavior with v2 API, ignores microversions
        HTTP headers X-OpenStack-Nova-API-Version and OpenStack-API-Version
        in the request.
        """

        if wsgi.API_VERSION_REQUEST_HEADER in req.headers:
            del req.headers[wsgi.API_VERSION_REQUEST_HEADER]
        if wsgi.LEGACY_API_VERSION_REQUEST_HEADER in req.headers:
            del req.headers[wsgi.LEGACY_API_VERSION_REQUEST_HEADER]
        return req

    def _filter_response_headers(self, response):
        """For keeping same behavior with v2 API, filter out microversions
        HTTP header and microversions field in header 'Vary'.
        """

        if wsgi.API_VERSION_REQUEST_HEADER in response.headers:
            del response.headers[wsgi.API_VERSION_REQUEST_HEADER]
        if wsgi.LEGACY_API_VERSION_REQUEST_HEADER in response.headers:
            del response.headers[wsgi.LEGACY_API_VERSION_REQUEST_HEADER]

        if 'Vary' in response.headers:
            vary_headers = response.headers['Vary'].split(',')
            filtered_vary = []
            for vary in vary_headers:
                vary = vary.strip()
                if (vary == wsgi.API_VERSION_REQUEST_HEADER or
                    vary == wsgi.LEGACY_API_VERSION_REQUEST_HEADER):
                    continue
                filtered_vary.append(vary)
            if filtered_vary:
                response.headers['Vary'] = ','.join(filtered_vary)
            else:
                del response.headers['Vary']
        return response

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        req.set_legacy_v2()
        req = self._filter_request_headers(req)
        response = req.get_response(self.application)
        return self._filter_response_headers(response)


class APIMapper(routes.Mapper):
    def routematch(self, url=None, environ=None):
        if url == "":
            result = self._match("", environ)
            return result[0], result[1]
        return routes.Mapper.routematch(self, url, environ)

    def connect(self, *args, **kargs):
        # NOTE(vish): Default the format part of a route to only accept json
        #             and xml so it doesn't eat all characters after a '.'
        #             in the url.
        kargs.setdefault('requirements', {})
        if not kargs['requirements'].get('format'):
            kargs['requirements']['format'] = 'json|xml'
        return routes.Mapper.connect(self, *args, **kargs)


class ProjectMapper(APIMapper):
    def _get_project_id_token(self):
        # NOTE(sdague): project_id parameter is only valid if its hex
        # or hex + dashes (note, integers are a subset of this). This
        # is required to hand our overlaping routes issues.
        project_id_regex = '[0-9a-f\-]+'
        if CONF.osapi_v21.project_id_regex:
            project_id_regex = CONF.osapi_v21.project_id_regex

        return '{project_id:%s}' % project_id_regex

    def resource(self, member_name, collection_name, **kwargs):
        project_id_token = self._get_project_id_token()
        if 'parent_resource' not in kwargs:
            kwargs['path_prefix'] = '%s/' % project_id_token
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/%s/:%s_id' % (
                project_id_token,
                p_collection,
                p_member)
        routes.Mapper.resource(
            self,
            member_name,
            collection_name,
            **kwargs)

        # while we are in transition mode, create additional routes
        # for the resource that do not include project_id.
        if 'parent_resource' not in kwargs:
            del kwargs['path_prefix']
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/:%s_id' % (p_collection,
                                                   p_member)
        routes.Mapper.resource(self, member_name,
                                     collection_name,
                                     **kwargs)

    def create_route(self, path, method, controller, action):
        project_id_token = self._get_project_id_token()

        # while we transition away from project IDs in the API URIs, create
        # additional routes that include the project_id
        self.connect('/%s%s' % (project_id_token, path),
                     conditions=dict(method=[method]),
                     controller=controller,
                     action=action)
        self.connect(path,
                     conditions=dict(method=[method]),
                     controller=controller,
                     action=action)


class PlainMapper(APIMapper):
    def resource(self, member_name, collection_name, **kwargs):
        if 'parent_resource' in kwargs:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '%s/:%s_id' % (p_collection, p_member)
        routes.Mapper.resource(self, member_name,
                                     collection_name,
                                     **kwargs)
