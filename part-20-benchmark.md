[← الجزء التاسع عشر](./part-19-leakage-prevention.md) · [الفهرس](./README.md)

# الجزء العشرون: Benchmark

بعد كل آليات منع التسرب (الجزء التاسع عشر)، هذا الجزء يبني الـBenchmark الرسمي v0.1 — المجموعة الثابتة التي ستُستخدم لقياس **كل** تجربة تدريب لاحقة بنفس المعايير بالضبط.

## الفصل 38: Benchmark v0.1

### 38.1 الفئات السبع الإلزامية

كل Benchmark يجب أن يغطي هذه الفئات، وليس فقط الحالات "السهلة" أو الأكثر توفرًا:

| الفئة | المصدر | الهدف من تضمينها |
|---|---|---|
| **Known patterns** | Vulnerable/Fixed pairs مألوفة النمط (الفصل 29) | خط أساس — النموذج يجب أن ينجح فيها كحد أدنى |
| **Unseen patches** | Future Patch Benchmark (الفصل 37) | الاختبار الأقوى للتعميم الحقيقي |
| **Secure samples** | Negatives عادية (الفصل 30) | يمنع الانحياز نحو "كل شيء vulnerable" |
| **Hard negatives** | من الفصل 31 تحديدًا | يقيس القدرة على تمييز الأنماط المتشابهة شكليًا |
| **Cross-version cases** | نفس الـmethod عبر إصدارات مختلفة (الفصل 35.5) | يقيس الاستقرار — نفس الكود يجب أن يُعطى نفس الحكم بصرف النظر عن الإصدار |
| **Multi-method cases** | حالات تتطلب Call Graph + Retrieval (الجزء 11-12) | يقيس القدرة على الـReasoning متعدد الدوال، وليس فقط قراءة method واحدة |
| **Insufficient-context cases** | من الجزء السادس عشر | يقيس الانضباط ضد التخمين |

### 38.2 لماذا لا نكتفي بسحب عينة عشوائية من الـtest split

عينة عشوائية من `test.jsonl` (الفصل 36) قد تكون منحازة بالصدفة — مثلًا 80% منها `vulnerable` لأن هذا ما توفّر أكثر في المصادر. الـBenchmark الرسمي **يُبنى بعناية** لضمان تمثيل متوازن نسبيًا عبر الفئات السبع، حتى لو تطلّب ذلك استبعاد بعض عينات الـtest split الفائضة عن فئة معيّنة أو استكمال عينات إضافية لفئة ناقصة.

### 38.3 تنسيق الـBenchmark (`benchmark/format.py`)

```python
# benchmark/format.py
from pydantic import BaseModel
from typing import Literal
from dataset.schema import DatasetSample

BenchmarkCategory = Literal[
    "known_patterns", "unseen_patches", "secure_samples",
    "hard_negatives", "cross_version", "multi_method",
    "insufficient_context_cases",
]

BenchmarkDifficulty = Literal["easy", "medium", "hard"]

class BenchmarkCase(BaseModel):
    case_id: str
    sample: DatasetSample
    category: BenchmarkCategory
    difficulty: BenchmarkDifficulty
    notes: str | None = None
```

### 38.4 بناء الـBenchmark من الأجزاء المتوفرة

