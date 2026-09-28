"""Durable interval scheduling, task operations and desktop API evidence."""

SOURCE = "async def run(ctx, inputs):\n    return ctx.result(data=inputs)\n"
from tests._runtime_fixture import RuntimeFixture

class TaskCopyLifecycleTests(RuntimeFixture):
    def test_copy_remaps_dependencies_and_keeps_history_out(self):
        first = self.step()
        self.app.repo.save_step_context(first['step_id'],'demo.page','登录组','draft',[{'content':'page'}],views=[{'title':'页面','renderer':'demo.image','data':{'image_base64':'abc'}}])
        self.app.repo.save_step(
            self.task,
            {
                "step_content": SOURCE,
                "bindings": {
                    "x": {
                        "ref": {
                            "source": "step",
                            "step_id": first["step_id"],
                            "pointer": "",
                            "output": "data",
                        }
                    }
                },
                "delay_after_previous_seconds": 30,
            },
        )
        target = self.app.dispatch("task.copy", {"task_id": self.task})
        steps = self.app.repo.steps(target["task_id"])
        self.assertNotEqual(steps[0]["step_id"], first["step_id"])
        self.assertEqual(
            steps[1]["bindings"]["x"]["ref"]["step_id"], steps[0]["step_id"]
        )
        self.assertEqual(steps[1]["delay_after_previous_seconds"], 30)
        self.assertEqual(steps[0]["validation_state"], "DRAFT")
        source_group=self.app.repo.list_step_contexts(first['step_id'])[0]
        copied_group=self.app.repo.list_step_contexts(steps[0]['step_id'])[0]
        self.assertNotEqual(source_group['context_id'],copied_group['context_id'])
        self.assertNotEqual(source_group['captures'][0]['capture_id'],copied_group['captures'][0]['capture_id'])
        copied_capture=self.app.repo.get_step_context_capture(copied_group['context_id'],copied_group['captures'][0]['capture_id'])
        self.assertEqual(copied_capture['views'][0]['data']['image_base64'],'abc')
        self.assertFalse(self.app.repo.list_runs(target["task_id"]))
        self.assertEqual(self.app.repo.list_tasks()[0]["task_id"], target["task_id"])
