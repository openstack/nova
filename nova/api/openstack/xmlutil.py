# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import os.path

from lxml import etree
from xml.dom import minidom
from xml.parsers import expat
from xml import sax
from xml.sax import expatreader

from nova import exception
from nova.openstack.common.gettextutils import _
from nova import utils


XMLNS_V10 = 'http://docs.rackspacecloud.com/servers/api/v1.0'
XMLNS_V11 = 'http://docs.openstack.org/compute/api/v1.1'
XMLNS_COMMON_V10 = 'http://docs.openstack.org/common/api/v1.0'
XMLNS_ATOM = 'http://www.w3.org/2005/Atom'


def validate_schema(xml, schema_name, version='v1.1'):
    if isinstance(xml, str):
        xml = etree.fromstring(xml)
    base_path = 'nova/api/openstack/compute/schemas/'
    if schema_name not in ('atom', 'atom-link'):
        base_path += '%s/' % version
    schema_path = os.path.join(utils.novadir(),
                               '%s%s.rng' % (base_path, schema_name))
    schema_doc = etree.parse(schema_path)
    relaxng = etree.RelaxNG(schema_doc)
    relaxng.assertValid(xml)


class Selector(object):
    """Selects datum to operate on from an object."""

    def __init__(self, *chain):
        """Initialize the selector.

        Each argument is a subsequent index into the object.
        """

        self.chain = chain

    def __repr__(self):
        """Return a representation of the selector."""

        return "Selector" + repr(self.chain)

    def __call__(self, obj, do_raise=False):
        """Select a datum to operate on.

        Selects the relevant datum within the object.

        :param obj: The object from which to select the object.
        :param do_raise: If False (the default), return None if the
                         indexed datum does not exist.  Otherwise,
                         raise a KeyError.
        """

        # Walk the selector list
        for elem in self.chain:
            # If it's callable, call it
            if callable(elem):
                obj = elem(obj)
            else:
                # Use indexing
                try:
                    obj = obj[elem]
                except (KeyError, IndexError):
                    # No sense going any further
                    if do_raise:
                        # Convert to a KeyError, for consistency
                        raise KeyError(elem)
                    return None

        # Return the finally-selected object
        return obj


def get_items(obj):
    """Get items in obj."""

    return list(obj.items())


class EmptyStringSelector(Selector):
    """Returns the empty string if Selector would return None."""
    def __call__(self, obj, do_raise=False):
        """Returns empty string if the selected value does not exist."""

        try:
            return super(EmptyStringSelector, self).__call__(obj, True)
        except KeyError:
            return ""


class ConstantSelector(object):
    """Returns a constant."""

    def __init__(self, value):
        """Initialize the selector.

        :param value: The value to return.
        """

        self.value = value

    def __repr__(self):
        """Return a representation of the selector."""

        return repr(self.value)

    def __call__(self, _obj, _do_raise=False):
        """Select a datum to operate on.

        Returns a constant value.  Compatible with
        Selector.__call__().
        """

        return self.value


