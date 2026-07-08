"""C3 — Opportunity scan + channel marketing copy drafting.

Deterministic part: rerun the analytics engine (对标 + capacity bands + 3 opportunity
rules). LLM part: draft 渠道推广文案 for each actionable insight, strictly from the
computed facts (same anti-hallucination stance as the reports).
"""

from __future__ import annotations

from chubb_ci.agent.runtime import AgentContext, finish_run
from chubb_ci.analytics.refresh import refresh_insights
from chubb_ci.llm.base import LLMClient, LLMError
from chubb_ci.llm.factory import resolve_model
from chubb_ci.storage.repositories import Repository

_COPY_SYSTEM = """你是集宝 ChubbSafes 中国市场的渠道营销文案撰写人。
基于给定的**系统计算事实**，为经销商渠道撰写简短有力的推广文案（每条 2-3 句）。

铁律：
- 只使用给定事实中的数字与结论，**严禁编造**任何参数、价格或对比。
- 语气专业自信，突出"现货交付/硬核认证/单位价值"等差异化论据。
- 每条文案后标注所依据的事实编号，如（依据：事实2）。
- 中文输出，Markdown 列表。"""

_COPY_USER = """以下是系统检测到的市场洞察事实：

{facts}

请为其中的「物流优势」与「定价异常」类洞察撰写渠道推广文案（每条洞察一段）。"""


def run_scan(ctx: AgentContext, llm: LLMClient) -> None:
    repo = Repository(ctx.session)

    ctx.log("规划", "开始机会扫描：重算对标分析与容量段矩阵")
    insights = refresh_insights(repo, run_id=None)
    ctx.run.iterations = 1
    ctx.log("评估", f"检测到 {len(insights)} 条市场洞察",
            "；".join(sorted({i.insight_type for i in insights})))

    if not insights:
        finish_run(ctx, result_md="# 机会扫描\n\n本次未检测到可行动的市场洞察。")
        return

    facts_lines = [
        f"事实{n}. [{i.insight_type}] {i.title}：{i.detail}"
        for n, i in enumerate(insights, 1)
    ]
    facts_block = "\n".join(facts_lines)
    actionable = [i for i in insights
                  if i.insight_type in ("logistics_advantage", "pricing_anomaly")]

    ctx.log("报告", f"为 {len(actionable)} 条可行动洞察起草渠道文案（LLM）")
    try:
        resp = ctx.track(llm.complete(
            system=_COPY_SYSTEM,
            user=_COPY_USER.format(facts=facts_block),
            model=resolve_model(ctx.settings, "daily"),
            temperature=0.3,
        ))
        copy_md = resp.content.strip()
    except LLMError as exc:
        ctx.log("报告", f"LLM 起草失败，保留事实清单（{exc}）")
        copy_md = "（LLM 起草失败，以下为事实清单）"

    result = (
        "# 机会扫描与渠道文案\n\n"
        f"## 渠道推广文案（AI 起草，基于系统计算事实）\n\n{copy_md}\n\n"
        f"---\n\n## 依据事实（系统计算）\n\n" + "\n".join(f"- {l}" for l in facts_lines)
    )
    ctx.log("应用", "扫描完成，文案已生成", f"洞察 {len(insights)} 条 / 文案 {len(actionable)} 段")
    finish_run(ctx, result_md=result)
