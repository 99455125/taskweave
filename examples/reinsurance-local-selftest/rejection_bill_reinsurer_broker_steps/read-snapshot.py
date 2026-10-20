async def run(ctx, inputs):
    result = await ctx.call("tidb.query", {"sql": "SELECT id, source_table, source_id, SHA2(back_up_data,256) AS snapshot_sha256 FROM t_business_back_up_data WHERE source_table=%s AND source_id=%s AND is_deleted='N' ORDER BY id", "params": [inputs["source_table"], inputs["source_id"]], "max_rows": 20, "title": "本轮有效快照"})
    if result["truncated"] or result["row_count"] != 1:
        raise ValueError("目标来源必须恰好1条有效快照，不能把空结果或截断结果计为通过")
    row = result["rows"][0]
    if not row["snapshot_sha256"]:
        raise ValueError("快照内容为空")
    if "expected_snapshot_sha256" in inputs:
        if row["snapshot_sha256"] != inputs["expected_snapshot_sha256"] or str(row["id"]) != str(inputs["expected_snapshot_id"]):
            raise ValueError("暂存或重新提交改变了应保留的旧快照")
    return ctx.result(data={"snapshot_id": row["id"], "snapshot_sha256": row["snapshot_sha256"], "source_table": row["source_table"], "source_id": row["source_id"]})
