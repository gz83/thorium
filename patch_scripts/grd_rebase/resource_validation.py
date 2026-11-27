# Copyright (c) 2026 Alex313031 and gz83.
"""Check the GRD declarations, installer exports and XTB content used by Thorium."""

import ast
from collections import Counter
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from xml.parsers import expat

if __package__:
    from .grit_messages import message_block_to_id, text_to_id
else:
    from grit_messages import message_block_to_id, text_to_id

WINDOWS_LEGACY_GRD = "chrome/app/chromium_strings.grd"
# Final GRIT IDs after Thorium branding. Four messages have a legacy inventory.
# The other five reuse Chromium translations from their original bundles.
WINDOWS_MESSAGE_IDS = {
    WINDOWS_LEGACY_GRD: {
        "IDS_SHORTCUT_NEW_WINDOW": "7339898014177206373",
        "IDS_UNINSTALL_SET_DEFAULT_BROWSER": "2770231113462710648",
        "IDS_UNSUPPORTED_OS_PRE_WIN_XP": "8583645872387407263",
        "IDS_INSTALL_OS_NOT_SUPPORTED": "6178837165959401440",
    },
    "chrome/app/generated_resources.grd": {
        "IDS_CREATE_SHORTCUTS_START_MENU_CHKBOX": "6100736666660498114",
        "IDS_HIDE_ICONS_NOT_SUPPORTED": "3941565636838060942",
    },
    "ui/strings/ui_strings.grd": {
        "IDS_SELECT_UPLOAD_FOLDER_DIALOG_TITLE": "364720409959344976",
        "IDS_SELECT_UPLOAD_FOLDER_DIALOG_UPLOAD_BUTTON": "1243314992276662751",
    },
    "ui/strings/ax_strings.grd": {"IDS_AX_ROLE_OUTPUT": "8711688047404765493"},
}
WINDOWS_LEGACY_MESSAGES = WINDOWS_MESSAGE_IDS[WINDOWS_LEGACY_GRD].keys()
INSTALLER_MESSAGES = {"IDS_INSTALL_OS_NOT_SUPPORTED", "IDS_SHORTCUT_NEW_WINDOW"}
INSTALLER_EXPORTS = "chrome/installer/util/prebuild/create_installer_string_rc.py"
FONT_GRD = "ui/strings/app_locale_settings.grd"
# M159 ships these locale-specific XP overrides. Other locales use the GRD defaults.
FONT_OVERRIDES = {
    "IDS_UI_FONT_FAMILY_XP": {"am": "abyssinica sil", "bn": "Vrinda", "ml": "kartika"},
    "IDS_UI_FONT_SIZE_SCALER_XP": {"bn": "160", "hi": "140", "kn": "142", "ml": "150", "mr": "140", "te": "145"},
    "IDS_WEB_FONT_FAMILY_XP": {
        "bn": "Vrinda", "ja": "Arial,Meiryo,'MS PGothic',sans-serif",
        "ko": "Arial,'Malgun Gothic',Gulim,sans-serif", "ml": "Arial,AnjaliOldLipi,Rachana,Kartika",
        "th": "Tahoma,sans-serif", "zh-CN": "Arial,'Microsoft Yahei',Simsun,sans-serif",
        "zh-TW": "Arial,'Microsoft Jhenghei',PMingLiu,sans-serif",
    },
    "IDS_WEB_FONT_SIZE_XP": {"bn": "110%"},
}
FONT_DEFAULTS = {
    "IDS_UI_FONT_FAMILY_XP": "default", "IDS_UI_FONT_SIZE_SCALER_XP": "100",
    "IDS_WEB_FONT_FAMILY_XP": "Tahoma, sans-serif", "IDS_WEB_FONT_SIZE_XP": "75%",
}
BUNDLE_GRDS = {
    "chromium_strings": WINDOWS_LEGACY_GRD,
    "generated_resources": "chrome/app/generated_resources.grd",
    "components_strings": "components/components_strings.grd",
    "components_chromium_strings": "components/components_chromium_strings.grd",
    "ui_chromeos_strings": "ui/chromeos/ui_chromeos_strings.grd",
    "android_chrome_strings": "chrome/browser/ui/android/strings/android_chrome_strings.grd",
}
CLOSING_TRANSLATION = re.compile(r"</translation\s*>")


