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
import nova.cmd.serialproxy
import nova.cmd.spicehtml5proxy
import nova.conductor.rpcapi
import nova.conf
import nova.console.rpcapi
import nova.console.serial
import nova.consoleauth.rpcapi
import nova.db.api
import nova.db.base
import nova.db.sqlalchemy.api
import nova.exception
import nova.image.download.file
import nova.volume


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             [nova.db.base.db_driver_opt],
             nova.db.api.db_opts,
             nova.db.sqlalchemy.api.db_opts,
             nova.exception.exc_log_opts,
             nova.volume._volume_opts,
         )),
        ('api_database', nova.db.sqlalchemy.api.api_db_opts),
        ('database', nova.db.sqlalchemy.api.oslo_db_options.database_opts),
    ]
