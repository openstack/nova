# Copyright (C) 2014 Red Hat, Inc.
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

"""
This provides a sphinx extension able to render the source/support-matrix.ini
file into the developer documentation.

It is used via a single directive in the .rst file

  .. support_matrix::

"""

import re
import sys

from six.moves import configparser

from docutils import nodes
from docutils.parsers import rst


class SupportMatrix(object):
    """Represents the entire support matrix for Nova virt drivers
    """

    def __init__(self):
        # List of SupportMatrixFeature instances, describing
        # all the features present in Nova virt drivers
        self.features = []

        # Dict of (name, SupportMatrixTarget) enumerating
        # all the hypervisor drivers that have data recorded
        # for them in self.features. The 'name' dict key is
        # the value from the SupportMatrixTarget.key attribute
        self.targets = {}


class SupportMatrixFeature(object):

    STATUS_MANDATORY = "mandatory"
    STATUS_CHOICE = "choice"
    STATUS_CONDITION = "condition"
    STATUS_OPTIONAL = "optional"

    STATUS_ALL = [STATUS_MANDATORY, STATUS_CHOICE,
                  STATUS_CONDITION, STATUS_OPTIONAL]

    def __init__(self, key, title, status=STATUS_OPTIONAL,
                 group=None, notes=None, cli=None):
        if not cli:
            cli = []
        # A unique key (eg 'foo.bar.wizz') to identify the feature
        self.key = key
        # A human friendly short title for the feature
        self.title = title
        # One of the status constants
        self.status = status
        # Detail string if status was choice/condition
        self.group = group
        # Arbitrarily long string describing the feature in detail
        self.notes = notes
        # Dict of (name, SupportMatrixImplementation) detailing
        # the implementation for each hypervisor driver. The
        # 'name' dict key is the value from SupportMatrixTarget.key
        # for the hypervisor in question
        self.implementations = {}
        # A list of CLI commands which are related to that feature
        self.cli = cli


class SupportMatrixImplementation(object):

    STATUS_COMPLETE = "complete"
    STATUS_PARTIAL = "partial"
    STATUS_MISSING = "missing"
    STATUS_UKNOWN = "unknown"

    STATUS_ALL = [STATUS_COMPLETE, STATUS_PARTIAL, STATUS_MISSING,
                  STATUS_UKNOWN]

    def __init__(self, status=STATUS_MISSING, notes=None):
        # One of the status constants detailing the implementation
        # level
        self.status = status
        # Arbitrary string describing any caveats of the implementation.
        # Mandatory if status is 'partial', optional otherwise.
        self.notes = notes


class SupportMatrixTarget(object):

    def __init__(self, key, title, driver, hypervisor=None, architecture=None):
        """:param key: Unique identifier for the hypervisor driver
        :param title: Human friendly name of the hypervisor
        :param driver: Name of the Nova driver
        :param hypervisor: (optional) Name of the hypervisor, if many
        :param architecture: (optional) Name of the architecture, if many
        """
        self.key = key
        self.title = title
        self.driver = driver
        self.hypervisor = hypervisor
        self.architecture = architecture


