async def run(ctx, inputs):
    await ctx.call("playwright.page_open", {"role": inputs["role"], "url": inputs["url"]})
    return ctx.result()
