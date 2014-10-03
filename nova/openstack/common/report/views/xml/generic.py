# Copyright 2013 Red Hat, Inc.
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

"""Provides generic XML views

This modules defines several basic views for serializing
data to XML.  Submodels that have already been serialized
as XML may have their string values marked with `__is_xml__
= True` using :class:`openstack.common.report.utils.StringWithAttrs`
(each of the classes within this module does this automatically,
and non-naive serializers check for this attribute and handle
such strings specially)
"""

import collections as col
import copy
import xml.etree.ElementTree as ET

import six

from nova.openstack.common.report import utils as utils


class KeyValueView(object):
    """A Key-Value XML View

    This view performs advanced serialization of a data model
    into XML.  It first deserializes any values marked as XML so
    that they can be properly reserialized later.  It then follows
    the following rules to perform serialization:

    key : text/xml
        The tag name is the key name, and the contents are the text or xml
    key : Sequence
        A wrapper tag is created with the key name, and each item is placed
        in an 'item' tag
    key : Mapping
        A wrapper tag is created with the key name, and the serialize is called
        on each key-value pair (such that each key gets its own tag)

    :param str wrapper_name: the name of the top-level element
    """

    def __init__(self, wrapper_name="model"):
        self.wrapper_name = wrapper_name

    def __call__(self, model):
        # this part deals with subviews that were already serialized
        cpy = copy.deepcopy(model)
        for key, valstr in model.items():
            if getattr(valstr, '__is_xml__', False):
                cpy[key] = ET.fromstring(valstr)

        def serialize(rootmodel, rootkeyname):
            res = ET.Element(rootkeyname)

            if isinstance(rootmodel, col.Mapping):
                for key in sorted(rootmodel):
                    res.append(serialize(rootmodel[key], key))
            elif (isinstance(rootmodel, col.Sequence)
                    and not isinstance(rootmodel, six.string_types)):
                for val in sorted(rootmodel, key=str):
                    res.append(serialize(val, 'item'))
            elif ET.iselement(rootmodel):
                res.append(rootmodel)
            else:
                res.text = str(rootmodel)

            return res

        str_ = ET.tostring(serialize(cpy,
                                     self.wrapper_name),
                           encoding="utf-8").decode("utf-8")
        res = utils.StringWithAttrs(str_)
        res.__is_xml__ = True
        return res
