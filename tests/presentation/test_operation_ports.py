"""Consumer ports enumerate operations and named parameters, never an open dispatcher."""
import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'src/taskweave/presentation'


class OperationPortTests(unittest.TestCase):
    def test_operation_contracts_are_closed_and_explicit(self):
        ports = {
            'authoring.py': ('RequestPort', {'step.generate', 'step.generate_goal'}),
            'execution.py': ('ExecutionQuery', {'run.list', 'run.get', 'environment.list', 'task.list', 'step.list'}),
            'settings.py': ('SettingsApplication', {'ai.settings.update'}),
            'planning.py': ('PlanningApplication', {
                'organization.metadata.set', 'plan.get', 'plan.create', 'plan.copy', 'plan.delete',
                'capabilities', 'environment.list', 'plan.update', 'plan.generate', 'plan.generation.list',
                'plan.generation.get', 'plan.generation.parse', 'plan.generation.import', 'plan.generation.imports',
                'plan.context.read', 'plan.context.record', 'plan.context.save_batch', 'plan.context.update',
                'plan.context.delete', 'plan.context.reorder', 'plan.context.capture.delete',
                'plan.context.capture.reorder', 'plan.context.capture.label', 'plan.context.list', 'instance.end'}),
            'step_actions.py': ('StepApplication', {'step.list', 'step.save', 'step.reorder', 'step.delete', 'step.validate', 'step.confirm.manual'}),
            'run_creation.py': ('RunCreationApplication', {'task.list', 'step.list', 'run.create', 'run.start'}),
            'tasks.py': ('TaskApplication', {'task.create', 'task.update', 'organization.metadata.set'}),
            'environment.py': ('EnvironmentOperation', {'environment.save'}),
            'organization.py': ('CategoryOperations', {'organization.category.list', 'organization.category.create',
                                                     'organization.category.rename', 'organization.category.delete'}),
            'step_contexts.py': ('StepContextOperations', {'context.list', 'context.save_batch', 'context.reorder', 'context.delete'}),
            'inputs.py': ('RunInputApplication', {'run.inputs', 'run.start'}),
            'context_collection.py': ('RecordingOperation', {'start', 'pause', 'resume', 'stop', 'read', 'ack', 'discard'}),
        }
        for filename, (name, expected) in ports.items():
            with self.subTest(port=name):
                tree = ast.parse((ROOT / filename).read_text())
                port = next((node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name), None)
                self.assertIsNotNone(port, 'Missing consumer port ' + name)
                operations = set()
                for method in port.body:
                    if not isinstance(method, ast.AsyncFunctionDef) or method.name not in {'__call__', 'call'}:
                        continue
                    self.assertIsNone(method.args.kwarg, 'Consumer parameters must be named')
                    self.assertIsNone(method.args.vararg)
                    operation = next(arg for arg in method.args.args if arg.arg in {'api_operation', 'operation'})
                    self.assertIsInstance(operation.annotation, ast.Subscript)
                    operations.update(node.value for node in ast.walk(operation.annotation.slice)
                                      if isinstance(node, ast.Constant) and isinstance(node.value, str))
                    self.assertIsNotNone(method.returns)
                self.assertEqual(operations, expected)
