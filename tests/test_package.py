from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLIST = os.path.join(ROOT, "workflow", "info.plist")
BUILD = os.path.join(ROOT, "build.sh")


def load_plist():
    with open(PLIST, "rb") as f:
        return plistlib.load(f)


class PlistTests(unittest.TestCase):
    def setUp(self):
        self.p = load_plist()
        self.objs = {o["uid"]: o for o in self.p["objects"]}

    def by_type(self, t):
        return [o for o in self.p["objects"] if o["type"] == t]

    def test_plutil_lint(self):
        r = subprocess.run(["plutil", "-lint", PLIST], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_top_level(self):
        self.assertEqual(self.p["bundleid"], "com.oleggohman.clipboard-semantic-search")
        self.assertEqual(self.p["name"], "Clipboard Semantic Search")
        self.assertEqual(self.p["createdby"], "Oleg Gohman")
        self.assertEqual(self.p["webaddress"], "")
        self.assertEqual(self.p["variablesdontexport"], [])
        self.assertTrue(self.p["description"])
        self.assertTrue(self.p["readme"])

    def test_objects_have_uid_type_version_config(self):
        self.assertEqual(len(self.p["objects"]), 3)
        for o in self.p["objects"]:
            for k in ("uid", "type", "version", "config"):
                self.assertIn(k, o)
            self.assertEqual(o["uid"], o["uid"].upper())
            self.assertIn(o["uid"], self.p["uidata"])

    def test_script_filter(self):
        sfs = self.by_type("alfred.workflow.input.scriptfilter")
        self.assertEqual(len(sfs), 1)
        sf = sfs[0]
        self.assertEqual(sf["version"], 3)
        c = sf["config"]
        self.assertEqual(c["keyword"], "cs")
        self.assertEqual(c["script"], '/usr/bin/python3 cs.py "$1"')
        self.assertEqual(c["scriptfile"], "")
        self.assertEqual(c["type"], 0)
        self.assertEqual(c["scriptargtype"], 1)
        self.assertEqual(c["argumenttype"], 0)
        self.assertIs(c["withspace"], True)
        self.assertEqual(c["queuemode"], 1)
        self.assertEqual(c["queuedelaymode"], 0)
        self.assertIs(c["queuedelayimmediatelyinitially"], False)
        self.assertEqual(c["queuedelaycustom"], 3)
        self.assertIs(c["alfredfiltersresults"], False)
        self.assertEqual(c["escaping"], 102)
        self.assertEqual(c["title"], "Clipboard Semantic Search")
        self.assertEqual(c["runningsubtext"], "Asking on-device model…")
        self.assertIn("subtext", c)

    def test_clipboard_outputs(self):
        outs = self.by_type("alfred.workflow.output.clipboard")
        self.assertEqual(len(outs), 2)
        self.assertEqual(sorted(o["config"]["autopaste"] for o in outs), [False, True])
        for o in outs:
            self.assertEqual(o["version"], 3)
            self.assertEqual(o["config"]["clipboardtext"], "{query}")
            # clip text must be copied verbatim, and not re-recorded in history
            self.assertIs(o["config"]["ignoredynamicplaceholders"], True)
            self.assertIs(o["config"]["transient"], True)

    def test_connections(self):
        sf = self.by_type("alfred.workflow.input.scriptfilter")[0]
        conns = self.p["connections"][sf["uid"]]
        self.assertEqual(len(conns), 3)
        for c in conns:
            self.assertIs(c["vitoclose"], False)
            self.assertIn("modifiersubtext", c)
        got = {c["modifiers"]: self.objs[c["destinationuid"]] for c in conns}
        self.assertEqual(set(got), {0, 1048576, 524288})
        self.assertIs(got[0]["config"]["autopaste"], True)
        self.assertIs(got[1048576]["config"]["autopaste"], True)
        self.assertIs(got[524288]["config"]["autopaste"], False)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out, ignore_errors=True)

    def test_build_contents(self):
        # Stray files that must be excluded from the archive.
        pyc_dir = os.path.join(ROOT, "workflow", "__pycache__")
        made = not os.path.exists(pyc_dir)
        os.makedirs(pyc_dir, exist_ok=True)
        stray = os.path.join(pyc_dir, "x.cpython-39.pyc")
        ds = os.path.join(ROOT, "workflow", ".DS_Store")
        ds_existed = os.path.exists(ds)
        with open(stray, "wb") as f:
            f.write(b"x")
        with open(ds, "wb") as f:
            f.write(b"x")
        try:
            r = subprocess.run(["bash", BUILD, self.out], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        finally:
            os.remove(stray)
            if made:
                shutil.rmtree(pyc_dir, ignore_errors=True)
            if not ds_existed:
                os.remove(ds)
        path = os.path.join(self.out, "ClipboardSemanticSearch.alfredworkflow")
        self.assertTrue(os.path.isfile(path))
        names = zipfile.ZipFile(path).namelist()
        for n in ("info.plist", "cs.py", "regexgen.py", "clipdb.py", "alfred.py"):
            self.assertIn(n, names)
        for n in names:
            self.assertNotIn("__pycache__", n)
            self.assertFalse(n.endswith(".pyc"))
            self.assertNotIn(".DS_Store", n)
            self.assertFalse(n.startswith("tests"))

    def test_build_executable(self):
        self.assertTrue(os.access(BUILD, os.X_OK))


RELEASE = os.path.join(ROOT, "scripts", "release.sh")
BUMP = os.path.join(ROOT, "scripts", "bump_version.py")
RELEASE_YML = os.path.join(ROOT, ".github", "workflows", "release.yml")


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.copy = os.path.join(self.tmp, "info.plist")
        shutil.copy(PLIST, self.copy)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def bump(self, version):
        return subprocess.run(["/usr/bin/python3", BUMP, self.copy, version],
                              capture_output=True, text=True)

    def test_bump_changes_only_version_line(self):
        with open(PLIST, encoding="utf-8") as f:
            before = f.read().splitlines()
        r = self.bump("9.8.7")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.copy, encoding="utf-8") as f:
            after = f.read().splitlines()
        changed = [(a, b) for a, b in zip(before, after) if a != b]
        self.assertEqual(len(before), len(after))
        self.assertEqual(len(changed), 1)
        self.assertIn("<string>9.8.7</string>", changed[0][1])
        with open(self.copy, "rb") as f:
            bumped = plistlib.load(f)
        original = load_plist()
        self.assertEqual(bumped["version"], "9.8.7")
        bumped.pop("version")
        original.pop("version")
        self.assertEqual(bumped, original)

    def test_bump_rejects_bad_version(self):
        r = self.bump("1.2")
        self.assertNotEqual(r.returncode, 0)
        with open(PLIST, "rb") as a, open(self.copy, "rb") as b:
            self.assertEqual(a.read(), b.read())

    def test_bump_rejects_plist_without_version(self):
        with open(self.copy, "w", encoding="utf-8") as f:
            f.write("<plist><dict><key>name</key><string>x</string></dict></plist>")
        self.assertNotEqual(self.bump("1.0.0").returncode, 0)

    def test_release_rejects_bad_version_before_touching_git(self):
        for arg in ([], ["abc"], ["1.2"], ["v1.2.3.4"]):
            r = subprocess.run(["bash", RELEASE] + arg, capture_output=True, text=True, cwd=self.tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("usage", r.stderr)

    def test_release_scripts_executable(self):
        self.assertTrue(os.access(RELEASE, os.X_OK))

    def test_release_workflow_checks_version_and_uploads_asset(self):
        with open(RELEASE_YML, encoding="utf-8") as f:
            yml = f.read()
        self.assertIn('tags: ["v*.*.*"]', yml)
        self.assertIn("plutil -extract version raw workflow/info.plist", yml)
        self.assertIn("/usr/bin/python3 -m unittest discover -s tests -t .", yml)
        self.assertIn("./build.sh dist", yml)
        self.assertIn("dist/ClipboardSemanticSearch.alfredworkflow", yml)
        self.assertIn("gh release create", yml)
        self.assertIn("contents: write", yml)


if __name__ == "__main__":
    unittest.main()