class TemplateElement(object):
    """Represent an element in the template."""

    def __init__(self, tag, attrib=None, selector=None, subselector=None,
                 colon_ns=False, **extra):
        """Initialize an element.

        Initializes an element in the template.  Keyword arguments
        specify attributes to be set on the element; values must be
        callables.  See TemplateElement.set() for more information.

        :param tag: The name of the tag to create.
        :param attrib: An optional dictionary of element attributes.
        :param selector: An optional callable taking an object and
                         optional boolean do_raise indicator and
                         returning the object bound to the element.
        :param subselector: An optional callable taking an object and
                            optional boolean do_raise indicator and
                            returning the object bound to the element.
                            This is used to further refine the datum
                            object returned by selector in the event
                            that it is a list of objects.
        :colon_ns: An optional flag indicates whether support k:v
                    type tagname, if so the k:v type tagname will
                    be supported by adding the k into namespace.
        """

        # Convert selector into a Selector
        if selector is None:
            selector = Selector()
        elif not callable(selector):
            selector = Selector(selector)

        # Convert subselector into a Selector
        if subselector is not None and not callable(subselector):
            subselector = Selector(subselector)

        self.tag = tag
        self.selector = selector
        self.subselector = subselector
        self.attrib = {}
        self._text = None
        self._children = []
        self._childmap = {}
        self.colon_ns = colon_ns

        # Run the incoming attributes through set() so that they
        # become selectorized
        if not attrib:
            attrib = {}
        attrib.update(extra)
        for k, v in attrib.items():
            self.set(k, v)

    def __repr__(self):
        """Return a representation of the template element."""

        return ('<%s.%s %r at %#x>' %
                (self.__class__.__module__, self.__class__.__name__,
                 self.tag, id(self)))

    def __len__(self):
        """Return the number of child elements."""

        return len(self._children)

    def __contains__(self, key):
        """Determine whether a child node named by key exists."""

        return key in self._childmap

    def __getitem__(self, idx):
        """Retrieve a child node by index or name."""

        if isinstance(idx, basestring):
            # Allow access by node name
            return self._childmap[idx]
        else:
            return self._children[idx]

    def append(self, elem):
        """Append a child to the element."""

        # Unwrap templates...
        elem = elem.unwrap()

        # Avoid duplications
        if elem.tag in self._childmap:
            raise KeyError(elem.tag)

        self._children.append(elem)
        self._childmap[elem.tag] = elem

    def extend(self, elems):
        """Append children to the element."""

        # Pre-evaluate the elements
        elemmap = {}
        elemlist = []
        for elem in elems:
            # Unwrap templates...
            elem = elem.unwrap()

            # Avoid duplications
            if elem.tag in self._childmap or elem.tag in elemmap:
                raise KeyError(elem.tag)

            elemmap[elem.tag] = elem
            elemlist.append(elem)

        # Update the children
        self._children.extend(elemlist)
        self._childmap.update(elemmap)

    def insert(self, idx, elem):
        """Insert a child element at the given index."""

        # Unwrap templates...
        elem = elem.unwrap()

        # Avoid duplications
        if elem.tag in self._childmap:
            raise KeyError(elem.tag)

        self._children.insert(idx, elem)
        self._childmap[elem.tag] = elem

    def remove(self, elem):
        """Remove a child element."""

        # Unwrap templates...
        elem = elem.unwrap()

        # Check if element exists
        if elem.tag not in self._childmap or self._childmap[elem.tag] != elem:
            raise ValueError(_('element is not a child'))

        self._children.remove(elem)
        del self._childmap[elem.tag]

    def get(self, key):
        """Get an attribute.

        Returns a callable which performs datum selection.

        :param key: The name of the attribute to get.
        """

        return self.attrib[key]

    def set(self, key, value=None):
        """Set an attribute.

        :param key: The name of the attribute to set.

        :param value: A callable taking an object and optional boolean
                      do_raise indicator and returning the datum bound
                      to the attribute.  If None, a Selector() will be
                      constructed from the key.  If a string, a
                      Selector() will be constructed from the string.
        """

        # Convert value to a selector
        if value is None:
            value = Selector(key)
        elif not callable(value):
            value = Selector(value)

        self.attrib[key] = value

    def keys(self):
        """Return the attribute names."""

        return self.attrib.keys()

    def items(self):
        """Return the attribute names and values."""

        return self.attrib.items()

    def unwrap(self):
        """Unwraps a template to return a template element."""

        # We are a template element
        return self

    def wrap(self):
        """Wraps a template element to return a template."""

        # Wrap in a basic Template
        return Template(self)

    def apply(self, elem, obj):
        """Apply text and attributes to an etree.Element.

        Applies the text and attribute instructions in the template
        element to an etree.Element instance.

        :param elem: An etree.Element instance.
        :param obj: The base object associated with this template
                    element.
        """

        # Start with the text...
        if self.text is not None:
            elem.text = unicode(self.text(obj))

        # Now set up all the attributes...
        for key, value in self.attrib.items():
            try:
                elem.set(key, unicode(value(obj, True)))
            except KeyError:
                # Attribute has no value, so don't include it
                pass

    def _render(self, parent, datum, patches, nsmap):
        """Internal rendering.

        Renders the template node into an etree.Element object.
        Returns the etree.Element object.

        :param parent: The parent etree.Element instance.
        :param datum: The datum associated with this template element.
        :param patches: A list of other template elements that must
                        also be applied.
        :param nsmap: An optional namespace dictionary to be
                      associated with the etree.Element instance.
        """

        # Allocate a node
        if callable(self.tag):
            tagname = self.tag(datum)
        else:
            tagname = self.tag

        if self.colon_ns:
            if ':' in tagname:
                if nsmap is None:
                    nsmap = {}
                colon_key, colon_name = tagname.split(':')
                nsmap[colon_key] = colon_key
                tagname = '{%s}%s' % (colon_key, colon_name)

        elem = etree.Element(tagname, nsmap=nsmap)

        # If we have a parent, append the node to the parent
        if parent is not None:
            parent.append(elem)

        # If the datum is None, do nothing else
        if datum is None:
            return elem

        # Apply this template element to the element
        self.apply(elem, datum)

        # Additionally, apply the patches
        for patch in patches:
            patch.apply(elem, datum)

        # We have fully rendered the element; return it
        return elem

    def render(self, parent, obj, patches=[], nsmap=None):
        """Render an object.

        Renders an object against this template node.  Returns a list
        of two-item tuples, where the first item is an etree.Element
        instance and the second item is the datum associated with that
        instance.

        :param parent: The parent for the etree.Element instances.
        :param obj: The object to render this template element
                    against.
        :param patches: A list of other template elements to apply
                        when rendering this template element.
        :param nsmap: An optional namespace dictionary to attach to
                      the etree.Element instances.
        """

        # First, get the datum we're rendering
        data = None if obj is None else self.selector(obj)

        # Check if we should render at all
        if not self.will_render(data):
            return []
        elif data is None:
            return [(self._render(parent, None, patches, nsmap), None)]

        # Make the data into a list if it isn't already
        if not isinstance(data, list):
            data = [data]
        elif parent is None:
            raise ValueError(_('root element selecting a list'))

        # Render all the elements
        elems = []
        for datum in data:
            if self.subselector is not None:
                datum = self.subselector(datum)
            elems.append((self._render(parent, datum, patches, nsmap), datum))

        # Return all the elements rendered, as well as the
        # corresponding datum for the next step down the tree
        return elems

    def will_render(self, datum):
        """Hook method.

        An overridable hook method to determine whether this template
        element will be rendered at all.  By default, returns False
        (inhibiting rendering) if the datum is None.

        :param datum: The datum associated with this template element.
        """

        # Don't render if datum is None
        return datum is not None

    def _text_get(self):
        """Template element text.

        Either None or a callable taking an object and optional
        boolean do_raise indicator and returning the datum bound to
        the text of the template element.
        """

        return self._text

    def _text_set(self, value):
        # Convert value to a selector
        if value is not None and not callable(value):
            value = Selector(value)

        self._text = value

    def _text_del(self):
        self._text = None

    text = property(_text_get, _text_set, _text_del)

    def tree(self):
        """Return string representation of the template tree.

        Returns a representation of the template rooted at this
        element as a string, suitable for inclusion in debug logs.
        """

        # Build the inner contents of the tag...
        contents = [self.tag, '!selector=%r' % self.selector]

        # Add the text...
        if self.text is not None:
            contents.append('!text=%r' % self.text)

        # Add all the other attributes
        for key, value in self.attrib.items():
            contents.append('%s=%r' % (key, value))

        # If there are no children, return it as a closed tag
        if len(self) == 0:
            return '<%s/>' % ' '.join([str(i) for i in contents])

        # OK, recurse to our children
        children = [c.tree() for c in self]

        # Return the result
        return ('<%s>%s</%s>' %
                (' '.join(contents), ''.join(children), self.tag))


