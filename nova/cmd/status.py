# Copyright 2016 IBM Corp.
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

"""
CLI interface for nova status commands.
"""

import functools
import sys
import traceback

from keystoneauth1 import exceptions as ks_exc
import microversion_parse
from oslo_config import cfg
from oslo_upgradecheck import common_checks
from oslo_upgradecheck import upgradecheck
import sqlalchemy as sa
from sqlalchemy import func as sqlfunc

from nova.cmd import common as cmd_common
import nova.conf
from nova import config
from nova import context as nova_context
from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova import exception
from nova.i18n import _
from nova.objects import cell_mapping as cell_mapping_obj
# NOTE(lyarwood): The following are imported as machine_type_utils expects them
# to be registered under nova.objects when called via _check_machine_type_set
from nova.objects import image_meta as image_meta_obj  # noqa: F401
from nova.objects import instance as instance_obj  # noqa: F401
from nova import utils
from nova import version
from nova.virt.libvirt import machine_type_utils
from nova.volume import cinder

CONF = nova.conf.CONF

# NOTE(gibi): 1.36 is required by nova-scheduler to support the same_subtree
# queryparam to make GET /allocation_candidates require that a list of request
# groups are satisfied from the same provider subtree.
# NOTE: If you bump this version, remember to update the history
# section in the nova-status man page (doc/source/cli/nova-status).
MIN_PLACEMENT_MICROVERSION = "1.36"

# NOTE(mriedem): 3.44 is needed to work with volume attachment records which
# are required for supporting multi-attach capable volumes.
MIN_CINDER_MICROVERSION = '3.44'


