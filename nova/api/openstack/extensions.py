# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
# Copyright 2011 Justin Santa Barbara
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

import imp
import inspect
import os
import sys
import routes
import webob.dec
import webob.exc

from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi
from nova.api.openstack import faults


LOG = logging.getLogger('extensions')


FLAGS = flags.FLAGS


class ExtensionDescriptor(object):
    """This is the base class that defines the contract for extensions."""

    def get_name(self):
        """The name of the extension.

        e.g. 'Fox In Socks'

        """
        raise NotImplementedError()

    def get_alias(self):
        """The alias for the extension.

        e.g. 'FOXNSOX'

        """
        raise NotImplementedError()

    def get_description(self):
        """Friendly description for the extension.

        e.g. 'The Fox In Socks Extension'

        """
        raise NotImplementedError()

    def get_namespace(self):
        """The XML namespace for the extension.

        e.g. 'http://www.fox.in.socks/api/ext/pie/v1.0'

        """
        raise NotImplementedError()

    def get_updated(self):
        """The timestamp when the extension was last updated.

        e.g. '2011-01-22T13:25:27-06:00'

        """
        # NOTE(justinsb): Not sure of the purpose of this is, vs the XML NS
        raise NotImplementedError()

    def get_resources(self):
        """List of extensions.ResourceExtension extension objects.

        Resources define new nouns, and are accessible through URLs.

        """
        resources = []
        return resources

    def get_actions(self):
        """List of extensions.ActionExtension extension objects.

        Actions are verbs callable from the API.

        """
        actions = []
        return actions

    def get_response_extensions(self):
        """List of extensions.ResponseExtension extension objects.

        Response extensions are used to insert information into existing
        response data.

        """
        response_exts = []
        return response_exts


class ActionExtensionController(wsgi.Controller):

    def __init__(self, application):

        self.application = application
        self.action_handlers = {}

    def add_action(self, action_name, handler):
        self.action_handlers[action_name] = handler

    def action(self, req, id):

        input_dict = self._deserialize(req.body, req.get_content_type())
        for action_name, handler in self.action_handlers.iteritems():
            if action_name in input_dict:
                return handler(input_dict, req, id)
        # no action handler found (bump to downstream application)
        res = self.application
        return res


class ResponseExtensionController(wsgi.Controller):

    def __init__(self, application):
        self.application = application
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def process(self, req, *args, **kwargs):
        res = req.get_response(self.application)
        content_type = req.best_match_content_type()
        # currently response handlers are un-ordered
        for handler in self.handlers:
            res = handler(res)
            try:
                body = res.body
                headers = res.headers
            except AttributeError:
                body = self._serialize(res, content_type)
                headers = {"Content-Type": content_type}
            res = webob.Response()
            res.body = body
            res.headers = headers
        return res


class ExtensionController(wsgi.Controller):

    def __init__(self, extension_manager):
        self.extension_manager = extension_manager

    def _translate(self, ext):
        ext_data = {}
        ext_data['name'] = ext.get_name()
        ext_data['alias'] = ext.get_alias()
        ext_data['description'] = ext.get_description()
        ext_data['namespace'] = ext.get_namespace()
        ext_data['updated'] = ext.get_updated()
        ext_data['links'] = []  # TODO(dprince): implement extension links
        return ext_data

    def index(self, req):
        extensions = []
        for _alias, ext in self.extension_manager.extensions.iteritems():
            extensions.append(self._translate(ext))
        return dict(extensions=extensions)

    def show(self, req, id):
        # NOTE(dprince): the extensions alias is used as the 'id' for show
        ext = self.extension_manager.extensions[id]
        return self._translate(ext)

    def delete(self, req, id):
        raise faults.Fault(webob.exc.HTTPNotFound())

    def create(self, req):
        raise faults.Fault(webob.exc.HTTPNotFound())


