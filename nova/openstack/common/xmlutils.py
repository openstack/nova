# Copyright 2013 IBM Corp.
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

from xml.dom import minidom
from xml.parsers import expat
from xml import sax
from xml.sax import expatreader


class ProtectedExpatParser(expatreader.ExpatParser):
    """An expat parser which disables DTD's and entities by default."""

    def __init__(self, forbid_dtd=True, forbid_entities=True,
                 *args, **kwargs):
        # Python 2.x old style class
        expatreader.ExpatParser.__init__(self, *args, **kwargs)
        self.forbid_dtd = forbid_dtd
        self.forbid_entities = forbid_entities

    def start_doctype_decl(self, name, sysid, pubid, has_internal_subset):
        raise ValueError("Inline DTD forbidden")

    def entity_decl(self, entityName, is_parameter_entity, value, base,
                    systemId, publicId, notationName):
        raise ValueError("<!ENTITY> entity declaration forbidden")

    def unparsed_entity_decl(self, name, base, sysid, pubid, notation_name):
        # expat 1.2
        raise ValueError("<!ENTITY> unparsed entity forbidden")

    def external_entity_ref(self, context, base, systemId, publicId):
        raise ValueError("<!ENTITY> external entity forbidden")

    def notation_decl(self, name, base, sysid, pubid):
        raise ValueError("<!ENTITY> notation forbidden")

    def reset(self):
        expatreader.ExpatParser.reset(self)
        if self.forbid_dtd:
            self._parser.StartDoctypeDeclHandler = self.start_doctype_decl
            self._parser.EndDoctypeDeclHandler = None
        if self.forbid_entities:
            self._parser.EntityDeclHandler = self.entity_decl
            self._parser.UnparsedEntityDeclHandler = self.unparsed_entity_decl
            self._parser.ExternalEntityRefHandler = self.external_entity_ref
            self._parser.NotationDeclHandler = self.notation_decl
            try:
                self._parser.SkippedEntityHandler = None
            except AttributeError:
                # some pyexpat versions do not support SkippedEntity
                pass


def safe_minidom_parse_string(xml_string):
    """Parse an XML string using minidom safely.

    """
    try:
        return minidom.parseString(xml_string, parser=ProtectedExpatParser())
    except sax.SAXParseException:
        raise expat.ExpatError()
