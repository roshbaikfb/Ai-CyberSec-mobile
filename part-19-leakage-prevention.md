[← الجزء الثامن عشر](./part-18-deduplication.md) · [الفهرس](./README.md)

# الجزء التاسع عشر: Leakage Prevention

هذا الجزء يتعامل مع **أخطر مشكلة منهجية** يمكن أن تصيب المشروع بالكامل، كما ذُكر في الفصل الثالث عشر من الكتاب الأصلي: نموذج يبدو ناجحًا في الـBenchmark لأنه **حفظ** الإجابة، وليس لأنه فهم المنهجية. Deduplication (الجزء السابق) يمنع التكرار الحرفي؛ هذا الجزء يمنع أشكالًا أخف وأخطر من التسرب لا يكتشفها الـhashing وحده.

## الفصل 36: Train/Test Splitting

### 36.1 لماذا Random Split وحده غير كافٍ

تقسيم عشوائي بسيط (`train_test_split` القياسي) يفترض أن العينات **مستقلة إحصائيًا** — وهذا افتراض خاطئ هنا. عدة عينات مشتقة من نفس الـpatch (الفصل 29 أنتج تسع عينات من patch واحد) تتشارك سياقًا شديد التقارب؛ لو عينة واحدة منها وقعت في Train والأخرى في Test، النموذج قد "يتعرف" على النمط من نسخة رآها أثناء التدريب.

### 36.2 خمسة مستويات للتقسيم

| المستوى | يضمن ماذا | متى نستخدمه |
|---|---|---|
| **Commit-level** | كل العينات المشتقة من نفس commit تقع بالكامل في نفس الـsplit | الحد الأدنى الإلزامي دائمًا — لا استثناء |
| **CVE-level** | كل العينات المرتبطة بنفس CVE (قد تشمل أكثر من commit عبر إصدارات مختلفة) تقع معًا | عند وجود ربط CVE فعلي (الفصل 18) |
| **File-family** | نفس الملف (أو ملفات متشابهة جدًا بنيويًا، مثل نفس الـService عبر إصدارات) لا تتوزع بين splits | يقلل تسرب الأسلوب/النمط الخاص بملف معيّن |
| **Version-level** | إصدار Android كامل (مثل android-14 بالكامل) يُخصَّص لـsplit واحد | مفيد لاختبار التعميم عبر إصدارات لم يرها النموذج إطلاقًا |
| **Time-based** | القطع الزمني: قبل تاريخ X للتدريب، بعده للاختبار | الأقوى للـFuture Patch Evaluation (الفصل 37) |

### 36.3 `dataset_splitting/splitter.py`

