# vim: tabstop=4 shiftwidth=4 softtabstop=4

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


class DictKeysMismatch(object):
    def __init__(self, d1only, d2only):
        self.d1only = d1only
        self.d2only = d2only

    def describe(self):
        return ('Keys in d1 and not d2: %(d1only)s.'
                ' Keys in d2 and not d1: %(d2only)s' % self.__dict__)

    def get_details(self):
        return {}


class DictMismatch(object):
    def __init__(self, key, d1_value, d2_value):
        self.key = key
        self.d1_value = d1_value
        self.d2_value = d2_value

    def describe(self):
        return ("Dictionaries do not match at %(key)s."
                " d1: %(d1_value)s d2: %(d2_value)s" % self.__dict__)

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
                'len(L2)=%(len2)d' % self.__dict__)

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
