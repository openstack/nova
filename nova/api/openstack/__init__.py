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

from oslo_config import cfg
import routes
import stevedore
import webob.dec
import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova.i18n import _
from nova.i18n import _LC
from nova.i18n import _LE
from nova.i18n import _LI
from nova.i18n import _LW
from nova.i18n import translate
from nova import notifications
from nova.openstack.common import log as logging
from nova import utils
from nova import wsgi as base_wsgi


api_opts = [
        cfg.BoolOpt('enabled',
                    default=False,
                    help='Whether the V3 API is enabled or not'),
        cfg.ListOpt('extensions_blacklist',
                    default=[],
                    help='A list of v3 API extensions to never load. '
                    'Specify the extension aliases here.'),
        cfg.ListOpt('extensions_whitelist',
                    default=[],
                    help='If the list is not empty then a v3 API extension '
                    'will only be loaded if it exists in this list. Specify '
                    'the extension aliases here.')
]
api_opts_group = cfg.OptGroup(name='osapi_v3', title='API v3 Options')

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.register_group(api_opts_group)
CONF.register_opts(api_opts, api_opts_group)

# List of v3 API extensions which are considered to form
# the core API and so must be present
# TODO(cyeoh): Expand this list as the core APIs are ported to V3
API_V3_CORE_EXTENSIONS = set(['os-consoles',
                              'extensions',
                              'os-flavor-extra-specs',
                              'os-flavor-manage',
                              'flavors',
                              'ips',
                              'os-keypairs',
                              'os-flavor-access',
                              'server-metadata',
                              'servers',
                              'versions'])


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
        LOG.exception(_LE("Caught error: %s"), unicode(inner))

        safe = getattr(inner, 'safe', False)
        headers = getattr(inner, 'headers', None)
        status = getattr(inner, 'code', 500)
        if status is None:
            status = 500

        msg_dict = dict(url=req.url, status=status)
        LOG.info(_LI("%(url)s returned with HTTP %(status)d"), msg_dict)
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

        notifications.send_api_fault(req.url, status, inner)
        return wsgi.Fault(outer)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        try:
            return req.get_response(self.application)
        except Exception as ex:
            return self._error(ex, req)


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
    def resource(self, member_name, collection_name, **kwargs):
        if 'parent_resource' not in kwargs:
            kwargs['path_prefix'] = '{project_id}/'
        else:
            parent_resource = kwargs['parent_resource']
            p_collection = parent_resource['collection_name']
            p_member = parent_resource['member_name']
            kwargs['path_prefix'] = '{project_id}/%s/:%s_id' % (p_collection,
                                                                p_member)
        routes.Mapper.resource(self, member_name,
                                     collection_name,
                                     **kwargs)


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


