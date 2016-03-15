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
    title='Cinder Options')

cinder_opts = [
    cfg.StrOpt('catalog_info',
            default='volumev2:cinderv2:publicURL',
            help='Info to match when looking for cinder in the service '
                 'catalog. Format is: separated values of the form: '
                 '<service_type>:<service_name>:<endpoint_type>'),
    cfg.StrOpt('endpoint_template',
               help='Override service catalog lookup with template for cinder '
                    'endpoint e.g. http://localhost:8776/v1/%(project_id)s'),
    cfg.StrOpt('os_region_name',
               help='Region name of this node'),
    cfg.IntOpt('http_retries',
               default=3,
               help='Number of cinderclient retries on failed http calls'),
    cfg.BoolOpt('cross_az_attach',
                default=True,
                help='Allow attach between instance and volume in different '
                     'availability zones. If False, volumes attached to an '
                     'instance must be in the same availability zone in '
                     'Cinder as the instance availability zone in Nova. '
                     'This also means care should be taken when booting an '
                     'instance from a volume where source is not "volume" '
                     'because Nova will attempt to create a volume using '
                     'the same availability zone as what is assigned to the '
                     'instance. If that AZ is not in Cinder (or '
                     'allow_availability_zone_fallback=False in cinder.conf), '
                     'the volume create request will fail and the instance '
                     'will fail the build request.'),
]

deprecated = {'timeout': [cfg.DeprecatedOpt('http_timeout',
                                            group=cinder_group.name)],
              'cafile': [cfg.DeprecatedOpt('ca_certificates_file',
                                           group=cinder_group.name)],
              'insecure': [cfg.DeprecatedOpt('api_insecure',
                                             group=cinder_group.name)]}


def register_opts(conf):
    conf.register_group(cinder_group)
    conf.register_opts(cinder_opts, group=cinder_group)
    ks_loading.register_session_conf_options(conf,
                                             cinder_group.name,
                                             deprecated_opts=deprecated)


def list_opts():
    return {
        cinder_group.name: cinder_opts
    }
