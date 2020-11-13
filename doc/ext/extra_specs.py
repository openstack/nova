# Copyright 2020, Red Hat, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Display extra specs in documentation.

Provides a single directive that can be used to list all extra specs validators
and, thus, document all extra specs that nova recognizes and supports.
"""

import typing as ty

from docutils import nodes
from docutils.parsers import rst
from docutils.parsers.rst import directives
from docutils import statemachine
from sphinx import addnodes
from sphinx import directives as sphinx_directives
from sphinx import domains
from sphinx import roles
from sphinx.util import logging
from sphinx.util import nodes as sphinx_nodes

from nova.api.validation.extra_specs import base
from nova.api.validation.extra_specs import validators

LOG = logging.getLogger(__name__)


class ExtraSpecXRefRole(roles.XRefRole):
    """Cross reference a extra spec.

    Example::

        :nova:extra-spec:`hw:cpu_policy`
    """

    def __init__(self):
        super(ExtraSpecXRefRole, self).__init__(
            warn_dangling=True,
        )

    def process_link(self, env, refnode, has_explicit_title, title, target):
        # The anchor for the extra spec link is the extra spec name
        return target, target


class ExtraSpecDirective(sphinx_directives.ObjectDescription):
    """Document an individual extra spec.

    Accepts one required argument - the extra spec name, including the group.

    Example::

        .. extra-spec:: hw:cpu_policy
    """

    def handle_signature(self, sig, signode):
        """Transform an option description into RST nodes."""
        # Insert a node into the output showing the extra spec name
        signode += addnodes.desc_name(sig, sig)
        signode['allnames'] = [sig]
        return sig

    def add_target_and_index(self, firstname, sig, signode):
        cached_options = self.env.domaindata['nova']['extra_specs']
        signode['ids'].append(sig)
        self.state.document.note_explicit_target(signode)
        # Store the location of the option definition for later use in
        # resolving cross-references
        cached_options[sig] = self.env.docname


def _indent(text, count=1):
    if not text:
        return text

    padding = ' ' * (4 * count)
    return padding + text


def _format_validator_group_help(
    validators: ty.Dict[str, base.ExtraSpecValidator],
    summary: bool,
):
    """Generate reStructuredText snippets for a group of validators."""
    for validator in validators.values():
        for line in _format_validator_help(validator, summary):
            yield line


def _format_validator_help(
    validator: base.ExtraSpecValidator,
    summary: bool,
):
    """Generate reStucturedText snippets for the provided validator.

    :param validator: A validator to document.
    :type validator: nova.api.validation.extra_specs.base.ExtraSpecValidator
    """
    yield f'.. nova:extra-spec:: {validator.name}'
    yield ''

    # NOTE(stephenfin): We don't print the pattern, if present, since it's too
    # internal. Instead, the description should provide this information in a
    # human-readable format
    yield _indent(f':Type: {validator.value["type"].__name__}')

    if validator.value.get('min') is not None:
        yield _indent(f':Min: {validator.value["min"]}')

    if validator.value.get('max') is not None:
        yield _indent(f':Max: {validator.value["max"]}')

    yield ''

    if not summary:
        for line in validator.description.splitlines():
            yield _indent(line)

        yield ''

    if validator.deprecated:
        yield _indent('.. warning::')
        yield _indent(
            'This extra spec has been deprecated and should not be used.', 2
        )
        yield ''


class ExtraSpecGroupDirective(rst.Directive):
    """Document extra specs belonging to the specified group.

    Accepts one optional argument - the extra spec group - and one option -
    whether to show a summary view only (omit descriptions). Example::

        .. extra-specs:: hw_rng
           :summary:
    """

    required_arguments = 0
    optional_arguments = 1
    option_spec = {
        'summary': directives.flag,
    }
    has_content = False

    def run(self):
        result = statemachine.ViewList()
        source_name = self.state.document.current_source

        group = self.arguments[0] if self.arguments else None
        summary = self.options.get('summary', False)

        if group:
            group_validators = {
                n.split(':', 1)[1]: v for n, v in validators.VALIDATORS.items()
                if ':' in n and n.split(':', 1)[0].split('{')[0] == group
            }
        else:
            group_validators = {
                n: v for n, v in validators.VALIDATORS.items()
                if ':' not in n
            }

        if not group_validators:
            LOG.warning("No validators found for group '%s'", group or '')

        for count, line in enumerate(
            _format_validator_group_help(group_validators, summary)
        ):
            result.append(line, source_name, count)
            LOG.debug('%5d%s%s', count, ' ' if line else '', line)

        node = nodes.section()
        node.document = self.state.document

        sphinx_nodes.nested_parse_with_titles(self.state, result, node)

        return node.children


class NovaDomain(domains.Domain):
    """nova domain."""
    name = 'nova'
    label = 'nova'
    object_types = {
        'configoption': domains.ObjType(
            'extra spec', 'spec',
        ),
    }
    directives = {
        'extra-spec': ExtraSpecDirective,
    }
    roles = {
        'extra-spec': ExtraSpecXRefRole(),
    }
    initial_data = {
        'extra_specs': {},
    }

    def resolve_xref(
        self, env, fromdocname, builder, typ, target, node, contnode,
    ):
        """Resolve cross-references"""
        if typ == 'option':
            return sphinx_nodes.make_refnode(
                builder,
                fromdocname,
                env.domaindata['nova']['extra_specs'][target],
                target,
                contnode,
                target,
            )
        return None


def setup(app):
    app.add_domain(NovaDomain)
    app.add_directive('extra-specs', ExtraSpecGroupDirective)
