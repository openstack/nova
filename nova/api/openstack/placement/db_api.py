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
"""Database context manager for placement database connection, kept in its
own file so the nova db_api (which has cascading imports) is not imported.
"""

from oslo_db.sqlalchemy import enginefacade
from oslo_log import log as logging

from nova.utils import run_once

placement_context_manager = enginefacade.transaction_context()
LOG = logging.getLogger(__name__)


def _get_db_conf(conf_group):
    return dict(conf_group.items())


@run_once("TransactionFactory already started, not reconfiguring.",
          LOG.warning)
def configure(conf):
    # If [placement_database]/connection is not set in conf, then placement
    # data will be stored in the nova_api database.
    if conf.placement_database.connection is None:
        placement_context_manager.configure(
            **_get_db_conf(conf.api_database))
    else:
        placement_context_manager.configure(
            **_get_db_conf(conf.placement_database))


def get_placement_engine():
    return placement_context_manager.get_legacy_facade().get_engine()


@enginefacade.transaction_context_provider
class DbContext(object):
    """Stub class for db session handling outside of web requests."""
