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

"""This provides a sphinx extension able to create the HTML needed
for the api-ref website.

It contains 2 new stanzas.

  .. rest_method:: GET /foo/bar

Which is designed to be used as the first stanza in a new section to
state that section is about that REST method. During processing the
rest stanza will be reparented to be before the section in question,
and used as a show/hide selector for it's details.

  .. rest_parameters:: file.yaml

     - name1: name_in_file1
     - name2: name_in_file2
     - name3: name_in_file3

Which is designed to build structured tables for either response or
request parameters. The stanza takes a value which is a file to lookup
details about the parameters in question.

The contents of the stanza are a yaml list of key / value pairs. The
key is the name of the parameter to be shown in the table. The value
is the key in the file.yaml where all other metadata about the
parameter will be extracted. This allows for reusing parameter
definitions widely in API definitions, but still providing for control
in both naming and ordering of parameters at every declaration.

"""

from docutils import nodes
from docutils.parsers.rst.directives.tables import Table
from docutils.statemachine import ViewList
from sphinx.util.compat import Directive

import yaml


def full_name(cls):
    return cls.__module__ + '.' + cls.__name__


class rest_method(nodes.Part, nodes.Element):
    """rest_method custom node type

    We specify a custom node type for rest_method so that we can
    accumulate all the data about the rest method, but not render as
    part of the normal rendering process. This means that we need a
    renderer for every format we wish to support with this.

    """
    pass


class RestMethodDirective(Directive):

    # this enables content in the directive
    has_content = True

    def run(self):
        lineno = self.state_machine.abs_line_number()
        target = nodes.target()
        section = nodes.section(classes=["detail-control"])
        # env = self.state.document.settings.env
        # env.app.info("Parent %s" % self.state.parent.attributes)

        node = rest_method()

        # TODO(sdague): this is a super simplistic parser, should be
        # more robust.
        method, sep, url = self.content[0].partition(' ')

        node['method'] = method
        node['url'] = url
        node['target'] = self.state.parent.attributes['ids'][0]

        # We need to build a temporary target that we can replace
        # later in the processing to get the TOC to resolve correctly.
        temp_target = "%s-selector" % node['target']
        target = nodes.target(ids=[temp_target])
        self.state.add_target(temp_target, '', target, lineno)
        section += node

        return [target, section]


class RestParametersDirective(Table):

    headers = ["Name", "In", "Type", "Description"]

    def yaml_from_file(self, fpath):
        """Collect Parameter stanzas from inline + file.

        This allows use to reference an external file for the actual
        parameter definitions.
        """
        # self.app.info("Fpath: %s" % fpath)
        with open(fpath, 'r') as stream:
            try:
                lookup = yaml.load(stream)
            except yaml.YAMLError as exc:
                self.app.warn(exc)
                raise

        content = "\n".join(self.content)
        parsed = yaml.load(content)
        # self.app.info("Params loaded is %s" % parsed)
        # self.app.info("Lookup table looks like %s" % lookup)
        new_content = list()
        for paramlist in parsed:
            for name, ref in paramlist.items():
                new_content.append((name, lookup[ref]))

        # self.app.info("New content %s" % new_content)
        self.yaml = new_content

    def run(self):
        env = self.state.document.settings.env
        self.app = env.app

        # Make sure we have some content, which should be yaml that
        # defines some parameters.
        if not self.content:
            error = self.state_machine.reporter.error(
                'No parameters defined',
                nodes.literal_block(self.block_text, self.block_text),
                line=self.lineno)
            return [error]

        if not len(self.arguments) >= 1:
            self.state_machine.reporter.error(
                'No reference file defined',
                nodes.literal_block(self.block_text, self.block_text),
                line=self.lineno)
            return [error]

        # NOTE(sdague): it's important that we pop the arg otherwise
        # we end up putting the filename as the table caption.
        rel_fpath, fpath = env.relfn2path(self.arguments.pop())
        self.yaml_from_file(fpath)

        self.max_cols = len(self.headers)
        # TODO(sdague): it would be good to dynamically set column
        # widths (or basically make the colwidth thing go away
        # entirely)
        self.options['widths'] = (20, 10, 10, 60)
        self.col_widths = self.get_column_widths(self.max_cols)
        # Actually convert the yaml
        title, messages = self.make_title()
        # self.app.info("Title %s, messages %s" % (title, messages))
        table_node = self.build_table()
        self.add_name(table_node)
        if title:
            table_node.insert(0, title)
        return [table_node] + messages

    def get_rows(self, table_data):
        rows = []
        groups = []
        trow = nodes.row()
        entry = nodes.entry()
        para = nodes.paragraph(text=unicode(table_data))
        entry += para
        trow += entry
        rows.append(trow)
        return rows, groups

    def collect_rows(self):

        # Add a column for a field. In order to have the RST inside
        # these fields get rendered, we need to use the
        # ViewList. Note, ViewList expects a list of lines, so chunk
        # up our content as a list to make it happy.
        def add_col(value):
            entry = nodes.entry()
            result = ViewList(value.split('\n'))
            self.state.nested_parse(result, 0, entry)
            return entry

        rows = []
        groups = []
        try:
            # self.app.info("Parsed content is: %s" % self.yaml)
            for key, values in self.yaml:
                min_version = values.get('min_version', '')
                desc = values.get('description', '')
                classes = []
                if min_version:
                    desc += ("\n\n**New in version %s**\n" % min_version)
                    min_ver_css_name = ("rp_min_ver_" +
                                        str(min_version).replace('.', '_'))
                    classes.append(min_ver_css_name)
                trow = nodes.row(classes=classes)
                name = key
                if values.get('optional') is True:
                    name += " (Optional)"
                trow += add_col(name)
                trow += add_col(values.get('in'))
                trow += add_col(values.get('type'))
                trow += add_col(desc)
                rows.append(trow)
        except AttributeError as exc:
            self.app.warn("Failure on key: %s, values: %s. %s" %
                          (key, values, exc))
            raise
        return rows, groups

    def build_table(self):
        table = nodes.table()
        tgroup = nodes.tgroup(cols=len(self.headers))
        table += tgroup

        # TODO(sdague): it would be really nice to figure out how not
        # to have this stanza, it kind of messes up all of the table
        # formatting because it doesn't let tables just be the right
        # size.
        tgroup.extend(
             nodes.colspec(colwidth=col_width, colname='c' + str(idx))
             for idx, col_width in enumerate(self.col_widths)
        )

        thead = nodes.thead()
        tgroup += thead

        row_node = nodes.row()
        thead += row_node
        row_node.extend(nodes.entry(h, nodes.paragraph(text=h))
                        for h in self.headers)

        tbody = nodes.tbody()
        tgroup += tbody

        rows, groups = self.collect_rows()
        tbody.extend(rows)
        table.extend(groups)

        return table


