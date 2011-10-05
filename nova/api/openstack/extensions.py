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
from lxml import etree

from nova import exception
from nova import flags
from nova import log as logging
from nova import wsgi as base_wsgi
import nova.api.openstack
from nova.api.openstack import common
from nova.api.openstack import faults
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil


LOG = logging.getLogger('extensions')


FLAGS = flags.FLAGS


class ExtensionDescriptor(object):
    """Base class that defines the contract for extensions.

    Note that you don't have to derive from this class to have a valid
    extension; it is purely a convenience.

    """

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

    def get_request_extensions(self):
        """List of extensions.RequestException extension objects.

        Request extensions are used to handle custom request data.

        """
        request_exts = []
        return request_exts


class ActionExtensionController(object):
    def __init__(self, application):
        self.application = application
        self.action_handlers = {}

    def add_action(self, action_name, handler):
        self.action_handlers[action_name] = handler

    def action(self, req, id, body):
        for action_name, handler in self.action_handlers.iteritems():
            if action_name in body:
                return handler(body, req, id)
        # no action handler found (bump to downstream application)
        res = self.application
        return res


class ActionExtensionResource(wsgi.Resource):

    def __init__(self, application):
        controller = ActionExtensionController(application)
        wsgi.Resource.__init__(self, controller)

    def add_action(self, action_name, handler):
        self.controller.add_action(action_name, handler)


class RequestExtensionController(object):

    def __init__(self, application):
        self.application = application
        self.handlers = []

    def add_handler(self, handler):
        self.handlers.append(handler)

    def process(self, req, *args, **kwargs):
        res = req.get_response(self.application)
        # currently request handlers are un-ordered
        for handler in self.handlers:
            res = handler(req, res)
        return res


class RequestExtensionResource(wsgi.Resource):

    def __init__(self, application):
        controller = RequestExtensionController(application)
        wsgi.Resource.__init__(self, controller)

    def add_handler(self, handler):
        self.controller.add_handler(handler)


class ExtensionsResource(wsgi.Resource):

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
        try:
            # NOTE(dprince): the extensions alias is used as the 'id' for show
            ext = self.extension_manager.extensions[id]
        except KeyError:
            return faults.Fault(webob.exc.HTTPNotFound())

        return dict(extension=self._translate(ext))

    def delete(self, req, id):
        raise faults.Fault(webob.exc.HTTPNotFound())

    def create(self, req):
        raise faults.Fault(webob.exc.HTTPNotFound())


