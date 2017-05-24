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
"""Test to see if docs exists for routes and methods in the placement API."""

import os
import sys

from nova.api.openstack.placement import handler

# A humane ordering of HTTP methods for sorted output.
ORDERED_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']


def _header_line(map_entry):
    method, route = map_entry
    line = '.. rest_method:: %s %s' % (method, route)
    return line


def inspect_doc(doc_files):
    """Load up doc_files and see if any routes are missing.

    The routes are defined in handler.ROUTE_DECLARATIONS.
    """
    routes = []
    for route in sorted(handler.ROUTE_DECLARATIONS, key=len):
        # Skip over the '' route.
        if route:
            for method in ORDERED_METHODS:
                if method in handler.ROUTE_DECLARATIONS[route]:
                    routes.append((method, route))

    header_lines = []
    for map_entry in routes:
        header_lines.append(_header_line(map_entry))

    content_lines = []
    for doc_file in doc_files:
        with open(doc_file) as doc_fh:
            content_lines.extend(doc_fh.read().splitlines())

    missing_lines = []
    for line in header_lines:
        if line not in content_lines:
            missing_lines.append(line)

    if missing_lines:
        print('Documentation likely missing for the following routes:')
        for line in missing_lines:
            print(line)
        return 1

    return 0


if __name__ == '__main__':
    path = sys.argv[1]
    doc_files = [os.path.join(path, file)
                 for file in os.listdir(path) if file.endswith(".inc")]
    sys.exit(inspect_doc(doc_files))