def language_key(lang):
    return {"iw": "he", "nb": "no"}.get(lang, lang)


def check_xtb_condition(tag, parent, attrs, path):
    if tag in {"then", "else"} or (
        tag == "if" and (parent != "translationbundle" or not attrs.get("expr", "").strip())
    ):
        raise ValueError(f"{path}: XTB requires a single flat <if expr=...> around translations")
    if parent == "if" and tag != "translation":
        raise ValueError(f"{path}: unexpected <{tag}> inside XTB <if>")


def xtb_spans(text, path, language="", unconditional_ids=()):
    """Locate unconditional translation elements without reserializing the source XML."""
    starts = [0, *(m.end() for m in re.finditer("\n", text))]
    parser = expat.ParserCreate()
    stack = []
    entries = {}
    closing = None

    def position():
        return starts[parser.CurrentLineNumber - 1] + parser.CurrentColumnNumber

    def start(tag, attrs):
        check_xtb_condition(tag, stack[-1][0] if stack else None, attrs, path)
        if not stack and (tag != "translationbundle" or not attrs.get("lang") or
                          language and language_key(attrs["lang"]) != language):
            raise ValueError(f"{path}: invalid translation bundle or language (expected {language})")
        if len(stack) > 1 and tag == "translation" and attrs.get("id") in unconditional_ids:
            raise ValueError(f"{path}: conditional entry for reviewed translation {attrs['id']}")
        stack.append((tag, attrs.get("id"), position()))

    def end(tag):
        nonlocal closing
        _, ident, offset = stack.pop()
        if not stack:
            closing = position()
        elif len(stack) == 1 and tag == "translation":
            if not ident or ident in entries:
                raise ValueError(f"{path}: missing or duplicate translation ID {ident}")
            end_offset = position()
            match = CLOSING_TRANSLATION.match(text, end_offset)
            if match:
                end_offset = match.end()
            entries[ident] = (offset, end_offset)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(text, True)
    except expat.ExpatError as error:
        raise ValueError(f"{path}: {error}") from error
    if closing is None or not text.startswith("</translationbundle", closing):
        raise ValueError(f"{path}: missing closing translationbundle tag")
    return entries, closing


def windows_condition(expr):
    """Evaluate platform predicates used by the audited Windows resources."""
    def evaluate(node):
        if isinstance(node, ast.Name) and node.id in {
            "is_win", "is_linux", "is_macosx", "is_posix", "is_android", "is_ios",
            "is_chromeos", "is_fuchsia", "is_bsd",
        }:
            return node.id == "is_win"
        if isinstance(node, ast.Constant) and isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not evaluate(node.operand)
        if isinstance(node, ast.BoolOp):
            operands = (evaluate(child) for child in node.values)
            return all(operands) if isinstance(node.op, ast.And) else any(operands)
        raise ValueError(f"unknown condition on a reviewed Windows resource: {expr}")
    return evaluate(ast.parse(expr, mode="eval").body)


def windows_nodes(root, selector, attribute, names):
    """Filter only the selected nodes, so unrelated product flags need no defaults."""
    parents = {child: parent for parent in root.iter() for child in parent}
    for node in root.findall(selector):
        if names is not None and node.get(attribute) not in names:
            continue
        child = node
        while child in parents:
            parent = parents[child]
            if parent.tag == "if" and windows_condition(parent.attrib["expr"]) == (child.tag == "else"):
                break
            child = parent
        else:
            yield node


