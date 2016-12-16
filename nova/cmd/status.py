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

from __future__ import print_function
import functools
import sys
import textwrap
import traceback

# enum comes from the enum34 package if python < 3.4, else it's stdlib
import enum
from oslo_config import cfg
import prettytable
from sqlalchemy import func as sqlfunc
from sqlalchemy import MetaData, Table, select

from nova.cmd import common as cmd_common
import nova.conf
from nova import config
from nova.db.sqlalchemy import api as db_session
from nova.i18n import _
from nova.objects import cell_mapping as cell_mapping_obj
from nova import version

CONF = nova.conf.CONF


class UpgradeCheckCode(enum.IntEnum):
    """These are the status codes for the nova-status upgrade check command
    and internal check commands.
    """

    # All upgrade readiness checks passed successfully and there is
    # nothing to do.
    SUCCESS = 0

    # At least one check encountered an issue and requires further
    # investigation. This is considered a warning but the upgrade may be OK.
    WARNING = 1

    # There was an upgrade status check failure that needs to be
    # investigated. This should be considered something that stops an upgrade.
    FAILURE = 2


UPGRADE_CHECK_MSG_MAP = {
    UpgradeCheckCode.SUCCESS: _('Success'),
    UpgradeCheckCode.WARNING: _('Warning'),
    UpgradeCheckCode.FAILURE: _('Failure'),
}


class UpgradeCheckResult(object):
    """Class used for 'nova-status upgrade check' results.

    The 'code' attribute is an UpgradeCheckCode enum.
    The 'details' attribute is a translated message generally only used for
    checks that result in a warning or failure code. The details should provide
    information on what issue was discovered along with any remediation.
    """

    def __init__(self, code, details=None):
        super(UpgradeCheckResult, self).__init__()
        self.code = code
        self.details = details


class UpgradeCommands(object):
    """Commands related to upgrades.

    The subcommands here must not rely on the nova object model since they
    should be able to run on n-1 data. Any queries to the database should be
    done through the sqlalchemy query language directly like the database
    schema migrations.
    """

    def _count_compute_nodes(self):
        """Returns the number of compute nodes in the cell database."""
        meta = MetaData(bind=db_session.get_engine())
        compute_nodes = Table('compute_nodes', meta, autoload=True)
        return select([sqlfunc.count()]).select_from(compute_nodes).scalar()

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
        meta = MetaData()
        meta.bind = db_session.get_api_engine()

        cell_mappings = Table('cell_mappings', meta, autoload=True)
        count = select([sqlfunc.count()]).select_from(cell_mappings).scalar()
        # Two mappings are required at a minimum, cell0 and your first cell
        if count < 2:
            msg = _('There needs to be at least two cell mappings, one for '
                    'cell0 and one for your first cell. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return UpgradeCheckResult(UpgradeCheckCode.FAILURE, msg)

        count = select([sqlfunc.count()]).select_from(cell_mappings).where(
            cell_mappings.c.uuid ==
                cell_mapping_obj.CellMapping.CELL0_UUID).scalar()
        if count != 1:
            msg = _('No cell0 mapping found. Run command '
                    '\'nova-manage cell_v2 simple_cell_setup\' and then '
                    'retry.')
            return UpgradeCheckResult(UpgradeCheckCode.FAILURE, msg)

        host_mappings = Table('host_mappings', meta, autoload=True)
        count = select([sqlfunc.count()]).select_from(host_mappings).scalar()
        if count == 0:
            # This may be a fresh install in which case there may not be any
            # compute_nodes in the cell database if the nova-compute service
            # hasn't started yet to create those records. So let's query the
            # the cell database for compute_nodes records and if we find at
            # least one it's a failure.
            num_computes = self._count_compute_nodes()
            if num_computes > 0:
                msg = _('No host mappings found but there are compute nodes. '
                        'Run command \'nova-manage cell_v2 '
                        'simple_cell_setup\' and then retry.')
                return UpgradeCheckResult(UpgradeCheckCode.FAILURE, msg)

            msg = _('No host mappings or compute nodes were found. Remember '
                    'to run command \'nova-manage cell_v2 discover_hosts\' '
                    'when new compute hosts are deployed.')
            return UpgradeCheckResult(UpgradeCheckCode.SUCCESS, msg)

        return UpgradeCheckResult(UpgradeCheckCode.SUCCESS)

    def _check_placement(self):
        # TODO(mriedem): check to see that the placement API service is running
        # and we can connect to it, and that the number of resource providers
        # in the placement service is greater than or equal to the number of
        # compute nodes in the database.
        return UpgradeCheckResult(UpgradeCheckCode.SUCCESS)

    # The format of the check functions is to return an UpgradeCheckResult
    # object with the appropriate UpgradeCheckCode and details set. If the
    # check hits warnings or failures then those should be stored in the
    # returned UpgradeCheckResult's "details" attribute. The summary will
    # be rolled up at the end of the check() function.
    _upgrade_checks = {
        # Added in Ocata
        _('Cells v2'): _check_cellsv2,
        # Added in Ocata
        _('Placement API'): _check_placement,
    }

    def _get_details(self, upgrade_check_result):
        if upgrade_check_result.details is not None:
            # wrap the text on the details to 60 characters
            return '\n'.join(textwrap.wrap(upgrade_check_result.details, 60,
                                           subsequent_indent='  '))

    def check(self):
        """Performs checks to see if the deployment is ready for upgrade.

        These checks are expected to be run BEFORE services are restarted with
        new code. These checks also require access to potentially all of the
        Nova databases (nova, nova_api, nova_api_cell0) and external services
        such as the placement API service.

        :returns: UpgradeCheckCode
        """
        return_code = UpgradeCheckCode.SUCCESS
        # This is a list if 2-item tuples for the check name and it's results.
        check_results = []
        # Sort the checks by name so that we have predictable test results.
        for name in sorted(self._upgrade_checks.keys()):
            func = self._upgrade_checks[name]
            result = func(self)
            # store the result of the check for the summary table
            check_results.append((name, result))
            # we want to end up with the highest level code of all checks
            if result.code > return_code:
                return_code = result.code

        # We're going to build a summary table that looks like:
        # +----------------------------------------------------+
        # | Upgrade Check Results                              |
        # +----------------------------------------------------+
        # | Check: Cells v2                                    |
        # | Result: Success                                    |
        # | Details: None                                      |
        # +----------------------------------------------------+
        # | Check: Placement API                               |
        # | Result: Failure                                    |
        # | Details: There is no placement-api endpoint in the |
        # |          service catalog.                          |
        # +----------------------------------------------------+
        t = prettytable.PrettyTable([_('Upgrade Check Results')],
                                    hrules=prettytable.ALL)
        t.align = 'l'
        for name, result in check_results:
            cell = (
                _('Check: %(name)s\n'
                  'Result: %(result)s\n'
                  'Details: %(details)s') %
                {
                    'name': name,
                    'result': UPGRADE_CHECK_MSG_MAP[result.code],
                    'details': self._get_details(result),
                }
            )
            t.add_row([cell])
        print(t)

        return return_code


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
        return(ret)
    except Exception:
        print(_('Error:\n%s') % traceback.format_exc())
        # This is 10 so it's not confused with the upgrade check exit codes.
        return 10