```python
# dataset_splitting/splitter.py
"""
ينفّذ تقسيمًا هرميًا: يبدأ بتجميع العينات في 'وحدات لا تُقسَّم'
(commit-level كحد أدنى، مع خيار CVE-level وfile-family)، ثم يوزّع
هذه الوحدات — وليس العينات الفردية — بين train/validation/test.
"""
import json
import random
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class SplitConfig:
    train_ratio: float = 0.7
    validation_ratio: float = 0.15
    test_ratio: float = 0.15
    group_by: str = "commit"   # 'commit' | 'cve' | 'file_family'
    random_seed: int = 42

def get_grouping_key(sample: dict, group_by: str) -> str:
    source = sample["source"]
    if group_by == "commit":
        # نستخدم كلا الـcommit hash — عينة before وafter لنفس الـpatch
        # يجب أن تبقيا معًا دائمًا
        return f"{source.get('commit_before')}_{source.get('commit_after')}"
    elif group_by == "cve":
        return source.get("cve") or get_grouping_key(sample, "commit")
    elif group_by == "file_family":
        return source["file"]
    raise ValueError(f"Unknown group_by: {group_by}")

def split_dataset(samples: list[dict], config: SplitConfig) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for sample in samples:
        key = get_grouping_key(sample, config.group_by)
        groups[key].append(sample)

    group_keys = list(groups.keys())
    random.Random(config.random_seed).shuffle(group_keys)

    n = len(group_keys)
    n_train = int(n * config.train_ratio)
    n_val = int(n * config.validation_ratio)

    train_keys = set(group_keys[:n_train])
    val_keys = set(group_keys[n_train:n_train + n_val])
    test_keys = set(group_keys[n_train + n_val:])

    result = {"train": [], "validation": [], "test": []}
    for key, group_samples in groups.items():
        if key in train_keys:
            result["train"].extend(group_samples)
        elif key in val_keys:
            result["validation"].extend(group_samples)
        else:
            result["test"].extend(group_samples)

    return result

def verify_no_leakage(splits: dict[str, list[dict]], group_by: str) -> bool:
    """تحقق إلزامي بعد كل تقسيم: لا مجموعة واحدة يجب أن تظهر
    مفاتيحها في أكثر من split واحد."""
    keys_per_split = {}
    for split_name, samples in splits.items():
        keys_per_split[split_name] = {
            get_grouping_key(s, group_by) for s in samples
        }

    overlap_found = False
    split_names = list(keys_per_split.keys())
    for i in range(len(split_names)):
        for j in range(i + 1, len(split_names)):
            overlap = keys_per_split[split_names[i]] & keys_per_split[split_names[j]]
            if overlap:
                print(f"LEAKAGE DETECTED between {split_names[i]} and "
                      f"{split_names[j]}: {len(overlap)} shared groups")
                overlap_found = True

    return not overlap_found

def run_split(samples_jsonl: Path, output_dir: Path, config: SplitConfig):
    samples = [json.loads(line) for line in samples_jsonl.open()]
    splits = split_dataset(samples, config)

    assert verify_no_leakage(splits, config.group_by), (
        "Leakage check failed — refusing to write split files"
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    for split_name, split_samples in splits.items():
        out_path = output_dir / f"{split_name}.jsonl"
        with out_path.open("w") as f:
            for s in split_samples:
                s["provenance"] = {**s["provenance"]}  # نسخة defensively
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"{split_name}: {len(split_samples)} samples -> {out_path}")

if __name__ == "__main__":
    config = SplitConfig(group_by="commit")
    run_split(
        samples_jsonl=Path("dataset/v0.1/deduplicated_samples.jsonl"),
        output_dir=Path("dataset/v0.1/splits"),
        config=config,
    )
```

> **لماذا `verify_no_leakage` جزء إلزامي من نفس السكريبت وليس خطوة منفصلة اختيارية:** فصل التحقق عن التقسيم يخلق فرصة لتشغيل التقسيم دون تحقق (نسيان، أو تعديل سريع لاحق). ربطهما في نفس الدالة (`assert` قبل الكتابة) يجعل من المستحيل بنيويًا إنتاج ملفات splits مسرَّبة دون أن يفشل السكريبت بوضوح.

---

## الفصل 37: Future Patch Evaluation

هذا هو الـBenchmark الأهم في المشروع بالكامل — الاختبار الحقيقي لسؤال: **"هل النموذج يكتشف شيئًا جديدًا، أم يسترجع ما حفظه؟"**

### 37.1 المبدأ

بدل التقسيم العشوائي (حتى الهرمي منه في الفصل 36)، نقسّم زمنيًا: **كل** الـpatches قبل تاريخ معيّن تُستخدم للتدريب، و**كل** الـpatches بعده تُحجَز بالكامل للاختبار — دون أي استثناء أو تسريب، بصرف النظر عن مدى تشابهها مع شيء في التدريب.

```
الخط الزمني:
├── Patches (2020 - 2023-06-30)  → Training pool بالكامل
│
├─────────── نقطة القطع (cutoff) ───────────
│
└── Patches (2023-07-01 - اليوم)  → Future Patch Benchmark
                                     (لم يرها النموذج بأي شكل)
```

### 37.2 لماذا هذا أقوى من أي split آخر

| نوع Split | يثبت ماذا |
|---|---|
| Random / Commit-level | النموذج لا يحفظ نفس الأمثلة الحرفية |
| Version-level | النموذج يعمم عبر بنية كود مختلفة قليلًا بين الإصدارات |
| **Time-based (Future Patch)** | النموذج يكتشف **نمط ثغرة لم يكن موجودًا حتى في أي شكل مشابه وقت التدريب** — أقرب محاكاة ممكنة لسيناريو "يوم الصفر" (zero-day) الحقيقي |