```python
# benchmark/build_v01.py
import json
import random
from pathlib import Path
from collections import defaultdict

TARGET_DISTRIBUTION = {
    "known_patterns": 40,
    "unseen_patches": 40,
    "secure_samples": 30,
    "hard_negatives": 30,
    "cross_version": 15,
    "multi_method": 20,
    "insufficient_context_cases": 25,
}

SOURCE_FILES = {
    "known_patterns": Path("dataset/v0.1/splits/test.jsonl"),
    "unseen_patches": Path("dataset/v0.1/future_patch_split/future_benchmark.jsonl"),
    "secure_samples": Path("dataset/v0.1/splits/test.jsonl"),  # يُفلتَر لاحقًا بالحكم
    "hard_negatives": Path("negative_mining/output/reviewed_hard_negatives.jsonl"),
    "cross_version": Path("dataset/v0.1/cross_version_candidates.jsonl"),
    "multi_method": Path("dataset/v0.1/multi_method_candidates.jsonl"),
    "insufficient_context_cases": Path("dataset/v0.1/splits/test.jsonl"),  # يُفلتَر بالحكم
}

def load_and_filter(path: Path, verdict_filter: str | None, seed: int) -> list[dict]:
    if not path.exists():
        print(f"⚠ Source not found, skipping: {path}")
        return []
    samples = [json.loads(line) for line in path.open()]
    if verdict_filter:
        samples = [s for s in samples if s["verdict"] == verdict_filter]
    random.Random(seed).shuffle(samples)
    return samples

def build_benchmark(output_path: Path, seed: int = 123):
    cases = []
    case_counter = 0

    filters = {
        "secure_samples": "secure",
        "insufficient_context_cases": "insufficient_context",
    }

    for category, target_count in TARGET_DISTRIBUTION.items():
        source_path = SOURCE_FILES[category]
        samples = load_and_filter(
            source_path, filters.get(category), seed + hash(category) % 1000
        )
        selected = samples[:target_count]

        if len(selected) < target_count:
            print(f"⚠ {category}: only {len(selected)}/{target_count} "
                  f"available — benchmark will be under-represented here "
                  f"until more source samples are produced")

        for s in selected:
            case_counter += 1
            cases.append({
                "case_id": f"bench_v01_{case_counter:04d}",
                "sample": s,
                "category": category,
                "difficulty": "medium",  # يُعدَّل يدويًا لاحقًا بعد المراجعة
                "notes": None,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for case in cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")

    print(f"\nBenchmark v0.1 built: {len(cases)} total cases")
    counts = defaultdict(int)
    for c in cases:
        counts[c["category"]] += 1
    for cat, count in counts.items():
        print(f"  {cat}: {count}")

if __name__ == "__main__":
    build_benchmark(Path("benchmark/v0.1/benchmark_cases.jsonl"))
```

> **ملاحظة مهمة على الشفافية:** السكريبت أعلاه **يطبع صراحة** عندما فئة ما ناقصة العدد المستهدف، بدل ملء الفجوة بعينات غير مناسبة أو التظاهر باكتمال التغطية. Benchmark v0.1 قد يكون فعليًا غير مكتمل في بعض الفئات (خصوصًا `multi_method` و`cross_version` اللتان تتطلبان بنية تحتية أكثر تعقيدًا) — وهذا مقبول ومُوثَّق، على أن يُستكمَل في v0.2.

---

## الفصل 39: Ground Truth

### 39.1 التسلسل الهرمي لمصادر الحقيقة

كل `BenchmarkCase` يحتاج حكمًا نهائيًا (`ground truth verdict`) موثوقًا به بأعلى درجة ممكنة. نرتّب مصادر الثقة كالتالي، من الأقوى للأضعف:

```
Code evidence (مباشر من الكود نفسه)
        +
Historical patch evidence (لو الطريقة تغيّرت لاحقًا لإصلاح مشكلة معروفة)
        +
Issue/CVE evidence (لو مرتبطة بـCVE موثَّق فعليًا — الجزء الثامن)
        +
Manual review (باحث بشري يقرأ ويقرر)
        +
Controlled lab validation (حين ممكن — الجزء العاشر لاحقًا في الكتاب الكامل)
```

قاعدة أساسية: **لا حالة Benchmark تُعتمَد بمصدر واحد فقط لو كان بالإمكان توفير أكثر من مصدر.** حالة مشتقة من patch حقيقي (Code evidence + Patch evidence) أقوى من حالة معتمدة فقط على مراجعة بشرية واحدة بدون سياق تاريخي.

### 39.2 حالات الثقة (`benchmark/ground_truth_status.py`)

