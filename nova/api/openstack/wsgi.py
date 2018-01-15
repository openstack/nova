# Copyright 2013 IBM Corp.
# Copyright 2011 OpenStack Foundation
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

import functools

import microversion_parse
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import strutils
import six
import webob

from nova.api.openstack import api_version_request as api_version
from nova.api.openstack import versioned_method
from nova.api import wsgi
from nova import exception
from nova import i18n
from nova.i18n import _


LOG = logging.getLogger(__name__)

_SUPPORTED_CONTENT_TYPES = (
    'application/json',
    'application/vnd.openstack.compute+json',
)

# These are typically automatically created by routes as either defaults
# collection or member methods.
_ROUTES_METHODS = [
    'create',
    'delete',
    'show',
    'update',
]

_METHODS_WITH_BODY = [
    'POST',
    'PUT',
]

# The default api version request if none is requested in the headers
# Note(cyeoh): This only applies for the v2.1 API once microversions
# support is fully merged. It does not affect the V2 API.
DEFAULT_API_VERSION = "2.1"

# name of attribute to keep version method information
VER_METHOD_ATTR = 'versioned_methods'

# Names of headers used by clients to request a specific version
# of the REST API
API_VERSION_REQUEST_HEADER = 'OpenStack-API-Version'
LEGACY_API_VERSION_REQUEST_HEADER = 'X-OpenStack-Nova-API-Version'


ENV_LEGACY_V2 = 'openstack.legacy_v2'


def get_supported_content_types():
    return _SUPPORTED_CONTENT_TYPES


# NOTE(rlrossit): This function allows a get on both a dict-like and an
# object-like object. cache_db_items() is used on both versioned objects and
# dicts, so the function can't be totally changed over to [] syntax, nor
# can it be changed over to use getattr().
def item_get(item, item_key):
    if hasattr(item, '__getitem__'):
        return item[item_key]
    else:
        return getattr(item, item_key)


