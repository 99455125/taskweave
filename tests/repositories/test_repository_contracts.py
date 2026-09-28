"""Keep public port signatures aligned with the concrete adapters."""

import inspect
import ast
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping, Sequence, get_type_hints

from taskweave.core import repositories as ports
from taskweave.infrastructure.repositories import build_sqlite_repositories
from taskweave.infrastructure.storage import Store


class RepositoryContractTests(unittest.TestCase):
    def test_context_port_return_shapes_and_unique_protocol_methods(self):
        expected = {
            ("StepContextRepository", "reorder_step_context_capture"): Sequence[Mapping[str, Any]],
            ("StepContextRepository", "update_step_context_capture_label"): Sequence[Mapping[str, Any]],
            ("PlanContextRepository", "reorder_context"): Mapping[str, Any],
            ("PlanContextRepository", "update_capture_label"): Mapping[str, Any],
        }
        for (protocol_name, method_name), expected_type in expected.items():
            with self.subTest(protocol=protocol_name, method=method_name):
                annotation = get_type_hints(getattr(getattr(ports, protocol_name), method_name))["return"]
                self.assertEqual(annotation, expected_type)

        tree = ast.parse(Path(ports.__file__).read_text(encoding="utf-8"))
        step_context = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "StepContextRepository")
        names = [node.name for node in step_context.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual(len(names), len(set(names)), "StepContextRepository declares a duplicate method")

    def test_ports_have_named_parameters_matching_adapters(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        repos = build_sqlite_repositories(Store(Path(temp.name)))
        pairs = (
            (ports.TaskRepository, repos.tasks),
            (ports.StepRepository, repos.steps),
            (ports.EnvironmentRepository, repos.environments),
            (ports.RunRepository, repos.runs),
            (ports.ResultRepository, repos.results),
            (ports.StepContextRepository, repos.step_contexts),
            (ports.PlanRepositoryPort, repos.plans),
            (ports.PlanContextRepository, repos.plan_contexts),
            (ports.PlanGenerationRepository, repos.plan_generations),
        )
        for protocol, adapter in pairs:
            method_names = tuple(name for name, member in vars(protocol).items() if not name.startswith("_") and inspect.isfunction(member))
            for method_name in method_names:
                with self.subTest(protocol=protocol.__name__, method=method_name):
                    port_signature = inspect.signature(getattr(protocol, method_name))
                    adapter_signature = inspect.signature(getattr(adapter, method_name))
                    self.assertEqual(tuple(port_signature.parameters)[1:], tuple(adapter_signature.parameters))
                    self.assertEqual(
                        tuple((p.kind, p.default) for p in list(port_signature.parameters.values())[1:]),
                        tuple((p.kind, p.default) for p in adapter_signature.parameters.values()),
                    )
                    self.assertFalse(any(p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) for p in port_signature.parameters.values()))

    def test_delete_contracts_report_results(self):
        for name in ("delete_task", "delete_step", "delete_environment", "delete_result", "delete_step_context_capture", "delete_step_context", "delete"):
            protocol = getattr(ports, "TaskRepository" if name == "delete_task" else "StepRepository" if name == "delete_step" else "EnvironmentRepository" if name == "delete_environment" else "ResultRepository" if name == "delete_result" else "StepContextRepository" if name.startswith("delete_step_context") else "PlanRepositoryPort")
            with self.subTest(method=name):
                self.assertIn("Mapping", str(inspect.signature(getattr(protocol, name)).return_annotation))


if __name__ == "__main__":
    unittest.main()
