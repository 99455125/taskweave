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
    simulator_environment = await ctx.call("wechat_dev.check_environment", {})
    assert simulator_environment["result"]["expected_project_root"] == artifact["output_path"], "simulator configuration must target this build directory"
    connection = await ctx.call("wechat_dev.connect", {})
    assert connection["result"]["root_verified"] or inputs.get("allow_unverified_simulator_root") is True, "runtime project root is unverified; confirm current DevTools project with allow_unverified_simulator_root=true"
    report_root_verified = connection["result"]["root_verified"]
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
    report = {"passed": True, "simulator_only": True, "tested_build_root_verified": report_root_verified, "project": project, "build": build,
              "artifact": artifact, "suite": suite, "connection": connection, "page": page,
              "element": element, "database": database, "logs": logs, "disconnected": disconnected}
    outputs.append(ctx.output("wechat_dev.image", "simulator_screenshot", screenshot["result"]["artifact"]))
    outputs.append(ctx.output("wechat_dev.json", "simulator_logs", logs))
    outputs.append(ctx.output("uniapp.json", "selftest_report", report))
    release_inputs = dict(inputs.get("preview", {}))
    release_inputs["project_path"] = artifact["output_path"]
    release_inputs["expected_artifacts"] = {name: {"sha256": row["sha256"], "size": row["size"]} for name, row in artifact["artifacts"].items()}
    preview = await ctx.call("wechat_dev.preview", release_inputs)
    report["preview"] = preview
    outputs.append(ctx.output("wechat_dev.image", "preview_qr", preview["artifact"]))
    if inputs.get("upload_version"):
        upload_inputs = {"version": inputs["upload_version"], "project_path": artifact["output_path"], "expected_artifacts": release_inputs["expected_artifacts"]}
        report["upload"] = await ctx.call("wechat_dev.upload", upload_inputs)
    outputs.append(ctx.output("wechat_dev.json", "release_report", {"preview": report["preview"], "upload": report.get("upload")}))
    return ctx.result(data=report, outputs=outputs)