def SubTemplateElement(parent, tag, attrib=None, selector=None,
                       subselector=None, colon_ns=False, **extra):
    """Create a template element as a child of another.

    Corresponds to the etree.SubElement interface.  Parameters are as
    for TemplateElement, with the addition of the parent.
    """

    # Convert attributes
    attrib = attrib or {}
    attrib.update(extra)

    # Get a TemplateElement
    elem = TemplateElement(tag, attrib=attrib, selector=selector,
                           subselector=subselector, colon_ns=colon_ns)

    # Append the parent safely
    if parent is not None:
        parent.append(elem)

    return elem


class Template(object):
    """Represent a template."""

    def __init__(self, root, nsmap=None):
        """Initialize a template.

        :param root: The root element of the template.
        :param nsmap: An optional namespace dictionary to be
                      associated with the root element of the
                      template.
        """

        self.root = root.unwrap() if root is not None else None
        self.nsmap = nsmap or {}
        self.serialize_options = dict(encoding='UTF-8', xml_declaration=True)

    def _serialize(self, parent, obj, siblings, nsmap=None):
        """Internal serialization.

        Recursive routine to build a tree of etree.Element instances
        from an object based on the template.  Returns the first
        etree.Element instance rendered, or None.

        :param parent: The parent etree.Element instance.  Can be
                       None.
        :param obj: The object to render.
        :param siblings: The TemplateElement instances against which
                         to render the object.
        :param nsmap: An optional namespace dictionary to be
                      associated with the etree.Element instance
                      rendered.
        """

        # First step, render the element
        elems = siblings[0].render(parent, obj, siblings[1:], nsmap)

        # Now, recurse to all child elements
        seen = set()
        for idx, sibling in enumerate(siblings):
            for child in sibling:
                # Have we handled this child already?
                if child.tag in seen:
                    continue
                seen.add(child.tag)

                # Determine the child's siblings
                nieces = [child]
                for sib in siblings[idx + 1:]:
                    if child.tag in sib:
                        nieces.append(sib[child.tag])

                # Now we recurse for every data element
                for elem, datum in elems:
                    self._serialize(elem, datum, nieces)

        # Return the first element; at the top level, this will be the
        # root element
        if elems:
            return elems[0][0]

    def serialize(self, obj, *args, **kwargs):
        """Serialize an object.

        Serializes an object against the template.  Returns a string
        with the serialized XML.  Positional and keyword arguments are
        passed to etree.tostring().

        :param obj: The object to serialize.
        """

        elem = self.make_tree(obj)
        if elem is None:
            return ''

        for k, v in self.serialize_options.items():
            kwargs.setdefault(k, v)

        # Serialize it into XML
        return etree.tostring(elem, *args, **kwargs)

    def make_tree(self, obj):
        """Create a tree.

        Serializes an object against the template.  Returns an Element
        node with appropriate children.

        :param obj: The object to serialize.
        """

        # If the template is empty, return the empty string
        if self.root is None:
            return None

        # Get the siblings and nsmap of the root element
        siblings = self._siblings()
        nsmap = self._nsmap()

        # Form the element tree
        return self._serialize(None, obj, siblings, nsmap)

    def _siblings(self):
        """Hook method for computing root siblings.

        An overridable hook method to return the siblings of the root
        element.  By default, this is the root element itself.
        """

        return [self.root]

    def _nsmap(self):
        """Hook method for computing the namespace dictionary.

        An overridable hook method to return the namespace dictionary.
        """

        return self.nsmap.copy()

    def unwrap(self):
        """Unwraps a template to return a template element."""

        # Return the root element
        return self.root

    def wrap(self):
        """Wraps a template element to return a template."""

        # We are a template
        return self

    def apply(self, master):
        """Hook method for determining slave applicability.

        An overridable hook method used to determine if this template
        is applicable as a slave to a given master template.

        :param master: The master template to test.
        """

        return True

    def tree(self):
        """Return string representation of the template tree.

        Returns a representation of the template as a string, suitable
        for inclusion in debug logs.
        """

        return "%r: %s" % (self, self.root.tree())


