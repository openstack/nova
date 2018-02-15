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

"""
This provides a sphinx extension able to render from an ini file (from the
doc/source/* directory) a feature matrix into the developer documentation.

It is used via a single directive in the .rst file

  .. feature_matrix:: feature_classification.ini

"""

import re
import sys

from six.moves import configparser

from docutils import nodes
from docutils.parsers import rst


class Matrix(object):
    """Matrix represents the entire feature matrix parsed from an ini file

    This includes:
    * self.features is a list of MatrixFeature instances, the rows and cells
    * self.targets is a dict of (MatrixTarget.key, MatrixTarget), the columns
    """
    def __init__(self):
        self.features = []
        self.targets = {}


class MatrixTarget(object):

    def __init__(self, key, title, driver, hypervisor=None, architecture=None,
                 link=None):
        """MatrixTarget modes a target, a column in the matrix

        This is usually a specific CI system, or collection of related
        deployment configurations.

        :param key: Unique identifier for the hypervisor driver
        :param title: Human friendly name of the hypervisor
        :param driver: Name of the Nova driver
        :param hypervisor: (optional) Name of the hypervisor, if many
        :param architecture: (optional) Name of the architecture, if many
        :param link: (optional) URL to docs about this target
        """
        self.key = key
        self.title = title
        self.driver = driver
        self.hypervisor = hypervisor
        self.architecture = architecture
        self.link = link


class MatrixImplementation(object):

    STATUS_COMPLETE = "complete"
    STATUS_PARTIAL = "partial"
    STATUS_MISSING = "missing"
    STATUS_UKNOWN = "unknown"

    STATUS_ALL = [STATUS_COMPLETE, STATUS_PARTIAL, STATUS_MISSING,
                  STATUS_UKNOWN]

    def __init__(self, status=STATUS_MISSING, notes=None, release=None):
        """MatrixImplementation models a cell in the matrix

        This models the current state of a target for a specific feature

        :param status: One off complete, partial, missing, unknown.
                       See the RST docs for a definition of those.
        :param notes: Arbitrary string describing any caveats of the
                      implementation. Mandatory if status is 'partial'.
        :param release: Letter of the release entry was last updated.
                        i.e. m=mitaka, c=cactus. If not known it is None.
        """
        self.status = status
        self.notes = notes
        self.release = release


class MatrixFeature(object):
    MATURITY_INCOMPLETE = "incomplete"
    MATURITY_EXPERIMENTAL = "experimental"
    MATURITY_COMPLETE = "complete"
    MATURITY_DEPRECATED = "deprecated"

    MATURITY_ALL = [MATURITY_INCOMPLETE, MATURITY_EXPERIMENTAL,
                    MATURITY_COMPLETE, MATURITY_DEPRECATED]

    def __init__(self, key, title,
                 notes=None, cli=None, maturity=None,
                 api_doc_link=None, admin_doc_link=None,
                 tempest_test_uuids=None):
        """MatrixFeature models a row in the matrix

        This initialises ``self.implementations``, which is a dict of
        (MatrixTarget.key, MatrixImplementation)
        This is the list of cells for the given row of the matrix.

        :param key: used as the HTML id for the details, and so in the URL
        :param title: human friendly short title, used in the matrix
        :param notes: Arbitrarily long string describing the feature
        :param cli: list of cli commands related to the feature
        :param maturity: incomplete, experimental, complete or deprecated
                         for a full definition see the rst doc
        :param api_doc_link: URL to the API ref for this feature
        :param admin_doc_link: URL to the admin docs for using this feature
        :param tempest_test_uuids: uuids for tests that validate this feature
        """
        if cli is None:
            cli = []
        if tempest_test_uuids is None:
            tempest_test_uuids = []
        self.key = key
        self.title = title
        self.notes = notes
        self.implementations = {}
        self.cli = cli
        self.maturity = maturity
        self.api_doc_link = api_doc_link
        self.admin_doc_link = admin_doc_link
        self.tempest_test_uuids = tempest_test_uuids


