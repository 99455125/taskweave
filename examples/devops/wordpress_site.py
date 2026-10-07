async def run(ctx, inputs):
    site = await ctx.call("baota_dashboard.create_site", inputs["site"])
    database = await ctx.call("baota_dashboard.create_database", inputs["database"])
    transfer = await ctx.call("ssh.upload", inputs["transfer"])
    core = await ctx.call("wordpress.core_download", inputs["core"])
    configuration = await ctx.call("wordpress.config_create", inputs["configuration"])
    installed = await ctx.call("wordpress.core_install", inputs["install"])
    content = await ctx.call("wordpress.create_post", inputs["content"])
    await ctx.call("playwright.page_open", {"url": inputs["page_url"]})
    page_assertion = inputs["page_assertion"]
    page = await ctx.call("playwright.page_assert_text", page_assertion)
    screenshot = await ctx.call("playwright.page_screenshot", {})
    backup = await ctx.call("wordpress.backup", inputs["backup"])
    panel_backup = await ctx.call("baota_dashboard.create_backup", {"kind": "site", "target_id": site["site_id"]})
    report = {"passed": True, "site": site, "database": database, "transfer": transfer,
              "core": core, "configuration": configuration, "installed": installed,
              "content": content, "page": page, "backup": backup["result"], "panel_backup": panel_backup}
    return ctx.result(data=report, outputs=[ctx.output("wordpress.json", "deployment_report", report),
                      ctx.output("wordpress.file", "site_backup", backup["artifact"]),
                      ctx.output("playwright.image", "site_screenshot", screenshot)])