class MasterTemplate(Template):
    """Represent a master template.

    Master templates are versioned derivatives of templates that
    additionally allow slave templates to be attached.  Slave
    templates allow modification of the serialized result without
    directly changing the master.
    """

    def __init__(self, root, version, nsmap=None):
        """Initialize a master template.

        :param root: The root element of the template.
        :param version: The version number of the template.
        :param nsmap: An optional namespace dictionary to be
                      associated with the root element of the
                      template.
        """

        super(MasterTemplate, self).__init__(root, nsmap)
        self.version = version
        self.slaves = []

    def __repr__(self):
        """Return string representation of the template."""

        return ("<%s.%s object version %s at %#x>" %
                (self.__class__.__module__, self.__class__.__name__,
                 self.version, id(self)))

    def _siblings(self):
        """Hook method for computing root siblings.

        An overridable hook method to return the siblings of the root
        element.  This is the root element plus the root elements of
        all the slave templates.
        """

        return [self.root] + [slave.root for slave in self.slaves]

    def _nsmap(self):
        """Hook method for computing the namespace dictionary.

        An overridable hook method to return the namespace dictionary.
        The namespace dictionary is computed by taking the master
        template's namespace dictionary and updating it from all the
        slave templates.
        """

        nsmap = self.nsmap.copy()
        for slave in self.slaves:
            nsmap.update(slave._nsmap())
        return nsmap

    def attach(self, *slaves):
        """Attach one or more slave templates.

        Attaches one or more slave templates to the master template.
        Slave templates must have a root element with the same tag as
        the master template.  The slave template's apply() method will
        be called to determine if the slave should be applied to this
        master; if it returns False, that slave will be skipped.
        (This allows filtering of slaves based on the version of the
        master template.)
        """

        slave_list = []
        for slave in slaves:
            slave = slave.wrap()

            # Make sure we have a tree match
            if slave.root.tag != self.root.tag:
                msg = _("Template tree mismatch; adding slave %(slavetag)s to "
                        "master %(mastertag)s") % {'slavetag': slave.root.tag,
                                                   'mastertag': self.root.tag}
                raise ValueError(msg)

            # Make sure slave applies to this template
            if not slave.apply(self):
                continue

            slave_list.append(slave)

        # Add the slaves
        self.slaves.extend(slave_list)

    def copy(self):
        """Return a copy of this master template."""

        # Return a copy of the MasterTemplate
        tmp = self.__class__(self.root, self.version, self.nsmap)
        tmp.slaves = self.slaves[:]
        return tmp


