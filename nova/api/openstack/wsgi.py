
import json
import webob
from xml.dom import minidom
from xml.parsers import expat

import faults
from nova import exception
from nova import log as logging
from nova import utils
from nova import wsgi


XMLNS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XMLNS_V11 = 'http://docs.openstack.org/compute/api/v1.1'

XMLNS_ATOM = 'http://www.w3.org/2005/Atom'

LOG = logging.getLogger('nova.api.openstack.wsgi')


class Request(webob.Request):
    """Add some Openstack API-specific logic to the base webob.Request."""

    def best_match_content_type(self, supported_content_types=None):
        """Determine the requested response content-type.

        Based on the query extension then the Accept header.

        """
        supported_content_types = supported_content_types or \
            ('application/json', 'application/xml')

        parts = self.path.rsplit('.', 1)
        if len(parts) > 1:
            ctype = 'application/{0}'.format(parts[1])
            if ctype in supported_content_types:
                return ctype

        bm = self.accept.best_match(supported_content_types)

        # default to application/json if we don't find a preference
        return bm or 'application/json'

    def get_content_type(self):
        """Determine content type of the request body.

        Does not do any body introspection, only checks header

        """
        if not "Content-Type" in self.headers:
            return None

        allowed_types = ("application/xml", "application/json")
        content_type = self.content_type

        if content_type not in allowed_types:
            raise exception.InvalidContentType(content_type=content_type)

        return content_type


class ActionDispatcher(object):
    """Maps method name to local methods through action name."""

    def dispatch(self, *args, **kwargs):
        """Find and call local method."""
        action = kwargs.pop('action', 'default')
        action_method = getattr(self, str(action), self.default)
        return action_method(*args, **kwargs)

    def default(self, data):
        raise NotImplementedError()


class TextDeserializer(ActionDispatcher):
    """Default request body deserialization"""

    def deserialize(self, datastring, action='default'):
        return self.dispatch(datastring, action=action)

    def default(self, datastring):
        return {}


class JSONDeserializer(TextDeserializer):

    def _from_json(self, datastring):
        try:
            return utils.loads(datastring)
        except ValueError:
            msg = _("cannot understand JSON")
            raise exception.MalformedRequestBody(reason=msg)

    def default(self, datastring):
        return {'body': self._from_json(datastring)}


class XMLDeserializer(TextDeserializer):

    def __init__(self, metadata=None):
        """
        :param metadata: information needed to deserialize xml into
                         a dictionary.
        """
        super(XMLDeserializer, self).__init__()
        self.metadata = metadata or {}

    def _from_xml(self, datastring):
        plurals = set(self.metadata.get('plurals', {}))

        try:
            node = minidom.parseString(datastring).childNodes[0]
            return {node.nodeName: self._from_xml_node(node, plurals)}
        except expat.ExpatError:
            msg = _("cannot understand XML")
            raise exception.MalformedRequestBody(reason=msg)

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

    def find_first_child_named(self, parent, name):
        """Search a nodes children for the first child with a given name"""
        for node in parent.childNodes:
            if node.nodeName == name:
                return node
        return None

    def find_children_named(self, parent, name):
        """Return all of a nodes children who have the given name"""
        for node in parent.childNodes:
            if node.nodeName == name:
                yield node

    def extract_text(self, node):
        """Get the text field contained by the given node"""
        if len(node.childNodes) == 1:
            child = node.childNodes[0]
            if child.nodeType == child.TEXT_NODE:
                return child.nodeValue
        return ""

    def default(self, datastring):
        return {'body': self._from_xml(datastring)}


class MetadataXMLDeserializer(XMLDeserializer):

    def extract_metadata(self, metadata_node):
        """Marshal the metadata attribute of a parsed request"""
        metadata = {}
        if metadata_node is not None:
            for meta_node in self.find_children_named(metadata_node, "meta"):
                key = meta_node.getAttribute("key")
                metadata[key] = self.extract_text(meta_node)
        return metadata


class RequestHeadersDeserializer(ActionDispatcher):
    """Default request headers deserializer"""

    def deserialize(self, request, action):
        return self.dispatch(request, action=action)

    def default(self, request):
        return {}


class RequestDeserializer(object):
    """Break up a Request object into more useful pieces."""

    def __init__(self, body_deserializers=None, headers_deserializer=None,
                 supported_content_types=None):

        self.supported_content_types = supported_content_types or \
                ('application/json', 'application/xml')

        self.body_deserializers = {
            'application/xml': XMLDeserializer(),
            'application/json': JSONDeserializer(),
        }
        self.body_deserializers.update(body_deserializers or {})

        self.headers_deserializer = headers_deserializer or \
                                        RequestHeadersDeserializer()

    def deserialize(self, request):
        """Extract necessary pieces of the request.

        :param request: Request object
        :returns tuple of expected controller action name, dictionary of
                 keyword arguments to pass to the controller, the expected
                 content type of the response

        """
        action_args = self.get_action_args(request.environ)
        action = action_args.pop('action', None)

        action_args.update(self.deserialize_headers(request, action))
        action_args.update(self.deserialize_body(request, action))

        accept = self.get_expected_content_type(request)

        return (action, action_args, accept)

    def deserialize_headers(self, request, action):
        return self.headers_deserializer.deserialize(request, action)

    def deserialize_body(self, request, action):
        try:
            content_type = request.get_content_type()
        except exception.InvalidContentType:
            LOG.debug(_("Unrecognized Content-Type provided in request"))
            return {}

        if content_type is None:
            LOG.debug(_("No Content-Type provided in request"))
            return {}

        if not len(request.body) > 0:
            LOG.debug(_("Empty body provided in request"))
            return {}

        try:
            deserializer = self.get_body_deserializer(content_type)
        except exception.InvalidContentType:
            LOG.debug(_("Unable to deserialize body as provided Content-Type"))
            raise

        return deserializer.deserialize(request.body, action)

    def get_body_deserializer(self, content_type):
        try:
            return self.body_deserializers[content_type]
        except (KeyError, TypeError):
            raise exception.InvalidContentType(content_type=content_type)

    def get_expected_content_type(self, request):
        return request.best_match_content_type(self.supported_content_types)

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


