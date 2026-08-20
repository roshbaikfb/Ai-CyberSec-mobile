[← الجزء الحادي والثلاثون](./part-31-teacher-model.md) · [الفهرس](./README.md)

# الجزء الثاني والثلاثون: معمارية Agent لاكتشاف الثغرات

هذا الجزء يضيف طبقة جديدة فوق النظام الكامل المبني في الأجزاء 1-31: **Agent قادر على استدعاء أدوات أثناء التفكير**، بدل استدعاء نموذج واحد ثابت (One-Shot) يأخذ context جاهزًا ويُخرج حكمًا نهائيًا فورًا.

## الفصل 62: قرار المعمارية — أين يعيش "عقل" الـAgent

### 62.1 القرار: Teacher-tier Agent فوق البنية الحالية (المسار أ)

بعد نقاش صريح لمسارين ممكنين، القرار المُتَّخذ هو:

```
النموذج المحلي (7B، من الجزء 21-25)
        |
    يبقى تمامًا كما هو -- Single-shot triage على كل الـCandidates
        |
    فقط أعلى Candidates خطورة (بعد Risk Ranking)
        |
Teacher-tier Agent (DeepSeek V4 Pro / Claude -- من الجزء 31)
        |
    Agent Loop كامل بالأدوات، فقط على هذا العدد الصغير المُصفَّى
```

### 62.2 لماذا هذا القرار تحديدًا

| البديل المرفوض (المسار ب) | لماذا رُفض الآن |
|---|---|
| تدريب النموذج المحلي (7B) نفسه ليصبح Agent | يتطلب Dataset مختلف جذريًا (multi-turn trajectories بدل samples ثابتة من الفصل 27)، وSFT بأسلوب مختلف بالكامل، ونماذج 7B غالبًا أضعف في tool-calling موثوق من نماذج أكبر |
| **الحل المُتَّخذ:** طبقة Agent منفصلة تستهلك مخرجات النظام الحالي كما هي | لا يتطلب أي تعديل على الأجزاء 1-31 -- إضافة صافية فوق بنية مُثبَتة، وليست إعادة بناء |

هذا القرار يعني عمليًا: **كل ما بُني سابقًا (Candidate Generator، Call Graph، Retriever، Dataset، النموذج المدرَّب) يبقى دون تغيير** -- الـAgent يستهلكها كأدوات (tools) بدل استهلاكها كخطوة واحدة مُجمَّعة مسبقًا (Context Builder -- الفصل 26).

### 62.3 الفرق الجوهري عن Context Builder (الفصل 26)

| | Context Builder (One-Shot) | Agent Loop |
|---|---|---|
| متى يُقرَّر ماذا نحتاج؟ | مسبقًا، بقواعد ثابتة (ميزانية 25%/20%/20%...) | ديناميكيًا، النموذج نفسه يقرر أثناء التفكير |
| ماذا لو المعلومة المسترجَعة غير كافية؟ | يُسجَّل كـ`unresolved_notes` وينتهي الأمر | الـAgent يمكنه طلب معلومة إضافية أو أداة أخرى |
| التكلفة | ثابتة تقريبًا لكل Candidate | متغيرة -- تعتمد على عدد الاستدعاءات الفعلي |

---

## الفصل 63: تعريف الأدوات (Tools)

### 63.1 الأدوات الخمس، وما تضيفه كل واحدة

كل أداة هنا **تُعيد استخدام كود موجود بالفعل** من الأجزاء السابقة -- لا شيء جديد من الصفر، فقط غلاف (wrapper) يجعله قابلًا للاستدعاء من داخل حلقة الـAgent.

