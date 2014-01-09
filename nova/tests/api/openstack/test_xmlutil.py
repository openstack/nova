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

from lxml import etree
from xml.dom import minidom

from nova.api.openstack import xmlutil
from nova import exception
from nova import test
from nova.tests import utils as tests_utils


class SelectorTest(test.NoDBTestCase):
    obj_for_test = {
        'test': {
            'name': 'test',
            'values': [1, 2, 3],
            'attrs': {
                'foo': 1,
                'bar': 2,
                'baz': 3,
                },
            },
        }

    def test_repr(self):
        sel = xmlutil.Selector()
        self.assertEqual(repr(sel), "Selector()")

    def test_empty_selector(self):
        sel = xmlutil.EmptyStringSelector()
        self.assertEqual(len(sel.chain), 0)
        self.assertEqual(sel(self.obj_for_test), self.obj_for_test)
        self.assertEqual(
            repr(self.obj_for_test),
            "{'test': {'values': [1, 2, 3], 'name': 'test', 'attrs': "
            "{'baz': 3, 'foo': 1, 'bar': 2}}}")

    def test_dict_selector(self):
        sel = xmlutil.Selector('test')
        self.assertEqual(len(sel.chain), 1)
        self.assertEqual(sel.chain[0], 'test')
        self.assertEqual(sel(self.obj_for_test),
                         self.obj_for_test['test'])

    def test_datum_selector(self):
        sel = xmlutil.Selector('test', 'name')
        self.assertEqual(len(sel.chain), 2)
        self.assertEqual(sel.chain[0], 'test')
        self.assertEqual(sel.chain[1], 'name')
        self.assertEqual(sel(self.obj_for_test), 'test')

    def test_list_selector(self):
        sel = xmlutil.Selector('test', 'values', 0)
        self.assertEqual(len(sel.chain), 3)
        self.assertEqual(sel.chain[0], 'test')
        self.assertEqual(sel.chain[1], 'values')
        self.assertEqual(sel.chain[2], 0)
        self.assertEqual(sel(self.obj_for_test), 1)

    def test_items_selector(self):
        sel = xmlutil.Selector('test', 'attrs', xmlutil.get_items)
        self.assertEqual(len(sel.chain), 3)
        self.assertEqual(sel.chain[2], xmlutil.get_items)
        for key, val in sel(self.obj_for_test):
            self.assertEqual(self.obj_for_test['test']['attrs'][key], val)

    def test_missing_key_selector(self):
        sel = xmlutil.Selector('test2', 'attrs')
        self.assertEqual(sel(self.obj_for_test), None)
        self.assertRaises(KeyError, sel, self.obj_for_test, True)

    def test_constant_selector(self):
        sel = xmlutil.ConstantSelector('Foobar')
        self.assertEqual(sel.value, 'Foobar')
        self.assertEqual(sel(self.obj_for_test), 'Foobar')
        self.assertEqual(repr(sel), "'Foobar'")