class SlaveTemplate(Template):
    """Represent a slave template.

    Slave templates are versioned derivatives of templates.  Each
    slave has a minimum version and optional maximum version of the
    master template to which they can be attached.
    """

    def __init__(self, root, min_vers, max_vers=None, nsmap=None):
        """Initialize a slave template.

        :param root: The root element of the template.
        :param min_vers: The minimum permissible version of the master
                         template for this slave template to apply.
        :param max_vers: An optional upper bound for the master
                         template version.
        :param nsmap: An optional namespace dictionary to be
                      associated with the root element of the
                      template.
        """

        super(SlaveTemplate, self).__init__(root, nsmap)
        self.min_vers = min_vers
        self.max_vers = max_vers

    def __repr__(self):
        """Return string representation of the template."""

        return ("<%s.%s object versions %s-%s at %#x>" %
                (self.__class__.__module__, self.__class__.__name__,
                 self.min_vers, self.max_vers, id(self)))

    def apply(self, master):
        """Hook method for determining slave applicability.

        An overridable hook method used to determine if this template
        is applicable as a slave to a given master template.  This
        version requires the master template to have a version number
        between min_vers and max_vers.

        :param master: The master template to test.
        """

        # Does the master meet our minimum version requirement?
        if master.version < self.min_vers:
            return False

        # How about our maximum version requirement?
        if self.max_vers is not None and master.version > self.max_vers:
            return False

        return True