```python
# agent/tools.py
"""
كل أداة هنا تستدعي مكوّنًا موجودًا فعليًا من الأجزاء السابقة.
الـAgent لا "يخترع" قدرات جديدة -- فقط يقرر متى يستخدم كل قدرة
موجودة بالفعل، بدل أن يُقرَّر ذلك مسبقًا بقواعد ثابتة.
"""
import json
from dataclasses import dataclass

from retriever.code_retriever import CodeRetriever, resolve_best_candidate
from call_graph.queries import get_security_relevant_neighborhood
from static_analysis.security_facts import extract_security_facts

# --- أداة 1: استرجاع تعريف method عند الطلب (يبني على الفصل 25) ---

def tool_retrieve_definition(method_name: str, retriever: CodeRetriever,
                              calling_package_hint: str | None = None) -> dict:
    result = retriever.find_method(method_name)
    resolved = resolve_best_candidate(result, None, calling_package_hint)
    if resolved is None:
        return {
            "found": False,
            "reason": "ambiguous_or_not_found",
            "candidate_count": len(result.candidates),
        }
    return {
        "found": True,
        "class_name": resolved["class_name"],
        "source_code": resolved["source_code"],
        "file_path": resolved["file_path"],
    }

# --- أداة 2: تتبّع متغير من Source إلى Sink (يوسّع الفصل 8) ---

def tool_trace_variable(variable_name: str, method_source: str) -> dict:
    """تتبّع حتمي مبسّط: يبحث عن كل الأسطر التي يظهر فيها المتغير،
    ويصنّفها كـ(تعريف / تحقق / استخدام في استدعاء حساس) بناءً على
    وجود كلمات مفتاحية من قاموس الفصل 20 (security_rules/api_catalog.yaml)."""
    from security_rules.catalog_loader import load_catalog
    catalog = load_catalog()

    lines_with_var = [
        (i + 1, line) for i, line in enumerate(method_source.splitlines())
        if variable_name in line
    ]

    trace = []
    for line_num, line in lines_with_var:
        category = None
        for name in catalog.all_short_names():
            if name in line:
                category = catalog.category_of(name)
                break
        trace.append({
            "line": line_num,
            "text": line.strip(),
            "security_relevance": category,
        })

    return {"variable": variable_name, "trace": trace, "n_occurrences": len(trace)}

# --- أداة 3: توسيع الـCall Graph لعمق أكبر (يوسّع الفصل 23) ---

def tool_query_call_graph(graph, node_id: str, depth: int = 2) -> dict:
    """depth أكبر من الافتراضي (1) في الفصل 24 -- الـAgent يطلب هذا
    فقط عند الحاجة الفعلية، بدل حسابه مسبقًا لكل Candidate."""
    neighborhood = get_security_relevant_neighborhood(graph, node_id, depth=depth)
    return {
        "callers": sorted(neighborhood["callers"]),
        "callees": sorted(neighborhood["callees"]),
        "depth_used": depth,
    }

# --- أداة 4: فحص تاريخ الـPatch لـmethod معيّنة (يُفعِّل الأجزاء 7-8 كـquery حي) ---

def tool_check_patch_history(method_name: str, file_path: str,
                              repo_path: str) -> dict:
    """يبحث في تاريخ Git المحلي (وليس بيانات تدريب مُجمَّعة مسبقًا)
    -- هل هذه الـmethod تحديدًا تغيّرت مؤخرًا؟ هل مرتبطة بـCVE موثَّق؟"""
    import subprocess
    log = subprocess.run(
        ["git", "log", "--oneline", "-5", "--", file_path],
        cwd=repo_path, capture_output=True, text=True
    ).stdout.strip()

    recent_commits = log.splitlines() if log else []
    return {
        "method": method_name,
        "recent_commits_touching_file": recent_commits,
        "has_recent_activity": len(recent_commits) > 0,
    }

# --- أداة 5: تحقق آلي أثناء التفكير (يُطبَّق الفصل 50 بشكل استباقي) ---

def tool_verify_claim_against_facts(claim: str, security_facts: dict) -> dict:
    """نفس منطق check_consistency_with_facts (الفصل 50.3) لكن يُستدعى
    أثناء بناء الـFinding، لا بعده -- يمنع الـAgent من الاستمرار في
    بناء استنتاج فوق ادعاء غير مدعوم بدل اكتشاف ذلك لاحقًا فقط."""
    claim_lower = claim.lower()
    supporting_evidence = []
    for field_name in ["permission_checks", "appops_checks", "cross_user_checks",
                        "identity_transitions", "potential_sinks"]:
        for item in security_facts.get(field_name, []):
            item_name = item if isinstance(item, str) else item.get("api", "")
            if item_name.lower() in claim_lower:
                supporting_evidence.append(f"{field_name}: {item_name}")

    return {
        "claim": claim,
        "grounded": len(supporting_evidence) > 0,
        "supporting_evidence": supporting_evidence,
    }
```