class TemplateElementTest(test.NoDBTestCase):
    def test_element_initial_attributes(self):
        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=dict(a=1, b=2, c=3),
                                       c=4, d=5, e=6)

        # Verify all the attributes are as expected
        expected = dict(a=1, b=2, c=4, d=5, e=6)
        for k, v in expected.items():
            self.assertEqual(elem.attrib[k].chain[0], v)
        self.assertTrue(repr(elem))

    def test_element_get_attributes(self):
        expected = dict(a=1, b=2, c=3)

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=expected)

        # Verify that get() retrieves the attributes
        for k, v in expected.items():
            self.assertEqual(elem.get(k).chain[0], v)

    def test_element_set_attributes(self):
        attrs = dict(a=None, b='foo', c=xmlutil.Selector('foo', 'bar'))

        # Create a bare template element with no attributes
        elem = xmlutil.TemplateElement('test')

        # Set the attribute values
        for k, v in attrs.items():
            elem.set(k, v)

        # Now verify what got set
        self.assertEqual(len(elem.attrib['a'].chain), 1)
        self.assertEqual(elem.attrib['a'].chain[0], 'a')
        self.assertEqual(len(elem.attrib['b'].chain), 1)
        self.assertEqual(elem.attrib['b'].chain[0], 'foo')
        self.assertEqual(elem.attrib['c'], attrs['c'])

    def test_element_attribute_keys(self):
        attrs = dict(a=1, b=2, c=3, d=4)
        expected = set(attrs.keys())

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=attrs)

        # Now verify keys
        self.assertEqual(set(elem.keys()), expected)

    def test_element_attribute_items(self):
        expected = dict(a=xmlutil.Selector(1),
                        b=xmlutil.Selector(2),
                        c=xmlutil.Selector(3))
        keys = set(expected.keys())

        # Create a template element with some attributes
        elem = xmlutil.TemplateElement('test', attrib=expected)

        # Now verify items
        for k, v in elem.items():
            self.assertEqual(expected[k], v)
            keys.remove(k)

        # Did we visit all keys?
        self.assertEqual(len(keys), 0)

    def test_element_selector_none(self):
        # Create a template element with no selector
        elem = xmlutil.TemplateElement('test')

        self.assertEqual(len(elem.selector.chain), 0)

    def test_element_selector_string(self):
        # Create a template element with a string selector
        elem = xmlutil.TemplateElement('test', selector='test')

        self.assertEqual(len(elem.selector.chain), 1)
        self.assertEqual(elem.selector.chain[0], 'test')

    def test_element_selector(self):
        sel = xmlutil.Selector('a', 'b')

        # Create a template element with an explicit selector
        elem = xmlutil.TemplateElement('test', selector=sel)

        self.assertEqual(elem.selector, sel)

    def test_element_subselector_none(self):
        # Create a template element with no subselector
        elem = xmlutil.TemplateElement('test')

        self.assertEqual(elem.subselector, None)

    def test_element_subselector_string(self):
        # Create a template element with a string subselector
        elem = xmlutil.TemplateElement('test', subselector='test')

        self.assertEqual(len(elem.subselector.chain), 1)
        self.assertEqual(elem.subselector.chain[0], 'test')

    def test_element_subselector(self):
        sel = xmlutil.Selector('a', 'b')

        # Create a template element with an explicit subselector
        elem = xmlutil.TemplateElement('test', subselector=sel)

        self.assertEqual(elem.subselector, sel)

    def test_element_append_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(len(elem), 0)

        # Create a child element
        child = xmlutil.TemplateElement('child')

        # Append the child to the parent
        elem.append(child)

        # Verify that the child was added
        self.assertEqual(len(elem), 1)
        self.assertEqual(elem[0], child)
        self.assertEqual('child' in elem, True)
        self.assertEqual(elem['child'], child)

        # Ensure that multiple children of the same name are rejected
        child2 = xmlutil.TemplateElement('child')
        self.assertRaises(KeyError, elem.append, child2)

    def test_element_extend_children(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(len(elem), 0)

        # Create a few children
        children = [
            xmlutil.TemplateElement('child1'),
            xmlutil.TemplateElement('child2'),
            xmlutil.TemplateElement('child3'),
            ]

        # Extend the parent by those children
        elem.extend(children)

        # Verify that the children were added
        self.assertEqual(len(elem), 3)
        for idx in range(len(elem)):
            self.assertEqual(children[idx], elem[idx])
            self.assertEqual(children[idx].tag in elem, True)
            self.assertEqual(elem[children[idx].tag], children[idx])

        # Ensure that multiple children of the same name are rejected
        children2 = [
            xmlutil.TemplateElement('child4'),
            xmlutil.TemplateElement('child1'),
            ]
        self.assertRaises(KeyError, elem.extend, children2)

        # Also ensure that child4 was not added
        self.assertEqual(len(elem), 3)
        self.assertEqual(elem[-1].tag, 'child3')

    def test_element_insert_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(len(elem), 0)

        # Create a few children
        children = [
            xmlutil.TemplateElement('child1'),
            xmlutil.TemplateElement('child2'),
            xmlutil.TemplateElement('child3'),
            ]

        # Extend the parent by those children
        elem.extend(children)

        # Create a child to insert
        child = xmlutil.TemplateElement('child4')

        # Insert it
        elem.insert(1, child)

        # Ensure the child was inserted in the right place
        self.assertEqual(len(elem), 4)
        children.insert(1, child)
        for idx in range(len(elem)):
            self.assertEqual(children[idx], elem[idx])
            self.assertEqual(children[idx].tag in elem, True)
            self.assertEqual(elem[children[idx].tag], children[idx])

        # Ensure that multiple children of the same name are rejected
        child2 = xmlutil.TemplateElement('child2')
        self.assertRaises(KeyError, elem.insert, 2, child2)

    def test_element_remove_child(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Make sure the element starts off empty
        self.assertEqual(len(elem), 0)

        # Create a few children
        children = [
            xmlutil.TemplateElement('child1'),
            xmlutil.TemplateElement('child2'),
            xmlutil.TemplateElement('child3'),
            ]

        # Extend the parent by those children
        elem.extend(children)

        # Create a test child to remove
        child = xmlutil.TemplateElement('child2')

        # Try to remove it
        self.assertRaises(ValueError, elem.remove, child)

        # Ensure that no child was removed
        self.assertEqual(len(elem), 3)

        # Now remove a legitimate child
        elem.remove(children[1])

        # Ensure that the child was removed
        self.assertEqual(len(elem), 2)
        self.assertEqual(elem[0], children[0])
        self.assertEqual(elem[1], children[2])
        self.assertEqual('child2' in elem, False)

        # Ensure the child cannot be retrieved by name
        def get_key(elem, key):
            return elem[key]
        self.assertRaises(KeyError, get_key, elem, 'child2')

    def test_element_text(self):
        # Create an element
        elem = xmlutil.TemplateElement('test')

        # Ensure that it has no text
        self.assertEqual(elem.text, None)

        # Try setting it to a string and ensure it becomes a selector
        elem.text = 'test'
        self.assertEqual(hasattr(elem.text, 'chain'), True)
        self.assertEqual(len(elem.text.chain), 1)
        self.assertEqual(elem.text.chain[0], 'test')

        # Try resetting the text to None
        elem.text = None
        self.assertEqual(elem.text, None)

        # Now make up a selector and try setting the text to that
        sel = xmlutil.Selector()
        elem.text = sel
        self.assertEqual(elem.text, sel)

        # Finally, try deleting the text and see what happens
        del elem.text
        self.assertEqual(elem.text, None)

    def test_apply_attrs(self):
        # Create a template element
        attrs = dict(attr1=xmlutil.ConstantSelector(1),
                     attr2=xmlutil.ConstantSelector(2))
        tmpl_elem = xmlutil.TemplateElement('test', attrib=attrs)

        # Create an etree element
        elem = etree.Element('test')

        # Apply the template to the element
        tmpl_elem.apply(elem, None)

        # Now, verify the correct attributes were set
        for k, v in elem.items():
            self.assertEqual(str(attrs[k].value), v)

    def test_apply_text(self):
        # Create a template element
        tmpl_elem = xmlutil.TemplateElement('test')
        tmpl_elem.text = xmlutil.ConstantSelector(1)

        # Create an etree element
        elem = etree.Element('test')

        # Apply the template to the element
        tmpl_elem.apply(elem, None)

        # Now, verify the text was set
        self.assertEqual(str(tmpl_elem.text.value), elem.text)

    def test__render(self):
        attrs = dict(attr1=xmlutil.ConstantSelector(1),
                     attr2=xmlutil.ConstantSelector(2),
                     attr3=xmlutil.ConstantSelector(3))

        # Create a master template element
        master_elem = xmlutil.TemplateElement('test', attr1=attrs['attr1'])

        # Create a couple of slave template element
        slave_elems = [
            xmlutil.TemplateElement('test', attr2=attrs['attr2']),
            xmlutil.TemplateElement('test', attr3=attrs['attr3']),
            ]

        # Try the render
        elem = master_elem._render(None, None, slave_elems, None)

        # Verify the particulars of the render
        self.assertEqual(elem.tag, 'test')
        self.assertEqual(len(elem.nsmap), 0)
        for k, v in elem.items():
            self.assertEqual(str(attrs[k].value), v)

        # Create a parent for the element to be rendered
        parent = etree.Element('parent')

        # Try the render again...
        elem = master_elem._render(parent, None, slave_elems, dict(a='foo'))

        # Verify the particulars of the render
        self.assertEqual(len(parent), 1)
        self.assertEqual(parent[0], elem)
        self.assertEqual(len(elem.nsmap), 1)
        self.assertEqual(elem.nsmap['a'], 'foo')

    def test_render(self):
        # Create a template element
        tmpl_elem = xmlutil.TemplateElement('test')
        tmpl_elem.text = xmlutil.Selector()

        # Create the object we're going to render
        obj = ['elem1', 'elem2', 'elem3', 'elem4']

        # Try a render with no object
        elems = tmpl_elem.render(None, None)
        self.assertEqual(len(elems), 0)

        # Try a render with one object
        elems = tmpl_elem.render(None, 'foo')
        self.assertEqual(len(elems), 1)
        self.assertEqual(elems[0][0].text, 'foo')
        self.assertEqual(elems[0][1], 'foo')

        # Now, try rendering an object with multiple entries
        parent = etree.Element('parent')
        elems = tmpl_elem.render(parent, obj)
        self.assertEqual(len(elems), 4)

        # Check the results
        for idx in range(len(obj)):
            self.assertEqual(elems[idx][0].text, obj[idx])
            self.assertEqual(elems[idx][1], obj[idx])

        # Check with a subselector
        tmpl_elem = xmlutil.TemplateElement(
            'test',
            subselector=xmlutil.ConstantSelector('foo'))
        parent = etree.Element('parent')

        # Try a render with no object
        elems = tmpl_elem.render(parent, obj)
        self.assertEqual(len(elems), 4)

    def test_subelement(self):
        # Try the SubTemplateElement constructor
        parent = xmlutil.SubTemplateElement(None, 'parent')
        self.assertEqual(parent.tag, 'parent')
        self.assertEqual(len(parent), 0)

        # Now try it with a parent element
        child = xmlutil.SubTemplateElement(parent, 'child')
        self.assertEqual(child.tag, 'child')
        self.assertEqual(len(parent), 1)
        self.assertEqual(parent[0], child)

    def test_wrap(self):
        # These are strange methods, but they make things easier
        elem = xmlutil.TemplateElement('test')
        self.assertEqual(elem.unwrap(), elem)
        self.assertEqual(elem.wrap().root, elem)

    def test_dyntag(self):
        obj = ['a', 'b', 'c']

        # Create a template element with a dynamic tag
        tmpl_elem = xmlutil.TemplateElement(xmlutil.Selector())

        # Try the render
        parent = etree.Element('parent')
        elems = tmpl_elem.render(parent, obj)

        # Verify the particulars of the render
        self.assertEqual(len(elems), len(obj))
        for idx in range(len(obj)):
            self.assertEqual(elems[idx][0].tag, obj[idx])

    def test_tree(self):
        # Create a template element
        elem = xmlutil.TemplateElement('test', attr3='attr3')
        elem.text = 'test'
        self.assertEqual(elem.tree(),
                         "<test !selector=Selector() "
                         "!text=Selector('test',) "
                          "attr3=Selector('attr3',)"
                         "/>")

        # Create a template element
        elem = xmlutil.TemplateElement('test2')

        # Create a child element
        child = xmlutil.TemplateElement('child')

        # Append the child to the parent
        elem.append(child)

        self.assertEqual(elem.tree(),
                         "<test2 !selector=Selector()>"
                         "<child !selector=Selector()/></test2>")


class TemplateTest(test.NoDBTestCase):
    def test_tree(self):
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem)
        self.assertTrue(tmpl.tree())

    def test_wrap(self):
        # These are strange methods, but they make things easier
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem)
        self.assertEqual(tmpl.unwrap(), elem)
        self.assertEqual(tmpl.wrap(), tmpl)

    def test__siblings(self):
        # Set up a basic template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem)

        # Check that we get the right siblings
        siblings = tmpl._siblings()
        self.assertEqual(len(siblings), 1)
        self.assertEqual(siblings[0], elem)

    def test__nsmap(self):
        # Set up a basic template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.Template(elem, nsmap=dict(a="foo"))

        # Check out that we get the right namespace dictionary
        nsmap = tmpl._nsmap()
        self.assertNotEqual(id(nsmap), id(tmpl.nsmap))
        self.assertEqual(len(nsmap), 1)
        self.assertEqual(nsmap['a'], 'foo')

    def test_master_attach(self):
        # Set up a master template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.MasterTemplate(elem, 1)

        # Make sure it has a root but no slaves
        self.assertEqual(tmpl.root, elem)
        self.assertEqual(len(tmpl.slaves), 0)
        self.assertTrue(repr(tmpl))

        # Try to attach an invalid slave
        bad_elem = xmlutil.TemplateElement('test2')
        self.assertRaises(ValueError, tmpl.attach, bad_elem)
        self.assertEqual(len(tmpl.slaves), 0)

        # Try to attach an invalid and a valid slave
        good_elem = xmlutil.TemplateElement('test')
        self.assertRaises(ValueError, tmpl.attach, good_elem, bad_elem)
        self.assertEqual(len(tmpl.slaves), 0)

        # Try to attach an inapplicable template
        class InapplicableTemplate(xmlutil.Template):
            def apply(self, master):
                return False
        inapp_tmpl = InapplicableTemplate(good_elem)
        tmpl.attach(inapp_tmpl)
        self.assertEqual(len(tmpl.slaves), 0)

        # Now try attaching an applicable template
        tmpl.attach(good_elem)
        self.assertEqual(len(tmpl.slaves), 1)
        self.assertEqual(tmpl.slaves[0].root, good_elem)

    def test_master_copy(self):
        # Construct a master template
        elem = xmlutil.TemplateElement('test')
        tmpl = xmlutil.MasterTemplate(elem, 1, nsmap=dict(a='foo'))

        # Give it a slave
        slave = xmlutil.TemplateElement('test')
        tmpl.attach(slave)

        # Construct a copy
        copy = tmpl.copy()

        # Check to see if we actually managed a copy
        self.assertNotEqual(tmpl, copy)
        self.assertEqual(tmpl.root, copy.root)
        self.assertEqual(tmpl.version, copy.version)
        self.assertEqual(id(tmpl.nsmap), id(copy.nsmap))
        self.assertNotEqual(id(tmpl.slaves), id(copy.slaves))
        self.assertEqual(len(tmpl.slaves), len(copy.slaves))
        self.assertEqual(tmpl.slaves[0], copy.slaves[0])

    def test_slave_apply(self):
        # Construct a master template
        elem = xmlutil.TemplateElement('test')
        master = xmlutil.MasterTemplate(elem, 3)

        # Construct a slave template with applicable minimum version
        slave = xmlutil.SlaveTemplate(elem, 2)
        self.assertEqual(slave.apply(master), True)
        self.assertTrue(repr(slave))

        # Construct a slave template with equal minimum version
        slave = xmlutil.SlaveTemplate(elem, 3)
        self.assertEqual(slave.apply(master), True)

        # Construct a slave template with inapplicable minimum version
        slave = xmlutil.SlaveTemplate(elem, 4)
        self.assertEqual(slave.apply(master), False)

        # Construct a slave template with applicable version range
        slave = xmlutil.SlaveTemplate(elem, 2, 4)
        self.assertEqual(slave.apply(master), True)

        # Construct a slave template with low version range
        slave = xmlutil.SlaveTemplate(elem, 1, 2)
        self.assertEqual(slave.apply(master), False)

        # Construct a slave template with high version range
        slave = xmlutil.SlaveTemplate(elem, 4, 5)
        self.assertEqual(slave.apply(master), False)

        # Construct a slave template with matching version range
        slave = xmlutil.SlaveTemplate(elem, 3, 3)
        self.assertEqual(slave.apply(master), True)

    def test__serialize(self):
        # Our test object to serialize
        obj = {
            'test': {
                'name': 'foobar',
                'values': [1, 2, 3, 4],
                'attrs': {
                    'a': 1,
                    'b': 2,
                    'c': 3,
                    'd': 4,
                    },
                'image': {
                    'name': 'image_foobar',
                    'id': 42,
                    },
                },
            }

        # Set up our master template
        root = xmlutil.TemplateElement('test', selector='test',
                                       name='name')
        value = xmlutil.SubTemplateElement(root, 'value', selector='values')
        value.text = xmlutil.Selector()
        attrs = xmlutil.SubTemplateElement(root, 'attrs', selector='attrs')
        xmlutil.SubTemplateElement(attrs, 'attr', selector=xmlutil.get_items,
                                   key=0, value=1)
        master = xmlutil.MasterTemplate(root, 1, nsmap=dict(f='foo'))

        # Set up our slave template
        root_slave = xmlutil.TemplateElement('test', selector='test')
        image = xmlutil.SubTemplateElement(root_slave, 'image',
                                           selector='image', id='id')
        image.text = xmlutil.Selector('name')
        slave = xmlutil.SlaveTemplate(root_slave, 1, nsmap=dict(b='bar'))

        # Attach the slave to the master...
        master.attach(slave)

        # Try serializing our object
        siblings = master._siblings()
        nsmap = master._nsmap()
        result = master._serialize(None, obj, siblings, nsmap)

        # Now we get to manually walk the element tree...
        self.assertEqual(result.tag, 'test')
        self.assertEqual(len(result.nsmap), 2)
        self.assertEqual(result.nsmap['f'], 'foo')
        self.assertEqual(result.nsmap['b'], 'bar')
        self.assertEqual(result.get('name'), obj['test']['name'])
        for idx, val in enumerate(obj['test']['values']):
            self.assertEqual(result[idx].tag, 'value')
            self.assertEqual(result[idx].text, str(val))
        idx += 1
        self.assertEqual(result[idx].tag, 'attrs')
        for attr in result[idx]:
            self.assertEqual(attr.tag, 'attr')
            self.assertEqual(attr.get('value'),
                             str(obj['test']['attrs'][attr.get('key')]))
        idx += 1
        self.assertEqual(result[idx].tag, 'image')
        self.assertEqual(result[idx].get('id'),
                         str(obj['test']['image']['id']))
        self.assertEqual(result[idx].text, obj['test']['image']['name'])

        templ = xmlutil.Template(None)
        self.assertEqual(templ.serialize(None), '')

    def test_serialize_with_colon_tagname_support(self):
        # Our test object to serialize
        obj = {'extra_specs': {'foo:bar': '999'}}
        expected_xml = (("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<extra_specs><foo:bar xmlns:foo="foo">999</foo:bar>'
                    '</extra_specs>'))
        # Set up our master template
        root = xmlutil.TemplateElement('extra_specs', selector='extra_specs',
                                       colon_ns=True)
        value = xmlutil.SubTemplateElement(root, 'foo:bar', selector='foo:bar',
                                           colon_ns=True)
        value.text = xmlutil.Selector()
        master = xmlutil.MasterTemplate(root, 1)
        result = master.serialize(obj)
        self.assertEqual(expected_xml, result)


