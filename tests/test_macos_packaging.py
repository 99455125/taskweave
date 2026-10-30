import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_macos', ROOT / 'scripts/build_macos.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class PackagingTests(unittest.TestCase):
    def test_missing_plugin_rejects_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'chrome'
            executable.touch()
            with self.assertRaisesRegex(RuntimeError, 'ocr'):
                build.validate_inventory(set(build.PLUGINS) - {'ocr'}, executable)

    def test_missing_browser_rejects_build(self):
        with self.assertRaisesRegex(RuntimeError, 'Chromium'):
            build.validate_inventory(set(build.PLUGINS), Path('/missing-taskweave-browser'))

    def test_release_manifest_has_only_distribution_metadata(self):
        manifest = build.release_manifest('0.1.0', {name: '0.1.0' for name in build.PLUGINS})
        self.assertEqual(manifest['platform'], 'macos-arm64')
        self.assertEqual(len(manifest['plugins']), 15)
        self.assertEqual(set(manifest), {'product', 'version', 'platform', 'built_at_utc', 'plugins', 'browser', 'external_tools'})

    def test_declared_plugins_match_approved_full_inventory(self):
        from taskweave.desktop.bundle import BUNDLED_PLUGINS
        self.assertEqual(set(build.PLUGINS), set(BUNDLED_PLUGINS))

    def test_missing_resource_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuntimeError, 'resource'):
                build.require_resources(Path(tmp))

    def test_browser_framework_layout_and_symlinks_survive_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / 'cache'
            framework = cache / 'Chrome.app/Contents/Frameworks/Chrome.framework'
            (framework / 'Versions/A').mkdir(parents=True)
            (framework / 'Versions/A/Chrome').write_bytes(b'original-browser-binary')
            (framework / 'Versions/Current').symlink_to('A')
            build.bundle_browsers(cache, root / 'TaskWeave.app')
            copy = root / 'TaskWeave.app/Contents/Resources/browsers/Chrome.app/Contents/Frameworks/Chrome.framework'
            self.assertTrue((copy / 'Versions/Current').is_symlink())
            self.assertEqual((copy / 'Versions/Current/Chrome').read_bytes(), b'original-browser-binary')