### 63.2 تعريف الأدوات بصيغة Tool-Calling القياسية

```python
# agent/tool_schemas.py
"""تعريفات الأدوات بصيغة JSON Schema -- متوافقة مع واجهات
tool-calling القياسية (Anthropic وOpenAI-compatible معًا)."""

TOOL_DEFINITIONS = [
    {
        "name": "retrieve_definition",
        "description": (
            "Retrieve the full source code of a method by name from the "
            "indexed AOSP repository. Use when a security-relevant call "
            "appears in the current code but its implementation is not "
            "visible."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method_name": {"type": "string"},
                "calling_package_hint": {"type": "string"},
            },
            "required": ["method_name"],
        },
    },
    {
        "name": "trace_variable",
        "description": (
            "Trace every occurrence of a variable within the current method "
            "source, flagging lines with known security-relevant API calls. "
            "Use to verify whether a caller-controlled value passes through "
            "any validation before reaching a sink."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "variable_name": {"type": "string"},
            },
            "required": ["variable_name"],
        },
    },
    {
        "name": "query_call_graph",
        "description": (
            "Expand the call graph neighborhood beyond the default depth of "
            "1. Use when the security-relevant logic appears to be more "
            "than one call away from the current method."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "check_patch_history",
        "description": (
            "Check whether this method was recently modified in git history "
            "and whether it is linked to a known CVE. Use to assess whether "
            "a candidate is a freshly introduced pattern or long-stable code."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method_name": {"type": "string"},
                "file_path": {"type": "string"},
            },
            "required": ["method_name", "file_path"],
        },
    },
    {
        "name": "verify_claim_against_facts",
        "description": (
            "Verify that a specific claim you are about to make is grounded "
            "in the deterministic Security Facts extracted from the code. "
            "Call this BEFORE finalizing any finding to avoid asserting "
            "something the static analysis did not actually detect."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim": {"type": "string"},
            },
            "required": ["claim"],
        },
    },
]
```

---

## الفصل 64: حلقة الـAgent، الحدود، وسياسة التكلفة

### 64.1 لماذا لازم حدود صارمة من البداية

Agent بدون حدود قد يدخل في استدعاءات لا نهائية (يطلب `retrieve_definition` لأسماء غير ذات صلة، أو يُوسِّع `query_call_graph` لعمق غير مبرَّر) -- هذا ليس افتراضًا نظريًا، بل نمط فشل معروف في أنظمة الـAgent بشكل عام. الحل: حدود صريحة **قبل** كتابة أي منطق تشغيلي، وليس بعد ملاحظة المشكلة.

