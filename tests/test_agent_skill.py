"""Packaged Skill installation is explicit and preserves existing user files."""
from pathlib import Path
import tempfile
import unittest
from taskweave.core.validation import TaskError


class AgentSkillTests(unittest.TestCase):
    def test_export_and_identical_install_are_safe_but_conflicts_are_preserved(self):
        from taskweave.integration.skill import install_skill, connection_config
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'taskweave'
            result = install_skill(folder)
            self.assertTrue((folder / 'SKILL.md').exists())
            self.assertIn('references/authoring.md', (folder / 'SKILL.md').read_text())
            self.assertEqual(result['status'], 'installed')
            self.assertEqual(install_skill(folder)['status'], 'unchanged')
            (folder / 'SKILL.md').write_text('my skill')
            with self.assertRaises(TaskError) as error:
                install_skill(folder)
            self.assertEqual(error.exception.code, 'SKILL_DESTINATION_CONFLICT')
            self.assertEqual((folder / 'SKILL.md').read_text(), 'my skill')
            config = connection_config(Path(root))
            self.assertIn('mcp', config['mcpServers']['taskweave']['args'])
            self.assertNotIn('token', str(config))