def registered_files(grd_path, grd, windows=False):
    nodes = (windows_nodes(grd, ".//translations//file", None, None) if windows
             else grd.findall(".//translations//file"))
    files = {}
    for node in nodes:
        path = (Path(grd_path).parent / node.attrib["path"]).as_posix()
        lang = language_key(node.attrib["lang"])
        if path in files or (windows and lang in files.values()):
            raise ValueError(f"{grd_path}: duplicate XTB registration {path}")
        files[path] = lang
    if windows:
        packages = windows_nodes(grd, ".//outputs//output", "type", {"data_package"})
        prefix = "branded_strings" if grd_path == WINDOWS_LEGACY_GRD else Path(grd_path).stem
        languages = set()
        for node in packages:
            lang = language_key(node.attrib["lang"])
            suffix = {"en": "en-US", "no": "nb"}.get(lang, lang)
            filename = node.attrib["filename"]
            if lang in languages or filename != f"{prefix}_{suffix}.pak":
                raise ValueError(f"{grd_path}: incorrect or duplicate Windows pack {filename} for {lang}")
            languages.add(lang)
        missing = set(files.values()) - languages
        if missing:
            raise ValueError(f"{grd_path}: missing Windows language pack outputs {sorted(missing)}")
        if grd_path in WINDOWS_MESSAGE_IDS:
            if "en" not in languages:
                raise ValueError(f"{grd_path}: missing Windows source-language pack")
            untranslated = languages - set(files.values()) - {"en", "en-XA", "ar-XB"}
            if untranslated:
                raise ValueError(f"{grd_path}: missing XTB registrations for {sorted(untranslated)}")
    return files


def read_exports(source):
    tree = ast.parse(source.read_bytes(), filename=str(source))

    def literal(name):
        declarations = [s for s in tree.body if isinstance(s, ast.Assign)
                        and any(isinstance(t, ast.Name) and t.id == name for t in s.targets)]
        uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == name]
        if len(declarations) != 1 or len(uses) != 1:
            raise ValueError(f"{source}: expected one literal installer {name} declaration")
        return ast.literal_eval(declarations[0].value)

    values = literal("STRING_IDS")
    if not isinstance(values, (list, tuple)) or not all(isinstance(v, str) for v in values):
        raise ValueError(f"{source}: invalid installer STRING_IDS")
    if len(set(values)) != len(values):
        raise ValueError(f"{source}: duplicate installer export")
    exports = set(values)
    modes = literal("MODE_SPECIFIC_STRINGS")
    if not isinstance(modes, dict):
        raise ValueError(f"{source}: invalid MODE_SPECIFIC_STRINGS")
    for name, by_brand in modes.items():
        names = by_brand.get("chromium") if isinstance(by_brand, dict) else None
        if (name not in values or not isinstance(names, list) or not names
                or not all(isinstance(n, str) for n in names)):
            raise ValueError(f"{source}: missing Chromium mode export for {name}")
        exports.update(names)
    return exports


def check_legacy_profile(source, requested):
    grd = ET.parse(source / WINDOWS_LEGACY_GRD).getroot()
    installer = source / INSTALLER_EXPORTS
    exports = read_exports(installer) if installer.is_file() else set()
    names = {node.get("name") for node in grd.iter("message")}
    if not (requested or (source / "base/win/legacy_locale.h").is_file() or
            "IDS_SHORTCUT_NEW_WINDOW" in exports or
            (WINDOWS_LEGACY_MESSAGES - {"IDS_INSTALL_OS_NOT_SUPPORTED"}) & names):
        return None
    missing = INSTALLER_MESSAGES - exports
    if missing:
        raise ValueError(f"{INSTALLER_EXPORTS}: missing installer exports {sorted(missing)}")
    return grd


def active_messages(grd_path, grd, names):
    messages = {}
    for node in windows_nodes(grd, ".//messages//message", "name", names):
        name = node.attrib["name"]
        if name in messages or node.get("translateable") == "false":
            raise ValueError(f"{grd_path}: invalid or duplicate Windows message {name}")
        messages[name] = node
    missing = names - messages.keys()
    if missing:
        raise ValueError(f"{grd_path}: missing active Windows messages {sorted(missing)}")
    return messages


def windows_resource_requirements(source, grds):
    """Read the effective Windows messages and locale registrations after branding."""
    requirements = {}
    for path, expected_ids in WINDOWS_MESSAGE_IDS.items():
        root = grds[path] if path in grds else ET.parse(source / path).getroot()
        messages = active_messages(path, root, expected_ids.keys())
        for name, node in messages.items():
            actual = message_block_to_id(ET.tostring(node, encoding="unicode"))
            if actual != expected_ids[name]:
                raise ValueError(f"{path}: {name} has GRIT ID {actual}, expected {expected_ids[name]}")
        files = registered_files(path, root, windows=True)
        requirements[path] = (messages, files)

    supported = set(requirements[WINDOWS_LEGACY_GRD][1].values())
    for path, (_, files) in requirements.items():
        missing = supported - set(files.values())
        if missing:
            raise ValueError(f"{path}: missing Windows locale registrations {sorted(missing)}")
    return requirements