```python
# agent/loop.py
"""
حلقة الـAgent الكاملة: يستدعي النموذج (عبر teacher_model/client.py
من الجزء 31)، يعالج طلبات استدعاء الأدوات، ويُرجِع النتائج، حتى
يُصدر Finding نهائي أو يصل لأحد الحدود.
"""
import json
from dataclasses import dataclass
from teacher_model.client import ClaudeVerifierClient
from agent.tools import (
    tool_retrieve_definition, tool_trace_variable,
    tool_query_call_graph, tool_check_patch_history,
    tool_verify_claim_against_facts,
)
from agent.tool_schemas import TOOL_DEFINITIONS

@dataclass
class AgentLimits:
    max_tool_calls: int = 8          # حد أقصى لعدد استدعاءات الأدوات لكل Candidate
    max_cost_usd: float = 0.50       # حد أقصى بالدولار لكل Candidate (يربط بالجزء 31)
    max_wall_clock_seconds: int = 120  # حد أقصى زمني لتجنّب حلقات بطيئة معلَّقة

@dataclass
class AgentRunResult:
    candidate_id: str
    finding: dict | None
    tool_calls_used: int
    estimated_cost_usd: float
    elapsed_seconds: float
    stopped_reason: str  # 'finding_produced' | 'max_tool_calls' | 'max_cost' | 'timeout' | 'error'

TOOL_DISPATCH = {
    "retrieve_definition": tool_retrieve_definition,
    "trace_variable": tool_trace_variable,
    "query_call_graph": tool_query_call_graph,
    "check_patch_history": tool_check_patch_history,
    "verify_claim_against_facts": tool_verify_claim_against_facts,
}

# تقدير تكلفة تقريبي لكل دورة نموذج -- يُحدَّث بأسعار Claude/DeepSeek
# الفعلية وقت التنفيذ (الفصل 60.2)
ESTIMATED_COST_PER_MODEL_TURN_USD = 0.03

def run_agent_on_candidate(
    candidate: dict, security_facts: dict, tool_context: dict,
    limits: AgentLimits = AgentLimits(),
) -> AgentRunResult:
    import time
    start = time.time()

    client = ClaudeVerifierClient(model_id="claude-opus-4-8")
    system_prompt = (
        "You are an Android Framework security researcher with access to "
        "tools for retrieving code, tracing variables, and verifying claims. "
        "Investigate the candidate below using the available tools as needed. "
        "Call verify_claim_against_facts before finalizing any security claim. "
        "When you have sufficient evidence (or have determined evidence is "
        "unavailable), output a final JSON finding matching the Chapter 27 "
        "schema. Do not guess -- use insufficient_context if a tool call "
        "does not resolve the needed information."
    )

    conversation = [
        {"role": "user", "content": json.dumps(candidate, ensure_ascii=False)}
    ]

    tool_calls_used = 0
    estimated_cost = 0.0

    while True:
        elapsed = time.time() - start
        if elapsed > limits.max_wall_clock_seconds:
            return AgentRunResult(
                candidate_id=candidate.get("case_id", "unknown"), finding=None,
                tool_calls_used=tool_calls_used, estimated_cost_usd=estimated_cost,
                elapsed_seconds=elapsed, stopped_reason="timeout",
            )
        if tool_calls_used >= limits.max_tool_calls:
            return AgentRunResult(
                candidate_id=candidate.get("case_id", "unknown"), finding=None,
                tool_calls_used=tool_calls_used, estimated_cost_usd=estimated_cost,
                elapsed_seconds=elapsed, stopped_reason="max_tool_calls",
            )
        if estimated_cost >= limits.max_cost_usd:
            return AgentRunResult(
                candidate_id=candidate.get("case_id", "unknown"), finding=None,
                tool_calls_used=tool_calls_used, estimated_cost_usd=estimated_cost,
                elapsed_seconds=elapsed, stopped_reason="max_cost",
            )

        response = client.client.messages.create(
            model=client.model_id,
            max_tokens=2000,
            system=system_prompt,
            tools=TOOL_DEFINITIONS,
            messages=conversation,
        )
        estimated_cost += ESTIMATED_COST_PER_MODEL_TURN_USD

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b for b in response.content if b.type == "text"]

        if not tool_use_blocks:
            final_text = "".join(b.text for b in text_blocks)
            finding, success = _try_parse_finding(final_text)
            return AgentRunResult(
                candidate_id=candidate.get("case_id", "unknown"),
                finding=finding if success else None,
                tool_calls_used=tool_calls_used, estimated_cost_usd=estimated_cost,
                elapsed_seconds=time.time() - start,
                stopped_reason="finding_produced" if success else "error",
            )

        conversation.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            tool_calls_used += 1
            handler = TOOL_DISPATCH.get(block.name)
            if handler is None:
                result = {"error": f"unknown tool {block.name}"}
            else:
                result = handler(**block.input, **tool_context.get(block.name, {}))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False),
            })
        conversation.append({"role": "user", "content": tool_results})

def _try_parse_finding(text: str) -> tuple[dict | None, bool]:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned), True
    except (json.JSONDecodeError, IndexError):
        return None, False
```

