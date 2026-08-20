[← الجزء السادس والعشرون](./part-26-synthetic-data.md) · [الفهرس](./README.md)

# الجزء السابع والعشرون: Quality Scoring

## الفصل 51: Sample Quality

كل الفصول السابقة أنتجت عينات "مسودة" (drafts) بحقل `provenance.quality_score = 0`. هذا الفصل يبني نظام التسجيل الرسمي الذي يحوّل مسودة إلى عينة معتمدة قابلة للدخول في `train.jsonl` — وهو نقطة التفتيش الأخيرة قبل أي عينة تصل للتدريب فعليًا.

### 51.1 الأبعاد الستة

كل عينة تُقيَّم على ستة أبعاد، كل واحد من 0 إلى 5، بمجموع أقصى 30:

| البعد | يقيس ماذا | مثال على تقييم منخفض (0-1) | مثال على تقييم عالٍ (4-5) |
|---|---|---|---|
| **Source authenticity** | هل الكود مصدره حقيقي وموثَّق (وليس مُتخيَّلاً)؟ | كود synthetic لم يُتحقَّق منه بعد | كود من commit حقيقي بـ`source.commit_hash` صالح وقابل للتحقق |
| **Security relevance** | هل الحالة فعليًا ذات دلالة أمنية، وليست تفصيلاً عاديًا؟ | method لا علاقة لها بأي trust boundary حقيقي | method تمس Binder identity أو cross-user authorization مباشرة |
| **Reasoning quality** | هل سلسلة التحليل في `analysis.*` منطقية ومتماسكة؟ | `candidate_issue` عام وغامض بلا تفاصيل | تحليل يتتبع Source → Validation → Sink بوضوح |
| **Groundedness** | هل كل ادعاء في النص له مصدر فعلي في الكود المُعطى؟ (نفس فحص الفصل 50.3) | يذكر method غير موجودة في `code_context` | كل اسم مذكور موجود فعليًا في الكود المرفق |
| **Context completeness** | هل `code_context` كافٍ لإصدار الحكم المذكور دون معلومة ناقصة حاسمة؟ | يوجد `unresolved_notes` غير فارغة لكن الحكم `vulnerable` قاطع رغم ذلك | كل ما يلزم للحكم متوفر، أو الحكم `insufficient_context` بشكل متسق |
| **Label confidence** | مدى ثقة المصدر نفسه (وليس النموذج المستقبلي) في صحة هذا التصنيف | مصدره `auto_draft_v1` بدون أي مراجعة | مصدره `manual_v1` بمراجعة بشرية كاملة موثَّقة |

### 51.2 `quality/scorer.py`