def read_bundle(source, path, language):
    root = ET.parse(source / path).getroot()
    if root.tag != "translationbundle" or not root.get("lang"):
        raise ValueError(f"{path}: missing translationbundle language")
    if language and language_key(root.attrib["lang"]) != language:
        raise ValueError(f"{path}: expected {language}, found {root.attrib['lang']}")
    if root.find(".//then") is not None or root.find(".//else") is not None:
        raise ValueError(f"{path}: XTB does not support <then> or <else>")
    direct = set(root.findall("if"))
    for condition in root.iter("if"):
        check_xtb_condition("if", "translationbundle" if condition in direct else None, condition.attrib, path)
        for child in condition:
            check_xtb_condition(child.tag, "if", child.attrib, path)
    return root


def check_installer(source):
    exports = read_exports(source / INSTALLER_EXPORTS)
    required = set()
    installer = source / "chrome/installer"
    for pattern in ("*.cc", "*.h"):
        for path in installer.rglob(pattern):
            if any("test" in part for part in path.relative_to(installer).parts):
                continue
            required.update(re.findall(r"\b(IDS_\w+)_BASE\b", path.read_text(encoding="utf-8")))
    if required - exports:
        raise ValueError(f"{INSTALLER_EXPORTS}: missing installer exports {sorted(required - exports)}")

    grd = ET.parse(source / WINDOWS_LEGACY_GRD).getroot()
    # The native RC generator takes the last declaration of each name and
    # fingerprints message text plus placeholder names, without GRIT meanings.
    messages = {n.attrib["name"]: n for n in grd.iter("message") if n.attrib["name"] in exports}
    if exports - messages.keys():
        raise ValueError(f"{WINDOWS_LEGACY_GRD}: missing installer messages {sorted(exports - messages.keys())}")
    expected = {}
    for name, msg in messages.items():
        if msg.get("translateable") == "false" and name == "IDS_PRODUCT_NAME":
            continue
        text = (msg.text or "") + "".join(ph.attrib["name"] + (ph.tail or "") for ph in msg)
        expected[text_to_id(text.strip())] = (name, [ph.attrib["name"] for ph in msg])

    files = registered_files(WINDOWS_LEGACY_GRD, grd, windows=True)
    folder = source / "chrome/app/resources"
    on_disk = {p.relative_to(source).as_posix() for p in folder.glob("chromium_strings*.xtb")}
    if on_disk != files.keys():
        raise ValueError(f"{WINDOWS_LEGACY_GRD}: installer XTB registration mismatch {sorted(on_disk ^ files.keys())}")
    for path, lang in files.items():
        bundle = read_bundle(source, path, lang)
        seen = set()
        # Unlike GRIT, the native installer reads all conditional branches.
        # An exported translation must also work as a standalone RC string.
        for node in bundle.findall("./*//translation"):
            if node.get("id") in expected:
                raise ValueError(f"{path}: conditional installer translation {expected[node.attrib['id']][0]}")
        for node in bundle.findall("translation"):
            ident = node.attrib["id"]
            if ident not in expected:
                continue
            name, placeholders = expected[ident]
            # create_string_rc.py substitutes installer arguments in occurrence order.
            if (ident in seen or any(child.tag != "ph" for child in node)
                    or [child.get("name") for child in node] != placeholders
                    or not (placeholders or (node.text or "").strip())):
                raise ValueError(f"{path}: invalid installer translation for {name}")
            seen.add(ident)
        if seen != expected.keys():
            names = sorted(expected[i][0] for i in expected.keys() - seen)
            raise ValueError(f"{path}: missing installer translations for {names}")


