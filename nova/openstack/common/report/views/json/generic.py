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

"""Provides generic JSON views

This modules defines several basic views for serializing
data to JSON.  Submodels that have already been serialized
as JSON may have their string values marked with `__is_json__
= True` using :class:`openstack.common.report.utils.StringWithAttrs`
(each of the classes within this module does this automatically,
and non-naive serializers check for this attribute and handle
such strings specially)
"""

import copy

from oslo.serialization import jsonutils as json

from nova.openstack.common.report import utils as utils


class BasicKeyValueView(object):
    """A Basic Key-Value JSON View

    This view performs a naive serialization of a model
    into JSON by simply calling :func:`json.dumps` on the model
    """

    def __call__(self, model):
        res = utils.StringWithAttrs(json.dumps(model.data))
        res.__is_json__ = True
        return res


class KeyValueView(object):
    """A Key-Value JSON View

    This view performs advanced serialization to a model
    into JSON.  It does so by first checking all values to
    see if they are marked as JSON.  If so, they are deserialized
    using :func:`json.loads`.  Then, the copy of the model with all
    JSON deserialized is reserialized into proper nested JSON using
    :func:`json.dumps`.
    """

    def __call__(self, model):
        # this part deals with subviews that were already serialized
        cpy = copy.deepcopy(model)
        for key in model.keys():
            if getattr(model[key], '__is_json__', False):
                cpy[key] = json.loads(model[key])

        res = utils.StringWithAttrs(json.dumps(cpy.data, sort_keys=True))
        res.__is_json__ = True
        return res
