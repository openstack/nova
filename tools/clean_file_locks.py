#!/usr/bin/env python

# Copyright 2012 La Honda Research Center, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""clean_file_locks.py - Cleans stale interprocess locks

This rountine can be used to find and delete stale lock files from
nova's interprocess synchroization.  It can be used safely while services
are running.

"""

import logging
import optparse

from nova import flags
from nova import utils
from nova import log


LOG = log.getLogger('nova.utils')
FLAGS = flags.FLAGS


def parse_options():
    """process command line options."""

    parser = optparse.OptionParser('usage: %prog [options]')
    parser.add_option('--verbose', action='store_true',
                      help='List lock files found and deleted')

    options, args = parser.parse_args()

    return options, args


def main():
    """Main loop."""
    options, args = parse_options()
    verbose = options.verbose

    if verbose:
        LOG.logger.setLevel(logging.DEBUG)
    else:
        LOG.logger.setLevel(logging.INFO)
    LOG.info('Cleaning stale locks from %s' % FLAGS.lock_path)
    utils.cleanup_file_locks()
    LOG.info('Finished')

if __name__ == '__main__':
    main()
