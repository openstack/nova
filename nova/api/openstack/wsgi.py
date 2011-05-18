
import json
import webob
from xml.dom import minidom

from nova import exception
from nova import log as logging
from nova import utils


XMLNS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XMLNS_V11 = 'http://docs.openstack.org/compute/api/v1.1'

LOG = logging.getLogger('nova.api.openstack.wsgi')


class Request(webob.Request):
    def best_match_content_type(self, supported=None):
        """Determine the requested content-type.

        Based on the query extension then the Accept header.

        :param supported: list of content-types to override defaults

        """
        supported = supported or ['application/json', 'application/xml']
        parts = self.path.rsplit('.', 1)

        if len(parts) > 1:
            ctype = 'application/{0}'.format(parts[1])
            if ctype in supported:
                return ctype

        bm = self.accept.best_match(supported)

        return bm or 'application/json'

    def get_content_type(self):
        if not "Content-Type" in self.headers:
            raise exception.InvalidContentType(content_type=None)

        allowed_types = ("application/xml", "application/json")
        type = self.content_type

        if type not in allowed_types:
            raise exception.InvalidContentType(content_type=type)
        else:
            return type


class JSONDeserializer(object):
    def deserialize(self, datastring):
        return utils.loads(datastring)


class JSONSerializer(object):
    def serialize(self, data):
        return utils.dumps(data)


class XMLDeserializer(object):
    def __init__(self, metadata=None):
        """
        :param metadata: information needed to deserialize xml into
                         a dictionary.
        """
        super(XMLDeserializer, self).__init__()
        self.metadata = metadata or {}

    def deserialize(self, datastring):
        """XML deserialization entry point."""
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


class XMLSerializer(object):
    def __init__(self, metadata=None, xmlns=None):
        """
        :param metadata: information needed to deserialize xml into
                         a dictionary.
        :param xmlns: XML namespace to include with serialized xml
        """
        super(XMLSerializer, self).__init__()
        self.metadata = metadata or {}
        self.xmlns = xmlns

    def serialize(self, data):
        # We expect data to contain a single key which is the XML root.
        root_key = data.keys()[0]
        doc = minidom.Document()
        node = self._to_xml_node(doc, self.metadata, root_key, data[root_key])

        xmlns = node.getAttribute('xmlns')
        if not xmlns and self.xmlns:
            node.setAttribute('xmlns', self.xmlns)

        return node.toprettyxml(indent='    ')

    def _to_xml_node(self, doc, metadata, nodename, data):
        """Recursive method to convert data members to XML nodes."""
        result = doc.createElement(nodename)

        # Set the xml namespace if one is specified
        # TODO(justinsb): We could also use prefixes on the keys
        xmlns = metadata.get('xmlns', None)
        if xmlns:
            result.setAttribute('xmlns', xmlns)

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


class Resource(object):
    """WSGI app that dispatched to methods.

    WSGI app that reads routing information supplied by RoutesMiddleware
    and calls the requested action method upon itself.  All action methods
    must, in addition to their normal parameters, accept a 'req' argument
    which is the incoming wsgi.Request.  They raise a webob.exc exception,
    or return a dict which will be serialized by requested content type.

    """
    def __init__(self, controller, serializers=None, deserializers=None):
        self.serializers = {
            'application/xml': XMLSerializer(),
            'application/json': JSONSerializer(),
        }
        self.serializers.update(serializers or {})

        self.deserializers = {
            'application/xml': XMLDeserializer(),
            'application/json': JSONDeserializer(),
        }
        self.deserializers.update(deserializers or {})

        self.controller = controller

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """Call the method specified in req.environ by RoutesMiddleware."""
        LOG.debug("%s %s" % (request.method, request.url))

        try:
            action, action_args, accept = self.deserialize_request(request)
        except exception.InvalidContentType:
            return webob.exc.HTTPBadRequest(_("Unsupported Content-Type"))

        controller_method = getattr(self.controller, action)
        result = controller_method(req=request, **action_args)

        response = self.serialize_response(accept, result)

        try:
            msg_dict = dict(url=request.url, status=response.status_int)
            msg = _("%(url)s returned with HTTP %(status)d") % msg_dict
        except AttributeError:
            msg_dict = dict(url=request.url)
            msg = _("%(url)s returned a fault")

        LOG.debug(msg)

        return response

    def serialize_response(self, content_type, response_body):
        """Serialize a dict into a string and wrap in a wsgi.Request object.

        :param content_type: expected mimetype of serialized response body
        :param response_body: dict produced by the Controller

        """
        if not type(response_body) is dict:
            return response_body

        response = webob.Response()
        response.headers['Content-Type'] = content_type

        serializer = self.get_serializer(content_type)
        response.body = serializer.serialize(response_body)

        return response

    def get_serializer(self, content_type):
        try:
            return self.serializers[content_type]
        except Exception:
            raise exception.InvalidContentType(content_type=content_type)

    def deserialize_request(self, request):
        """Parse a wsgi request into a set of params we care about.

        :param request: wsgi.Request object

        """
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action')

        if request.method.lower() in ('post', 'put'):
            if len(request.body) == 0:
                action_args['body'] = None
            else:
                content_type = request.get_content_type()
                deserializer = self.get_deserializer(content_type)

                try:
                    action_args['body'] = deserializer.deserialize(request.body)
                except exception.InvalidContentType:
                    action_args['body'] = None

        accept = self.get_expected_content_type(request)

        return (action, action_args, accept)

    def get_expected_content_type(self, request):
        return request.best_match_content_type()

    def get_action_args(self, request_environment):
        args = request_environment['wsgiorg.routing_args'][1].copy()

        del args['controller']

        if 'format' in args:
            del args['format']

        return args

    def get_deserializer(self, content_type):
        try:
            return self.deserializers[content_type]
        except Exception:
            raise exception.InvalidContentType(content_type=content_type)