class UpgradeCommands(upgradecheck.UpgradeCommands):
    """Commands related to upgrades.

    The subcommands here must not rely on the nova object model since they
    should be able to run on n-1 data. Any queries to the database should be
    done through the sqlalchemy query language directly like the database
    schema migrations.
    """

    def _count_compute_nodes(self, context=None):
        """Returns the number of compute nodes in the cell database."""
        # NOTE(mriedem): This does not filter based on the service status
        # because a disabled nova-compute service could still be reporting
        # inventory info to the placement service. There could be an outside
        # chance that there are compute node records in the database for
        # disabled nova-compute services that aren't yet upgraded to Ocata or
        # the nova-compute service was deleted and the service isn't actually
        # running on the compute host but the operator hasn't cleaned up the
        # compute_nodes entry in the database yet. We consider those edge cases
        # here and the worst case scenario is we give a warning that there are
        # more compute nodes than resource providers. We can tighten this up
        # later if needed, for example by not including compute nodes that
        # don't have a corresponding nova-compute service in the services
        # table, or by only counting compute nodes with a service version of at
        # least 15 which was the highest service version when Newton was
        # released.
        meta = sa.MetaData()
        engine = main_db_api.get_engine(context=context)
        compute_nodes = sa.Table('compute_nodes', meta, autoload_with=engine)
        with engine.connect() as conn:
            return conn.execute(
                sa.select(sqlfunc.count()).select_from(compute_nodes).where(
                    compute_nodes.c.deleted == 0
                )
            ).scalars().first()

    def _check_cellsv2(self):
        """Checks to see if cells v2 has been setup.

        These are the same checks performed in the 030_require_cell_setup API
        DB migration except we expect this to be run AFTER the
        nova-manage cell_v2 simple_cell_setup command, which would create the
        cell and host mappings and sync the cell0 database schema, so we don't
        check for flavors at all because you could create those after doing
        this on an initial install. This also has to be careful about checking
        for compute nodes if there are no host mappings on a fresh install.
        """
        meta = sa.MetaData()
        engine = api_db_api.get_engine()

        cell_mappings = self._get_cell_mappings()
        count = len(cell_mappings)
        # Two mappings are required at a minimum, cell0 and your first cell
        if count < 2:
            msg = _('There needs to be at least two cell mappings, one for '
                    'cell0 and one for your first cell. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        cell0 = any(mapping.is_cell0() for mapping in cell_mappings)
        if not cell0:
            msg = _('No cell0 mapping found. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        host_mappings = sa.Table('host_mappings', meta, autoload_with=engine)

        with engine.connect() as conn:
            count = conn.execute(
                sa.select(sqlfunc.count()).select_from(host_mappings)
            ).scalars().first()

        if count == 0:
            # This may be a fresh install in which case there may not be any
            # compute_nodes in the cell database if the nova-compute service
            # hasn't started yet to create those records. So let's query the
            # cell database for compute_nodes records and if we find at least
            # one it's a failure.
            num_computes = self._count_compute_nodes()
            if num_computes > 0:
                msg = _('No host mappings found but there are compute nodes. '
                        'Run command \'nova-manage cell_v2 '
                        'simple_cell_setup\' and then retry.')
                return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

            msg = _('No host mappings or compute nodes were found. Remember '
                    'to run command \'nova-manage cell_v2 discover_hosts\' '
                    'when new compute hosts are deployed.')
            return upgradecheck.Result(upgradecheck.Code.SUCCESS, msg)

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    @staticmethod
    def _placement_get(path):
        """Do an HTTP get call against placement engine.

        This is in a dedicated method to make it easier for unit
        testing purposes.

        """
        client = utils.get_ksa_adapter('placement')
        return client.get(path, raise_exc=True).json()

    def _check_placement(self):
        """Checks to see if the placement API is ready for scheduling.

        Checks to see that the placement API service is registered in the
        service catalog and that we can make requests against it.
        """
        try:
            # TODO(efried): Use ksa's version filtering in _placement_get
            versions = self._placement_get("/")
            max_version = microversion_parse.parse_version_string(
                versions["versions"][0]["max_version"])
            needs_version = microversion_parse.parse_version_string(
                MIN_PLACEMENT_MICROVERSION)
            if max_version < needs_version:
                msg = (_('Placement API version %(needed)s needed, '
                         'you have %(current)s.') %
                       {'needed': needs_version, 'current': max_version})
                return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.MissingAuthPlugin:
            msg = _('No credentials specified for placement API in nova.conf.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.Unauthorized:
            msg = _('Placement service credentials do not work.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.EndpointNotFound:
            msg = _('Placement API endpoint not found.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.DiscoveryFailure:
            msg = _('Discovery for placement API URI failed.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        except ks_exc.NotFound:
            msg = _('Placement API does not seem to be running.')
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    @staticmethod
    def _get_cell_mappings():
        """Queries the API database for cell mappings.

        .. note:: This method is unique in that it queries the database using
                  CellMappingList.get_all() rather than a direct query using
                  the sqlalchemy models. This is because
                  CellMapping.database_connection can be a template and the
                  object takes care of formatting the URL. We cannot use
                  RowProxy objects from sqlalchemy because we cannot set the
                  formatted 'database_connection' value back on those objects
                  (they are read-only).

        :returns: list of nova.objects.CellMapping objects
        """
        ctxt = nova_context.get_admin_context()
        cell_mappings = cell_mapping_obj.CellMappingList.get_all(ctxt)
        return cell_mappings

    def _check_cinder(self):
        """Checks to see that the cinder API is available at a given minimum
        microversion.
        """
        # Check to see if nova is even configured for Cinder yet (fresh install
        # or maybe not using Cinder at all).
        if CONF.cinder.auth_type is None:
            return upgradecheck.Result(upgradecheck.Code.SUCCESS)

        try:
            # TODO(mriedem): Eventually use get_ksa_adapter here when it
            # supports cinder.
            cinder.is_microversion_supported(
                nova_context.get_admin_context(), MIN_CINDER_MICROVERSION)
        except exception.CinderAPIVersionNotAvailable:
            return upgradecheck.Result(
                upgradecheck.Code.FAILURE,
                _('Cinder API %s or greater is required. Deploy at least '
                  'Cinder 12.0.0 (Queens).') % MIN_CINDER_MICROVERSION)
        except Exception as ex:
            # Anything else trying to connect, like bad config, is out of our
            # hands so just return a warning.
            return upgradecheck.Result(
                upgradecheck.Code.WARNING,
                _('Unable to determine Cinder API version due to error: %s') %
                str(ex))
        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_old_computes(self):
        # warn if there are computes in the system older than the previous
        # major release
        try:
            utils.raise_if_old_compute()
        except exception.TooOldComputeService as e:
            return upgradecheck.Result(upgradecheck.Code.FAILURE, str(e))

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_machine_type_set(self):
        ctxt = nova_context.get_admin_context()
        if machine_type_utils.get_instances_without_type(ctxt):
            msg = (_("""
Instances found without hw_machine_type set. This warning can be ignored if
your environment does not contain libvirt based compute hosts.
Use the `nova-manage machine_type list_unset` command to list these instances.
For more details see the following:
https://docs.openstack.org/nova/latest/admin/hw-machine-type.html"""))
            return upgradecheck.Result(upgradecheck.Code.WARNING, msg)

        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    def _check_service_user_token(self):
        if not CONF.service_user.send_service_user_token:
            msg = (_("""
Service user token configuration is required for all Nova services.
For more details see the following:
https://docs.openstack.org/nova/latest/admin/configuration/service-user-token.html"""))  # noqa
            return upgradecheck.Result(upgradecheck.Code.FAILURE, msg)
        return upgradecheck.Result(upgradecheck.Code.SUCCESS)

    # The format of the check functions is to return an upgradecheck.Result
    # object with the appropriate upgradecheck.Code and details set. If the
    # check hits warnings or failures then those should be stored in the
    # returned upgradecheck.Result's "details" attribute. The summary will
    # be rolled up at the end of the check() function. These functions are
    # intended to be run in order and build on top of each other so order
    # matters.
    _upgrade_checks = (
        # Added in Ocata
        (_('Cells v2'), _check_cellsv2),
        # Added in Ocata
        (_('Placement API'), _check_placement),
        # Added in Train
        (_('Cinder API'), _check_cinder),
        # Added in Victoria
        (
            _('Policy File JSON to YAML Migration'),
            (common_checks.check_policy_json, {'conf': CONF})
        ),
        # Added in Wallaby
        (_('Older than N-1 computes'), _check_old_computes),
        # Added in Wallaby
        (_('hw_machine_type unset'), _check_machine_type_set),
        # Added in Bobcat
        (_('Service User Token Configuration'), _check_service_user_token),
    )


CATEGORIES = {
    'upgrade': UpgradeCommands,
}


add_command_parsers = functools.partial(cmd_common.add_command_parsers,
                                        categories=CATEGORIES)


category_opt = cfg.SubCommandOpt('category',
                                 title='Command categories',
                                 help='Available categories',
                                 handler=add_command_parsers)


def main():
    """Parse options and call the appropriate class/method."""
    CONF.register_cli_opt(category_opt)
    config.parse_args(sys.argv)

    if CONF.category.name == "version":
        print(version.version_string_with_package())
        return 0

    if CONF.category.name == "bash-completion":
        cmd_common.print_bash_completion(CATEGORIES)
        return 0

    try:
        fn, fn_args, fn_kwargs = cmd_common.get_action_fn()
        ret = fn(*fn_args, **fn_kwargs)
        return ret
    except Exception:
        print(_('Error:\n%s') % traceback.format_exc())
        # This is 255 so it's not confused with the upgrade check exit codes.
        return 255