class ExtensionMiddleware(base_wsgi.Middleware):
    """Extensions middleware for WSGI."""
    @classmethod
    def factory(cls, global_config, **local_config):
        """Paste factory."""
        def _factory(app):
            return cls(app, **local_config)
        return _factory

    def _action_ext_resources(self, application, ext_mgr, mapper):
        """Return a dict of ActionExtensionResource-s by collection."""
        action_resources = {}
        for action in ext_mgr.get_actions():
            if not action.collection in action_resources.keys():
                resource = ActionExtensionResource(application)
                mapper.connect("/:(project_id)/%s/:(id)/action.:(format)" %
                                action.collection,
                                action='action',
                                controller=resource,
                                conditions=dict(method=['POST']))
                mapper.connect("/:(project_id)/%s/:(id)/action" %
                                action.collection,
                                action='action',
                                controller=resource,
                                conditions=dict(method=['POST']))
                action_resources[action.collection] = resource

        return action_resources

    def _request_ext_resources(self, application, ext_mgr, mapper):
        """Returns a dict of RequestExtensionResource-s by collection."""
        request_ext_resources = {}
        for req_ext in ext_mgr.get_request_extensions():
            if not req_ext.key in request_ext_resources.keys():
                resource = RequestExtensionResource(application)
                mapper.connect(req_ext.url_route + '.:(format)',
                                action='process',
                                controller=resource,
                                conditions=req_ext.conditions)

                mapper.connect(req_ext.url_route,
                                action='process',
                                controller=resource,
                                conditions=req_ext.conditions)
                request_ext_resources[req_ext.key] = resource

        return request_ext_resources

    def __init__(self, application, ext_mgr=None):

        if ext_mgr is None:
            ext_mgr = ExtensionManager(FLAGS.osapi_extensions_path)
        self.ext_mgr = ext_mgr

        mapper = nova.api.openstack.ProjectMapper()

        serializer = wsgi.ResponseSerializer(
            {'application/xml': ExtensionsXMLSerializer()})
        # extended resources
        for resource in ext_mgr.get_resources():
            LOG.debug(_('Extended resource: %s'),
                        resource.collection)
            if resource.serializer is None:
                resource.serializer = serializer

            kargs = dict(
                controller=wsgi.Resource(
                    resource.controller, resource.deserializer,
                    resource.serializer),
                collection=resource.collection_actions,
                member=resource.member_actions)

            if resource.parent:
                kargs['parent_resource'] = resource.parent

            mapper.resource(resource.collection, resource.collection, **kargs)

        # extended actions
        action_resources = self._action_ext_resources(application, ext_mgr,
                                                        mapper)
        for action in ext_mgr.get_actions():
            LOG.debug(_('Extended action: %s'), action.action_name)
            resource = action_resources[action.collection]
            resource.add_action(action.action_name, action.handler)

        # extended requests
        req_controllers = self._request_ext_resources(application, ext_mgr,
                                                      mapper)
        for request_ext in ext_mgr.get_request_extensions():
            LOG.debug(_('Extended request: %s'), request_ext.key)
            controller = req_controllers[request_ext.key]
            controller.add_handler(request_ext.handler)

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

        self.path = path
        self.extensions = {}
        self._load_all_extensions()

    def get_resources(self):
        """Returns a list of ResourceExtension objects."""
        resources = []
        resources.append(ResourceExtension('extensions',
                                            ExtensionsResource(self)))
        for alias, ext in self.extensions.iteritems():
            try:
                resources.extend(ext.get_resources())
            except AttributeError:
                # NOTE(dprince): Extension aren't required to have resource
                # extensions
                pass
        return resources

    def get_actions(self):
        """Returns a list of ActionExtension objects."""
        actions = []
        for alias, ext in self.extensions.iteritems():
            try:
                actions.extend(ext.get_actions())
            except AttributeError:
                # NOTE(dprince): Extension aren't required to have action
                # extensions
                pass
        return actions

    def get_request_extensions(self):
        """Returns a list of RequestExtension objects."""
        request_exts = []
        for alias, ext in self.extensions.iteritems():
            try:
                request_exts.extend(ext.get_request_extensions())
            except AttributeError:
                # NOTE(dprince): Extension aren't required to have request
                # extensions
                pass
        return request_exts

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
            return False
        return True

    def _load_all_extensions(self):
        """Load extensions from the configured path.

        Load extensions from the configured path. The extension name is
        constructed from the module_name. If your extension module was named
        widgets.py the extension class within that module should be
        'Widgets'.

        In addition, extensions are loaded from the 'contrib' directory.

        See nova/tests/api/openstack/extensions/foxinsocks.py for an example
        extension implementation.

        """
        if os.path.exists(self.path):
            self._load_all_extensions_from_path(self.path)

        contrib_path = os.path.join(os.path.dirname(__file__), "contrib")
        if os.path.exists(contrib_path):
            self._load_all_extensions_from_path(contrib_path)

    def _load_all_extensions_from_path(self, path):
        for f in os.listdir(path):
            LOG.audit(_('Loading extension file: %s'), f)
            mod_name, file_ext = os.path.splitext(os.path.split(f)[-1])
            ext_path = os.path.join(path, f)
            if file_ext.lower() == '.py' and not mod_name.startswith('_'):
                mod = imp.load_source(mod_name, ext_path)
                ext_name = mod_name[0].upper() + mod_name[1:]
                new_ext_class = getattr(mod, ext_name, None)
                if not new_ext_class:
                    LOG.warn(_('Did not find expected name '
                               '"%(ext_name)s" in %(file)s'),
                             {'ext_name': ext_name,
                              'file': ext_path})
                    continue
                new_ext = new_ext_class()
                self.add_extension(new_ext)

    def add_extension(self, ext):
        # Do nothing if the extension doesn't check out
        if not self._check_extension(ext):
            return

        alias = ext.get_alias()
        LOG.audit(_('Loaded extension: %s'), alias)

        if alias in self.extensions:
            raise exception.Error("Found duplicate extension: %s" % alias)
        self.extensions[alias] = ext


class RequestExtension(object):
    """Extend requests and responses of core nova OpenStack API resources.

    Provide a way to add data to responses and handle custom request data
    that is sent to core nova OpenStack API controllers.

    """
    def __init__(self, method, url_route, handler):
        self.url_route = url_route
        self.handler = handler
        self.conditions = dict(method=[method])
        self.key = "%s-%s" % (method, url_route)


class ActionExtension(object):
    """Add custom actions to core nova OpenStack API resources."""

    def __init__(self, collection, action_name, handler):
        self.collection = collection
        self.action_name = action_name
        self.handler = handler


class ResourceExtension(object):
    """Add top level resources to the OpenStack API in nova."""

    def __init__(self, collection, controller, parent=None,
                 collection_actions=None, member_actions=None,
                 deserializer=None, serializer=None):
        if not collection_actions:
            collection_actions = {}
        if not member_actions:
            member_actions = {}
        self.collection = collection
        self.controller = controller
        self.parent = parent
        self.collection_actions = collection_actions
        self.member_actions = member_actions
        self.deserializer = deserializer
        self.serializer = serializer


class ExtensionsXMLSerializer(wsgi.XMLDictSerializer):

    NSMAP = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}

    def show(self, ext_dict):
        ext = etree.Element('extension', nsmap=self.NSMAP)
        self._populate_ext(ext, ext_dict['extension'])
        return self._to_xml(ext)

    def index(self, exts_dict):
        exts = etree.Element('extensions', nsmap=self.NSMAP)
        for ext_dict in exts_dict['extensions']:
            ext = etree.SubElement(exts, 'extension')
            self._populate_ext(ext, ext_dict)
        return self._to_xml(exts)

    def _populate_ext(self, ext_elem, ext_dict):
        """Populate an extension xml element from a dict."""

        ext_elem.set('name', ext_dict['name'])
        ext_elem.set('namespace', ext_dict['namespace'])
        ext_elem.set('alias', ext_dict['alias'])
        ext_elem.set('updated', ext_dict['updated'])
        desc = etree.Element('description')
        desc.text = ext_dict['description']
        ext_elem.append(desc)
        for link in ext_dict.get('links', []):
            elem = etree.SubElement(ext_elem, '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
            elem.set('type', link['type'])
        return ext_elem

    def _to_xml(self, root):
        """Convert the xml object to an xml string."""

        return etree.tostring(root, encoding='UTF-8')
