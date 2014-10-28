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

"""Provides OpenStack Configuration Model

This module defines a class representing the data
model for :mod:`oslo.config` configuration options
"""

from nova.openstack.common.report.models import with_default_views as mwdv
from nova.openstack.common.report.views.text import generic as generic_text_views


class ConfigModel(mwdv.ModelWithDefaultViews):
    """A Configuration Options Model

    This model holds data about a set of configuration options
    from :mod:`oslo.config`.  It supports both the default group
    of options and named option groups.

    :param conf_obj: a configuration object
    :type conf_obj: :class:`oslo.config.cfg.ConfigOpts`
    """

    def __init__(self, conf_obj):
        kv_view = generic_text_views.KeyValueView(dict_sep=": ",
                                                  before_dict='')
        super(ConfigModel, self).__init__(text_view=kv_view)

        def opt_title(optname, co):
            return co._opts[optname]['opt'].name

        def opt_value(opt_obj, value):
            if opt_obj['opt'].secret:
                return '*******'
            else:
                return value

        self['default'] = dict(
            (opt_title(optname, conf_obj),
             opt_value(conf_obj._opts[optname], conf_obj[optname]))
            for optname in conf_obj._opts
        )

        groups = {}
        for groupname in conf_obj._groups:
            group_obj = conf_obj._groups[groupname]
            curr_group_opts = dict(
                (opt_title(optname, group_obj),
                 opt_value(group_obj._opts[optname],
                           conf_obj[groupname][optname]))
                for optname in group_obj._opts)
            groups[group_obj.name] = curr_group_opts

        self.update(groups)
