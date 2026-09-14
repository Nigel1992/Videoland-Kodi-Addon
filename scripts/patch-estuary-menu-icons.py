"""Run on LibreELEC to add Videoland list icons to a local Estuary override.

Keeps the system skin untouched. Remove the local skin.estuary directory and
restart Kodi to return to the system version (when created by this script).
"""
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

system = Path('/usr/share/kodi/addons/skin.estuary')
local = Path('/storage/.kodi/addons/skin.estuary')
if not local.exists():
    shutil.copytree(system, local)
variables = local / 'xml/Variables.xml'
text = variables.read_text()
marker = '<variable name="ListWatchedIconVar">'
rule = '<value condition="!String.IsEmpty(ListItem.Property(videoland.menuicon))">$INFO[ListItem.Property(videoland.menuicon)]</value>'
if rule not in text:
    if text.count(marker) != 1:
        raise RuntimeError('Unexpected Estuary structure; no changes applied')
    shutil.copy2(variables, variables.with_suffix('.xml.before-videoland'))
    text = text.replace(marker, marker + '\n\t\t' + rule, 1)
    ET.fromstring(text)
    variables.write_text(text)
# Prefer the local override to the same system skin during addon discovery.
manifest = local / 'addon.xml'
text = manifest.read_text()
version = ET.fromstring(text).get('version')
system_version = ET.parse(system / 'addon.xml').getroot().get('version')
if version == system_version:
    pieces = version.split('.')
    pieces[-1] = str(int(pieces[-1]) + 1)
    text = text.replace('version="' + version + '"', 'version="' + '.'.join(pieces) + '"', 1)
    ET.fromstring(text)
    manifest.write_text(text)
print('Local Estuary override ready; system skin unchanged.')
