"""Topic contracts remain independent and old serialized names remain valid."""
import pickle
import subprocess
import sys
import unittest


class CoreContractTests(unittest.TestCase):
    def test_model_and_context_contracts_import_without_legacy_aggregate(self):
        result = subprocess.run([sys.executable, '-c', '''
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'taskweave.core.ports': raise AssertionError(fullname)
sys.meta_path.insert(0, Block())
from taskweave.core.model_ports import ModelReply, ModelPort, ToolCall
from taskweave.core.context_contracts import ContextCollection, ContextRecordingBatch
assert ModelReply().tool_calls == ()
assert ContextRecordingBatch('r', 'STOPPED', 0).collection == ContextCollection(())
'''], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_paths_and_public_sdk_share_the_same_contract_classes(self):
        from taskweave.core import ports, model_ports, context_contracts, capability_contracts
        from taskweave.plugins import sdk
        for module, names in ((capability_contracts, ('Diagnostic', 'CapabilitySpec', 'AuthoringContribution')),
                              (model_ports, ('ModelReply', 'ToolCall')),
                              (context_contracts, ('ContextItem', 'ContextView', 'ContextCollection', 'ContextRecordingCommand', 'ContextRecordingBatch'))):
            for name in names:
                cls = getattr(module, name)
                self.assertIs(getattr(ports, name), cls)
                self.assertIs(pickle.loads(f'ctaskweave.core.ports\n{name}\n.'.encode()), cls)
                if hasattr(sdk, name): self.assertIs(getattr(sdk, name), cls)
