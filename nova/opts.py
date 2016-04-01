# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools

import nova.baserpc
import nova.cloudpipe.pipelib
import nova.cmd.novnc
import nova.cmd.serialproxy
import nova.cmd.spicehtml5proxy
import nova.conductor.rpcapi
import nova.conductor.tasks.live_migrate
import nova.conf
import nova.console.manager
import nova.console.rpcapi
import nova.console.serial
import nova.console.xvp
import nova.consoleauth
import nova.consoleauth.manager
import nova.consoleauth.rpcapi
import nova.crypto
import nova.db.api
import nova.db.base
import nova.db.sqlalchemy.api
import nova.exception
import nova.image.download.file
import nova.ipv6.api
import nova.netconf
import nova.notifications
import nova.objects.network
import nova.paths
import nova.quota
import nova.service
import nova.servicegroup.api
import nova.spice
import nova.utils
import nova.volume
import nova.volume.cinder


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.conductor.tasks.live_migrate.migrate_opt],
             [nova.consoleauth.consoleauth_topic_opt],
             [nova.db.base.db_driver_opt],
             [nova.ipv6.api.ipv6_backend_opt],
             [nova.servicegroup.api.servicegroup_driver_opt],
             nova.cloudpipe.pipelib.cloudpipe_opts,
             nova.cmd.novnc.opts,
             nova.console.manager.console_manager_opts,
             nova.console.rpcapi.rpcapi_opts,
             nova.console.xvp.xvp_opts,
             nova.consoleauth.manager.consoleauth_opts,
             nova.crypto.crypto_opts,
             nova.db.api.db_opts,
             nova.db.sqlalchemy.api.db_opts,
             nova.exception.exc_log_opts,
             nova.netconf.netconf_opts,
             nova.notifications.notify_opts,
             nova.objects.network.network_opts,
             nova.paths.path_opts,
             nova.quota.quota_opts,
             nova.service.service_opts,
             nova.utils.monkey_patch_opts,
             nova.utils.utils_opts,
             nova.volume._volume_opts,
         )),
        ('cinder', nova.volume.cinder.cinder_opts),
        ('api_database', nova.db.sqlalchemy.api.api_db_opts),
        ('database', nova.db.sqlalchemy.api.oslo_db_options.database_opts),
        ('image_file_url', [nova.image.download.file.opt_group]),
        ('spice',
         itertools.chain(
             nova.cmd.spicehtml5proxy.opts,
             nova.spice.spice_opts,
         )),
        ('upgrade_levels',
         itertools.chain(
             [nova.baserpc.rpcapi_cap_opt],
             [nova.conductor.rpcapi.rpcapi_cap_opt],
             [nova.console.rpcapi.rpcapi_cap_opt],
             [nova.consoleauth.rpcapi.rpcapi_cap_opt],
         )),
        ('workarounds', nova.utils.workarounds_opts),
    ]