class SupportMatrixDirective(rst.Directive):

    # The argument is the filename, e.g. support-matrix.ini
    required_arguments = 1

    def run(self):
        matrix = self._load_support_matrix()
        return self._build_markup(matrix)

    def _load_support_matrix(self):
        """Reads the support-matrix.ini file and populates an instance
        of the SupportMatrix class with all the data.

        :returns: SupportMatrix instance
        """

        # SafeConfigParser was deprecated in Python 3.2
        if sys.version_info >= (3, 2):
            cfg = configparser.ConfigParser()
        else:
            cfg = configparser.SafeConfigParser()
        env = self.state.document.settings.env
        fname = self.arguments[0]
        rel_fpath, fpath = env.relfn2path(fname)
        with open(fpath) as fp:
            cfg.readfp(fp)

        # This ensures that the docs are rebuilt whenever the
        # .ini file changes
        env.note_dependency(rel_fpath)

        matrix = SupportMatrix()
        matrix.targets = self._get_targets(cfg)
        matrix.features = self._get_features(cfg, matrix.targets)

        return matrix

    def _get_targets(self, cfg):
        # The 'targets' section is special - it lists all the
        # hypervisors that this file records data for

        targets = {}

        for item in cfg.options("targets"):
            if not item.startswith("driver-impl-"):
                continue

            # The driver string will optionally contain
            # a hypervisor and architecture qualifier
            # so we expect between 1 and 3 components
            # in the name
            key = item[12:]
            title = cfg.get("targets", item)
            name = key.split("-")
            if len(name) == 1:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0])
            elif len(name) == 2:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0],
                                             name[1])
            elif len(name) == 3:
                target = SupportMatrixTarget(key,
                                             title,
                                             name[0],
                                             name[1],
                                             name[2])
            else:
                raise Exception("'%s' field is malformed in '[%s]' section" %
                                (item, "DEFAULT"))

            targets[key] = target

        return targets

    def _get_features(self, cfg, targets):
        # All sections except 'targets' describe some feature of
        # the Nova hypervisor driver implementation

        features = []

        for section in cfg.sections():
            if section == "targets":
                continue
            if not cfg.has_option(section, "title"):
                raise Exception(
                    "'title' field missing in '[%s]' section" % section)

            title = cfg.get(section, "title")

            status = SupportMatrixFeature.STATUS_OPTIONAL
            if cfg.has_option(section, "status"):
                # The value is a string  "status(group)" where
                # the 'group' part is optional
                status = cfg.get(section, "status")
                offset = status.find("(")
                group = None
                if offset != -1:
                    group = status[offset + 1:-1]
                    status = status[0:offset]

                if status not in SupportMatrixFeature.STATUS_ALL:
                    raise Exception(
                        "'status' field value '%s' in ['%s']"
                        "section must be %s" %
                        (status, section,
                         ",".join(SupportMatrixFeature.STATUS_ALL)))

            notes = None
            if cfg.has_option(section, "notes"):
                notes = cfg.get(section, "notes")
            cli = []
            if cfg.has_option(section, "cli"):
                cli = cfg.get(section, "cli")
            feature = SupportMatrixFeature(section,
                                           title,
                                           status,
                                           group,
                                           notes,
                                           cli)

            # Now we've got the basic feature details, we must process
            # the hypervisor driver implementation for each feature
            for item in cfg.options(section):
                if not item.startswith("driver-impl-"):
                    continue

                key = item[12:]
                if key not in targets:
                    raise Exception(
                        "Driver impl '%s' in '[%s]' not declared" %
                        (item, section))

                status = cfg.get(section, item)
                if status not in SupportMatrixImplementation.STATUS_ALL:
                    raise Exception(
                        "'%s' value '%s' in '[%s]' section must be %s" %
                        (item, status, section,
                         ",".join(SupportMatrixImplementation.STATUS_ALL)))

                noteskey = "driver-notes-" + item[12:]
                notes = None
                if cfg.has_option(section, noteskey):
                    notes = cfg.get(section, noteskey)

                target = targets[key]
                impl = SupportMatrixImplementation(status,
                                                   notes)
                feature.implementations[target.key] = impl

            for key in targets:
                if key not in feature.implementations:
                    raise Exception("'%s' missing in '[%s]' section" %
                                    (key, section))

            features.append(feature)

        return features

    def _build_markup(self, matrix):
        """Constructs the docutils content for the support matrix
        """
        content = []
        self._build_summary(matrix, content)
        self._build_details(matrix, content)
        self._build_notes(content)
        return content

    def _build_summary(self, matrix, content):
        """Constructs the docutils content for the summary of
        the support matrix.

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
        blank.append(nodes.emphasis(text="Status"))
        header.append(blank)
        summaryhead.append(header)

        # then one column for each hypervisor driver
        impls = list(matrix.targets.keys())
        impls.sort()
        for key in impls:
            target = matrix.targets[key]
            implcol = nodes.entry()
            header.append(implcol)
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

            statuscol = nodes.entry()
            item.append(statuscol)
            statuscol.append(nodes.inline(
                text=feature.status,
                classes=["sp_feature_" + feature.status]))

            # and then one column for each hypervisor driver
            impls = list(matrix.targets.keys())
            impls.sort()
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

                status = ""
                if impl.status == SupportMatrixImplementation.STATUS_COMPLETE:
                    status = u"\u2714"
                elif impl.status == SupportMatrixImplementation.STATUS_MISSING:
                    status = u"\u2716"
                elif impl.status == SupportMatrixImplementation.STATUS_PARTIAL:
                    status = u"\u2714"
                elif impl.status == SupportMatrixImplementation.STATUS_UKNOWN:
                    status = u"?"

                implref.append(nodes.literal(
                    text=status,
                    classes=["sp_impl_summary", "sp_impl_" + impl.status]))

            summarybody.append(item)

    def _build_details(self, matrix, content):
        """Constructs the docutils content for the details of
        the support matrix.

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

            status = feature.status
            if feature.group is not None:
                status += "(" + feature.group + ")"

            # The hypervisor target name linked from summary table
            id = re.sub("[^a-zA-Z0-9_]", "_",
                        feature.key)

            # Highlight the feature title name
            item.append(nodes.strong(text=feature.title,
                                     ids=[id]))

            para = nodes.paragraph()
            para.append(nodes.strong(text="Status: " + status + ". "))
            if feature.notes is not None:
                para.append(nodes.inline(text=feature.notes))
            item.append(para)

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
                                  classes=["sp_impl_" + impl.status],
                                  ids=[id]),
                ]
                if impl.notes is not None:
                    subitem.append(self._create_notes_paragraph(impl.notes))
                impls.append(subitem)

            para_divers.append(impls)
            item.append(para_divers)
            details.append(item)

    def _build_notes(self, content):
        """Constructs a list of notes content for the support matrix.

        This is generated as a bullet list.
        """
        notestitle = nodes.subtitle(text="Notes")
        notes = nodes.bullet_list()

        content.append(notestitle)
        content.append(notes)

        NOTES = [
                "Virtuozzo was formerly named Parallels in this document"
                ]

        for note in NOTES:
            item = nodes.list_item()
            item.append(nodes.strong(text=note))
            notes.append(item)

    def _create_cli_paragraph(self, feature):
        """Create a paragraph which represents the CLI commands of the feature

        The paragraph will have a bullet list of CLI commands.
        """
        para = nodes.paragraph()
        para.append(nodes.strong(text="CLI commands:"))
        commands = nodes.bullet_list()
        for c in feature.cli.split(";"):
            cli_command = nodes.list_item()
            cli_command += nodes.literal(text=c, classes=["sp_cli"])
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
    app.add_directive('support_matrix', SupportMatrixDirective)
    app.add_stylesheet('support-matrix.css')
