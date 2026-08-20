[← الجزء السابع والعشرون](./part-27-quality-scoring.md) · [الفهرس](./README.md)

# الجزء الثامن والعشرون: Evaluation

بعد أول تدريب فعلي (الجزء الرابع والعشرون)، هذا الجزء يبني طبقة التقييم الكاملة — تتوسع مباشرة على `evaluation/metrics.py` الأساسي من الفصل 2، لتغطي تحليلًا أعمق من مجرد الأرقام الإجمالية.

## الفصل 52: Automated Evaluation

### 52.1 من مقاييس إجمالية إلى تحليل تفصيلي

الفصل 2 أعطانا `summarize()` — أرقام إجمالية (Precision, Recall, F1...). هذا كافٍ لمعرفة "هل تحسّن النموذج عمومًا؟" لكن غير كافٍ لمعرفة **أين تحديدًا** يخطئ، وهو ما نحتاجه لتوجيه الفصل القادم من عمل: تحسين الـDataset (دورة التعلّم النشط، تُفصَّل لاحقًا في المشروع الكامل).

### 52.2 `evaluation/detailed_evaluator.py`

```python
# evaluation/detailed_evaluator.py
"""
يحلل مخرجات النموذج مقابل Benchmark v0.1 (الفصل 38) بتفصيل أعمق:
- الأداء لكل فئة من Taxonomy (الفصل 10)
- الأداء لكل مستوى Curriculum (الفصل 48)
- تحليل الأخطاء حسب النوع (وليس فقط العدد الإجمالي)
"""
import json
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from evaluation.metrics import EvalCase, compute_confusion, precision, recall, f1

@dataclass
class CategoryBreakdown:
    category: str
    n_cases: int
    precision: float
    recall: float
    f1: float
    common_errors: list[str] = field(default_factory=list)

def load_eval_cases_with_metadata(
    results_path: Path, benchmark_path: Path
) -> list[dict]:
    results = {
        json.loads(line)["case_id"]: json.loads(line)
        for line in results_path.open()
    }
    cases = []
    for line in benchmark_path.open():
        bench_case = json.loads(line)
        result = results.get(bench_case["case_id"])
        if not result or not result.get("parsing_succeeded"):
            continue
        cases.append({
            "case_id": bench_case["case_id"],
            "category": bench_case["category"],
            "difficulty": bench_case.get("difficulty", "unknown"),
            "predicted_verdict": result["parsed_verdict"],
            "true_verdict": bench_case["sample"]["verdict"],
            "predicted_confidence": result.get("confidence") or 0.0,
        })
    return cases

def breakdown_by_category(cases: list[dict]) -> list[CategoryBreakdown]:
    by_category = defaultdict(list)
    for c in cases:
        by_category[c["category"]].append(c)

    breakdowns = []
    for category, group in by_category.items():
        eval_cases = [
            EvalCase(
                sample_id=c["case_id"],
                predicted_verdict=c["predicted_verdict"],
                true_verdict=c["true_verdict"],
            ) for c in group
        ]
        confusion = compute_confusion(eval_cases)
        errors = [
            f"predicted={c['predicted_verdict']} true={c['true_verdict']}"
            for c in group if c["predicted_verdict"] != c["true_verdict"]
        ]
        breakdowns.append(CategoryBreakdown(
            category=category,
            n_cases=len(group),
            precision=round(precision(confusion), 3),
            recall=round(recall(confusion), 3),
            f1=round(f1(confusion), 3),
            common_errors=errors[:5],  # عينة، وليس كل الأخطاء
        ))
    return sorted(breakdowns, key=lambda b: b.f1)  # الأضعف أولاً — الأولوية للانتباه

def print_report(breakdowns: list[CategoryBreakdown]):
    print(f"{'Category':<30} {'N':>5} {'Prec':>6} {'Rec':>6} {'F1':>6}")
    print("-" * 60)
    for b in breakdowns:
        print(f"{b.category:<30} {b.n_cases:>5} {b.precision:>6.2f} "
              f"{b.recall:>6.2f} {b.f1:>6.2f}")
        if b.f1 < 0.6:
            print(f"    ⚠ Low performance — sample errors:")
            for err in b.common_errors[:3]:
                print(f"      {err}")

if __name__ == "__main__":
    cases = load_eval_cases_with_metadata(
        Path("experiments/v0.1_qlora_run1/eval_results.jsonl"),
        Path("benchmark/v0.1/benchmark_cases.jsonl"),
    )
    breakdowns = breakdown_by_category(cases)
    print_report(breakdowns)
```

### 52.3 لماذا الفئات الأضعف تُطبَع أولًا وليس الأقوى

القرار المتعمَّد: `sorted(breakdowns, key=lambda b: b.f1)` يضع الأداء الأضعف في أعلى التقرير. الهدف من هذا التقرير ليس الاحتفال بما ينجح فيه النموذج بالفعل — بل توجيه الانتباه فورًا لما يحتاج عملاً إضافيًا. هذا يتماشى مباشرة مع دورة الفصل التالي في الكتاب الكامل (Active Learning: النموذج يفشل → الإنسان يراجع → الـDataset يتحسّن → إعادة تدريب).

---

## الفصل 53: Semantic Evaluation

### 53.1 لماذا Exact Match لا يكفي للحقول النصية

