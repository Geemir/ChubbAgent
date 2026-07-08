"""Prompt construction for structured extraction.

The field spec is generated from :class:`ExtractedProduct` so the prompt and the
validation schema can never drift apart.
"""

from __future__ import annotations

from chubb_ci.config.sources import Source
from chubb_ci.schemas.models import ExtractedProduct


def schema_hint() -> str:
    """Compact, token-cheap field spec derived from the Pydantic model."""
    lines = ["产品对象字段（缺失填 null，不要臆造）："]
    for name, field in ExtractedProduct.model_fields.items():
        desc = field.description or ""
        lines.append(f"- {name}: {desc}")
    return "\n".join(lines)


SYSTEM_TEMPLATE = """你是集宝 ChubbSafes 中国市场竞争情报分析助手。
你的任务：从竞争对手网页的正文中，**只抽取页面中真实出现的**保险柜/防火柜/金库门/保管箱/\
锁具等产品信息，输出严格 JSON。

铁律：
1. 只依据给定正文，**严禁编造或推断**未出现的价格、等级、日期等信息；不确定就填 null。
2. 保留中文原文（品牌、系列名、促销措辞照抄）。价格只保留数字。
3. 输出必须是**单个 JSON 对象**，形如 {{"products": [ {{...}}, ... ]}}；无产品则 products 为空数组。
4. 不要输出解释、注释或 Markdown 代码块，只输出 JSON。

以下是集宝的领域背景，帮助你判断品类、等级与竞争关注点：
---
{domain_context}
---
"""

USER_TEMPLATE = """竞争对手：{company}
渠道：{channel} ｜ 页面类型：{page_type}
页面 URL：{url}

注意：**只提取明确属于「{company}」品牌的产品**；电商搜索/列表页上其他品牌的商品一律忽略。

{schema}

网页正文（已抽取主体）：
<<<
{page_text}
>>>

请输出严格 JSON。"""

REPAIR_TEMPLATE = """你上一次的输出无法通过校验。
错误信息：
{error}

你上一次的输出：
{previous}

请**仅**输出修正后的、符合下述结构的严格 JSON（{{"products": [...]}}），不要任何多余文字。
{schema}"""


def build_system(domain_context: str) -> str:
    return SYSTEM_TEMPLATE.format(domain_context=domain_context.strip() or "(无)")


def build_user(source: Source, url: str, page_text: str) -> str:
    return USER_TEMPLATE.format(
        company=source.company,
        channel=source.channel,
        page_type=source.page_type.value,
        url=url,
        schema=schema_hint(),
        page_text=page_text,
    )


def build_repair(error: str, previous: str) -> str:
    return REPAIR_TEMPLATE.format(error=error, previous=previous[:4000], schema=schema_hint())