class Request(wsgi.Request):
    """Add some OpenStack API-specific logic to the base webob.Request."""

    def __init__(self, *args, **kwargs):
        super(Request, self).__init__(*args, **kwargs)
        self._extension_data = {'db_items': {}}
        if not hasattr(self, 'api_version_request'):
            self.api_version_request = api_version.APIVersionRequest()

    def cache_db_items(self, key, items, item_key='id'):
        """Allow API methods to store objects from a DB query to be
        used by API extensions within the same API request.

        An instance of this class only lives for the lifetime of a
        single API request, so there's no need to implement full
        cache management.
        """
        db_items = self._extension_data['db_items'].setdefault(key, {})
        for item in items:
            db_items[item_get(item, item_key)] = item

    def get_db_items(self, key):
        """Allow an API extension to get previously stored objects within
        the same API request.

        Note that the object data will be slightly stale.
        """
        return self._extension_data['db_items'][key]

    def get_db_item(self, key, item_key):
        """Allow an API extension to get a previously stored object
        within the same API request.

        Note that the object data will be slightly stale.
        """
        return self.get_db_items(key).get(item_key)

    def cache_db_instances(self, instances):
        self.cache_db_items('instances', instances, 'uuid')

    def cache_db_instance(self, instance):
        self.cache_db_items('instances', [instance], 'uuid')

    def get_db_instances(self):
        return self.get_db_items('instances')

    def get_db_instance(self, instance_uuid):
        return self.get_db_item('instances', instance_uuid)

    def cache_db_flavors(self, flavors):
        self.cache_db_items('flavors', flavors, 'flavorid')

    def cache_db_flavor(self, flavor):
        self.cache_db_items('flavors', [flavor], 'flavorid')

    def get_db_flavors(self):
        return self.get_db_items('flavors')

    def get_db_flavor(self, flavorid):
        return self.get_db_item('flavors', flavorid)

    def best_match_content_type(self):
        """Determine the requested response content-type."""
        if 'nova.best_content_type' not in self.environ:
            # Calculate the best MIME type
            content_type = None

            # Check URL path suffix
            parts = self.path.rsplit('.', 1)
            if len(parts) > 1:
                possible_type = 'application/' + parts[1]
                if possible_type in get_supported_content_types():
                    content_type = possible_type

            if not content_type:
                content_type = self.accept.best_match(
                    get_supported_content_types())

            self.environ['nova.best_content_type'] = (content_type or
                                                      'application/json')

        return self.environ['nova.best_content_type']

    def get_content_type(self):
        """Determine content type of the request body.

        Does not do any body introspection, only checks header

        """
        if "Content-Type" not in self.headers:
            return None

        content_type = self.content_type

        # NOTE(markmc): text/plain is the default for eventlet and
        # other webservers which use mimetools.Message.gettype()
        # whereas twisted defaults to ''.
        if not content_type or content_type == 'text/plain':
            return None

        if content_type not in get_supported_content_types():
            raise exception.InvalidContentType(content_type=content_type)

        return content_type

    def best_match_language(self):
        """Determine the best available language for the request.

        :returns: the best language match or None if the 'Accept-Language'
                  header was not available in the request.
        """
        if not self.accept_language:
            return None
        return self.accept_language.best_match(
                i18n.get_available_languages())

    def set_api_version_request(self):
        """Set API version request based on the request header information."""
        hdr_string = microversion_parse.get_version(
            self.headers, service_type='compute',
            legacy_headers=[LEGACY_API_VERSION_REQUEST_HEADER])

        if hdr_string is None:
            self.api_version_request = api_version.APIVersionRequest(
                api_version.DEFAULT_API_VERSION)
        elif hdr_string == 'latest':
            # 'latest' is a special keyword which is equivalent to
            # requesting the maximum version of the API supported
            self.api_version_request = api_version.max_api_version()
        else:
            self.api_version_request = api_version.APIVersionRequest(
                hdr_string)

            # Check that the version requested is within the global
            # minimum/maximum of supported API versions
            if not self.api_version_request.matches(
                    api_version.min_api_version(),
                    api_version.max_api_version()):
                raise exception.InvalidGlobalAPIVersion(
                    req_ver=self.api_version_request.get_string(),
                    min_ver=api_version.min_api_version().get_string(),
                    max_ver=api_version.max_api_version().get_string())

    def set_legacy_v2(self):
        self.environ[ENV_LEGACY_V2] = True

    def is_legacy_v2(self):
        return self.environ.get(ENV_LEGACY_V2, False)


class ActionDispatcher(object):
    """Maps method name to local methods through action name."""

    def dispatch(self, *args, **kwargs):
        """Find and call local method."""
        action = kwargs.pop('action', 'default')
        action_method = getattr(self, str(action), self.default)
        return action_method(*args, **kwargs)

    def default(self, data):
        raise NotImplementedError()


class JSONDeserializer(ActionDispatcher):

    def _from_json(self, datastring):
        try:
            return jsonutils.loads(datastring)
        except ValueError:
            msg = _("cannot understand JSON")
            raise exception.MalformedRequestBody(reason=msg)

    def deserialize(self, datastring, action='default'):
        return self.dispatch(datastring, action=action)

    def default(self, datastring):
        return {'body': self._from_json(datastring)}


class JSONDictSerializer(ActionDispatcher):
    """Default JSON request body serialization."""

    def serialize(self, data, action='default'):
        return self.dispatch(data, action=action)

    def default(self, data):
        return six.text_type(jsonutils.dumps(data))


def response(code):
    """Attaches response code to a method.

    This decorator associates a response code with a method.  Note
    that the function attributes are directly manipulated; the method
    is not wrapped.
    """

    def decorator(func):
        func.wsgi_code = code
        return func
    return decorator