### 37.3 `dataset_splitting/future_patch_split.py`

```python
# dataset_splitting/future_patch_split.py
import json
from pathlib import Path
from datetime import datetime, timezone

def parse_commit_date(sample: dict) -> datetime | None:
    """يعتمد على metadata محفوظة أثناء الفصل 14/17 — نفترض هنا
    وجود حقل author_date ضمن source إن أُضيف مسبقًا (يتطلب توسيع
    خفيف لـSchema الفصل 27 لحمل تاريخ الـcommit — إضافة موصى بها)."""
    date_str = sample["source"].get("commit_date")
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str)
    except ValueError:
        return None

def split_by_cutoff(
    samples: list[dict], cutoff: datetime
) -> tuple[list[dict], list[dict], list[dict]]:
    """يُرجع (training_pool, future_benchmark, undated_excluded)."""
    training_pool, future_benchmark, undated = [], [], []

    for sample in samples:
        date = parse_commit_date(sample)
        if date is None:
            undated.append(sample)  # لا نخمّن — نستبعد بصراحة
            continue
        if date < cutoff:
            training_pool.append(sample)
        else:
            future_benchmark.append(sample)

    return training_pool, future_benchmark, undated

def run_future_patch_split(
    samples_jsonl: Path, output_dir: Path, cutoff_date: str
):
    cutoff = datetime.fromisoformat(cutoff_date).replace(tzinfo=timezone.utc)
    samples = [json.loads(line) for line in samples_jsonl.open()]

    training_pool, future_benchmark, undated = split_by_cutoff(samples, cutoff)

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, group in [
        ("training_pool", training_pool),
        ("future_benchmark", future_benchmark),
        ("undated_excluded", undated),
    ]:
        path = output_dir / f"{name}.jsonl"
        with path.open("w") as f:
            for s in group:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"{name}: {len(group)} samples -> {path}")

    if undated:
        print(f"\n⚠ {len(undated)} samples lack commit_date and were "
              f"EXCLUDED entirely from this benchmark — they must not be "
              f"assumed 'safe for training' by default.")

if __name__ == "__main__":
    run_future_patch_split(
        samples_jsonl=Path("dataset/v0.1/deduplicated_samples.jsonl"),
        output_dir=Path("dataset/v0.1/future_patch_split"),
        cutoff_date="2023-07-01",
    )
```

### 37.4 قاعدة تشغيلية: هذا Benchmark لا يُعاد استخدامه بلا حدود

بمجرد استخدام `future_benchmark.jsonl` لتقييم نموذج معيّن، **يجب توثيق ذلك رسميًا** (في جدول `evaluations` من الفصل 34). لو استمر الفريق في ضبط الـDataset أو الـPrompt بناءً على نتائج هذا الـBenchmark تحديدًا بشكل متكرر، فهو يتحوّل تدريجيًا لجزء ضمني من عملية التطوير (overfitting على مستوى القرارات الهندسية، وليس أوزان النموذج) — ويفقد قيمته كاختبار "يوم صفر" حقيقي. الممارسة السليمة: تحديث نافذة الـcutoff دوريًا (كل بضعة أشهر) بحيث تشمل patches أحدث لم تُستخدم من قبل في أي تقييم سابق.

> **Definition of Done — الجزء التاسع عشر:** ملفا `future_benchmark.jsonl` وملفات `dataset/v0.1/splits/*.jsonl` (من الفصل 36) موجودان فعليًا، مع تشغيل ناجح لـ`verify_no_leakage` بدون أي تحذير، وتوثيق صريح لعدد العينات المستبعدة بسبب غياب `commit_date` (`undated_excluded`) — هذا العدد يجب ألا يكون مرتفعًا بشكل يُفرغ الـFuture Benchmark من قيمته الإحصائية.

---

[← الجزء الثامن عشر](./part-18-deduplication.md) · [الفهرس](./README.md) · [الجزء العشرون →](./part-20-benchmark.md)
