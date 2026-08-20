[← الجزء الحادي والعشرون](./part-21-model-selection.md) · [الفهرس](./README.md)

# الجزء الثاني والعشرون: Baseline

## الفصل 42: Baseline Before Training

هذا الفصل يفرض قاعدة صريحة سبق ذكرها في الفصل 25 من الكتاب الأصلي: **لا تدريب قبل Baseline موثَّق**. بدون معرفة أداء النموذج الخام (بدون أي Fine-Tuning) على الـBenchmark v0.1 (الفصل 38)، أي تحسّن لاحق مزعوم غير قابل للتحقق — قد يكون تحسّنًا حقيقيًا، أو مجرد ضجيج إحصائي، أو حتى تراجعًا مقنّعًا.

### 42.1 ماذا يعني "بدون تدريب" بالضبط هنا

النموذج المختار (من الفصل 40-41) يُشغَّل على الـBenchmark **كما هو** — بدون أي LoRA adapter، فقط باستخدام Prompt engineering أساسي (تعليمات واضحة + الـSchema المطلوب كجزء من الـPrompt نفسه). هذا يحاكي "ماذا لو استخدمنا نموذجًا عامًا مباشرة دون استثمار في التدريب" — وهو خط الأساس الذي يجب أن يتفوّق عليه أي استثمار لاحق في QLoRA ليكون مبرَّرًا.

### 42.2 ماذا نسجّل لكل حالة اختبار

| الحقل | لماذا نسجّله |
|---|---|
| `prompt` | إعادة الإنتاج الكاملة — أي تجربة لاحقة يجب أن تستطيع إعادة توليد نفس الظروف بدقة |
| `raw_output` | النص الخام قبل أي تحليل — ضروري لتشخيص أخطاء الـparsing لاحقًا (مقابل أخطاء الـreasoning الفعلية) |
| `parsed_verdict` | الحكم بعد استخراجه من `raw_output` — قد يفشل الاستخراج حتى لو كان الـreasoning صحيحًا (مشكلة تنسيق، وليس مشكلة فهم) |
| `latency_seconds` | مهم لتخطيط تشغيل الـRepository Scanner لاحقًا على نطاق واسع |
| `token_count` | يربط بميزانية الفصل 26، ويكشف لو Context Builder ينتج مخرجات أطول من المتوقَّع |
| `confidence` | المُعلَنة من النموذج نفسه — أساس لاحق لقياس Calibration (الفصل 54) |

### 42.3 `baseline/run_baseline.py`

```python
# baseline/run_baseline.py
"""
يشغّل النموذج الأساسي (بدون أي fine-tuning) على كل حالات
Benchmark v0.1، ويسجّل كل شيء لازم لاحقًا للمقارنة والتشخيص.
"""
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict

SYSTEM_PROMPT = """You are an Android Framework security reviewer.
Analyze the provided code context and output a JSON object matching
exactly this structure:

{
  "entry_point": "...",
  "caller_identity": "...",
  "attacker_controlled_inputs": [...],
  "permission_checks": [...],
  "appops_checks": [...],
  "identity_transitions": [...],
  "cross_user_checks": [...],
  "privileged_operations": [...],
  "trust_boundary": "...",
  "security_invariant": "...",
  "candidate_issue": "...",
  "counter_evidence": [...],
  "missing_context": [...],
  "confidence": 0.0,
  "verdict": "vulnerable" | "secure" | "ambiguous" | "insufficient_context"
}

Rules:
- If any required piece of information (such as the definition of a
  called helper method) is not present in the provided context, you
  MUST use verdict "insufficient_context" rather than guessing.
- clearCallingIdentity() alone is NOT evidence of a vulnerability.
- A permission check alone does NOT guarantee cross-user authorization.
- Output ONLY the JSON object, no additional text.
"""

@dataclass
class BaselineResult:
    case_id: str
    prompt: str
    raw_output: str
    parsed_verdict: str | None
    parsing_succeeded: bool
    latency_seconds: float
    token_count_estimate: int
    confidence: float | None

def build_prompt(benchmark_case: dict) -> str:
    ctx = benchmark_case["sample"]["code_context"]
    sections = [
        f"## Current Method\n```java\n{ctx['current_method']}\n```",
    ]
    if ctx.get("caller"):
        sections.append(f"## Caller\n```java\n{ctx['caller']}\n```")
    if ctx.get("security_helpers"):
        for name, src in ctx["security_helpers"].items():
            if src:
                sections.append(f"## Helper: {name}\n```java\n{src}\n```")
            else:
                sections.append(f"## Helper: {name}\n[DEFINITION NOT AVAILABLE]")
    if ctx.get("unresolved_notes"):
        sections.append(
            "## Notes\n" + "\n".join(f"- {n}" for n in ctx["unresolved_notes"])
        )
    return "\n\n".join(sections)

def parse_model_output(raw_output: str) -> tuple[dict | None, bool]:
    try:
        cleaned = raw_output.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        parsed = json.loads(cleaned)
        return parsed, True
    except (json.JSONDecodeError, IndexError):
        return None, False

def call_model(system_prompt: str, user_prompt: str) -> str:
    """Placeholder — التنفيذ الفعلي يعتمد على واجهة الاستدلال المختارة
    (transformers pipeline محلي، أو vLLM، إلخ). يُفصَّل في الجزء
    الخاص بالـInference لاحقًا في الكتاب الكامل."""
    raise NotImplementedError(
        "Connect this to the actual local inference backend for the "
        "selected model (Chapter 40-41)."
    )

def run_baseline_on_case(case: dict) -> BaselineResult:
    prompt = build_prompt(case)
    start = time.time()
    raw_output = call_model(SYSTEM_PROMPT, prompt)
    latency = time.time() - start

    parsed, success = parse_model_output(raw_output)

    return BaselineResult(
        case_id=case["case_id"],
        prompt=prompt,
        raw_output=raw_output,
        parsed_verdict=parsed.get("verdict") if parsed else None,
        parsing_succeeded=success,
        latency_seconds=round(latency, 2),
        token_count_estimate=len(prompt) // 4,
        confidence=parsed.get("confidence") if parsed else None,
    )

def run_full_baseline(benchmark_path: Path, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cases = [json.loads(line) for line in benchmark_path.open()]

    total, parse_failures = 0, 0
    with output_path.open("w") as f:
        for case in cases:
            result = run_baseline_on_case(case)
            f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
            total += 1
            if not result.parsing_succeeded:
                parse_failures += 1
            if total % 20 == 0:
                print(f"...{total}/{len(cases)} cases processed")

    print(f"\nBaseline run complete: {total} cases, "
          f"{parse_failures} parsing failures "
          f"({parse_failures/total*100:.1f}%)")

if __name__ == "__main__":
    run_full_baseline(
        benchmark_path=Path("benchmark/v0.1/benchmark_cases.jsonl"),
        output_path=Path("experiments/baseline/results.jsonl"),
    )
```