class APIRouter(base_wsgi.Router):
    """Routes requests on the OpenStack API to the appropriate controller
    and method.
    """
    ExtensionManager = None  # override in subclasses

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory, :class:`nova.wsgi.Router` doesn't have one."""
        return cls()

    def __init__(self, ext_mgr=None, init_only=None):
        if ext_mgr is None:
            if self.ExtensionManager:
                ext_mgr = self.ExtensionManager()
            else:
                raise Exception(_("Must specify an ExtensionManager class"))

        mapper = ProjectMapper()
        self.resources = {}
        self._setup_routes(mapper, ext_mgr, init_only)
        self._setup_ext_routes(mapper, ext_mgr, init_only)
        self._setup_extensions(ext_mgr)
        super(APIRouter, self).__init__(mapper)

    def _setup_ext_routes(self, mapper, ext_mgr, init_only):
        for resource in ext_mgr.get_resources():
            LOG.debug('Extending resource: %s',
                      resource.collection)

            if init_only is not None and resource.collection not in init_only:
                continue

            inherits = None
            if resource.inherits:
                inherits = self.resources.get(resource.inherits)
                if not resource.controller:
                    resource.controller = inherits.controller
            wsgi_resource = wsgi.Resource(resource.controller,
                                          inherits=inherits)
            self.resources[resource.collection] = wsgi_resource
            kargs = dict(
                controller=wsgi_resource,
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            mapper.resource(resource.collection, resource.collection, **kargs)

            if resource.custom_routes_fn:
                resource.custom_routes_fn(mapper, wsgi_resource)

    def _setup_extensions(self, ext_mgr):
        for extension in ext_mgr.get_controller_extensions():
            collection = extension.collection
            controller = extension.controller

            msg_format_dict = {'collection': collection,
                               'ext_name': extension.extension.name}
            if collection not in self.resources:
                LOG.warning(_LW('Extension %(ext_name)s: Cannot extend '
                                'resource %(collection)s: No such resource'),
                            msg_format_dict)
                continue

            LOG.debug('Extension %(ext_name)s extended resource: '
                      '%(collection)s',
                      msg_format_dict)

            resource = self.resources[collection]
            resource.register_actions(controller)
            resource.register_extensions(controller)

    def _setup_routes(self, mapper, ext_mgr, init_only):
        raise NotImplementedError()


class APIRouterV21(base_wsgi.Router):
    """Routes requests on the OpenStack v2.1 API to the appropriate controller
    and method.
    """

    @classmethod
    def factory(cls, global_config, **local_config):
        """Simple paste factory, :class:`nova.wsgi.Router` doesn't have one."""
        return cls()

    @staticmethod
    def api_extension_namespace():
        # TODO(oomichi): This namespaces will be changed after moving all v3
        # APIs to v2.1.
        return 'nova.api.v3.extensions'

    def __init__(self, init_only=None, v3mode=False):
        # TODO(cyeoh): bp v3-api-extension-framework. Currently load
        # all extensions but eventually should be able to exclude
        # based on a config file
        # TODO(oomichi): We can remove v3mode argument after moving all v3 APIs
        # to v2.1.
        def _check_load_extension(ext):
            if (self.init_only is None or ext.obj.alias in
                self.init_only) and isinstance(ext.obj,
                                               extensions.V3APIExtensionBase):

                # Check whitelist is either empty or if not then the extension
                # is in the whitelist
                if (not CONF.osapi_v3.extensions_whitelist or
                        ext.obj.alias in CONF.osapi_v3.extensions_whitelist):

                    # Check the extension is not in the blacklist
                    if ext.obj.alias not in CONF.osapi_v3.extensions_blacklist:
                        return self._register_extension(ext)
            return False

        if not CONF.osapi_v3.enabled:
            LOG.info(_LI("V3 API has been disabled by configuration"))
            return

        self.init_only = init_only
        LOG.debug("v3 API Extension Blacklist: %s",
                  CONF.osapi_v3.extensions_blacklist)
        LOG.debug("v3 API Extension Whitelist: %s",
                  CONF.osapi_v3.extensions_whitelist)

        in_blacklist_and_whitelist = set(
            CONF.osapi_v3.extensions_whitelist).intersection(
                CONF.osapi_v3.extensions_blacklist)
        if len(in_blacklist_and_whitelist) != 0:
            LOG.warning(_LW("Extensions in both blacklist and whitelist: %s"),
                        list(in_blacklist_and_whitelist))

        self.api_extension_manager = stevedore.enabled.EnabledExtensionManager(
            namespace=self.api_extension_namespace(),
            check_func=_check_load_extension,
            invoke_on_load=True,
            invoke_kwds={"extension_info": self.loaded_extension_info})

        if v3mode:
            mapper = PlainMapper()
        else:
            mapper = ProjectMapper()

        self.resources = {}

        # NOTE(cyeoh) Core API support is rewritten as extensions
        # but conceptually still have core
        if list(self.api_extension_manager):
            # NOTE(cyeoh): Stevedore raises an exception if there are
            # no plugins detected. I wonder if this is a bug.
            self._register_resources_check_inherits(mapper)
            self.api_extension_manager.map(self._register_controllers)

        missing_core_extensions = self.get_missing_core_extensions(
            self.loaded_extension_info.get_extensions().keys())
        if not self.init_only and missing_core_extensions:
            LOG.critical(_LC("Missing core API extensions: %s"),
                         missing_core_extensions)
            raise exception.CoreAPIMissing(
                missing_apis=missing_core_extensions)

        LOG.info(_LI("Loaded extensions: %s"),
                 sorted(self.loaded_extension_info.get_extensions().keys()))
        super(APIRouterV21, self).__init__(mapper)

    def _register_resources_list(self, ext_list, mapper):
        for ext in ext_list:
            self._register_resources(ext, mapper)

    def _register_resources_check_inherits(self, mapper):
        ext_has_inherits = []
        ext_no_inherits = []

        for ext in self.api_extension_manager:
            for resource in ext.obj.get_resources():
                if resource.inherits:
                    ext_has_inherits.append(ext)
                    break
            else:
                ext_no_inherits.append(ext)

        self._register_resources_list(ext_no_inherits, mapper)
        self._register_resources_list(ext_has_inherits, mapper)

    @staticmethod
    def get_missing_core_extensions(extensions_loaded):
        extensions_loaded = set(extensions_loaded)
        missing_extensions = API_V3_CORE_EXTENSIONS - extensions_loaded
        return list(missing_extensions)

    @property
    def loaded_extension_info(self):
        raise NotImplementedError()

    def _register_extension(self, ext):
        raise NotImplementedError()

    def _register_resources(self, ext, mapper):
        """Register resources defined by the extensions

        Extensions define what resources they want to add through a
        get_resources function
        """

        handler = ext.obj
        LOG.debug("Running _register_resources on %s", ext.obj)

        for resource in handler.get_resources():
            LOG.debug('Extended resource: %s', resource.collection)

            inherits = None
            if resource.inherits:
                inherits = self.resources.get(resource.inherits)
                if not resource.controller:
                    resource.controller = inherits.controller
            wsgi_resource = wsgi.ResourceV21(resource.controller,
                                             inherits=inherits)
            self.resources[resource.collection] = wsgi_resource
            kargs = dict(
                controller=wsgi_resource,
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            # non core-API plugins use the collection name as the
            # member name, but the core-API plugins use the
            # singular/plural convention for member/collection names
            if resource.member_name:
                member_name = resource.member_name
            else:
                member_name = resource.collection
            mapper.resource(member_name, resource.collection,
                            **kargs)

            if resource.custom_routes_fn:
                    resource.custom_routes_fn(mapper, wsgi_resource)

    def _register_controllers(self, ext):
        """Register controllers defined by the extensions

        Extensions define what resources they want to add through
        a get_controller_extensions function
        """

        handler = ext.obj
        LOG.debug("Running _register_controllers on %s", ext.obj)

        for extension in handler.get_controller_extensions():
            ext_name = extension.extension.name
            collection = extension.collection
            controller = extension.controller

            if collection not in self.resources:
                LOG.warning(_LW('Extension %(ext_name)s: Cannot extend '
                                'resource %(collection)s: No such resource'),
                            {'ext_name': ext_name, 'collection': collection})
                continue

            LOG.debug('Extension %(ext_name)s extending resource: '
                      '%(collection)s',
                      {'ext_name': ext_name, 'collection': collection})

            resource = self.resources[collection]
            resource.register_actions(controller)
            resource.register_extensions(controller)
