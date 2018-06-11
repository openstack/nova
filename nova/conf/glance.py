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

from nova.conf import utils as confutils


DEFAULT_SERVICE_TYPE = 'image'

glance_group = cfg.OptGroup(
    'glance',
    title='Glance Options',
    help='Configuration options for the Image service')

glance_opts = [
    # NOTE(sdague/efried): there is intentionally no default here. This
    # requires configuration if ksa adapter config is not used.
    cfg.ListOpt('api_servers',
        deprecated_for_removal=True,
        deprecated_since='21.0.0',
        deprecated_reason="""
Support for image service configuration via standard keystoneauth1 Adapter
options was added in the 17.0.0 Queens release. The api_servers option was
retained temporarily to allow consumers time to cut over to a real load
balancing solution.
""",
        help="""
List of glance api servers endpoints available to nova.

https is used for ssl-based glance api servers.

NOTE: The preferred mechanism for endpoint discovery is via keystoneauth1
loading options. Only use api_servers if you need multiple endpoints and are
unable to use a load balancer for some reason.

Possible values:

* A list of any fully qualified url of the form "scheme://hostname:port[/path]"
  (i.e. "http://10.0.1.0:9292" or "https://my.glance.server/image").
"""),
    cfg.IntOpt('num_retries',
        default=3,
        min=0,
        help="""
Enable glance operation retries.

Specifies the number of retries when uploading / downloading
an image to / from glance. 0 means no retries.
"""),
    cfg.ListOpt('allowed_direct_url_schemes',
        default=[],
        deprecated_for_removal=True,
        deprecated_since='17.0.0',
        deprecated_reason="""
This was originally added for the 'nova.image.download.file' FileTransfer
extension which was removed in the 16.0.0 Pike release. The
'nova.image.download.modules' extension point is not maintained
and there is no indication of its use in production clouds.
""",
        help="""
List of url schemes that can be directly accessed.

This option specifies a list of url schemes that can be downloaded
directly via the direct_url. This direct_URL can be fetched from
Image metadata which can be used by nova to get the
image more efficiently. nova-compute could benefit from this by
invoking a copy when it has access to the same file system as glance.

Possible values:

* [file], Empty list (default)
"""),
    cfg.BoolOpt('verify_glance_signatures',
        default=False,
        help="""
Enable image signature verification.

nova uses the image signature metadata from glance and verifies the signature
of a signed image while downloading that image. If the image signature cannot
be verified or if the image signature metadata is either incomplete or
unavailable, then nova will not boot the image and instead will place the
instance into an error state. This provides end users with stronger assurances
of the integrity of the image data they are using to create servers.

Related options:

* The options in the `key_manager` group, as the key_manager is used
  for the signature validation.
* Both enable_certificate_validation and default_trusted_certificate_ids
  below depend on this option being enabled.
"""),
    cfg.BoolOpt('enable_certificate_validation',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='16.0.0',
        deprecated_reason="""
This option is intended to ease the transition for deployments leveraging
image signature verification. The intended state long-term is for signature
verification and certificate validation to always happen together.
""",
        help="""
Enable certificate validation for image signature verification.

During image signature verification nova will first verify the validity of the
image's signing certificate using the set of trusted certificates associated
with the instance. If certificate validation fails, signature verification
will not be performed and the instance will be placed into an error state. This
provides end users with stronger assurances that the image data is unmodified
and trustworthy. If left disabled, image signature verification can still
occur but the end user will not have any assurance that the signing
certificate used to generate the image signature is still trustworthy.

Related options:

* This option only takes effect if verify_glance_signatures is enabled.
* The value of default_trusted_certificate_ids may be used when this option
  is enabled.
"""),
    cfg.ListOpt('default_trusted_certificate_ids',
        default=[],
        help="""
List of certificate IDs for certificates that should be trusted.

May be used as a default list of trusted certificate IDs for certificate
validation. The value of this option will be ignored if the user provides a
list of trusted certificate IDs with an instance API request. The value of
this option will be persisted with the instance data if signature verification
and certificate validation are enabled and if the user did not provide an
alternative list. If left empty when certificate validation is enabled the
user must provide a list of trusted certificate IDs otherwise certificate
validation will fail.

Related options:

* The value of this option may be used if both verify_glance_signatures and
  enable_certificate_validation are enabled.
"""),
    cfg.BoolOpt('enable_rbd_download',
        default=False,
        help="""
Enable download of Glance images directly via RBD.

Allow compute hosts to quickly download and cache images localy directly
from Ceph rather than slow dowloads from the Glance API. This can
reduce download time for images in the ten to hundreds of GBs from tens of
minutes to tens of seconds, but requires a Ceph-based deployment and access
from the compute nodes to Ceph.

Related options:

* ``[glance] rbd_user``
* ``[glance] rbd_connect_timeout``
* ``[glance] rbd_pool``
* ``[glance] rbd_ceph_conf``
"""),
    cfg.StrOpt('rbd_user',
        default='',
        help="""
The RADOS client name for accessing Glance images stored as rbd volumes.

Related options:

* This option is only used if ``[glance] enable_rbd_download`` is set to True.
"""),
    cfg.IntOpt('rbd_connect_timeout',
        default=5,
        help="""
The RADOS client timeout in seconds when initially connecting to the cluster.

Related options:

* This option is only used if ``[glance] enable_rbd_download`` is set to True.
"""),
    cfg.StrOpt('rbd_pool',
        default='',
        help="""
The RADOS pool in which the Glance images are stored as rbd volumes.

Related options:

* This option is only used if ``[glance] enable_rbd_download`` is set to True.
"""),
    cfg.StrOpt('rbd_ceph_conf',
        default='',
        help="""
Path to the ceph configuration file to use.

Related options:

* This option is only used if ``[glance] enable_rbd_download`` is set to True.
"""),

    cfg.BoolOpt('debug',
        default=False,
        help='Enable or disable debug logging with glanceclient.')
]

deprecated_ksa_opts = {
    'insecure': [cfg.DeprecatedOpt('api_insecure', group=glance_group.name)],
    'cafile': [cfg.DeprecatedOpt('ca_file', group="ssl")],
    'certfile': [cfg.DeprecatedOpt('cert_file', group="ssl")],
    'keyfile': [cfg.DeprecatedOpt('key_file', group="ssl")],
}


def register_opts(conf):
    conf.register_group(glance_group)
    conf.register_opts(glance_opts, group=glance_group)

    confutils.register_ksa_opts(
        conf, glance_group, DEFAULT_SERVICE_TYPE, include_auth=False,
        deprecated_opts=deprecated_ksa_opts)


def list_opts():
    return {glance_group: (
        glance_opts +
        ks_loading.get_session_conf_options() +
        confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE,
                                       deprecated_opts=deprecated_ksa_opts))
    }
