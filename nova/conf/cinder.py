# Copyright (c) 2016 OpenStack Foundation
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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

cinder_group = cfg.OptGroup(
    'cinder',
    title='Cinder Options',
    help="Configuration options for the block storage")

cinder_opts = [
    cfg.StrOpt('catalog_info',
            default='volumev3::publicURL',
            regex=r'^\w+:\w*:.*$',
            help="""
Info to match when looking for cinder in the service catalog.

The ``<service_name>`` is optional and omitted by default since it should
not be necessary in most deployments.

Possible values:

* Format is separated values of the form:
  <service_type>:<service_name>:<endpoint_type>

Note: Nova does not support the Cinder v2 API since the Nova 17.0.0 Queens
release.

Related options:

* endpoint_template - Setting this option will override catalog_info
"""),
    cfg.StrOpt('endpoint_template',
               help="""
If this option is set then it will override service catalog lookup with
this template for cinder endpoint

Possible values:

* URL for cinder endpoint API
  e.g. http://localhost:8776/v3/%(project_id)s

Note: Nova does not support the Cinder v2 API since the Nova 17.0.0 Queens
release.

Related options:

* catalog_info - If endpoint_template is not set, catalog_info will be used.
"""),
    cfg.StrOpt('os_region_name',
               help="""
Region name of this node. This is used when picking the URL in the service
catalog.

Possible values:

* Any string representing region name
"""),
    cfg.IntOpt('http_retries',
               default=3,
               min=0,
               help="""
Number of times cinderclient should retry on any failed http call.
0 means connection is attempted only once. Setting it to any positive integer
means that on failure connection is retried that many times e.g. setting it
to 3 means total attempts to connect will be 4.

Possible values:

* Any integer value. 0 means connection is attempted only once
"""),
    cfg.BoolOpt('cross_az_attach',
                default=True,
                help="""
Allow attach between instance and volume in different availability zones.

If False, volumes attached to an instance must be in the same availability
zone in Cinder as the instance availability zone in Nova.

This also means care should be taken when booting an instance from a volume
where source is not "volume" because Nova will attempt to create a volume using
the same availability zone as what is assigned to the instance.

If that AZ is not in Cinder (or ``allow_availability_zone_fallback=False`` in
cinder.conf), the volume create request will fail and the instance will fail
the build request.

By default there is no availability zone restriction on volume attach.

Related options:

* ``[DEFAULT]/default_schedule_zone``
"""),
]


def register_opts(conf):
    conf.register_group(cinder_group)
    conf.register_opts(cinder_opts, group=cinder_group)
    ks_loading.register_session_conf_options(conf,
                                             cinder_group.name)
    ks_loading.register_auth_conf_options(conf, cinder_group.name)


def list_opts():
    return {
        cinder_group.name: (
            cinder_opts +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password'))
    }
