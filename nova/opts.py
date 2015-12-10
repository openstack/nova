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

import nova.availability_zones
import nova.baserpc
import nova.cert.rpcapi
import nova.cloudpipe.pipelib
import nova.cmd.novnc
import nova.cmd.novncproxy
import nova.cmd.serialproxy
import nova.cmd.spicehtml5proxy
import nova.conductor.api
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
import nova.image.glance
import nova.image.s3
import nova.ipv6.api
import nova.keymgr
import nova.keymgr.barbican
import nova.keymgr.conf_key_mgr
import nova.netconf
import nova.notifications
import nova.objects.network
import nova.objectstore.s3server
import nova.paths
import nova.pci.request
import nova.pci.whitelist
import nova.quota
import nova.rdp
import nova.service
import nova.servicegroup.api
import nova.servicegroup.drivers.zk
import nova.spice
import nova.utils
import nova.vnc
import nova.vnc.xvp_proxy
import nova.volume
import nova.volume.cinder
import nova.wsgi


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.conductor.tasks.live_migrate.migrate_opt],
             [nova.consoleauth.consoleauth_topic_opt],
             [nova.db.base.db_driver_opt],
             [nova.ipv6.api.ipv6_backend_opt],
             [nova.servicegroup.api.servicegroup_driver_opt],
             nova.availability_zones.availability_zone_opts,
             nova.cert.rpcapi.rpcapi_opts,
             nova.cloudpipe.pipelib.cloudpipe_opts,
             nova.cmd.novnc.opts,
             nova.cmd.novncproxy.opts,
             nova.cmd.spicehtml5proxy.opts,
             nova.console.manager.console_manager_opts,
             nova.console.rpcapi.rpcapi_opts,
             nova.console.xvp.xvp_opts,
             nova.consoleauth.manager.consoleauth_opts,
             nova.crypto.crypto_opts,
             nova.db.api.db_opts,
             nova.db.sqlalchemy.api.db_opts,
             nova.exception.exc_log_opts,
             nova.image.s3.s3_opts,
             nova.netconf.netconf_opts,
             nova.notifications.notify_opts,
             nova.objects.network.network_opts,
             nova.objectstore.s3server.s3_opts,
             nova.paths.path_opts,
             nova.pci.request.pci_alias_opts,
             nova.pci.whitelist.pci_opts,
             nova.quota.quota_opts,
             nova.service.service_opts,
             nova.utils.monkey_patch_opts,
             nova.utils.utils_opts,
             nova.vnc.xvp_proxy.xvp_proxy_opts,
             nova.volume._volume_opts,
             nova.wsgi.wsgi_opts,
         )),
        ('barbican', nova.keymgr.barbican.barbican_opts),
        ('cinder', nova.volume.cinder.cinder_opts),
        ('api_database', nova.db.sqlalchemy.api.api_db_opts),
        ('conductor', nova.conductor.api.conductor_opts),
        ('database', nova.db.sqlalchemy.api.oslo_db_options.database_opts),
        ('glance', nova.image.glance.glance_opts),
        ('image_file_url', [nova.image.download.file.opt_group]),
        ('keymgr',
         itertools.chain(
             nova.keymgr.conf_key_mgr.key_mgr_opts,
             nova.keymgr.keymgr_opts,
         )),
        ('rdp', nova.rdp.rdp_opts),
        nova.conf.serial_console.list_opts(),
        ('spice',
         itertools.chain(
             nova.cmd.spicehtml5proxy.opts,
             nova.spice.spice_opts,
         )),
        ('upgrade_levels',
         itertools.chain(
             [nova.baserpc.rpcapi_cap_opt],
             [nova.cert.rpcapi.rpcapi_cap_opt],
             [nova.conductor.rpcapi.rpcapi_cap_opt],
             [nova.console.rpcapi.rpcapi_cap_opt],
             [nova.consoleauth.rpcapi.rpcapi_cap_opt],
         )),
        ('vnc', nova.vnc.vnc_opts),
        ('workarounds', nova.utils.workarounds_opts),
        ('zookeeper', nova.servicegroup.drivers.zk.zk_driver_opts)
    ]