### 64.2 سياسة متى يشتغل الـAgent أصلًا (Triage أولًا)

```python
# agent/entry_policy.py
"""يحدد أي Candidates تصل لمرحلة الـAgent -- ليس كل Candidate،
فقط ما اجتاز الفلترة الأولى من النموذج المحلي (7B)."""

def should_invoke_agent(candidate: dict, local_model_result: dict) -> bool:
    # الشرط 1: النموذج المحلي أصدر verdict = vulnerable بثقة معقولة --
    # يستحق تحقيقًا أعمق قبل تقديمه كـFinding نهائي للباحث البشري
    if local_model_result["verdict"] == "vulnerable" and \
       local_model_result["confidence"] >= 0.5:
        return True

    # الشرط 2: النموذج المحلي أصدر insufficient_context لكن الـCandidate
    # من رتبة عالية (الفصل 22 -- rule_sink_without_any_check أو أعلى)
    # -- يستحق محاولة حل الغموض عبر الأدوات بدل تركه معلَّقًا
    if local_model_result["verdict"] == "insufficient_context" and \
       candidate.get("score", 0) >= 8.0:
        return True

    return False
```

### 64.3 الـLab الديناميكي: مؤجَّل عمدًا، وليس منسيًا

كما اتُّفق، أعقد مكوّن في اقتراح Big Sleep الكامل -- التحقق الديناميكي الفعلي عبر Android Emulator وADB hooking -- **لا يُبنى في v0.1 من هذا الجزء**. السبب: تعقيد الإعداد (userdebug build، أتمتة توليد تطبيقات اختبار، تفسير logs) يستحق دورة تطوير منفصلة، بعد إثبات أن الـAgent Static-Only (الأدوات الخمس أعلاه فقط) يحسّن جودة الـFindings بشكل ملموس أولًا.

**معيار الانتقال لبناء الـLab (v2):** لو تحليل نتائج الـAgent Static-Only (بعد تشغيله على دفعة حقيقية من Candidates) أظهر أن نسبة معتبرة من الـFindings عالية الثقة تبقى غير مؤكَّدة (`insufficient_context` أو `ambiguous` رغم استنفاد كل الأدوات المتاحة)، فهذا دليل كمّي على أن التحقق الديناميكي يستحق الاستثمار. بدون هذا الدليل، بناء الـLab قرار سابق لأوانه.

> **Definition of Done -- الجزء الثاني والثلاثون:** تشغيل `run_agent_on_candidate` فعليًا على 10 Candidates حقيقية اجتازت `should_invoke_agent`، مع توثيق: متوسط عدد استدعاءات الأدوات لكل Candidate، متوسط التكلفة الفعلية مقابل `max_cost_usd`، ونسبة الحالات التي انتهت بـ`finding_produced` مقابل الحدود الأخرى (`max_tool_calls`, `timeout`) -- لو نسبة معتبرة تصطدم بالحدود قبل الوصول لإجابة، هذا مؤشر على أن الحدود ضيّقة جدًا أو أن الأدوات المتاحة غير كافية لحل نوع الغموض الموجود.

---

[← الجزء الحادي والثلاثون](./part-31-teacher-model.md) · [الفهرس](./README.md) · [الجزء الثالث والثلاثون →](./part-33-dynamic-verification-lab.md)
