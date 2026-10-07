async def run(ctx, inputs):
    project = await ctx.call("uniapp.inspect", {})
    build = await ctx.call("uniapp.build", {"platform": "mp-weixin", "environment": inputs.get("environment", "development")})
    artifact = await ctx.call("uniapp.check_artifact", {"build_id": build["build_id"], "started_at": build["started_at"], "platform": "mp-weixin"})
    suite = None
    outputs = []
    if inputs.get("test_suite"):
        suite = await ctx.call("uniapp.run_tests", inputs["test_suite"])
        reports = await ctx.call("uniapp.collect_report", {"paths": [suite["report_path"]], "test_run_id": suite["test_run_id"]})
        for index, file in enumerate(reports["artifacts"]):
            outputs.append(ctx.output("uniapp.file", "suite_report_" + str(index), file))
    connection = await ctx.call("wechat_dev.connect", {})
    if inputs.get("navigation"):
        await ctx.call("wechat_dev.navigate", inputs["navigation"])
    if inputs.get("tap_selector"):
        await ctx.call("wechat_dev.tap", {"selector": inputs["tap_selector"]})
    page = await ctx.call("wechat_dev.assert_page", {"path": inputs["expected_page"]})
    element = await ctx.call("wechat_dev.assert_element", inputs["element_assertion"])
    database = None
    if inputs.get("database_query"):
        database = await ctx.call("tidb.query", inputs["database_query"])
        assert not database["truncated"], "database verification was truncated"
        assert database["rows"] == inputs["expected_rows"], "database verification mismatch"
    screenshot = await ctx.call("wechat_dev.screenshot", {})
    logs = await ctx.call("wechat_dev.read_logs", {"limit": 100})
    disconnected = await ctx.call("wechat_dev.disconnect", {})
    report = {"passed": True, "simulator_only": True, "project": project, "build": build,
              "artifact": artifact, "suite": suite, "connection": connection, "page": page,
              "element": element, "database": database, "logs": logs, "disconnected": disconnected}
    outputs.append(ctx.output("wechat_dev.image", "simulator_screenshot", screenshot["result"]["artifact"]))
    outputs.append(ctx.output("wechat_dev.json", "simulator_logs", logs))
    outputs.append(ctx.output("uniapp.json", "selftest_report", report))
    return ctx.result(data=report, outputs=outputs)
