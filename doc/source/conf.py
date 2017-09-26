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
#
#  nova documentation build configuration file
#
# Refer to the Sphinx documentation for advice on configuring this file:
#
#   http://www.sphinx-doc.org/en/stable/config.html

import os
import sys

from nova.version import version_info

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
sys.path.insert(0, os.path.abspath('../../'))
sys.path.insert(0, os.path.abspath('../'))
sys.path.insert(0, os.path.abspath('./'))

# -- General configuration ----------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom ones.

extensions = ['sphinx.ext.autodoc',
              'sphinx.ext.todo',
              'openstackdocstheme',
              'sphinx.ext.coverage',
              'sphinx.ext.graphviz',
              'ext.support_matrix',
              'oslo_config.sphinxconfiggen',
              'oslo_config.sphinxext',
              'oslo_policy.sphinxpolicygen',
              'oslo_policy.sphinxext',
              'ext.versioned_notifications',
              'ext.feature_matrix',
              'sphinxcontrib.actdiag',
              'sphinxcontrib.seqdiag',
              ]

# openstackdocstheme options
repository_name = 'openstack/nova'
bug_project = 'nova'
bug_tag = ''

config_generator_config_file = '../../etc/nova/nova-config-generator.conf'
sample_config_basename = '_static/nova'

policy_generator_config_file = '../../etc/nova/nova-policy-generator.conf'
sample_policy_basename = '_static/nova'

actdiag_html_image_format = 'SVG'
actdiag_antialias = True

seqdiag_html_image_format = 'SVG'
seqdiag_antialias = True

todo_include_todos = True

# The suffix of source filenames.
source_suffix = '.rst'

# The master toctree document.
master_doc = 'index'

# General information about the project.
project = u'nova'
copyright = u'2010-present, OpenStack Foundation'

# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
#
# The full version, including alpha/beta/rc tags.
release = version_info.release_string()
# The short X.Y version.
version = version_info.version_string()

# A list of glob-style patterns that should be excluded when looking for
# source files. They are matched against the source file names relative to the
# source directory, using slashes as directory separators on all platforms.
exclude_patterns = [
    'api/nova.wsgi.nova-*',
    'api/nova.tests.*',
]

# If true, the current module name will be prepended to all description
# unit titles (such as .. function::).
add_module_names = False

# If true, sectionauthor and moduleauthor directives will be shown in the
# output. They are ignored by default.
show_authors = False

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = 'sphinx'

# A list of ignored prefixes for module index sorting.
modindex_common_prefix = ['nova.']

# -- Options for man page output ----------------------------------------------

# Grouping the document tree for man pages.
# List of tuples 'sourcefile', 'target', u'title', u'Authors name', 'manual'

_man_pages = [
    ('nova-api-metadata', u'Cloud controller fabric'),
    ('nova-api-os-compute', u'Cloud controller fabric'),
    ('nova-api', u'Cloud controller fabric'),
    ('nova-cells', u'Cloud controller fabric'),
    ('nova-compute', u'Cloud controller fabric'),
    ('nova-console', u'Cloud controller fabric'),
    ('nova-consoleauth', u'Cloud controller fabric'),
    ('nova-dhcpbridge', u'Cloud controller fabric'),
    ('nova-manage', u'Cloud controller fabric'),
    ('nova-network', u'Cloud controller fabric'),
    ('nova-novncproxy', u'Cloud controller fabric'),
    ('nova-spicehtml5proxy', u'Cloud controller fabric'),
    ('nova-serialproxy', u'Cloud controller fabric'),
    ('nova-rootwrap', u'Cloud controller fabric'),
    ('nova-scheduler', u'Cloud controller fabric'),
    ('nova-xvpvncproxy', u'Cloud controller fabric'),
    ('nova-conductor', u'Cloud controller fabric'),
]

man_pages = [
    ('cli/%s' % name, name, description, [u'OpenStack'], 1)
    for name, description in _man_pages]

# -- Options for HTML output --------------------------------------------------

# The theme to use for HTML and HTML Help pages.  Major themes that come with
# Sphinx are currently 'default' and 'sphinxdoc'.
html_theme = 'openstackdocs'

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ['_static']

# Add any paths that contain "extra" files, such as .htaccess or
# robots.txt.
html_extra_path = ['_extra']

# If not '', a 'Last updated on:' timestamp is inserted at every page bottom,
# using the given strftime format.
html_last_updated_fmt = '%Y-%m-%d %H:%M'

# -- Options for LaTeX output -------------------------------------------------

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title, author, documentclass
# [howto/manual]).
latex_documents = [
    ('index', 'Nova.tex', u'Nova Documentation',
     u'OpenStack Foundation', 'manual'),
]

# -- Custom extensions --------------------------------------------------------


def monkey_patch_blockdiag():
    """Monkey patch the blockdiag library.

    The default word wrapping in blockdiag is poor, and breaks on a fixed
    text width rather than on word boundaries. There's a patch submitted to
    resolve this [1]_ but it's unlikely to merge anytime soon.

    TODO: Remove this once blockdiag is bumped to 1.6, which will hopefully
    include the fix.

    .. [1] https://bitbucket.org/blockdiag/blockdiag/pull-requests/16/
    """
    from blockdiag.imagedraw import textfolder

    def splitlabel(text):
        """Split text to lines as generator.

        Every line will be stripped. If text includes characters "\n\n", treat
        as line separator. Ignore '\n' to allow line wrapping.
        """
        lines = [x.strip() for x in text.splitlines()]
        out = []

        for line in lines:
            if line:
                out.append(line)
            else:
                yield ' '.join(out)
                out = []

        yield ' '.join(out)

    def splittext(metrics, text, bound, measure='width'):
        folded = [' ']
        for word in text.split():
            # Try appending the word to the last line
            tryline = ' '.join([folded[-1], word]).strip()
            textsize = metrics.textsize(tryline)
            if getattr(textsize, measure) > bound:
                # Start a new line. Appends `word` even if > bound.
                folded.append(word)
            else:
                folded[-1] = tryline
        return folded

    # monkey patch those babies
    textfolder.splitlabel = splitlabel
    textfolder.splittext = splittext


monkey_patch_blockdiag()