class TemplateBuilder(object):
    """Template builder.

    This class exists to allow templates to be lazily built without
    having to build them each time they are needed.  It must be
    subclassed, and the subclass must implement the construct()
    method, which must return a Template (or subclass) instance.  The
    constructor will always return the template returned by
    construct(), or, if it has a copy() method, a copy of that
    template.
    """

    _tmpl = None

    def __new__(cls, copy=True):
        """Construct and return a template.

        :param copy: If True (the default), a copy of the template
                     will be constructed and returned, if possible.
        """

        # Do we need to construct the template?
        if cls._tmpl is None:
            tmp = super(TemplateBuilder, cls).__new__(cls)

            # Construct the template
            cls._tmpl = tmp.construct()

        # If the template has a copy attribute, return the result of
        # calling it
        if copy and hasattr(cls._tmpl, 'copy'):
            return cls._tmpl.copy()

        # Return the template
        return cls._tmpl

    def construct(self):
        """Construct a template.

        Called to construct a template instance, which it must return.
        Only called once.
        """

        raise NotImplementedError(_("subclasses must implement construct()!"))


def make_links(parent, selector=None):
    """
    Attach an Atom <links> element to the parent.
    """

    elem = SubTemplateElement(parent, '{%s}link' % XMLNS_ATOM,
                              selector=selector)
    elem.set('rel')
    elem.set('type')
    elem.set('href')

    # Just for completeness...
    return elem


def make_flat_dict(name, selector=None, subselector=None,
                   ns=None, colon_ns=False):
    """
    Utility for simple XML templates that traditionally used
    XMLDictSerializer with no metadata.  Returns a template element
    where the top-level element has the given tag name, and where
    sub-elements have tag names derived from the object's keys and
    text derived from the object's values.  This only works for flat
    dictionary objects, not dictionaries containing nested lists or
    dictionaries.
    """

    # Set up the names we need...
    if ns is None:
        elemname = name
        tagname = Selector(0)
    else:
        elemname = '{%s}%s' % (ns, name)
        tagname = lambda obj, do_raise=False: '{%s}%s' % (ns, obj[0])

    if selector is None:
        selector = name

    # Build the root element
    root = TemplateElement(elemname, selector=selector,
                           subselector=subselector, colon_ns=colon_ns)

    # Build an element to represent all the keys and values
    elem = SubTemplateElement(root, tagname, selector=get_items,
                              colon_ns=colon_ns)
    elem.text = 1

    # Return the template
    return root


class ProtectedExpatParser(expatreader.ExpatParser):
    """An expat parser which disables DTD's and entities by default."""

    def __init__(self, forbid_dtd=True, forbid_entities=True,
                 *args, **kwargs):
        # Python 2.x old style class
        expatreader.ExpatParser.__init__(self, *args, **kwargs)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities

    def start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise ValueError("Inline DTD forbidden")

    def entity_decl(self, entityName, is_parameter_entity, value, base,
                    systemId, publicId, notationName):
        raise ValueError("<!ENTITY> entity declaration forbidden")

    def unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        # expat 1.2
        raise ValueError("<!ENTITY> unparsed entity forbidden")

    def external_entity_ref(self, context, base, systemId, publicId):
        raise ValueError("<!ENTITY> external entity forbidden")

    def notation_decl(self, name, base, sysid, pubid):
        raise ValueError("<!ENTITY> notation forbidden")

    def reset(self):
        expatreader.ExpatParser.reset(self)
        if self.forbid_dtd:
            self._parser.StartDoctypeDeclHandler = self.start_doctype_decl
            self._parser.EndDoctypeDeclHandler = None
        if self.forbid_entities:
            self._parser.EntityDeclHandler = self.entity_decl
            self._parser.UnparsedEntityDeclHandler = self.unparsed_entity_decl
            self._parser.ExternalEntityRefHandler = self.external_entity_ref
            self._parser.NotationDeclHandler = self.notation_decl
            try:
                self._parser.SkippedEntityHandler = None
            except AttributeError:
                # some pyexpat versions do not support SkippedEntity
                pass


def safe_minidom_parse_string(xml_string):
    """Parse an XML string using minidom safely."""
    try:
        return minidom.parseString(xml_string, parser=ProtectedExpatParser())
    except (sax.SAXParseException, ValueError,
            expat.ExpatError, LookupError) as e:
        #NOTE(Vijaya Erukala): XML input such as
        #                      <?xml version="1.0" encoding="TF-8"?>
        #                      raises LookupError: unknown encoding: TF-8
        raise exception.MalformedRequestBody(reason=str(e))
