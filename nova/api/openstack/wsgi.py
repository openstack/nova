
import json
import webob
from xml.dom import minidom

from nova import exception
from nova import log as logging
from nova import utils
from nova import wsgi


XMLNS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XMLNS_V11 = 'http://docs.openstack.org/compute/api/v1.1'

LOG = logging.getLogger('nova.api.openstack.wsgi')


class Request(webob.Request):
    """Add some Openstack API-specific logic to the base webob.Request."""

    def best_match_content_type(self):
        """Determine the requested response content-type.

        Based on the query extension then the Accept header.

        """
        supported = ('application/json', 'application/xml')

        parts = self.path.rsplit('.', 1)
        if len(parts) > 1:
            ctype = 'application/{0}'.format(parts[1])
            if ctype in supported:
                return ctype

        bm = self.accept.best_match(supported)

        # default to application/json if we don't find a preference
        return bm or 'application/json'

    def get_content_type(self):
        """Determine content type of the request body.

        Does not do any body introspection, only checks header

        """
        if not "Content-Type" in self.headers:
            raise exception.InvalidContentType(content_type=None)

        allowed_types = ("application/xml", "application/json")
        content_type = self.content_type

        if content_type not in allowed_types:
            raise exception.InvalidContentType(content_type=content_type)
        else:
            return content_type


class TextDeserializer(object):
    """Custom request body deserialization based on controller action name."""

    def deserialize(self, datastring, action='default'):
        """Find local deserialization method and parse request body."""
        action_method = getattr(self, action, self.default)
        return action_method(datastring)

    def default(self, datastring):
        """Default deserialization code should live here"""
        raise NotImplementedError()


class JSONDeserializer(TextDeserializer):

    def default(self, datastring):
        return utils.loads(datastring)


class XMLDeserializer(TextDeserializer):

    def __init__(self, metadata=None):
        """
        :param metadata: information needed to deserialize xml into
                         a dictionary.
        """
        super(XMLDeserializer, self).__init__()
        self.metadata = metadata or {}

    def default(self, datastring):
        plurals = set(self.metadata.get('plurals', {}))
        node = minidom.parseString(datastring).childNodes[0]
        return {node.nodeName: self._from_xml_node(node, plurals)}

    def _from_xml_node(self, node, listnames):
        """Convert a minidom node to a simple Python type.

        :param listnames: list of XML node names whose subnodes should
                          be considered list items.

        """
        if len(node.childNodes) == 1 and node.childNodes[0].nodeType == 3:
            return node.childNodes[0].nodeValue
        elif node.nodeName in listnames:
            return [self._from_xml_node(n, listnames) for n in node.childNodes]
        else:
            result = dict()
            for attr in node.attributes.keys():
                result[attr] = node.attributes[attr].nodeValue
            for child in node.childNodes:
                if child.nodeType != node.TEXT_NODE:
                    result[child.nodeName] = self._from_xml_node(child,
                                                                 listnames)
            return result


class RequestDeserializer(object):
    """Break up a Request object into more useful pieces."""

    def __init__(self, deserializers=None):
        """
        :param deserializers: dictionary of content-type-specific deserializers

        """
        self.deserializers = {
            'application/xml': XMLDeserializer(),
            'application/json': JSONDeserializer(),
        }

        self.deserializers.update(deserializers or {})

    def deserialize(self, request):
        """Extract necessary pieces of the request.

        :param request: Request object
        :returns tuple of expected controller action name, dictionary of
                 keyword arguments to pass to the controller, the expected
                 content type of the response

        """
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        if request.method.lower() in ('post', 'put'):
            if len(request.body) == 0:
                action_args['body'] = None
            else:
                content_type = request.get_content_type()
                deserializer = self.get_deserializer(content_type)

                try:
                    body = deserializer.deserialize(request.body, action)
                    action_args['body'] = body
                except exception.InvalidContentType:
                    action_args['body'] = None

        accept = self.get_expected_content_type(request)

        return (action, action_args, accept)

    def get_deserializer(self, content_type):
        try:
            return self.deserializers[content_type]
        except (KeyError, TypeError):
            raise exception.InvalidContentType(content_type=content_type)

    def get_expected_content_type(self, request):
        return request.best_match_content_type()

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        try:
            args = request_environment['wsgiorg.routing_args'][1].copy()
        except Exception:
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


class DictSerializer(object):
    """Custom response body serialization based on controller action name."""

    def serialize(self, data, action='default'):
        """Find local serialization method and encode response body."""
        action_method = getattr(self, action, self.default)
        return action_method(data)

    def default(self, data):
        """Default serialization code should live here"""
        raise NotImplementedError()


class JSONDictSerializer(DictSerializer):

    def default(self, data):
        return utils.dumps(data)