### 42.2 ربط النتائج بمقاييس الفصل 2

```python
# baseline/score_baseline.py
import json
from pathlib import Path
from evaluation.metrics import EvalCase, summarize

def build_eval_cases(
    baseline_results_path: Path, benchmark_path: Path
) -> list[EvalCase]:
    results = {
        json.loads(line)["case_id"]: json.loads(line)
        for line in baseline_results_path.open()
    }
    cases = []
    for line in benchmark_path.open():
        bench_case = json.loads(line)
        result = results.get(bench_case["case_id"])
        if not result or not result["parsing_succeeded"]:
            continue  # فشل التحليل يُحتسَب منفصلاً — لا يُدرَج كخطأ تصنيف
        cases.append(EvalCase(
            sample_id=bench_case["case_id"],
            predicted_verdict=result["parsed_verdict"],
            true_verdict=bench_case["sample"]["verdict"],
            predicted_confidence=result["confidence"] or 0.0,
        ))
    return cases

if __name__ == "__main__":
    eval_cases = build_eval_cases(
        Path("experiments/baseline/results.jsonl"),
        Path("benchmark/v0.1/benchmark_cases.jsonl"),
    )
    summary = summarize(eval_cases)
    print(json.dumps(summary, indent=2))

    Path("experiments/baseline/summary.json").write_text(
        json.dumps(summary, indent=2)
    )
```

### 42.3 لماذا فشل الـParsing يُحتسَب منفصلاً عن الخطأ التصنيفي

نموذج بدون تدريب على الـSchema المحدَّد (الفصل 27) قد يُنتج مخرجات صحيحة منطقيًا لكن بتنسيق غير متوافق (مثلًا JSON بحقول بأسماء مختلفة قليلًا، أو نص إضافي قبل/بعد الـJSON). هذا **ليس** فشلًا في الـreasoning — هو فشل في اتباع التنسيق، وهو بالضبط ما يُفترَض أن يُصلِحه SFT (الفصل 46) لاحقًا. خلط هذين النوعين من الفشل في تحليل واحد يُخفي أين المشكلة الحقيقية.

> **Definition of Done — الجزء الثاني والعشرون:** ملف `experiments/baseline/summary.json` موجود وموقَّع بتاريخ التشغيل، يحتوي كل المقاييس من الفصل 2 محسوبة فعليًا على الـBenchmark الكامل، مع نسبة `parsing failures` موثَّقة صراحة (منفصلة عن الأخطاء التصنيفية) — هذا الملف هو **نقطة المقارنة الرسمية** التي ستُقاس ضدها كل تجربة QLoRA لاحقة في الجزء الثالث والعشرين وما بعده.

---

[← الجزء الحادي والعشرون](./part-21-model-selection.md) · [الفهرس](./README.md) · [الجزء الثالث والعشرون →](./part-23-qlora.md)
