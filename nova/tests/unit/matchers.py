# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2012 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Matcher classes to be used inside of the testtools assertThat framework."""

import pprint

from lxml import etree
from testtools import content


class DictKeysMismatch(object):
    def __init__(self, d1only, d2only):
        self.d1only = d1only
        self.d2only = d2only

    def describe(self):
        return ('Keys in d1 and not d2: %(d1only)s.'
                ' Keys in d2 and not d1: %(d2only)s' %
                {'d1only': self.d1only, 'd2only': self.d2only})

    def get_details(self):
        return {}


class DictMismatch(object):
    def __init__(self, key, d1_value, d2_value):
        self.key = key
        self.d1_value = d1_value
        self.d2_value = d2_value

    def describe(self):
        return ("Dictionaries do not match at %(key)s."
                " d1: %(d1_value)s d2: %(d2_value)s" %
                {'key': self.key, 'd1_value': self.d1_value,
                 'd2_value': self.d2_value})

    def get_details(self):
        return {}


class DictMatches(object):

    def __init__(self, d1, approx_equal=False, tolerance=0.001):
        self.d1 = d1
        self.approx_equal = approx_equal
        self.tolerance = tolerance

    def __str__(self):
        return 'DictMatches(%s)' % (pprint.pformat(self.d1))

    # Useful assertions
    def match(self, d2):
        """Assert two dicts are equivalent.

        This is a 'deep' match in the sense that it handles nested
        dictionaries appropriately.

        NOTE:

            If you don't care (or don't know) a given value, you can specify
            the string DONTCARE as the value. This will cause that dict-item
            to be skipped.

        """

        d1keys = set(self.d1.keys())
        d2keys = set(d2.keys())
        if d1keys != d2keys:
            d1only = d1keys - d2keys
            d2only = d2keys - d1keys
            return DictKeysMismatch(d1only, d2only)

        for key in d1keys:
            d1value = self.d1[key]
            d2value = d2[key]
            try:
                error = abs(float(d1value) - float(d2value))
                within_tolerance = error <= self.tolerance
            except (ValueError, TypeError):
                # If both values aren't convertible to float, just ignore
                # ValueError if arg is a str, TypeError if it's something else
                # (like None)
                within_tolerance = False

            if hasattr(d1value, 'keys') and hasattr(d2value, 'keys'):
                matcher = DictMatches(d1value)
                did_match = matcher.match(d2value)
                if did_match is not None:
                    return did_match
            elif 'DONTCARE' in (d1value, d2value):
                continue
            elif self.approx_equal and within_tolerance:
                continue
            elif d1value != d2value:
                return DictMismatch(key, d1value, d2value)


class ListLengthMismatch(object):
    def __init__(self, len1, len2):
        self.len1 = len1
        self.len2 = len2

    def describe(self):
        return ('Length mismatch: len(L1)=%(len1)d != '
                'len(L2)=%(len2)d' % {'len1': self.len1, 'len2': self.len2})

    def get_details(self):
        return {}


class DictListMatches(object):

    def __init__(self, l1, approx_equal=False, tolerance=0.001):
        self.l1 = l1
        self.approx_equal = approx_equal
        self.tolerance = tolerance

    def __str__(self):
        return 'DictListMatches(%s)' % (pprint.pformat(self.l1))

    # Useful assertions
    def match(self, l2):
        """Assert a list of dicts are equivalent."""

        l1count = len(self.l1)
        l2count = len(l2)
        if l1count != l2count:
            return ListLengthMismatch(l1count, l2count)

        for d1, d2 in zip(self.l1, l2):
            matcher = DictMatches(d2,
                                  approx_equal=self.approx_equal,
                                  tolerance=self.tolerance)
            did_match = matcher.match(d1)
            if did_match:
                return did_match


class SubDictMismatch(object):
    def __init__(self,
                 key=None,
                 sub_value=None,
                 super_value=None,
                 keys=False):
        self.key = key
        self.sub_value = sub_value
        self.super_value = super_value
        self.keys = keys

    def describe(self):
        if self.keys:
            return "Keys between dictionaries did not match"
        else:
            return("Dictionaries do not match at %s. d1: %s d2: %s"
                   % (self.key,
                      self.super_value,
                      self.sub_value))

    def get_details(self):
        return {}


