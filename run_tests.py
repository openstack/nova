# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
This is our basic test running framework based on Twisted's Trial.

Usage Examples:

    # to run all the tests
    python run_tests.py

    # to run a specific test suite imported here
    python run_tests.py NodeConnectionTestCase

    # to run a specific test imported here
    python run_tests.py NodeConnectionTestCase.test_reboot

    # to run some test suites elsewhere
    python run_tests.py nova.tests.node_unittest
    python run_tests.py nova.tests.node_unittest.NodeConnectionTestCase

Due to our use of multiprocessing it we frequently get some ignorable
'Interrupted system call' exceptions after test completion.

"""
import __main__
import sys

from nova import vendor
from twisted.scripts import trial as trial_script

from nova import flags
from nova import twistd

from nova.tests.access_unittest import *
from nova.tests.api_unittest import *
from nova.tests.cloud_unittest import *
from nova.tests.keeper_unittest import *
from nova.tests.network_unittest import *
from nova.tests.node_unittest import *
from nova.tests.objectstore_unittest import *
from nova.tests.process_unittest import *
from nova.tests.storage_unittest import *
from nova.tests.users_unittest import *
from nova.tests.datastore_unittest import *
from nova.tests.validator_unittest import *
from nova.tests.model_unittest import *


FLAGS = flags.FLAGS

flags.DEFINE_bool('flush_db', True,
                  'Flush the database before running fake tests')

if __name__ == '__main__':
    OptionsClass = twistd.WrapTwistedOptions(trial_script.Options)
    config = OptionsClass()
    argv = config.parseOptions()

    FLAGS.verbose = True

    # TODO(termie): these should make a call instead of doing work on import
    if FLAGS.fake_tests:
        from nova.tests.fake_flags import *
        # use db 8 for fake tests
        FLAGS.redis_db = 8
        if FLAGS.flush_db:
            logging.info("Flushing redis datastore")
            r = datastore.Redis.instance()
            r.flushdb()
    else:
        from nova.tests.real_flags import *

    if len(argv) == 1 and len(config['tests']) == 0:
        # If no tests were specified run the ones imported in this file
        # NOTE(termie): "tests" is not a flag, just some Trial related stuff
        config['tests'].update(['__main__'])
    elif len(config['tests']):
        # If we specified tests check first whether they are in __main__
        for arg in config['tests']:
            key = arg.split('.')[0]
            if hasattr(__main__, key):
                config['tests'].remove(arg)
                config['tests'].add('__main__.%s' % arg)

    trial_script._initialDebugSetup(config)
    trialRunner = trial_script._makeRunner(config)
    suite = trial_script._getSuite(config)
    if config['until-failure']:
        test_result = trialRunner.runUntilFailure(suite)
    else:
        test_result = trialRunner.run(suite)
    if config.tracer:
        sys.settrace(None)
        results = config.tracer.results()
        results.write_results(show_missing=1, summary=False,
                              coverdir=config.coverdir)
    sys.exit(not test_result.wasSuccessful())
