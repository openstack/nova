# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import jsonschema.exceptions

from nova.api.openstack import compute
from nova.api.validation import validators
from nova import test


class SchemaTest(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.router = compute.APIRouterV21()
        self.meta_schema = validators._SchemaValidator.validator_org

    def test_schemas(self):
        missing_request_schemas = set()
        missing_query_schemas = set()
        invalid_schemas = set()

        def _validate_func(func, method):
            if method in ("POST", "PUT", "PATCH"):
                # request body validation
                if not hasattr(func, '_request_schema'):
                    missing_request_schemas.add(func.__qualname__)
                else:
                    try:
                        self.meta_schema.check_schema(func._request_schema)
                    except jsonschema.exceptions.SchemaError:
                        invalid_schemas.add(func.__qualname__)
            elif method in ("GET",):
                # request query string validation
                if not hasattr(func, '_query_schema'):
                    missing_query_schemas.add(func.__qualname__)
                else:
                    try:
                        self.meta_schema.check_schema(func._query_schema)
                    except jsonschema.exceptions.SchemaError:
                        invalid_schemas.add(func.__qualname__)

            # TODO(stephenfin): Check for missing schemas once we have added
            # them all
            if hasattr(func, '_response_schema'):
                try:
                    self.meta_schema.check_schema(func._response_schema)
                except jsonschema.exceptions.SchemaError:
                    invalid_schemas.add(func.__qualname__)

        for route in self.router.map.matchlist:
            if 'controller' not in route.defaults:
                continue

            controller = route.defaults['controller']

            path = ""
            for part in route.routelist:
                if isinstance(part, dict):
                    path += "{" + part["name"] + "}"
                else:
                    path += part

            method = (
                route.conditions.get("method", "GET")[0]
                if route.conditions
                else "GET"
            )
            action = route.defaults["action"]

            if path.endswith('/action'):
                # all actions should use POST
                assert method == 'POST'

                wsgi_actions = [
                    (k, v, controller.controller) for k, v in
                    controller.controller.wsgi_actions.items()
                ]
                for sub_controller in controller.sub_controllers:
                    wsgi_actions += [
                        (k, v, sub_controller) for k, v in
                        sub_controller.wsgi_actions.items()
                    ]

                for (
                    wsgi_action, wsgi_method, action_controller
                ) in wsgi_actions:
                    func = controller.wsgi_actions[wsgi_action]

                    if hasattr(action_controller, 'versioned_methods'):
                        if wsgi_method in action_controller.versioned_methods:
                            # currently all our actions are unversioned and if
                            # this changes then we need to fix this
                            funcs = action_controller.versioned_methods[
                                wsgi_method
                            ]
                            assert len(funcs) == 1
                            func = funcs[0].func

                    # method will always be POST for actions
                    _validate_func(func, method)
            else:
                # body validation
                versioned_methods = getattr(
                    controller.controller, 'versioned_methods', {}
                )
                if action in versioned_methods:
                    # versioned method
                    for versioned_method in sorted(
                        versioned_methods[action],
                        key=lambda v: v.start_version
                    ):
                        func = versioned_method.func

                        _validate_func(func, method)
                else:
                    # unversioned method
                    func = getattr(controller.controller, action)
                    _validate_func(func, method)

        if missing_request_schemas:
            raise test.TestingException(
                f"Found API resources without schemas: "
                f"{sorted(missing_request_schemas)}"
            )

        if missing_query_schemas:
            raise test.TestingException(
                f"Found API resources without query schemas: "
                f"{sorted(missing_query_schemas)}"
            )

        if invalid_schemas:
            raise test.TestingException(
                f"Found API resources with invalid schemas: "
                f"{sorted(invalid_schemas)}"
            )