class IsSubDictOf(object):

    def __init__(self, super_dict):
        self.super_dict = super_dict

    def __str__(self):
        return 'IsSubDictOf(%s)' % (self.super_dict)

    def match(self, sub_dict):
        """Assert a sub_dict is subset of super_dict."""
        if not set(sub_dict.keys()).issubset(set(self.super_dict.keys())):
            return SubDictMismatch(keys=True)
        for k, sub_value in sub_dict.items():
            super_value = self.super_dict[k]
            if isinstance(sub_value, dict):
                matcher = IsSubDictOf(super_value)
                did_match = matcher.match(sub_value)
                if did_match is not None:
                    return did_match
            elif 'DONTCARE' in (sub_value, super_value):
                continue
            else:
                if sub_value != super_value:
                    return SubDictMismatch(k, sub_value, super_value)


class FunctionCallMatcher(object):

    def __init__(self, expected_func_calls):
        self.expected_func_calls = expected_func_calls
        self.actual_func_calls = []

    def call(self, *args, **kwargs):
        func_call = {'args': args, 'kwargs': kwargs}
        self.actual_func_calls.append(func_call)

    def match(self):
        dict_list_matcher = DictListMatches(self.expected_func_calls)
        return dict_list_matcher.match(self.actual_func_calls)


class XMLMismatch(object):
    """Superclass for XML mismatch."""

    def __init__(self, state):
        self.path = str(state)
        self.expected = state.expected
        self.actual = state.actual

    def describe(self):
        return "%(path)s: XML does not match" % self.path

    def get_details(self):
        return {
            'expected': content.text_content(self.expected),
            'actual': content.text_content(self.actual),
        }


class XMLTagMismatch(XMLMismatch):
    """XML tags don't match."""

    def __init__(self, state, idx, expected_tag, actual_tag):
        super(XMLTagMismatch, self).__init__(state)
        self.idx = idx
        self.expected_tag = expected_tag
        self.actual_tag = actual_tag

    def describe(self):
        return ("%(path)s: XML tag mismatch at index %(idx)d: "
                "expected tag <%(expected_tag)s>; "
                "actual tag <%(actual_tag)s>" %
                {'path': self.path, 'idx': self.idx,
                 'expected_tag': self.expected_tag,
                 'actual_tag': self.actual_tag})


class XMLAttrKeysMismatch(XMLMismatch):
    """XML attribute keys don't match."""

    def __init__(self, state, expected_only, actual_only):
        super(XMLAttrKeysMismatch, self).__init__(state)
        self.expected_only = ', '.join(sorted(expected_only))
        self.actual_only = ', '.join(sorted(actual_only))

    def describe(self):
        return ("%(path)s: XML attributes mismatch: "
                "keys only in expected: %(expected_only)s; "
                "keys only in actual: %(actual_only)s" %
                {'path': self.path, 'expected_only': self.expected_only,
                 'actual_only': self.actual_only})


class XMLAttrValueMismatch(XMLMismatch):
    """XML attribute values don't match."""

    def __init__(self, state, key, expected_value, actual_value):
        super(XMLAttrValueMismatch, self).__init__(state)
        self.key = key
        self.expected_value = expected_value
        self.actual_value = actual_value

    def describe(self):
        return ("%(path)s: XML attribute value mismatch: "
                "expected value of attribute %(key)s: %(expected_value)r; "
                "actual value: %(actual_value)r" %
                {'path': self.path, 'key': self.key,
                 'expected_value': self.expected_value,
                 'actual_value': self.actual_value})


class XMLTextValueMismatch(XMLMismatch):
    """XML text values don't match."""

    def __init__(self, state, expected_text, actual_text):
        super(XMLTextValueMismatch, self).__init__(state)
        self.expected_text = expected_text
        self.actual_text = actual_text

    def describe(self):
        return ("%(path)s: XML text value mismatch: "
                "expected text value: %(expected_text)r; "
                "actual value: %(actual_text)r" %
                {'path': self.path, 'expected_text': self.expected_text,
                 'actual_text': self.actual_text})


class XMLUnexpectedChild(XMLMismatch):
    """Unexpected child present in XML."""

    def __init__(self, state, tag, idx):
        super(XMLUnexpectedChild, self).__init__(state)
        self.tag = tag
        self.idx = idx

    def describe(self):
        return ("%(path)s: XML unexpected child element <%(tag)s> "
                "present at index %(idx)d" %
                {'path': self.path, 'tag': self.tag, 'idx': self.idx})