```python
# quality/scorer.py
"""
نظام تسجيل جزئي آلي: بعض الأبعاد تُحسَب آليًا بالكامل (Groundedness,
Context completeness)، وبعضها يحصل على تقدير آلي أولي قابل للتعديل
اليدوي (Reasoning quality, Security relevance) — لا بُعد واحد يُترَك
لتخمين عشوائي بلا أي أساس محسوب.
"""
from dataclasses import dataclass
import re

@dataclass
class QualityScore:
    source_authenticity: int
    security_relevance: int
    reasoning_quality: int
    groundedness: int
    context_completeness: int
    label_confidence_score: int
    total: int
    auto_computed_dimensions: list[str]
    needs_manual_review_dimensions: list[str]

def score_source_authenticity(sample: dict) -> int:
    source = sample["source"]
    provenance = sample["provenance"]

    if provenance["generation_method"] == "synthetic_verified":
        return 2  # حتى لو اجتاز التحقق، يبقى أقل من مصدر حقيقي مباشر
    if source.get("commit_before") and source.get("commit_after"):
        return 5  # patch حقيقي كامل التوثيق
    if source.get("commit_before") or source.get("commit_after"):
        return 4  # نصف توثيق (مثلاً stable code بدون patch مقابل)
    return 1

def score_groundedness(sample: dict) -> int:
    """يعيد استخدام منطق الفصل 50.3 — نفس الفحص، لكن كنقاط 0-5 بدل bool."""
    ctx = sample["code_context"]
    analysis = sample["analysis"]
    combined_text = " ".join([
        analysis.get("candidate_issue", ""),
        " ".join(analysis.get("counter_evidence", [])),
    ])
    combined_code = ctx.get("current_method", "") + " " + (ctx.get("caller") or "")

    mentioned = set(re.findall(r"\b[a-zA-Z][a-zA-Z0-9_]{4,}\b", combined_text))
    common_words = {"context", "method", "caller", "before", "after", "would", "could"}
    mentioned -= common_words

    if not mentioned:
        return 3  # لا يوجد نص كافٍ للحكم — درجة متوسطة محايدة
    missing = [m for m in mentioned if m not in combined_code]
    missing_ratio = len(missing) / len(mentioned)

    if missing_ratio == 0:
        return 5
    elif missing_ratio < 0.15:
        return 4
    elif missing_ratio < 0.3:
        return 3
    elif missing_ratio < 0.5:
        return 2
    return 1

def score_context_completeness(sample: dict) -> int:
    ctx = sample["code_context"]
    verdict = sample["verdict"]
    has_unresolved = bool(ctx.get("unresolved_notes"))

    if verdict == "insufficient_context":
        return 5 if has_unresolved else 1
    else:
        return 5 if not has_unresolved else 2

LABEL_CONFIDENCE_MAP = {"high": 5, "medium": 3, "low": 1}

def score_label_confidence(sample: dict) -> int:
    return LABEL_CONFIDENCE_MAP.get(
        sample["provenance"]["label_confidence"], 1
    )

def score_sample(
    sample: dict,
    manual_security_relevance: int | None = None,
    manual_reasoning_quality: int | None = None,
) -> QualityScore:
    """security_relevance وreasoning_quality يتطلبان حكمًا دلاليًا
    أعمق من قواعد بسيطة قابلة للأتمتة الكاملة في v0.1 — يُقبَل تقدير
    يدوي هنا، مع قيمة افتراضية محافظة (3) لو لم يُقدَّم بعد، ليُعاد
    ترقيمها لاحقًا أثناء المراجعة البشرية الرسمية بدل تركها صفرًا
    مضللاً في التجميع الأولي."""
    auto_dims = ["source_authenticity", "groundedness", "context_completeness", "label_confidence_score"]
    manual_dims = []

    source_auth = score_source_authenticity(sample)
    groundedness = score_groundedness(sample)
    context_completeness = score_context_completeness(sample)
    label_conf = score_label_confidence(sample)

    if manual_security_relevance is None:
        security_relevance = 3
        manual_dims.append("security_relevance")
    else:
        security_relevance = manual_security_relevance

    if manual_reasoning_quality is None:
        reasoning_quality = 3
        manual_dims.append("reasoning_quality")
    else:
        reasoning_quality = manual_reasoning_quality

    total = (
        source_auth + security_relevance + reasoning_quality
        + groundedness + context_completeness + label_conf
    )

    return QualityScore(
        source_authenticity=source_auth,
        security_relevance=security_relevance,
        reasoning_quality=reasoning_quality,
        groundedness=groundedness,
        context_completeness=context_completeness,
        label_confidence_score=label_conf,
        total=total,
        auto_computed_dimensions=auto_dims,
        needs_manual_review_dimensions=manual_dims,
    )
```

### 51.3 عتبات القرار