class FeatureMatrixDirective(rst.Directive):
    """The Sphinx directive plugin

    Has single required argument, the filename for the ini file.

    The usage of the directive looks like this::

        .. feature_matrix:: feature_matrix_gp.ini

    """
    required_arguments = 1

    def run(self):
        matrix = self._load_feature_matrix()
        return self._build_markup(matrix)

    def _load_feature_matrix(self):
        """Reads the feature-matrix.ini file and populates an instance
        of the Matrix class with all the data.

        :returns: Matrix instance
        """

        # SafeConfigParser was deprecated in Python 3.2
        if sys.version_info >= (3, 2):
            cfg = configparser.ConfigParser()
        else:
            cfg = configparser.SafeConfigParser()
        env = self.state.document.settings.env
        filename = self.arguments[0]
        rel_fpath, fpath = env.relfn2path(filename)
        with open(fpath) as fp:
            cfg.readfp(fp)

        # This ensures that the docs are rebuilt whenever the
        # .ini file changes
        env.note_dependency(rel_fpath)

        matrix = Matrix()
        matrix.targets = self._get_targets(cfg)
        matrix.features = self._get_features(cfg, matrix.targets)

        return matrix

    def _get_targets(self, cfg):
        """The 'targets' section is special - it lists all the
        hypervisors that this file records data for.
        """

        targets = {}

        for section in cfg.sections():
            if not section.startswith("target."):
                continue

            key = section[7:]
            title = cfg.get(section, "title")
            link = cfg.get(section, "link")
            driver = key.split("-")[0]
            target = MatrixTarget(key, title, driver, link=link)

            targets[key] = target

        return targets

    def _get_features(self, cfg, targets):
        """All sections except 'targets' describe some feature of
        the Nova hypervisor driver implementation.
        """

        features = []

        for section in cfg.sections():
            if section == "targets":
                continue
            if section.startswith("target."):
                continue
            if not cfg.has_option(section, "title"):
                raise Exception(
                    "'title' field missing in '[%s]' section" % section)

            title = cfg.get(section, "title")

            maturity = MatrixFeature.MATURITY_INCOMPLETE
            if cfg.has_option(section, "maturity"):
                maturity = cfg.get(section, "maturity").lower()
                if maturity not in MatrixFeature.MATURITY_ALL:
                    raise Exception(
                        "'maturity' field value '%s' in ['%s']"
                        "section must be %s" %
                        (maturity, section,
                         ",".join(MatrixFeature.MATURITY_ALL)))

            notes = None
            if cfg.has_option(section, "notes"):
                notes = cfg.get(section, "notes")
            cli = []
            if cfg.has_option(section, "cli"):
                cli = cfg.get(section, "cli")
            api_doc_link = None
            if cfg.has_option(section, "api_doc_link"):
                api_doc_link = cfg.get(section, "api_doc_link")
            admin_doc_link = None
            if cfg.has_option(section, "admin_doc_link"):
                admin_doc_link = cfg.get(section, "admin_doc_link")
            tempest_test_uuids = []
            if cfg.has_option(section, "tempest_test_uuids"):
                tempest_test_uuids = cfg.get(section, "tempest_test_uuids")

            feature = MatrixFeature(section, title, notes, cli, maturity,
                api_doc_link, admin_doc_link, tempest_test_uuids)

            # Now we've got the basic feature details, we must process
            # the hypervisor driver implementation for each feature
            for item in cfg.options(section):
                key = item.replace("driver-impl-", "")

                if key not in targets:
                    # TODO(johngarbutt) would be better to skip known list
                    if item.startswith("driver-impl-"):
                        raise Exception(
                            "Driver impl '%s' in '[%s]' not declared" %
                            (item, section))
                    continue

                impl_status_and_release = cfg.get(section, item)
                impl_status_and_release = impl_status_and_release.split(":")
                impl_status = impl_status_and_release[0]
                release = None
                if len(impl_status_and_release) == 2:
                    release = impl_status_and_release[1]

                if impl_status not in MatrixImplementation.STATUS_ALL:
                    raise Exception(
                        "'%s' value '%s' in '[%s]' section must be %s" %
                        (item, impl_status, section,
                         ",".join(MatrixImplementation.STATUS_ALL)))

                noteskey = "driver-notes-" + item[12:]
                notes = None
                if cfg.has_option(section, noteskey):
                    notes = cfg.get(section, noteskey)

                target = targets[key]
                impl = MatrixImplementation(impl_status, notes, release)
                feature.implementations[target.key] = impl

            for key in targets:
                if key not in feature.implementations:
                    raise Exception("'%s' missing in '[%s]' section" %
                                    (key, section))

            features.append(feature)

        return features

    def _build_markup(self, matrix):
        """Constructs the docutils content for the feature matrix"""
        content = []
        self._build_summary(matrix, content)
        self._build_details(matrix, content)
        return content

    def _build_summary(self, matrix, content):
        """Constructs the docutils content for the summary of
        the feature matrix.

        The summary consists of a giant table, with one row
        for each feature, and a column for each hypervisor
        driver. It provides an 'at a glance' summary of the
        status of each driver
        """

        summarytitle = nodes.subtitle(text="Summary")
        summary = nodes.table()
        cols = len(matrix.targets.keys())
        cols += 2
        summarygroup = nodes.tgroup(cols=cols)
        summarybody = nodes.tbody()
        summaryhead = nodes.thead()

        for i in range(cols):
            summarygroup.append(nodes.colspec(colwidth=1))
        summarygroup.append(summaryhead)
        summarygroup.append(summarybody)
        summary.append(summarygroup)
        content.append(summarytitle)
        content.append(summary)

        # This sets up all the column headers - two fixed
        # columns for feature name & status
        header = nodes.row()
        blank = nodes.entry()
        blank.append(nodes.emphasis(text="Feature"))
        header.append(blank)
        blank = nodes.entry()
        blank.append(nodes.emphasis(text="Maturity"))
        header.append(blank)
        summaryhead.append(header)

        # then one column for each hypervisor driver
        impls = sorted(matrix.targets.keys())
        for key in impls:
            target = matrix.targets[key]
            implcol = nodes.entry()
            header.append(implcol)
            if target.link:
                uri = target.link
                target_ref = nodes.reference("", refuri=uri)
                target_txt = nodes.inline()
                implcol.append(target_txt)
                target_txt.append(target_ref)
                target_ref.append(nodes.strong(text=target.title))
            else:
                implcol.append(nodes.strong(text=target.title))

        # We now produce the body of the table, one row for
        # each feature to report on
        for feature in matrix.features:
            item = nodes.row()

            # the hyperlink target name linking to details
            id = re.sub("[^a-zA-Z0-9_]", "_",
                        feature.key)

            # first the to fixed columns for title/status
            keycol = nodes.entry()
            item.append(keycol)
            keyref = nodes.reference(refid=id)
            keytxt = nodes.inline()
            keycol.append(keytxt)
            keytxt.append(keyref)
            keyref.append(nodes.strong(text=feature.title))

            maturitycol = nodes.entry()
            item.append(maturitycol)
            maturitycol.append(nodes.inline(
                text=feature.maturity,
                classes=["fm_maturity_" + feature.maturity]))

            # and then one column for each hypervisor driver
            impls = sorted(matrix.targets.keys())
            for key in impls:
                target = matrix.targets[key]
                impl = feature.implementations[key]
                implcol = nodes.entry()
                item.append(implcol)

                id = re.sub("[^a-zA-Z0-9_]", "_",
                            feature.key + "_" + key)

                implref = nodes.reference(refid=id)
                impltxt = nodes.inline()
                implcol.append(impltxt)
                impltxt.append(implref)

                impl_status = ""
                if impl.status == MatrixImplementation.STATUS_COMPLETE:
                    impl_status = u"\u2714"
                elif impl.status == MatrixImplementation.STATUS_MISSING:
                    impl_status = u"\u2716"
                elif impl.status == MatrixImplementation.STATUS_PARTIAL:
                    impl_status = u"\u2714"
                elif impl.status == MatrixImplementation.STATUS_UKNOWN:
                    impl_status = u"?"

                implref.append(nodes.literal(
                    text=impl_status,
                    classes=["fm_impl_summary", "fm_impl_" + impl.status]))

                if impl.release:
                    implref.append(nodes.inline(text=" %s" % impl.release))

            summarybody.append(item)

    def _build_details(self, matrix, content):
        """Constructs the docutils content for the details of
        the feature matrix.

        This is generated as a bullet list of features.
        Against each feature we provide the description of
        the feature and then the details of the hypervisor
        impls, with any driver specific notes that exist
        """

        detailstitle = nodes.subtitle(text="Details")
        details = nodes.bullet_list()

        content.append(detailstitle)
        content.append(details)

        # One list entry for each feature we're reporting on
        for feature in matrix.features:
            item = nodes.list_item()

            # The hypervisor target name linked from summary table
            id = re.sub("[^a-zA-Z0-9_]", "_",
                        feature.key)

            # Highlight the feature title name
            item.append(nodes.strong(text=feature.title,
                                     ids=[id]))

            if feature.notes is not None:
                para_notes = nodes.paragraph()
                para_notes.append(nodes.inline(text=feature.notes))
                item.append(para_notes)

            self._add_feature_info(item, feature)

            if feature.cli:
                item.append(self._create_cli_paragraph(feature))

            para_divers = nodes.paragraph()
            para_divers.append(nodes.strong(text="drivers:"))
            # A sub-list giving details of each hypervisor target
            impls = nodes.bullet_list()
            for key in feature.implementations:
                target = matrix.targets[key]
                impl = feature.implementations[key]
                subitem = nodes.list_item()

                id = re.sub("[^a-zA-Z0-9_]", "_",
                            feature.key + "_" + key)
                subitem += [
                    nodes.strong(text=target.title + ": "),
                    nodes.literal(text=impl.status,
                                  classes=["fm_impl_" + impl.status],
                                  ids=[id]),
                ]
                if impl.release:
                    release_letter = impl.release.upper()
                    release_text = \
                        ' (updated in "%s" release)' % release_letter
                    subitem.append(nodes.inline(text=release_text))
                if impl.notes is not None:
                    subitem.append(self._create_notes_paragraph(impl.notes))
                impls.append(subitem)

            para_divers.append(impls)
            item.append(para_divers)
            details.append(item)

    def _add_feature_info(self, item, feature):
        para_info = nodes.paragraph()
        para_info.append(nodes.strong(text="info:"))
        info_list = nodes.bullet_list()

        maturity_literal = nodes.literal(text=feature.maturity,
                classes=["fm_maturity_" + feature.maturity])
        self._append_info_list_item(info_list,
                "Maturity", items=[maturity_literal])
        self._append_info_list_item(info_list,
                "API Docs", link=feature.api_doc_link)
        self._append_info_list_item(info_list,
                "Admin Docs", link=feature.admin_doc_link)

        tempest_items = []
        if feature.tempest_test_uuids:
            for uuid in feature.tempest_test_uuids.split(";"):
                base = "https://github.com/openstack/tempest/search?q=%s"
                link = base % uuid
                inline_ref = self._get_uri_ref(link, text=uuid)
                tempest_items.append(inline_ref)
                tempest_items.append(nodes.inline(text=", "))
            # removing trailing punctuation
            tempest_items = tempest_items[:-1]
        self._append_info_list_item(info_list,
                "Tempest tests", items=tempest_items)

        para_info.append(info_list)
        item.append(para_info)

    def _get_uri_ref(self, link, text=None):
        if not text:
            text = link
        ref = nodes.reference("", text, refuri=link)
        inline = nodes.inline()
        inline.append(ref)
        return inline

    def _append_info_list_item(self, info_list, title,
                               text=None, link=None, items=None):
        subitem = nodes.list_item()
        subitem.append(nodes.strong(text="%s: " % title))
        if items:
            for item in items:
                subitem.append(item)
        elif link:
            inline_link = self._get_uri_ref(link, text)
            subitem.append(inline_link)
        elif text:
            subitem.append(nodes.literal(text=text))
        info_list.append(subitem)

    def _create_cli_paragraph(self, feature):
        """Create a paragraph which represents the CLI commands of the feature

        The paragraph will have a bullet list of CLI commands.
        """
        para = nodes.paragraph()
        para.append(nodes.strong(text="CLI commands:"))
        commands = nodes.bullet_list()
        for c in feature.cli.split(";"):
            cli_command = nodes.list_item()
            cli_command += nodes.literal(text=c, classes=["fm_cli"])
            commands.append(cli_command)
        para.append(commands)
        return para

    def _create_notes_paragraph(self, notes):
        """Constructs a paragraph which represents the implementation notes

        The paragraph consists of text and clickable URL nodes if links were
        given in the notes.
        """
        para = nodes.paragraph()
        # links could start with http:// or https://
        link_idxs = [m.start() for m in re.finditer('https?://', notes)]
        start_idx = 0
        for link_idx in link_idxs:
            # assume the notes start with text (could be empty)
            para.append(nodes.inline(text=notes[start_idx:link_idx]))
            # create a URL node until the next text or the end of the notes
            link_end_idx = notes.find(" ", link_idx)
            if link_end_idx == -1:
                # In case the notes end with a link without a blank
                link_end_idx = len(notes)
            uri = notes[link_idx:link_end_idx + 1]
            para.append(nodes.reference("", uri, refuri=uri))
            start_idx = link_end_idx + 1

        # get all text after the last link (could be empty) or all of the
        # text if no link was given
        para.append(nodes.inline(text=notes[start_idx:]))
        return para


def setup(app):
    app.add_directive('feature_matrix', FeatureMatrixDirective)
    app.add_stylesheet('feature-matrix.css')