class XMLExpectedChild(XMLMismatch):
    """Expected child not present in XML."""

    def __init__(self, state, tag, idx):
        super(XMLExpectedChild, self).__init__(state)
        self.tag = tag
        self.idx = idx

    def describe(self):
        return ("%(path)s: XML expected child element <%(tag)s> "
                "not present at index %(idx)d" %
                {'path': self.path, 'tag': self.tag, 'idx': self.idx})


class XMLMatchState(object):
    """Maintain some state for matching.

    Tracks the XML node path and saves the expected and actual full
    XML text, for use by the XMLMismatch subclasses.
    """

    def __init__(self, expected, actual):
        self.path = []
        self.expected = expected
        self.actual = actual

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, exc_tb):
        self.path.pop()
        return False

    def __str__(self):
        return '/' + '/'.join(self.path)

    def node(self, tag, idx):
        """Adds tag and index to the path; they will be popped off when
        the corresponding 'with' statement exits.

        :param tag: The element tag
        :param idx: If not None, the integer index of the element
                    within its parent.  Not included in the path
                    element if None.
        """

        if idx is not None:
            self.path.append("%s[%d]" % (tag, idx))
        else:
            self.path.append(tag)
        return self


class XMLMatches(object):
    """Compare XML strings.  More complete than string comparison."""

    def __init__(self, expected):
        self.expected_xml = expected
        self.expected = etree.fromstring(expected)

    def __str__(self):
        return 'XMLMatches(%r)' % self.expected_xml

    def match(self, actual_xml):
        actual = etree.fromstring(actual_xml)

        state = XMLMatchState(self.expected_xml, actual_xml)
        result = self._compare_node(self.expected, actual, state, None)

        if result is False:
            return XMLMismatch(state)
        elif result is not True:
            return result

    def _compare_node(self, expected, actual, state, idx):
        """Recursively compares nodes within the XML tree."""

        # Start by comparing the tags
        if expected.tag != actual.tag:
            return XMLTagMismatch(state, idx, expected.tag, actual.tag)

        with state.node(expected.tag, idx):
            # Compare the attribute keys
            expected_attrs = set(expected.attrib.keys())
            actual_attrs = set(actual.attrib.keys())
            if expected_attrs != actual_attrs:
                expected_only = expected_attrs - actual_attrs
                actual_only = actual_attrs - expected_attrs
                return XMLAttrKeysMismatch(state, expected_only, actual_only)

            # Compare the attribute values
            for key in expected_attrs:
                expected_value = expected.attrib[key]
                actual_value = actual.attrib[key]

                if 'DONTCARE' in (expected_value, actual_value):
                    continue
                elif expected_value != actual_value:
                    return XMLAttrValueMismatch(state, key, expected_value,
                                                actual_value)

            # Compare the contents of the node
            if len(expected) == 0 and len(actual) == 0:
                # No children, compare text values
                if ('DONTCARE' not in (expected.text, actual.text) and
                        expected.text != actual.text):
                    return XMLTextValueMismatch(state, expected.text,
                                                actual.text)
            else:
                expected_idx = 0
                actual_idx = 0
                while (expected_idx < len(expected) and
                       actual_idx < len(actual)):
                    # Ignore comments and processing instructions
                    # TODO(Vek): may interpret PIs in the future, to
                    # allow for, say, arbitrary ordering of some
                    # elements
                    if (expected[expected_idx].tag in
                            (etree.Comment, etree.ProcessingInstruction)):
                        expected_idx += 1
                        continue

                    # Compare the nodes
                    result = self._compare_node(expected[expected_idx],
                                                actual[actual_idx], state,
                                                actual_idx)
                    if result is not True:
                        return result

                    # Step on to comparing the next nodes...
                    expected_idx += 1
                    actual_idx += 1

                # Make sure we consumed all nodes in actual
                if actual_idx < len(actual):
                    return XMLUnexpectedChild(state, actual[actual_idx].tag,
                                              actual_idx)

                # Make sure we consumed all nodes in expected
                if expected_idx < len(expected):
                    for node in expected[expected_idx:]:
                        if (node.tag in
                                (etree.Comment, etree.ProcessingInstruction)):
                            continue

                        return XMLExpectedChild(state, node.tag, actual_idx)

        # The nodes match
        return True