class MasterTemplateBuilder(xmlutil.TemplateBuilder):
    def construct(self):
        elem = xmlutil.TemplateElement('test')
        return xmlutil.MasterTemplate(elem, 1)


class SlaveTemplateBuilder(xmlutil.TemplateBuilder):
    def construct(self):
        elem = xmlutil.TemplateElement('test')
        return xmlutil.SlaveTemplate(elem, 1)


class TemplateBuilderTest(test.NoDBTestCase):
    def test_master_template_builder(self):
        # Make sure the template hasn't been built yet
        self.assertEqual(MasterTemplateBuilder._tmpl, None)

        # Now, construct the template
        tmpl1 = MasterTemplateBuilder()

        # Make sure that there is a template cached...
        self.assertNotEqual(MasterTemplateBuilder._tmpl, None)

        # Make sure it wasn't what was returned...
        self.assertNotEqual(MasterTemplateBuilder._tmpl, tmpl1)

        # Make sure it doesn't get rebuilt
        cached = MasterTemplateBuilder._tmpl
        tmpl2 = MasterTemplateBuilder()
        self.assertEqual(MasterTemplateBuilder._tmpl, cached)

        # Make sure we're always getting fresh copies
        self.assertNotEqual(tmpl1, tmpl2)

        # Make sure we can override the copying behavior
        tmpl3 = MasterTemplateBuilder(False)
        self.assertEqual(MasterTemplateBuilder._tmpl, tmpl3)

    def test_slave_template_builder(self):
        # Make sure the template hasn't been built yet
        self.assertEqual(SlaveTemplateBuilder._tmpl, None)

        # Now, construct the template
        tmpl1 = SlaveTemplateBuilder()

        # Make sure there is a template cached...
        self.assertNotEqual(SlaveTemplateBuilder._tmpl, None)

        # Make sure it was what was returned...
        self.assertEqual(SlaveTemplateBuilder._tmpl, tmpl1)

        # Make sure it doesn't get rebuilt
        tmpl2 = SlaveTemplateBuilder()
        self.assertEqual(SlaveTemplateBuilder._tmpl, tmpl1)

        # Make sure we're always getting the cached copy
        self.assertEqual(tmpl1, tmpl2)