class XMLDictSerializer(DictSerializer):

    def __init__(self, metadata=None, xmlns=None):
        """
        :param metadata: information needed to deserialize xml into
                         a dictionary.
        :param xmlns: XML namespace to include with serialized xml
        """
        super(XMLDictSerializer, self).__init__()
        self.metadata = metadata or {}
        self.xmlns = xmlns

    def default(self, data):
        # We expect data to contain a single key which is the XML root.
        root_key = data.keys()[0]
        doc = minidom.Document()
        node = self._to_xml_node(doc, self.metadata, root_key, data[root_key])

        self._add_xmlns(node)

        return node.toprettyxml(indent='    ')

    def _add_xmlns(self, node):
        if self.xmlns is not None:
            node.setAttribute('xmlns', self.xmlns)

    def _to_xml_node(self, doc, metadata, nodename, data):
        """Recursive method to convert data members to XML nodes."""
        result = doc.createElement(nodename)

        # Set the xml namespace if one is specified
        # TODO(justinsb): We could also use prefixes on the keys
        xmlns = metadata.get('xmlns', None)
        if xmlns:
            result.setAttribute('xmlns', xmlns)

        #TODO(bcwaldon): accomplish this without a type-check
        if type(data) is list:
            collections = metadata.get('list_collections', {})
            if nodename in collections:
                metadata = collections[nodename]
                for item in data:
                    node = doc.createElement(metadata['item_name'])
                    node.setAttribute(metadata['item_key'], str(item))
                    result.appendChild(node)
                return result
            singular = metadata.get('plurals', {}).get(nodename, None)
            if singular is None:
                if nodename.endswith('s'):
                    singular = nodename[:-1]
                else:
                    singular = 'item'
            for item in data:
                node = self._to_xml_node(doc, metadata, singular, item)
                result.appendChild(node)
        #TODO(bcwaldon): accomplish this without a type-check
        elif type(data) is dict:
            collections = metadata.get('dict_collections', {})
            if nodename in collections:
                metadata = collections[nodename]
                for k, v in data.items():
                    node = doc.createElement(metadata['item_name'])
                    node.setAttribute(metadata['item_key'], str(k))
                    text = doc.createTextNode(str(v))
                    node.appendChild(text)
                    result.appendChild(node)
                return result
            attrs = metadata.get('attributes', {}).get(nodename, {})
            for k, v in data.items():
                if k in attrs:
                    result.setAttribute(k, str(v))
                else:
                    node = self._to_xml_node(doc, metadata, k, v)
                    result.appendChild(node)
        else:
            # Type is atom
            node = doc.createTextNode(str(data))
            result.appendChild(node)
        return result


class ResponseSerializer(object):
    """Encode the necessary pieces into a response object"""

    def __init__(self, serializers=None):
        """
        :param serializers: dictionary of content-type-specific serializers

        """
        self.serializers = {
            'application/xml': XMLDictSerializer(),
            'application/json': JSONDictSerializer(),
        }
        self.serializers.update(serializers or {})

    def serialize(self, response_data, content_type):
        """Serialize a dict into a string and wrap in a wsgi.Request object.

        :param response_data: dict produced by the Controller
        :param content_type: expected mimetype of serialized response body

        """
        response = webob.Response()
        response.headers['Content-Type'] = content_type

        serializer = self.get_serializer(content_type)
        response.body = serializer.serialize(response_data)

        return response

    def get_serializer(self, content_type):
        try:
            return self.serializers[content_type]
        except (KeyError, TypeError):
            raise exception.InvalidContentType(content_type=content_type)


class Resource(wsgi.Application):
    """WSGI app that handles (de)serialization and controller dispatch.

    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon its controller.  All
    controller action methods must accept a 'req' argument, which is the
    incoming wsgi.Request. If the operation is a PUT or POST, the controller
    method must also accept a 'body' argument (the deserialized request body).
    They may raise a webob.exc exception or return a dict, which will be
    serialized by requested content type.

    """
    def __init__(self, controller, serializers=None, deserializers=None):
        """
        :param controller: object that implement methods created by routes lib
        :param serializers: dict of content-type specific text serializers
        :param deserializers: dict of content-type specific text deserializers

        """
        self.controller = controller
        self.serializer = ResponseSerializer(serializers)
        self.deserializer = RequestDeserializer(deserializers)

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""

        LOG.debug("%(method)s %(url)s" % {"method": request.method,
                                          "url": request.url})

        try:
            action, action_args, accept = self.deserializer.deserialize(
                                                                      request)
        except exception.InvalidContentType:
            return webob.exc.HTTPBadRequest(_("Unsupported Content-Type"))

        action_result = self.dispatch(request, action, action_args)

        #TODO(bcwaldon): find a more elegant way to pass through non-dict types
        if type(action_result) is dict:
            response = self.serializer.serialize(action_result, accept)
        else:
            response = action_result

        try:
            msg_dict = dict(url=request.url, status=response.status_int)
            msg = _("%(url)s returned with HTTP %(status)d") % msg_dict
        except AttributeError:
            msg_dict = dict(url=request.url)
            msg = _("%(url)s returned a fault")

        LOG.debug(msg)

        return response

    def dispatch(self, request, action, action_args):
        """Find action-spefic method on controller and call it."""

        controller_method = getattr(self.controller, action)
        return controller_method(req=request, **action_args)
