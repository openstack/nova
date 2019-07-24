# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg

upgrade_group = cfg.OptGroup('upgrade_levels',
        title='Upgrade levels Options',
        help="""
upgrade_levels options are used to set version cap for RPC
messages sent between different nova services.

By default all services send messages using the latest version
they know about.

The compute upgrade level is an important part of rolling upgrades
where old and new nova-compute services run side by side.

The other options can largely be ignored, and are only kept to
help with a possible future backport issue.
""")

# TODO(sneti): Add default=auto for compute
upgrade_levels_opts = [
    cfg.StrOpt('compute',
        help="""
Compute RPC API version cap.

By default, we always send messages using the most recent version
the client knows about.

Where you have old and new compute services running, you should set
this to the lowest deployed version. This is to guarantee that all
services never send messages that one of the compute nodes can't
understand. Note that we only support upgrading from release N to
release N+1.

Set this option to "auto" if you want to let the compute RPC module
automatically determine what version to use based on the service
versions in the deployment.

Possible values:

* By default send the latest version the client knows about
* 'auto': Automatically determines what version to use based on
  the service versions in the deployment.
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt("cert",
        deprecated_for_removal=True,
        deprecated_since='18.0.0',
        deprecated_reason="""
The nova-cert service was removed in 16.0.0 (Pike) so this option
is no longer used.
""",
        help="""
Cert RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt("scheduler",
        help="""
Scheduler RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt('conductor',
        help="""
Conductor RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt('console',
        help="""
Console RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt('network',
        deprecated_for_removal=True,
        deprecated_since='18.0.0',
        deprecated_reason="""
The nova-network service was deprecated in 14.0.0 (Newton) and will be
removed in an upcoming release.
""",
        help="""
Network RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
"""),
    cfg.StrOpt('baseapi',
        help="""
Base API RPC API version cap.

Possible values:

* By default send the latest version the client knows about
* A string representing a version number in the format 'N.N';
  for example, possible values might be '1.12' or '2.0'.
* An OpenStack release name, in lower case, such as 'mitaka' or
  'liberty'.
""")
]


def register_opts(conf):
    conf.register_group(upgrade_group)
    conf.register_opts(upgrade_levels_opts, group=upgrade_group)


def list_opts():
    return {upgrade_group: upgrade_levels_opts}
