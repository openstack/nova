#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

"""
This script concurrently builds and migrates instances. This can be useful when
troubleshooting race-conditions in virt-layer code.

Expects:

    novarc to be sourced in the environment

Helper Script for Xen Dom0:

    # cat /tmp/destroy_cache_vdis
    #!/bin/bash
    xe vdi-list | grep "Glance Image" -C1 | grep "^uuid" | awk '{print $5}' |
        xargs -n1 -I{} xe vdi-destroy uuid={}
"""
import argparse
import contextlib
import multiprocessing
import subprocess
import sys
import time

DOM0_CLEANUP_SCRIPT = "/tmp/destroy_cache_vdis"


def run(cmd):
    ret = subprocess.call(cmd, shell=True)
    if ret != 0:
        sys.stderr.write("Command exited non-zero: %s" % cmd)


@contextlib.contextmanager
def server_built(server_name, image_name, flavor=1, cleanup=True):
    run("nova boot --image=%s --flavor=%s"
        " --poll %s" % (image_name, flavor, server_name))
    try:
        yield
    finally:
        if cleanup:
            run("nova delete %s" % server_name)


@contextlib.contextmanager
def snapshot_taken(server_name, snapshot_name, cleanup=True):
    run("nova image-create %s %s"
        " --poll" % (server_name, snapshot_name))
    try:
        yield
    finally:
        if cleanup:
            run("nova image-delete %s" % snapshot_name)


def migrate_server(server_name):
    run("nova migrate %s --poll" % server_name)

    cmd = "nova list | grep %s | awk '{print $6}'" % server_name
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
    stdout, stderr = proc.communicate()
    status = stdout.strip()
    if status.upper() != 'VERIFY_RESIZE':
        sys.stderr.write("Server %s failed to rebuild" % server_name)
        return False

    # Confirm the resize
    run("nova resize-confirm %s" % server_name)
    return True


def test_migrate(context):
    count, args = context
    server_name = "server%d" % count
    cleanup = args.cleanup
    with server_built(server_name, args.image, cleanup=cleanup):
        # Migrate A -> B
        result = migrate_server(server_name)
        if not result:
            return False

        # Migrate B -> A
        return migrate_server(server_name)


def rebuild_server(server_name, snapshot_name):
    run("nova rebuild %s %s --poll" % (server_name, snapshot_name))

    cmd = "nova list | grep %s | awk '{print $6}'" % server_name
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
    stdout, stderr = proc.communicate()
    status = stdout.strip()
    if status != 'ACTIVE':
        sys.stderr.write("Server %s failed to rebuild" % server_name)
        return False

    return True


def test_rebuild(context):
    count, args = context
    server_name = "server%d" % count
    snapshot_name = "snap%d" % count
    cleanup = args.cleanup
    with server_built(server_name, args.image, cleanup=cleanup):
        with snapshot_taken(server_name, snapshot_name, cleanup=cleanup):
            return rebuild_server(server_name, snapshot_name)


def _parse_args():
    parser = argparse.ArgumentParser(
            description='Test Nova for Race Conditions.')

    parser.add_argument('tests', metavar='TESTS', type=str, nargs='*',
                        default=['rebuild', 'migrate'],
                        help='tests to run: [rebuilt|migrate]')

    parser.add_argument('-i', '--image', help="image to build from",
                        required=True)
    parser.add_argument('-n', '--num-runs', type=int, help="number of runs",
                        default=1)
    parser.add_argument('-c', '--concurrency', type=int, default=5,
                        help="number of concurrent processes")
    parser.add_argument('--no-cleanup', action='store_false', dest="cleanup",
                        default=True)
    parser.add_argument('-d', '--dom0-ips',
                        help="IP of dom0's to run cleanup script")

    return parser.parse_args()


def main():
    dom0_cleanup_script = DOM0_CLEANUP_SCRIPT
    args = _parse_args()

    if args.dom0_ips:
        dom0_ips = args.dom0_ips.split(',')
    else:
        dom0_ips = []

    start_time = time.time()
    batch_size = min(args.num_runs, args.concurrency)
    pool = multiprocessing.Pool(processes=args.concurrency)

    results = []
    for test in args.tests:
        test_func = globals().get("test_%s" % test)
        if not test_func:
            sys.stderr.write("test '%s' not found" % test)
            sys.exit(1)

        contexts = [(x, args) for x in range(args.num_runs)]

        try:
            results += pool.map(test_func, contexts)
        finally:
            if args.cleanup:
                for dom0_ip in dom0_ips:
                    run("ssh root@%s %s" % (dom0_ip, dom0_cleanup_script))

    success = all(results)
    result = "SUCCESS" if success else "FAILED"

    duration = time.time() - start_time
    print("%s, finished in %.2f secs" % (result, duration))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
