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

from castellan import options as castellan_opts
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

# All barbican related code and options have been moved to
# a separate library the Castellan. Deprecating these option for
# Newton. These will be deleted post Newton

barbican_group = cfg.OptGroup(
    "barbican",
    title="Barbican options")

barbican_opts = [
     cfg.StrOpt("catalog_info",
                default="key-manager:barbican:public",
                deprecated_for_removal=True,
                deprecated_reason="This option have been moved to the "
                                  "Castellan library",
                help="""
Info to match when looking for barbican in the service
catalog. Format is: separated values of the form:
<service_type>:<service_name>:<endpoint_type>
"""),
    cfg.StrOpt("endpoint_template",
               deprecated_for_removal=True,
               deprecated_reason="This option have been moved to the "
                                 "Castellan library",
               help="""
Override service catalog lookup with template for
barbican endpoint e.g.
http://localhost:9311/v1/%(project_id)s
"""),
    cfg.StrOpt("os_region_name",
               deprecated_for_removal=True,
               deprecated_reason="This option have been moved to the "
                                 "Castellan library",
               help="""
Region name of this node
"""),
]


def register_opts(conf):
    castellan_opts.set_defaults(conf)
    # TODO(raj_singh): Code block below is deprecated and will be removed
    # post Newton
    conf.register_group(barbican_group)
    conf.register_opts(barbican_opts, group=barbican_group)
    ks_loading.register_session_conf_options(conf, barbican_group.name)


def list_opts():
    # Castellan library also has a group name barbican. So if we append
    # list returned from barbican to this list, oslo will remove one group as
    # duplicate and only one group (either from this file or Castellan library)
    # will show up.
    # So fix is to merge options of this file to "barbican" group returned from
    # Castellan
    opts = {barbican_group.name: barbican_opts}
    for group, options in castellan_opts.list_opts():
        if group not in opts.keys():
            opts[group] = options
        else:
            opts[group] = opts[group] + options
    return opts
    # TODO(raj_singh): Post Newton delete code block from above and comment in
    # line below. Castellan already returned a list which can be returned
    # directly from list_opts()
    # return castellan_opts.list_opts()