مقارنة `verdict` (`vulnerable` مقابل `secure`) بسيطة — تطابق نصي حرفي كافٍ. لكن حقولًا مثل `root_cause` أو `security_invariant` نصوص حرة؛ النموذج قد يُعبِّر عن **نفس** المفهوم الصحيح بصياغة مختلفة تمامًا عن الـground truth. مقارنة نصية حرفية هنا (`==`) ستُسجِّل هذا كخطأ رغم أن الفهم صحيح.

### 53.2 ثلاث طبقات للمقارنة الدلالية

| الطبقة | الوصف | متى تكفي وحدها |
|---|---|---|
| **Structured labels** | مقارنة `category` (من Taxonomy الفصل 10) أو رقم `matched_invariant_id` (من مكتبة الفصل 9) — هذه حقول مُصنَّفة، ليست نصًا حرًا | عندما تكون الأداة (الفصل 29) وسمت العينة بـcategory/invariant ID صريح |
| **Normalized categories** | تطبيع النص (lowercase، إزالة كلمات وظيفية، مطابقة كلمات مفتاحية من مكتبة الفصل 9) قبل المقارنة | عندما لا يوجد تصنيف صريح لكن يوجد نمط نصي متوقَّع بشكل معقول |
| **LLM judge (مع ضمانات)** | استخدام نموذج آخر (أو نفس النموذج بشكل منفصل) للحكم إن كان نصان يعبّران عن نفس المعنى الجوهري | فقط للحالات التي تفشل فيها الطبقتان السابقتان — ويُستخدَم بحذر شديد |

### 53.3 `evaluation/semantic_matcher.py`

```python
# evaluation/semantic_matcher.py
"""
يطبّق الطبقات الثلاث بالترتيب — لا يقفز للـLLM judge (الأغلى والأقل
موثوقية) إلا بعد فشل الطبقتين الأرخص والأكثر حتمية.
"""
import re
from dataclasses import dataclass

INVARIANT_KEYWORDS = {
    # يُبنى من مكتبة الفصل 9 — تعيين مبسّط لأغراض التوضيح هنا؛
    # النسخة الكاملة تُحمَّل من ملف تهيئة يغطي كل الـ50 invariant
    "cross_user": ["cross-user", "another user", "userid", "user handle"],
    "package_identity": ["package", "packagename", "ownership"],
    "identity_transition": ["clearcallingidentity", "identity", "restore"],
}

@dataclass
class SemanticMatchResult:
    matched: bool
    method_used: str  # 'structured' | 'normalized' | 'llm_judge' | 'no_match'
    confidence: float

def match_by_structured_label(
    predicted_category: str | None, true_category: str | None
) -> SemanticMatchResult | None:
    if predicted_category is None or true_category is None:
        return None  # لا توجد بيانات مُصنَّفة — ننتقل للطبقة التالية
    matched = predicted_category == true_category
    return SemanticMatchResult(matched, "structured", 1.0 if matched else 0.0)

def match_by_normalized_keywords(
    predicted_text: str, true_category_hint: str
) -> SemanticMatchResult | None:
    keywords = INVARIANT_KEYWORDS.get(true_category_hint)
    if not keywords:
        return None
    normalized = predicted_text.lower()
    hits = sum(1 for kw in keywords if kw in normalized)
    matched = hits >= max(1, len(keywords) // 2)  # أغلبية الكلمات المفتاحية
    confidence = min(1.0, hits / len(keywords))
    return SemanticMatchResult(matched, "normalized", confidence)

def match_semantic(
    predicted_text: str,
    predicted_category: str | None,
    true_category: str | None,
    true_category_hint: str | None,
) -> SemanticMatchResult:
    structured = match_by_structured_label(predicted_category, true_category)
    if structured is not None:
        return structured

    if true_category_hint:
        normalized = match_by_normalized_keywords(predicted_text, true_category_hint)
        if normalized is not None:
            return normalized

    # الطبقة الثالثة (LLM judge) تتطلب استدعاء نموذج فعلي — تُترَك كنقطة
    # تكامل صريحة هنا بدل تنفيذها بلا ضوابط، تفاديًا لاستخدامها كحل
    # افتراضي كسول بدل الطبقتين الأرخص والأكثر ثباتًا
    return SemanticMatchResult(False, "no_match", 0.0)
```

### 53.4 ضوابط استخدام LLM Judge

لو استُخدِم LLM judge فعليًا (خارج نطاق دالة `match_semantic` أعلاه)، يجب أن يخضع لنفس ضوابط الفصل 50 (Teacher Model Workflow):

- **لا يُستخدَم كطبقة أولى أبدًا** — فقط بعد فشل الطبقتين الأرخص.
- **Prompt محدود جدًا وموجَّه**: "هل النصان يعبّران عن نفس security invariant جوهريًا؟ نعم/لا فقط" — وليس تقييمًا حرًا مفتوحًا عرضة لعدم الاتساق.
- **عينة عشوائية من قراراته تخضع لمراجعة بشرية دوريًا** للتأكد من موثوقيته المستمرة — لا يُترَك بلا تدقيق دائم.

> **Definition of Done — الجزء الثامن والعشرون:** تشغيل `detailed_evaluator.py` على أول نتائج تقييم فعلية (بعد تدريب الفصل 46) ينتج تقريرًا كاملاً موزَّعًا حسب الفئة، مع تحديد صريح لأضعف فئتين على الأقل والأخطاء النموذجية فيهما — هذا التقرير هو المدخل المباشر لبدء دورة Active Learning اللاحقة في المشروع الكامل.

---

[← الجزء السابع والعشرون](./part-27-quality-scoring.md) · [الفهرس](./README.md) · [الجزء التاسع والعشرون →](./part-29-calibration-and-beyond.md)
