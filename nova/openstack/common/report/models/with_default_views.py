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

import copy

from nova.openstack.common.report.models import base as base_model
from nova.openstack.common.report.views.json import generic as jsonviews
from nova.openstack.common.report.views.text import generic as textviews
from nova.openstack.common.report.views.xml import generic as xmlviews


class ModelWithDefaultViews(base_model.ReportModel):
    """A Model With Default Views of Various Types

    A model with default views has several predefined views,
    each associated with a given type.  This is often used for
    when a submodel should have an attached view, but the view
    differs depending on the serialization format

    Parameters are as the superclass, except for any
    parameters ending in '_view': these parameters
    get stored as default views.

    The default 'default views' are

    text
        :class:`openstack.common.report.views.text.generic.KeyValueView`
    xml
        :class:`openstack.common.report.views.xml.generic.KeyValueView`
    json
        :class:`openstack.common.report.views.json.generic.KeyValueView`

    .. function:: to_type()

       ('type' is one of the 'default views' defined for this model)
       Serializes this model using the default view for 'type'

       :rtype: str
       :returns: this model serialized as 'type'
    """

    def __init__(self, *args, **kwargs):
        self.views = {
            'text': textviews.KeyValueView(),
            'json': jsonviews.KeyValueView(),
            'xml': xmlviews.KeyValueView()
        }

        newargs = copy.copy(kwargs)
        for k in kwargs:
            if k.endswith('_view'):
                self.views[k[:-5]] = kwargs[k]
                del newargs[k]
        super(ModelWithDefaultViews, self).__init__(*args, **newargs)

    def set_current_view_type(self, tp):
        self.attached_view = self.views[tp]
        super(ModelWithDefaultViews, self).set_current_view_type(tp)

    def __getattr__(self, attrname):
        if attrname[:3] == 'to_':
            if self.views[attrname[3:]] is not None:
                return lambda: self.views[attrname[3:]](self)
            else:
                raise NotImplementedError((
                    "Model {cn.__module__}.{cn.__name__} does not have" +
                    " a default view for "
                    "{tp}").format(cn=type(self), tp=attrname[3:]))
        else:
            return super(ModelWithDefaultViews, self).__getattr__(attrname)