class DictSerializer(ActionDispatcher):
    """Default request body serialization"""

    def serialize(self, data, action='default'):
        return self.dispatch(data, action=action)

    def default(self, data):
        return ""


class JSONDictSerializer(DictSerializer):
    """Default JSON request body serialization"""

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

        return self.to_xml_string(node)

    def to_xml_string(self, node, has_atom=False):
        self._add_xmlns(node, has_atom)
        return node.toprettyxml(indent='    ', encoding='UTF-8')

    #NOTE (ameade): the has_atom should be removed after all of the
    # xml serializers and view builders have been updated to the current
    # spec that required all responses include the xmlns:atom, the has_atom
    # flag is to prevent current tests from breaking
    def _add_xmlns(self, node, has_atom=False):
        if self.xmlns is not None:
            node.setAttribute('xmlns', self.xmlns)
        if has_atom:
            node.setAttribute('xmlns:atom', "http://www.w3.org/2005/Atom")

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

    def _create_link_nodes(self, xml_doc, links):
        link_nodes = []
        for link in links:
            link_node = xml_doc.createElement('atom:link')
            link_node.setAttribute('rel', link['rel'])
            link_node.setAttribute('href', link['href'])
            if 'type' in link:
                link_node.setAttribute('type', link['type'])
            link_nodes.append(link_node)
        return link_nodes


class ResponseHeadersSerializer(ActionDispatcher):
    """Default response headers serialization"""

    def serialize(self, response, data, action):
        self.dispatch(response, data, action=action)

    def default(self, response, data):
        response.status_int = 200


class ResponseSerializer(object):
    """Encode the necessary pieces into a response object"""

    def __init__(self, body_serializers=None, headers_serializer=None):
        self.body_serializers = {
            'application/xml': XMLDictSerializer(),
            'application/json': JSONDictSerializer(),
        }
        self.body_serializers.update(body_serializers or {})

        self.headers_serializer = headers_serializer or \
                                    ResponseHeadersSerializer()

    def serialize(self, response_data, content_type, action='default'):
        """Serialize a dict into a string and wrap in a wsgi.Request object.

        :param response_data: dict produced by the Controller
        :param content_type: expected mimetype of serialized response body

        """
        response = webob.Response()
        self.serialize_headers(response, response_data, action)
        self.serialize_body(response, response_data, content_type, action)
        return response

    def serialize_headers(self, response, data, action):
        self.headers_serializer.serialize(response, data, action)

    def serialize_body(self, response, data, content_type, action):
        response.headers['Content-Type'] = content_type
        if data is not None:
            serializer = self.get_body_serializer(content_type)
            response.body = serializer.serialize(data, action)

    def get_body_serializer(self, content_type):
        try:
            return self.body_serializers[content_type]
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

    def __init__(self, controller, deserializer=None, serializer=None):
        """
        :param controller: object that implement methods created by routes lib
        :param deserializer: object that can serialize the output of a
                             controller into a webob response
        :param serializer: object that can deserialize a webob request
                           into necessary pieces

        """
        self.controller = controller
        self.deserializer = deserializer or RequestDeserializer()
        self.serializer = serializer or ResponseSerializer()

    @webob.dec.wsgify(RequestClass=Request)
    def __call__(self, request):
        """WSGI method that controls (de)serialization and method dispatch."""

        LOG.info("%(method)s %(url)s" % {"method": request.method,
                                          "url": request.url})

        try:
            action, args, accept = self.deserializer.deserialize(request)
        except exception.InvalidContentType:
            msg = _("Unsupported Content-Type")
            return faults.Fault(webob.exc.HTTPBadRequest(explanation=msg))
        except exception.MalformedRequestBody:
            msg = _("Malformed request body")
            return faults.Fault(webob.exc.HTTPBadRequest(explanation=msg))

        project_id = args.pop("project_id", None)
        if 'nova.context' in request.environ and project_id:
            request.environ['nova.context'].project_id = project_id

        try:
            action_result = self.dispatch(request, action, args)
        except webob.exc.HTTPException as ex:
            LOG.info(_("HTTP exception thrown: %s"), unicode(ex))
            action_result = faults.Fault(ex)

        if type(action_result) is dict or action_result is None:
            response = self.serializer.serialize(action_result,
                                                 accept,
                                                 action=action)
        else:
            response = action_result

        try:
            msg_dict = dict(url=request.url, status=response.status_int)
            msg = _("%(url)s returned with HTTP %(status)d") % msg_dict
        except AttributeError, e:
            msg_dict = dict(url=request.url, e=e)
            msg = _("%(url)s returned a fault: %(e)s" % msg_dict)

        LOG.info(msg)

        return response

    def dispatch(self, request, action, action_args):
        """Find action-spefic method on controller and call it."""

        controller_method = getattr(self.controller, action)
        try:
            return controller_method(req=request, **action_args)
        except TypeError as exc:
            LOG.exception(exc)
            return faults.Fault(webob.exc.HTTPBadRequest())