```python
# benchmark/ground_truth_status.py
from enum import Enum

class GroundTruthStatus(str, Enum):
    UNCONFIRMED = "unconfirmed"
    LIKELY = "likely"
    CONFIRMED_BUG = "confirmed_bug"                 # خطأ برمجي مؤكَّد، لكن أمنيته غير مؤكَّدة
    CONFIRMED_SECURITY_ISSUE = "confirmed_security_issue"
    FALSE_POSITIVE = "false_positive"                 # تبيّن لاحقًا أن الحكم الأصلي خاطئ

def determine_status(
    has_code_evidence: bool,
    has_patch_evidence: bool,
    has_cve_evidence: bool,
    has_manual_review: bool,
    has_lab_validation: bool,
) -> GroundTruthStatus:
    """قاعدة قرار حتمية — لا نترك هذا لتقدير حر غير موثَّق."""
    if has_lab_validation and (has_code_evidence or has_patch_evidence):
        return GroundTruthStatus.CONFIRMED_SECURITY_ISSUE

    if has_cve_evidence and has_patch_evidence:
        return GroundTruthStatus.CONFIRMED_SECURITY_ISSUE

    if has_patch_evidence and has_manual_review:
        return GroundTruthStatus.CONFIRMED_BUG

    if has_code_evidence and has_manual_review:
        return GroundTruthStatus.LIKELY

    return GroundTruthStatus.UNCONFIRMED
```

### 39.3 لماذا `CONFIRMED_BUG` منفصلة عن `CONFIRMED_SECURITY_ISSUE`

هذا تمييز حاسم كثيرًا ما يُهمَل: **ليس كل خطأ برمجي مصحَّح ثغرة أمنية فعلية.** كثير من الـcommits المُرشَّحة (الفصل 16) تصلح أخطاء منطقية عادية اكتُشفت أثناء التطوير، دون أي دلالة أمنية حقيقية (لا CVE، لا تصعيد صلاحيات محتمل). التصنيف يجب أن يعكس هذا الفرق بدقة — استخدام `CONFIRMED_SECURITY_ISSUE` لكل patch مُصلَح يُضخّم بشكل مصطنع من قيمة الـBenchmark ويُربك القياس لاحقًا.

### 39.4 دليل المراجع البشري (`docs/reviewer_guide.md` — ملخّص)

عند إجراء `manual_review`، يجب على المراجع الإجابة عن هذه الأسئلة بالترتيب (ونفس الترتيب المستخدم في الفصل 1 كعمود فقري للكتاب بالكامل):

1. من المتصل؟ هل هويته Trusted/Untrusted/Derived (الفصل 7.2)؟
2. ما البيانات التي يتحكم فيها المتصل (Sources — الفصل 8)؟
3. هل هناك Trust Boundary واضح (الفصل 7)؟
4. هل يوجد تحقق (Permission/AppOps/Cross-user) **قبل** الوصول للـSink؟
5. لو يوجد identity transition، هل التحقق حدث **قبله**؟
6. أي Security Invariant (الفصل 9) — إن وُجد — يُنتهَك أو يُطبَّق هنا؟
7. ما الفرق بين `ambiguous` و`insufficient_context` في هذه الحالة تحديدًا (الفصل 28.3)؟
8. ما مستوى الثقة الواقعي (`confidence`) — وليس 1.0 أو 0.0 افتراضيًا؟

> **قاعدة صارمة للمراجعين:** لو المراجع لا يستطيع الإجابة على السؤال 4 أو 5 بثقة من السياق المُعطى وحده (دون افتراضات)، الحكم الصحيح هو `insufficient_context`، بصرف النظر عن مدى "منطقية" الحكم البديل الذي يخطر بباله.

> **Definition of Done — الجزء العشرون:** ملف `benchmark/v0.1/benchmark_cases.jsonl` يحتوي على الأقل 150 حالة موزَّعة عبر الفئات السبع (حتى لو بعضها ناقص العدد المستهدف مع توثيق ذلك صراحة)، وكل حالة تحمل `ground_truth_status` محدَّد وفق `determine_status()`، مع عدم وجود أي حالة `UNCONFIRMED` ضمن الـBenchmark الرسمي (يُسمح بها فقط في مجموعات المراجعة الأولية قبل الاعتماد).

---

[← الجزء التاسع عشر](./part-19-leakage-prevention.md) · [الفهرس](./README.md) · [الجزء الحادي والعشرون →](./part-21-model-selection.md)
