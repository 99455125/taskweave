async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"role": inputs["role"], "url": inputs["url"]})
    page = await ctx.call("playwright.page_title", {"role": inputs["role"]})
    if not page["title"].strip():
        raise ValueError("Page title is empty")
    outputs = []
    if inputs["capture"]:
        shot = await ctx.call("playwright.page_screenshot", {"role": inputs["role"]})
        outputs.append(ctx.output("playwright.image", "page", shot))
    return ctx.result(data={"title": page["title"]}, outputs=outputs)