class ExtensionMiddleware(wsgi.Middleware):
    """Extensions middleware for WSGI."""
    @classmethod
    def factory(cls, global_config, **local_config):
        """Paste factory."""
        def _factory(app):
            return cls(app, **local_config)
        return _factory

    def _action_ext_controllers(self, application, ext_mgr, mapper):
        """Return a dict of ActionExtensionController-s by collection."""
        action_controllers = {}
        for action in ext_mgr.get_actions():
            if not action.collection in action_controllers.keys():
                controller = ActionExtensionController(application)
                mapper.connect("/%s/:(id)/action.:(format)" %
                                action.collection,
                                action='action',
                                controller=controller,
                                conditions=dict(method=['POST']))
                mapper.connect("/%s/:(id)/action" % action.collection,
                                action='action',
                                controller=controller,
                                conditions=dict(method=['POST']))
                action_controllers[action.collection] = controller

        return action_controllers

    def _response_ext_controllers(self, application, ext_mgr, mapper):
        """Returns a dict of ResponseExtensionController-s by collection."""
        response_ext_controllers = {}
        for resp_ext in ext_mgr.get_response_extensions():
            if not resp_ext.key in response_ext_controllers.keys():
                controller = ResponseExtensionController(application)
                mapper.connect(resp_ext.url_route + '.:(format)',
                                action='process',
                                controller=controller,
                                conditions=resp_ext.conditions)

                mapper.connect(resp_ext.url_route,
                                action='process',
                                controller=controller,
                                conditions=resp_ext.conditions)
                response_ext_controllers[resp_ext.key] = controller

        return response_ext_controllers

    def __init__(self, application, ext_mgr=None):

        if ext_mgr is None:
            ext_mgr = ExtensionManager(FLAGS.osapi_extensions_path)
        self.ext_mgr = ext_mgr

        mapper = routes.Mapper()

        # extended resources
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                        resource.collection)
            mapper.resource(resource.collection, resource.collection,
                            controller=resource.controller,
                            collection=resource.collection_actions,
                            member=resource.member_actions,
                            parent_resource=resource.parent)

        # extended actions
        action_controllers = self._action_ext_controllers(application, ext_mgr,
                                                        mapper)
        for action in ext_mgr.get_actions():
            LOG.debug(_('Extended action: %s'), action.action_name)
            controller = action_controllers[action.collection]
            controller.add_action(action.action_name, action.handler)

        # extended responses
        resp_controllers = self._response_ext_controllers(application, ext_mgr,
                                                            mapper)
        for response_ext in ext_mgr.get_response_extensions():
            LOG.debug(_('Extended response: %s'), response_ext.key)
            controller = resp_controllers[response_ext.key]
            controller.add_handler(response_ext.handler)

        self._router = routes.middleware.RoutesMiddleware(self._dispatch,
                                                          mapper)

        super(ExtensionMiddleware, self).__init__(application)

    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def __call__(self, req):
        """Route the incoming request with router."""
        req.environ['extended.app'] = self.application
        return self._router

    @staticmethod
    @webob.dec.wsgify(RequestClass=wsgi.Request)
    def _dispatch(req):
        """Dispatch the request.

        Returns the routed WSGI app's response or defers to the extended
        application.

        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return req.environ['extended.app']
        app = match['controller']
        return app


class ExtensionManager(object):
    """Load extensions from the configured extension path.

    See nova/tests/api/openstack/extensions/foxinsocks/extension.py for an
    example extension implementation.

    """

    def __init__(self, path):
        LOG.audit(_('Initializing extension manager.'))

        self.super_verbose = False

        self.path = path
        self.extensions = {}
        self._load_all_extensions()

    def get_resources(self):
        """Returns a list of ResourceExtension objects."""
        resources = []
        resources.append(ResourceExtension('extensions',
                                            ExtensionController(self)))
        for _alias, ext in self.extensions.iteritems():
            resources.extend(ext.get_resources())
        return resources

    def get_actions(self):
        """Returns a list of ActionExtension objects."""
        actions = []
        for _alias, ext in self.extensions.iteritems():
            actions.extend(ext.get_actions())
        return actions

    def get_response_extensions(self):
        """Returns a list of ResponseExtension objects."""
        response_exts = []
        for _alias, ext in self.extensions.iteritems():
            response_exts.extend(ext.get_response_extensions())
        return response_exts

    def _check_extension(self, extension):
        """Checks for required methods in extension objects."""
        try:
            LOG.debug(_('Ext name: %s'), extension.get_name())
            LOG.debug(_('Ext alias: %s'), extension.get_alias())
            LOG.debug(_('Ext description: %s'), extension.get_description())
            LOG.debug(_('Ext namespace: %s'), extension.get_namespace())
            LOG.debug(_('Ext updated: %s'), extension.get_updated())
        except AttributeError as ex:
            LOG.exception(_("Exception loading extension: %s"), unicode(ex))

    def _load_all_extensions(self):
        """Load extensions from the configured path.

        An extension consists of a directory of related files, with a class
        that defines a class that inherits from ExtensionDescriptor.

        Because of some oddities involving identically named modules, it's
        probably best to name your file after the name of your extension,
        rather than something likely to clash like 'extension.py'.

        The name of your directory should be the same as the alias your
        extension uses, for everyone's sanity.

        See nova/tests/api/openstack/extensions/foxinsocks.py for an example
        extension implementation.

        """
        self._load_extensions_under_path(self.path)

        incubator_path = os.path.join(os.path.dirname(__file__), "incubator")
        self._load_extensions_under_path(incubator_path)

    def _load_extensions_under_path(self, path):
        if not os.path.isdir(path):
            LOG.warning(_('Extensions directory not found: %s') % path)
            return

        LOG.debug(_('Looking for extensions in: %s') % path)

        for child in os.listdir(path):
            child_path = os.path.join(path, child)
            if not os.path.isdir(child_path):
                continue
            self._load_extension(child_path)

    def _load_extension(self, path):
        if not os.path.isdir(path):
            return

        for f in os.listdir(path):
            mod_name, file_ext = os.path.splitext(os.path.split(f)[-1])
            if mod_name.startswith('_'):
                continue
            if file_ext.lower() != '.py':
                continue

            ext_path = os.path.join(path, f)
            if self.super_verbose:
                LOG.debug(_('Checking extension file: %s'), ext_path)

            mod = imp.load_source(mod_name, ext_path)
            for _name, cls in inspect.getmembers(mod):
                try:
                    if not inspect.isclass(cls):
                        continue

                    # NOTE(justinsb): It seems that python modules are odd.
                    # If you have two identically named modules, the classes
                    # from both are mixed in.  So name your extension based
                    # on the alias, not 'extension.py'!
                    # TODO(justinsb): Any way to work around this?

                    if self.super_verbose:
                        LOG.debug(_('Checking class: %s'), cls)

                    if not ExtensionDescriptor in cls.__bases__:
                        if self.super_verbose:
                            LOG.debug(_('Not a ExtensionDescriptor: %s'), cls)
                        continue

                    obj = cls()
                    self._add_extension(obj)
                except AttributeError as ex:
                    LOG.exception(_("Exception loading extension: %s"),
                                  unicode(ex))

    def _add_extension(self, ext):
        alias = ext.get_alias()
        LOG.audit(_('Loaded extension: %s'), alias)

        self._check_extension(ext)

        if alias in self.extensions:
            raise exception.Error("Found duplicate extension: %s" % alias)
        self.extensions[alias] = ext


class ResponseExtension(object):
    """Add data to responses from core nova OpenStack API controllers."""

    def __init__(self, method, url_route, handler):
        self.url_route = url_route
        self.handler = handler
        self.conditions = dict(method=[method])
        self.key = "%s-%s" % (method, url_route)


class ActionExtension(object):
    """Add custom actions to core nova OpenStack API controllers."""

    def __init__(self, collection, action_name, handler):
        self.collection = collection
        self.action_name = action_name
        self.handler = handler


class ResourceExtension(object):
    """Add top level resources to the OpenStack API in nova."""

    def __init__(self, collection, controller, parent=None,
                 collection_actions={}, member_actions={}):
        self.collection = collection
        self.controller = controller
        self.parent = parent
        self.collection_actions = collection_actions
        self.member_actions = member_actions