class MiscellaneousXMLUtilTests(test.NoDBTestCase):
    def test_validate_schema(self):
        xml = '''<?xml version='1.0' encoding='UTF-8'?>
<metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
<meta key="key6">value6</meta><meta key="key4">value4</meta>
</metadata>
'''
        xmlutil.validate_schema(xml, 'metadata')
        # No way to test the return value of validate_schema.
        # It just raises an exception when something is wrong.
        self.assertTrue(True)

    def test_make_links(self):
        elem = xmlutil.TemplateElement('image', selector='image')
        self.assertTrue(repr(xmlutil.make_links(elem, 'links')))

    def test_make_flat_dict(self):
        expected_xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                        '<wrapper><a>foo</a><b>bar</b></wrapper>')
        root = xmlutil.make_flat_dict('wrapper')
        tmpl = xmlutil.MasterTemplate(root, 1)
        result = tmpl.serialize(dict(wrapper=dict(a='foo', b='bar')))
        self.assertEqual(result, expected_xml)

        expected_xml = ("<?xml version='1.0' encoding='UTF-8'?>\n"
'<ns0:wrapper xmlns:ns0="ns"><ns0:a>foo</ns0:a><ns0:b>bar</ns0:b>'
"</ns0:wrapper>")
        root = xmlutil.make_flat_dict('wrapper', ns='ns')
        tmpl = xmlutil.MasterTemplate(root, 1)
        result = tmpl.serialize(dict(wrapper=dict(a='foo', b='bar')))
        self.assertEqual(result, expected_xml)

    def test_make_flat_dict_with_colon_tagname_support(self):
        # Our test object to serialize
        obj = {'extra_specs': {'foo:bar': '999'}}
        expected_xml = (("<?xml version='1.0' encoding='UTF-8'?>\n"
                    '<extra_specs><foo:bar xmlns:foo="foo">999</foo:bar>'
                    '</extra_specs>'))
        # Set up our master template
        root = xmlutil.make_flat_dict('extra_specs', colon_ns=True)
        master = xmlutil.MasterTemplate(root, 1)
        result = master.serialize(obj)
        self.assertEqual(expected_xml, result)

    def test_safe_parse_xml(self):

        normal_body = ('<?xml version="1.0" ?>'
                       '<foo><bar><v1>hey</v1><v2>there</v2></bar></foo>')

        dom = xmlutil.safe_minidom_parse_string(normal_body)
        # Some versions of minidom inject extra newlines so we ignore them
        result = str(dom.toxml()).replace('\n', '')
        self.assertEqual(normal_body, result)

        self.assertRaises(exception.MalformedRequestBody,
                          xmlutil.safe_minidom_parse_string,
                          tests_utils.killer_xml_body())


