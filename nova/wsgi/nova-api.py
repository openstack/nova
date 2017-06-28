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

"""Broken, non-working WSGI script for Nova API that will not work.

#################################
#        DO NOT RUN THIS        #
#################################

This is not experimental, it's BROKEN. It will not work. It is kept
in the tree for gate reasons and will be removed as soon as possible.
There is an updated WSGI application for use under a real http daemon
which does things that this does not, which is actually tested, and
which will be supported. Run this instead:

  nova/api/openstack/compute/wsgi.py

which, when installed, becomes

  $BINDIR/nova-api-wsgi

Post-warning quiz:

Q: Should I run this?

  (a) No
  (b) Heck no
  (c) Definitely not
  (d) All of the above

"""

from oslo_config import cfg
from oslo_log import log as logging
from paste import deploy

from nova import config
from nova import objects
from nova import service  # noqa
from nova import utils

CONF = cfg.CONF

config_files = ['/etc/nova/api-paste.ini', '/etc/nova/nova.conf']
config.parse_args([], default_config_files=config_files)

logging.setup(CONF, "nova")
utils.monkey_patch()
objects.register_all()

conf = config_files[0]
name = "osapi_compute"

options = deploy.appconfig('config:%s' % conf, name=name)

application = deploy.loadapp('config:%s' % conf, name=name)