```python
# quality/decide.py
from dataclasses import dataclass

@dataclass
class QualityDecision:
    action: str  # 'accept' | 'manual_review' | 'reject'
    reason: str

def decide(score_total: int, has_pending_manual_dims: bool) -> QualityDecision:
    if has_pending_manual_dims:
        return QualityDecision(
            "manual_review",
            "security_relevance and/or reasoning_quality not yet "
            "manually scored — cannot finalize decision from automated "
            "score alone"
        )
    if score_total >= 26:
        return QualityDecision("accept", f"score {score_total} >= 26")
    if score_total >= 22:
        return QualityDecision(
            "manual_review", f"score {score_total} in 22-25 range"
        )
    return QualityDecision("reject", f"score {score_total} < 22")
```

### 51.4 تشغيل على دفعة كاملة

```python
# quality/run_scoring.py
import json
from pathlib import Path
from dataclasses import asdict
from quality.scorer import score_sample
from quality.decide import decide

def process_batch(input_path: Path, accepted_path: Path,
                   review_path: Path, rejected_path: Path):
    for p in (accepted_path, review_path, rejected_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    counts = {"accept": 0, "manual_review": 0, "reject": 0}

    with input_path.open() as fin, \
         accepted_path.open("w") as f_accept, \
         review_path.open("w") as f_review, \
         rejected_path.open("w") as f_reject:

        for line in fin:
            sample = json.loads(line)
            quality = score_sample(sample)
            decision = decide(
                quality.total, bool(quality.needs_manual_review_dimensions)
            )
            counts[decision.action] += 1

            sample["provenance"]["quality_score"] = quality.total
            output_record = {
                "sample": sample,
                "quality_breakdown": asdict(quality),
                "decision": decision.action,
                "decision_reason": decision.reason,
            }

            target = {
                "accept": f_accept, "manual_review": f_review,
                "reject": f_reject,
            }[decision.action]
            target.write(json.dumps(output_record, ensure_ascii=False) + "\n")

    print(f"Accepted: {counts['accept']}")
    print(f"Needs manual review: {counts['manual_review']}")
    print(f"Rejected: {counts['reject']}")

if __name__ == "__main__":
    process_batch(
        input_path=Path("sample_generator/output/android-14_draft_samples.jsonl"),
        accepted_path=Path("quality/output/accepted.jsonl"),
        review_path=Path("quality/output/needs_review.jsonl"),
        rejected_path=Path("quality/output/rejected.jsonl"),
    )
```

### 51.5 لماذا الأبعاد الدلالية (Security relevance, Reasoning quality) لا تُؤتمَت بالكامل في v0.1

هذان البُعدان يتطلبان حكمًا يقترب من فهم عميق لجودة سلسلة الاستدلال نفسها — وهو بالضبط ما نحاول تدريب النموذج على فعله. أتمتتهما بالكامل الآن (قبل وجود نموذج مدرَّب موثوق) تخاطر بحلقة دائرية: استخدام تقييم غير موثوق لبناء بيانات تدريب، ثم تدريب نموذج على تقييمات قد تكون خاطئة من الأساس. لذلك v0.1 تفرض مراجعة يدوية لهذين البُعدين تحديدًا، وتترك الباب مفتوحًا لأتمتتهما لاحقًا (v0.2+) فقط بعد توفر نموذج أولي موثوق كفاية ليُستخدَم كـ"مساعد تقييم" مُتحقَّق منه بدوره.

> **Definition of Done — الجزء السابع والعشرون:** تشغيل `run_scoring.py` على كل عينات المسودات (نواتج الفصل 29، 31، 32، 26 هذا الجزء)، مع مراجعة يدوية فعلية لكل عينة وقعت في `needs_review.jsonl` (تحديد `manual_security_relevance` و`manual_reasoning_quality` لكل واحدة)، وإعادة تشغيل التسجيل بعد اكتمال المراجعة اليدوية للوصول لقرار نهائي (`accept`/`reject`) لكل عينة قبل دخولها لمرحلة الـTrain/Test Splitting (الفصل 36).

---

[← الجزء السادس والعشرون](./part-26-synthetic-data.md) · [الفهرس](./README.md) · [الجزء الثامن والعشرون →](./part-28-evaluation.md)