class SafeParserTestCase(test.NoDBTestCase):
    def test_external_dtd(self):
        xml_string = ("""<?xml version="1.0" encoding="utf-8"?>
                <!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN"
                 "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
                <html>
                   <head/>
                     <body>html with dtd</body>
                   </html>""")

        parser = xmlutil.ProtectedExpatParser(forbid_dtd=False,
                                            forbid_entities=True)
        self.assertRaises(ValueError,
                          minidom.parseString,
                          xml_string, parser)

    def test_external_file(self):
        xml_string = """<!DOCTYPE external [
                <!ENTITY ee SYSTEM "file:///PATH/TO/root.xml">
                ]>
                <root>&ee;</root>"""

        parser = xmlutil.ProtectedExpatParser(forbid_dtd=False,
                                            forbid_entities=True)
        self.assertRaises(ValueError,
                          minidom.parseString,
                          xml_string, parser)

    def test_notation(self):
        xml_string = """<?xml version="1.0" standalone="no"?>
                        <!-- comment data -->
                        <!DOCTYPE x [
                        <!NOTATION notation SYSTEM "notation.jpeg">
                        ]>
                        <root attr1="value1">
                        </root>"""

        parser = xmlutil.ProtectedExpatParser(forbid_dtd=False,
                                            forbid_entities=True)
        self.assertRaises(ValueError,
                          minidom.parseString,
                          xml_string, parser)