class ResponseObject(object):
    """Bundles a response object

    Object that app methods may return in order to allow its response
    to be modified by extensions in the code. Its use is optional (and
    should only be used if you really know what you are doing).
    """

    def __init__(self, obj, code=None, headers=None):
        """Builds a response object."""

        self.obj = obj
        self._default_code = 200
        self._code = code
        self._headers = headers or {}
        self.serializer = JSONDictSerializer()

    def __getitem__(self, key):
        """Retrieves a header with the given name."""

        return self._headers[key.lower()]

    def __setitem__(self, key, value):
        """Sets a header with the given name to the given value."""

        self._headers[key.lower()] = value

    def __delitem__(self, key):
        """Deletes the header with the given name."""

        del self._headers[key.lower()]

    def serialize(self, request, content_type):
        """Serializes the wrapped object.

        Utility method for serializing the wrapped object.  Returns a
        webob.Response object.
        """

        serializer = self.serializer

        body = None
        if self.obj is not None:
            body = serializer.serialize(self.obj)
        response = webob.Response(body=body)
        response.status_int = self.code
        for hdr, val in self._headers.items():
            if not isinstance(val, six.text_type):
                val = six.text_type(val)
            if six.PY2:
                # In Py2.X Headers must be byte strings
                response.headers[hdr] = encodeutils.safe_encode(val)
            else:
                # In Py3.X Headers must be utf-8 strings
                response.headers[hdr] = encodeutils.safe_decode(
                        encodeutils.safe_encode(val))
        # Deal with content_type
        if not isinstance(content_type, six.text_type):
            content_type = six.text_type(content_type)
        if six.PY2:
            # In Py2.X Headers must be byte strings
            response.headers['Content-Type'] = encodeutils.safe_encode(
                content_type)
        else:
            # In Py3.X Headers must be utf-8 strings
            response.headers['Content-Type'] = encodeutils.safe_decode(
                    encodeutils.safe_encode(content_type))
        return response

    @property
    def code(self):
        """Retrieve the response status."""

        return self._code or self._default_code

    @property
    def headers(self):
        """Retrieve the headers."""

        return self._headers.copy()


def action_peek(body):
    """Determine action to invoke.

    This looks inside the json body and fetches out the action method
    name.
    """

    try:
        decoded = jsonutils.loads(body)
    except ValueError:
        msg = _("cannot understand JSON")
        raise exception.MalformedRequestBody(reason=msg)

    # Make sure there's exactly one key...
    if len(decoded) != 1:
        msg = _("too many body keys")
        raise exception.MalformedRequestBody(reason=msg)

    # Return the action name
    return list(decoded.keys())[0]


class ResourceExceptionHandler(object):
    """Context manager to handle Resource exceptions.

    Used when processing exceptions generated by API implementation
    methods (or their extensions).  Converts most exceptions to Fault
    exceptions, with the appropriate logging.
    """

    def __enter__(self):
        return None

    def __exit__(self, ex_type, ex_value, ex_traceback):
        if not ex_value:
            return True

        if isinstance(ex_value, exception.Forbidden):
            raise Fault(webob.exc.HTTPForbidden(
                    explanation=ex_value.format_message()))
        elif isinstance(ex_value, exception.VersionNotFoundForAPIMethod):
            raise
        elif isinstance(ex_value, exception.Invalid):
            raise Fault(exception.ConvertedException(
                    code=ex_value.code,
                    explanation=ex_value.format_message()))
        elif isinstance(ex_value, TypeError):
            exc_info = (ex_type, ex_value, ex_traceback)
            LOG.error('Exception handling resource: %s', ex_value,
                      exc_info=exc_info)
            raise Fault(webob.exc.HTTPBadRequest())
        elif isinstance(ex_value, Fault):
            LOG.info("Fault thrown: %s", ex_value)
            raise ex_value
        elif isinstance(ex_value, webob.exc.HTTPException):
            LOG.info("HTTP exception thrown: %s", ex_value)
            raise Fault(ex_value)

        # We didn't handle the exception
        return False