def rest_method_html(self, node):
    tmpl = """
<div class="row operation-grp">
    <div class="col-md-1 operation">
    <a name="%(target)s" class="operation-anchor" href="#%(target)s">
      <span class="glyphicon glyphicon-link"></span></a>
    <span class="label label-success">%(method)s</span>
    </div>
    <div class="col-md-5">%(url)s</div>
    <div class="col-md-5">%(desc)s</div>
    <div class="col-md-1">
    <button
       class="btn btn-info btn-sm btn-detail"
       data-target="#%(target)s-detail"
       data-toggle="collapse"
       id="%(target)s-detail-btn"
       >detail</button>
    </div>
</div>"""

    self.body.append(tmpl % node)
    raise nodes.SkipNode


def resolve_rest_references(app, doctree):
    for node in doctree.traverse():
        if isinstance(node, rest_method):
            rest_node = node
            rest_method_section = node.parent
            rest_section = rest_method_section.parent
            gp = rest_section.parent

            # Added required classes to the top section
            rest_section.attributes['classes'].append('api-detail')
            rest_section.attributes['classes'].append('collapse')

            # Pop the title off the collapsed section
            title = rest_section.children.pop(0)
            rest_node['desc'] = title.children[0]

            # In order to get the links in the sidebar to be right, we
            # have to do some id flipping here late in the game. The
            # rest_method_section has basically had a dummy id up
            # until this point just to keep it from colliding with
            # it's parent.
            rest_section.attributes['ids'][0] = (
                "%s-detail" % rest_section.attributes['ids'][0])
            rest_method_section.attributes['ids'][0] = rest_node['target']

            # Pop the overall section into it's grand parent,
            # right before where the current parent lives
            idx = gp.children.index(rest_section)
            rest_section.remove(rest_method_section)
            gp.insert(idx, rest_method_section)


def setup(app):
    app.add_node(rest_method,
                 html=(rest_method_html, None))
    app.add_directive('rest_parameters', RestParametersDirective)
    app.add_directive('rest_method', RestMethodDirective)
    app.add_stylesheet('bootstrap.min.css')
    app.add_stylesheet('api-site.css')
    app.add_javascript('bootstrap.min.js')
    app.add_javascript('api-site.js')
    app.connect('doctree-read', resolve_rest_references)
    return {'version': '0.1'}