def check_xp_fonts(source):
    grd = ET.parse(source / FONT_GRD).getroot()
    messages = active_messages(FONT_GRD, grd, FONT_DEFAULTS.keys())
    for name, node in messages.items():
        if (message_block_to_id(ET.tostring(node, encoding="unicode")) != name
                or len(node) or (node.text or "").strip() != FONT_DEFAULTS[name]):
            raise ValueError(f"{FONT_GRD}: incorrect XP font declaration {name}")
    expected = {(lang, name): value for name, locales in FONT_OVERRIDES.items() for lang, value in locales.items()}
    for path, lang in registered_files(FONT_GRD, grd, windows=True).items():
        root = read_bundle(source, path, lang)
        seen = set()
        for node in windows_nodes(root, ".//translation", "id", FONT_OVERRIDES):
            name = node.attrib["id"]
            if name in seen:
                raise ValueError(f"{path}: duplicate Windows font override {name}")
            seen.add(name)
            key = (lang, name)
            if len(node) or (node.text or "").strip() != expected.pop(key, FONT_DEFAULTS[name]):
                raise ValueError(f"{path}: incorrect {name}")
    if expected:
        raise ValueError(f"{FONT_GRD}: missing XP font overrides {sorted(expected)}")


def normalized_block(node):
    node.tail = None
    return ET.tostring(node, encoding="unicode")


def missing_windows_translations(source, requirements, planned=()):
    for grd_path, (messages, files) in requirements.items():
        ids = WINDOWS_MESSAGE_IDS[grd_path]
        placeholders = {ids[name]: Counter(ph.attrib["name"] for ph in node.iter("ph"))
                        for name, node in messages.items()}
        for path, lang in files.items():
            expected = {ident for ident in placeholders if (path, ident) not in planned}
            if not expected:
                continue
            bundle = read_bundle(source, path, lang)
            present = set()
            for node in windows_nodes(bundle, ".//translation", "id", expected):
                ident = node.attrib["id"]
                if ident in present:
                    raise ValueError(f"{path}: duplicate Windows translation {ident}")
                if not "".join(node.itertext()).strip():
                    raise ValueError(f"{path}: empty Windows translation {ident}")
                if Counter(ph.get("name") for ph in node.iter("ph")) != placeholders[ident]:
                    raise ValueError(f"{path}: incorrect placeholders for Windows translation {ident}")
                present.add(ident)
            for name, ident in ids.items():
                if ident in expected and ident not in present:
                    yield grd_path, name, ident, lang, path


def check_inventory(source, groups, legacy_grd):
    check_installer(source)
    requirements = {}
    if legacy_grd is not None:
        requirements = windows_resource_requirements(source, {WINDOWS_LEGACY_GRD: legacy_grd})
        check_xp_fonts(source)

    registrations = {path: files for path, (_, files) in requirements.items()}
    missing_entries = set()
    differing_count = 0
    for path, additions in groups.items():
        first = additions[0]
        grd_path = BUNDLE_GRDS.get(first.bundle)
        if grd_path and grd_path not in registrations:
            grd = ET.parse(source / grd_path).getroot()
            registrations[grd_path] = registered_files(grd_path, grd)
        lang = first.locale
        if grd_path:
            registry = registrations[grd_path]
            if path not in registry or (lang and registry[path] != lang):
                raise ValueError(f"{grd_path}: missing or incorrect registration for {path}")
            lang = registry[path]
        root = read_bundle(source, path, lang)
        # These inventories describe unconditional translations in shared bundles.
        reviewed = {row.translation_id for row in additions}
        for node in root.findall("./*//translation"):
            if node.get("id") in reviewed:
                raise ValueError(f"{path}: conditional entry for reviewed translation {node.attrib['id']}")
        found = {}
        for node in root.findall("translation"):
            ident = node.attrib["id"]
            if ident in found:
                raise ValueError(f"{path}: duplicate translation ID {ident}")
            found[ident] = node
        missing = differing = 0
        for row in additions:
            node = found.get(row.translation_id)
            if node is None:
                missing += 1
                missing_entries.add((path, row.translation_id))
            elif normalized_block(node) != normalized_block(ET.fromstring(row.block)):
                differing += 1
        if missing or differing:
            print(f"{path}: {missing} missing, {differing} differing")
        differing_count += differing
    for _, name, ident, _, path in missing_windows_translations(source, requirements):
        print(f"{path}: missing {name} ({ident})")
        missing_entries.add((path, ident))
    total = sum(map(len, groups.values()))
    missing_count = len(missing_entries)
    print(f"checked {total} Thorium translations across {len(groups)} XTB files: "
          f"{missing_count} missing, {differing_count} differing")
    return int(bool(missing_count or differing_count))