class Resource(wsgi.Application):
    """WSGI app that handles (de)serialization and controller dispatch.

    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon its controller.  All
    controller action methods must accept a 'req' argument, which is the
    incoming wsgi.Request. If the operation is a PUT or POST, the controller
    method must also accept a 'body' argument (the deserialized request body).
    They may raise a webob.exc exception or return a dict, which will be
    serialized by requested content type.

    Exceptions derived from webob.exc.HTTPException will be automatically
    wrapped in Fault() to provide API friendly error responses.

    """
    support_api_request_version = True

    def __init__(self, controller):
        """:param controller: object that implement methods created by routes
                              lib
        """

        self.controller = controller

        self.default_serializers = dict(json=JSONDictSerializer)

        # Copy over the actions dictionary
        self.wsgi_actions = {}
        if controller:
            self.register_actions(controller)

        # Save a mapping of extensions
        self.wsgi_extensions = {}
        self.wsgi_action_extensions = {}

    def register_actions(self, controller):
        """Registers controller actions with this resource."""

        actions = getattr(controller, 'wsgi_actions', {})
        for key, method_name in actions.items():
            self.wsgi_actions[key] = getattr(controller, method_name)

    def register_extensions(self, controller):
        """Registers controller extensions with this resource."""

        extensions = getattr(controller, 'wsgi_extensions', [])
        for method_name, action_name in extensions:
            # Look up the extending method
            extension = getattr(controller, method_name)

            if action_name:
                # Extending an action...
                if action_name not in self.wsgi_action_extensions:
                    self.wsgi_action_extensions[action_name] = []
                self.wsgi_action_extensions[action_name].append(extension)
            else:
                # Extending a regular method
                if method_name not in self.wsgi_extensions:
                    self.wsgi_extensions[method_name] = []
                self.wsgi_extensions[method_name].append(extension)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""

        # NOTE(Vek): Check for get_action_args() override in the
        # controller
        if hasattr(self.controller, 'get_action_args'):
            return self.controller.get_action_args(request_environment)

        try:
            args = request_environment['wsgiorg.routing_args'][1].copy()
        except (KeyError, IndexError, AttributeError):
            return {}

        try:
            del args['controller']
        except KeyError:
            pass

        try:
            del args['format']
        except KeyError:
            pass

        return args

    def get_body(self, request):
        content_type = request.get_content_type()

        return content_type, request.body

    def deserialize(self, body):
        return JSONDeserializer().deserialize(body)

    def process_extensions(self, extensions, resp_obj, request,
                           action_args):
        for ext in extensions:
            response = None
            # Regular functions get post-processing...
            try:
                with ResourceExceptionHandler():
                    response = ext(req=request, resp_obj=resp_obj,
                                   **action_args)
            except exception.VersionNotFoundForAPIMethod:
                # If an attached extension (@wsgi.extends) for the
                # method has no version match its not an error. We
                # just don't run the extends code
                continue
            except Fault as ex:
                response = ex

            # We had a response return it, to exit early. This is
            # actually a failure mode. None is success.
            if response:
                return response

        return None

    def _should_have_body(self, request):
        return request.method in _METHODS_WITH_BODY

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""

        if self.support_api_request_version:
            # Set the version of the API requested based on the header
            try:
                request.set_api_version_request()
            except exception.InvalidAPIVersionString as e:
                return Fault(webob.exc.HTTPBadRequest(
                    explanation=e.format_message()))
            except exception.InvalidGlobalAPIVersion as e:
                return Fault(webob.exc.HTTPNotAcceptable(
                    explanation=e.format_message()))

        # Identify the action, its arguments, and the requested
        # content type
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        # NOTE(sdague): we filter out InvalidContentTypes early so we
        # know everything is good from here on out.
        try:
            content_type, body = self.get_body(request)
            accept = request.best_match_content_type()
        except exception.InvalidContentType:
            msg = _("Unsupported Content-Type")
            return Fault(webob.exc.HTTPUnsupportedMediaType(explanation=msg))

        # NOTE(Vek): Splitting the function up this way allows for
        #            auditing by external tools that wrap the existing
        #            function.  If we try to audit __call__(), we can
        #            run into troubles due to the @webob.dec.wsgify()
        #            decorator.
        return self._process_stack(request, action, action_args,
                               content_type, body, accept)

    def _process_stack(self, request, action, action_args,
                       content_type, body, accept):
        """Implement the processing stack."""

        # Get the implementing method
        try:
            meth, extensions = self.get_method(request, action,
                                               content_type, body)
        except (AttributeError, TypeError):
            return Fault(webob.exc.HTTPNotFound())
        except KeyError as ex:
            msg = _("There is no such action: %s") % ex.args[0]
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))
        except exception.MalformedRequestBody:
            msg = _("Malformed request body")
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        if body:
            msg = _("Action: '%(action)s', calling method: %(meth)s, body: "
                    "%(body)s") % {'action': action,
                                   'body': six.text_type(body, 'utf-8'),
                                   'meth': str(meth)}
            LOG.debug(strutils.mask_password(msg))
        else:
            LOG.debug("Calling method '%(meth)s'",
                      {'meth': str(meth)})

        # Now, deserialize the request body...
        try:
            contents = self._get_request_content(body, request)
        except exception.MalformedRequestBody:
            msg = _("Malformed request body")
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        # Update the action args
        action_args.update(contents)

        project_id = action_args.pop("project_id", None)
        context = request.environ.get('nova.context')
        if (context and project_id and (project_id != context.project_id)):
            msg = _("Malformed request URL: URL's project_id '%(project_id)s'"
                    " doesn't match Context's project_id"
                    " '%(context_project_id)s'") % \
                    {'project_id': project_id,
                     'context_project_id': context.project_id}
            return Fault(webob.exc.HTTPBadRequest(explanation=msg))

        response = None
        try:
            with ResourceExceptionHandler():
                action_result = self.dispatch(meth, request, action_args)
        except Fault as ex:
            response = ex

        if not response:
            # No exceptions; convert action_result into a
            # ResponseObject
            resp_obj = None
            if type(action_result) is dict or action_result is None:
                resp_obj = ResponseObject(action_result)
            elif isinstance(action_result, ResponseObject):
                resp_obj = action_result
            else:
                response = action_result

            # Run post-processing extensions
            if resp_obj:
                # Do a preserialize to set up the response object
                if hasattr(meth, 'wsgi_code'):
                    resp_obj._default_code = meth.wsgi_code
                # Process extensions
                response = self.process_extensions(extensions, resp_obj,
                                                        request, action_args)

            if resp_obj and not response:
                response = resp_obj.serialize(request, accept)

        if hasattr(response, 'headers'):
            for hdr, val in list(response.headers.items()):
                if not isinstance(val, six.text_type):
                    val = six.text_type(val)
                if six.PY2:
                    # In Py2.X Headers must be byte strings
                    response.headers[hdr] = encodeutils.safe_encode(val)
                else:
                    # In Py3.X Headers must be utf-8 strings
                    response.headers[hdr] = encodeutils.safe_decode(
                            encodeutils.safe_encode(val))

            if not request.api_version_request.is_null():
                response.headers[API_VERSION_REQUEST_HEADER] = \
                    'compute ' + request.api_version_request.get_string()
                response.headers[LEGACY_API_VERSION_REQUEST_HEADER] = \
                    request.api_version_request.get_string()
                response.headers.add('Vary', API_VERSION_REQUEST_HEADER)
                response.headers.add('Vary', LEGACY_API_VERSION_REQUEST_HEADER)

        return response

    def _get_request_content(self, body, request):
        contents = {}
        if self._should_have_body(request):
            # allow empty body with PUT and POST
            if request.content_length == 0 or request.content_length is None:
                contents = {'body': None}
            else:
                contents = self.deserialize(body)
        return contents

    def get_method(self, request, action, content_type, body):
        meth, extensions = self._get_method(request,
                                            action,
                                            content_type,
                                            body)
        return meth, extensions

    def _get_method(self, request, action, content_type, body):
        """Look up the action-specific method and its extensions."""
        # Look up the method
        try:
            if not self.controller:
                meth = getattr(self, action)
            else:
                meth = getattr(self.controller, action)
        except AttributeError:
            if (not self.wsgi_actions or
                    action not in _ROUTES_METHODS + ['action']):
                # Propagate the error
                raise
        else:
            return meth, self.wsgi_extensions.get(action, [])

        if action == 'action':
            action_name = action_peek(body)
        else:
            action_name = action

        # Look up the action method
        return (self.wsgi_actions[action_name],
                self.wsgi_action_extensions.get(action_name, []))

    def dispatch(self, method, request, action_args):
        """Dispatch a call to the action-specific method."""

        try:
            return method(req=request, **action_args)
        except exception.VersionNotFoundForAPIMethod:
            # We deliberately don't return any message information
            # about the exception to the user so it looks as if
            # the method is simply not implemented.
            return Fault(webob.exc.HTTPNotFound())


def action(name):
    """Mark a function as an action.

    The given name will be taken as the action key in the body.

    This is also overloaded to allow extensions to provide
    non-extending definitions of create and delete operations.
    """

    def decorator(func):
        func.wsgi_action = name
        return func
    return decorator


def extends(*args, **kwargs):
    """Indicate a function extends an operation.

    Can be used as either::

        @extends
        def index(...):
            pass

    or as::

        @extends(action='resize')
        def _action_resize(...):
            pass
    """

    def decorator(func):
        # Store enough information to find what we're extending
        func.wsgi_extends = (func.__name__, kwargs.get('action'))
        return func

    # If we have positional arguments, call the decorator
    if args:
        return decorator(*args)

    # OK, return the decorator instead
    return decorator


def expected_errors(errors):
    """Decorator for v2.1 API methods which specifies expected exceptions.

    Specify which exceptions may occur when an API method is called. If an
    unexpected exception occurs then return a 500 instead and ask the user
    of the API to file a bug report.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as exc:
                if isinstance(exc, webob.exc.WSGIHTTPException):
                    if isinstance(errors, int):
                        t_errors = (errors,)
                    else:
                        t_errors = errors
                    if exc.code in t_errors:
                        raise
                elif isinstance(exc, exception.Forbidden):
                    # Note(cyeoh): Special case to handle
                    # Forbidden exceptions so every
                    # extension method does not need to wrap authorize
                    # calls. ResourceExceptionHandler silently
                    # converts NotAuthorized to HTTPForbidden
                    raise
                elif isinstance(exc, exception.ValidationError):
                    # Note(oomichi): Handle a validation error, which
                    # happens due to invalid API parameters, as an
                    # expected error.
                    raise
                elif isinstance(exc, exception.Unauthorized):
                    # Handle an authorized exception, will be
                    # automatically converted to a HTTP 401, clients
                    # like python-novaclient handle this error to
                    # generate new token and do another attempt.
                    raise

                LOG.exception("Unexpected exception in API method")
                msg = _('Unexpected API Error. Please report this at '
                    'http://bugs.launchpad.net/nova/ and attach the Nova '
                    'API log if possible.\n%s') % type(exc)
                raise webob.exc.HTTPInternalServerError(explanation=msg)

        return wrapped

    return decorator


class ControllerMetaclass(type):
    """Controller metaclass.

    This metaclass automates the task of assembling a dictionary
    mapping action keys to method names.
    """

    def __new__(mcs, name, bases, cls_dict):
        """Adds the wsgi_actions dictionary to the class."""

        # Find all actions
        actions = {}
        extensions = []
        versioned_methods = None
        # start with wsgi actions from base classes
        for base in bases:
            actions.update(getattr(base, 'wsgi_actions', {}))

            if base.__name__ == "Controller":
                # NOTE(cyeoh): This resets the VER_METHOD_ATTR attribute
                # between API controller class creations. This allows us
                # to use a class decorator on the API methods that doesn't
                # require naming explicitly what method is being versioned as
                # it can be implicit based on the method decorated. It is a bit
                # ugly.
                if VER_METHOD_ATTR in base.__dict__:
                    versioned_methods = getattr(base, VER_METHOD_ATTR)
                    delattr(base, VER_METHOD_ATTR)

        for key, value in cls_dict.items():
            if not callable(value):
                continue
            if getattr(value, 'wsgi_action', None):
                actions[value.wsgi_action] = key
            elif getattr(value, 'wsgi_extends', None):
                extensions.append(value.wsgi_extends)

        # Add the actions and extensions to the class dict
        cls_dict['wsgi_actions'] = actions
        cls_dict['wsgi_extensions'] = extensions
        if versioned_methods:
            cls_dict[VER_METHOD_ATTR] = versioned_methods

        return super(ControllerMetaclass, mcs).__new__(mcs, name, bases,
                                                       cls_dict)


@six.add_metaclass(ControllerMetaclass)
class Controller(object):
    """Default controller."""

    _view_builder_class = None

    def __init__(self, view_builder=None):
        """Initialize controller with a view builder instance."""
        if view_builder:
            self._view_builder = view_builder
        elif self._view_builder_class:
            self._view_builder = self._view_builder_class()
        else:
            self._view_builder = None

    def __getattribute__(self, key):

        def version_select(*args, **kwargs):
            """Look for the method which matches the name supplied and version
            constraints and calls it with the supplied arguments.

            @return: Returns the result of the method called
            @raises: VersionNotFoundForAPIMethod if there is no method which
                 matches the name and version constraints
            """

            # The first arg to all versioned methods is always the request
            # object. The version for the request is attached to the
            # request object
            if len(args) == 0:
                ver = kwargs['req'].api_version_request
            else:
                ver = args[0].api_version_request

            func_list = self.versioned_methods[key]
            for func in func_list:
                if ver.matches(func.start_version, func.end_version):
                    # Update the version_select wrapper function so
                    # other decorator attributes like wsgi.response
                    # are still respected.
                    functools.update_wrapper(version_select, func.func)
                    return func.func(self, *args, **kwargs)

            # No version match
            raise exception.VersionNotFoundForAPIMethod(version=ver)

        try:
            version_meth_dict = object.__getattribute__(self, VER_METHOD_ATTR)
        except AttributeError:
            # No versioning on this class
            return object.__getattribute__(self, key)

        if version_meth_dict and \
          key in object.__getattribute__(self, VER_METHOD_ATTR):
            return version_select

        return object.__getattribute__(self, key)

    # NOTE(cyeoh): This decorator MUST appear first (the outermost
    # decorator) on an API method for it to work correctly
    @classmethod
    def api_version(cls, min_ver, max_ver=None):
        """Decorator for versioning api methods.

        Add the decorator to any method which takes a request object
        as the first parameter and belongs to a class which inherits from
        wsgi.Controller.

        @min_ver: string representing minimum version
        @max_ver: optional string representing maximum version
        """

        def decorator(f):
            obj_min_ver = api_version.APIVersionRequest(min_ver)
            if max_ver:
                obj_max_ver = api_version.APIVersionRequest(max_ver)
            else:
                obj_max_ver = api_version.APIVersionRequest()

            # Add to list of versioned methods registered
            func_name = f.__name__
            new_func = versioned_method.VersionedMethod(
                func_name, obj_min_ver, obj_max_ver, f)

            func_dict = getattr(cls, VER_METHOD_ATTR, {})
            if not func_dict:
                setattr(cls, VER_METHOD_ATTR, func_dict)

            func_list = func_dict.get(func_name, [])
            if not func_list:
                func_dict[func_name] = func_list
            func_list.append(new_func)
            # Ensure the list is sorted by minimum version (reversed)
            # so later when we work through the list in order we find
            # the method which has the latest version which supports
            # the version requested.
            is_intersect = Controller.check_for_versions_intersection(
                func_list)

            if is_intersect:
                raise exception.ApiVersionsIntersect(
                    name=new_func.name,
                    min_ver=new_func.start_version,
                    max_ver=new_func.end_version,
                )

            func_list.sort(key=lambda f: f.start_version, reverse=True)

            return f

        return decorator

    @staticmethod
    def is_valid_body(body, entity_name):
        if not (body and entity_name in body):
            return False

        def is_dict(d):
            try:
                d.get(None)
                return True
            except AttributeError:
                return False

        return is_dict(body[entity_name])

    @staticmethod
    def check_for_versions_intersection(func_list):
        """Determines whether function list contains version intervals
        intersections or not. General algorithm:

        https://en.wikipedia.org/wiki/Intersection_algorithm

        :param func_list: list of VersionedMethod objects
        :return: boolean
        """
        pairs = []
        counter = 0

        for f in func_list:
            pairs.append((f.start_version, 1, f))
            pairs.append((f.end_version, -1, f))

        def compare(x):
            return x[0]

        pairs.sort(key=compare)

        for p in pairs:
            counter += p[1]

            if counter > 1:
                return True

        return False


class Fault(webob.exc.HTTPException):
    """Wrap webob.exc.HTTPException to provide API friendly response."""

    _fault_names = {
            400: "badRequest",
            401: "unauthorized",
            403: "forbidden",
            404: "itemNotFound",
            405: "badMethod",
            409: "conflictingRequest",
            413: "overLimit",
            415: "badMediaType",
            429: "overLimit",
            501: "notImplemented",
            503: "serviceUnavailable"}

    def __init__(self, exception):
        """Create a Fault for the given webob.exc.exception."""
        self.wrapped_exc = exception
        for key, value in list(self.wrapped_exc.headers.items()):
            self.wrapped_exc.headers[key] = str(value)
        self.status_int = exception.status_int

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, req):
        """Generate a WSGI response based on the exception passed to ctor."""

        user_locale = req.best_match_language()
        # Replace the body with fault details.
        code = self.wrapped_exc.status_int
        fault_name = self._fault_names.get(code, "computeFault")
        explanation = self.wrapped_exc.explanation
        LOG.debug("Returning %(code)s to user: %(explanation)s",
                  {'code': code, 'explanation': explanation})

        explanation = i18n.translate(explanation, user_locale)
        fault_data = {
            fault_name: {
                'code': code,
                'message': explanation}}
        if code == 413 or code == 429:
            retry = self.wrapped_exc.headers.get('Retry-After', None)
            if retry:
                fault_data[fault_name]['retryAfter'] = retry

        if not req.api_version_request.is_null():
            self.wrapped_exc.headers[API_VERSION_REQUEST_HEADER] = \
                'compute ' + req.api_version_request.get_string()
            self.wrapped_exc.headers[LEGACY_API_VERSION_REQUEST_HEADER] = \
                req.api_version_request.get_string()
            self.wrapped_exc.headers.add('Vary', API_VERSION_REQUEST_HEADER)
            self.wrapped_exc.headers.add('Vary',
                                         LEGACY_API_VERSION_REQUEST_HEADER)

        self.wrapped_exc.content_type = 'application/json'
        self.wrapped_exc.charset = 'UTF-8'
        self.wrapped_exc.text = JSONDictSerializer().serialize(fault_data)

        return self.wrapped_exc

    def __str__(self):
        return self.wrapped_exc.__str__()
