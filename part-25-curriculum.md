[← الجزء الرابع والعشرون](./part-24-sft.md) · [الفهرس](./README.md)

# الجزء الخامس والعشرون: Curriculum

## الفصل 48: Curriculum Learning

هذا الفصل يبني الترتيب التدريجي لصعوبة العينات أثناء التدريب — بدل تقديم كل شيء بترتيب عشوائي منذ البداية، نُرتّب العينات من الأبسط (method واحدة) للأكثر تعقيدًا (patch غير معروف مع دفاعات جزئية) عبر ستة مستويات.

### 48.1 المستويات الستة وتعريف كل واحد بدقة

| المستوى | التعريف الدقيق | مصدر العينات (من فصول سابقة) |
|---|---|---|
| **1. Single-method** | `code_context.caller` = null و`security_helpers` فارغة — الحكم يعتمد فقط على محتوى method واحدة | Vulnerable/Fixed pairs بسيطة (الفصل 29)، Negatives أساسية (الفصل 30) |
| **2. Method + helper** | يوجد `security_helpers` واحد على الأقل محلول (غير null) | عينات مرَّت عبر Context Builder (الفصل 26) بنجاح استرجاع helper واحد |
| **3. Binder entry + service** | `is_binder_entry=true` (من الفصل 21) + `caller` محلول أيضًا | عينات تشمل نتائج Call Graph (الفصل 23) لتحديد caller فعلي |
| **4. Multi-method** | أكثر من `security_helper` واحد **و** caller محلولين معًا | أعقد نواتج Context Builder — عدة عناصر محلولة في نفس السياق |
| **5. Unknown patch + distracting code** | من Future Patch Benchmark (الفصل 37) — لم يُستخدَم في أي تدريب سابق، مع `code_context` يحتوي عناصر غير مؤثرة في الحكم (نصوص أو استدعاءات ليست هي المصدر الحقيقي للثغرة) | يُصنَّع يدويًا بإضافة استدعاءات/متغيرات إضافية غير حاسمة لعينات الفصل 37 |
| **6. Partial mitigations** | حالات تحقق **جزئي** — يوجد تحقق لكنه لا يغطي كل الاستخدام اللاحق (مثل مثال `grantAccess` من الفصل 8.4: تحقق `packageName` لكن ليس `targetUserId`) | Hard Negatives من الفصل 31 المصنَّفة تحديدًا كـ`ambiguous` وليس `secure`/`vulnerable` قاطعة |

### 48.2 لماذا هذا الترتيب تحديدًا

الأساس النظري: تعليم النموذج **البنية الأساسية للتحليل** (Sources، Sinks، Trust Boundary) على أبسط الحالات أولًا، قبل مطالبته بتطبيق نفس المنطق على حالات يتوزع فيها الدليل عبر عدة methods أو تختلط فيه إشارات صحيحة بمُشتِّتات. هذا يحاكي تدريب باحث بشري مبتدئ — يبدأ بمراجعة methods بسيطة قبل الانتقال لتتبع تدفقات معقدة عبر خدمة كاملة.

### 48.3 `curriculum/classifier.py`

```python
# curriculum/classifier.py
"""
يصنّف كل عينة موجودة بالفعل في train.jsonl (بعد كل مراحل الفصل
13-19) إلى أحد المستويات الستة، بناءً على خصائص code_context
المتاحة فعليًا — لا يُعيد توليد أي شيء، فقط يصنّف الموجود.
"""
import json
from pathlib import Path
from dataclasses import dataclass

CurriculumLevel = int  # 1-6

@dataclass
class ClassifiedSample:
    sample_id: str
    level: CurriculumLevel
    reason: str

def classify_sample(sample: dict) -> ClassifiedSample:
    ctx = sample["code_context"]
    provenance = sample["provenance"]

    has_caller = bool(ctx.get("caller"))
    resolved_helpers = [
        v for v in ctx.get("security_helpers", {}).values() if v is not None
    ]
    n_resolved_helpers = len(resolved_helpers)
    is_future_patch = provenance.get("generation_method") == "patch_derived" and \
        sample["source"].get("commit_date_after_cutoff", False)
    is_partial_mitigation = (
        sample["verdict"] == "ambiguous"
        and provenance.get("generation_method") == "hard_negative_mined"
    )

    if is_partial_mitigation:
        return ClassifiedSample(sample["sample_id"], 6, "partial mitigation (ambiguous hard negative)")

    if is_future_patch:
        return ClassifiedSample(sample["sample_id"], 5, "unseen future patch")

    if n_resolved_helpers >= 2 and has_caller:
        return ClassifiedSample(sample["sample_id"], 4, "multi-method: 2+ helpers + caller")

    if has_caller and sample["analysis"].get("entry_point"):
        return ClassifiedSample(sample["sample_id"], 3, "binder entry + resolved caller")

    if n_resolved_helpers >= 1:
        return ClassifiedSample(sample["sample_id"], 2, "method + resolved helper")

    return ClassifiedSample(sample["sample_id"], 1, "single method, no external dependencies")

def classify_dataset(input_path: Path, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    level_counts = {i: 0 for i in range(1, 7)}

    with input_path.open() as fin, output_path.open("w") as fout:
        for line in fin:
            sample = json.loads(line)
            classification = classify_sample(sample)
            level_counts[classification.level] += 1
            fout.write(json.dumps({
                "sample_id": classification.sample_id,
                "level": classification.level,
                "reason": classification.reason,
            }, ensure_ascii=False) + "\n")

    print("Curriculum level distribution:")
    for level, count in level_counts.items():
        print(f"  Level {level}: {count}")

if __name__ == "__main__":
    classify_dataset(
        input_path=Path("dataset/v0.1/splits/train.jsonl"),
        output_path=Path("curriculum/output/train_levels.jsonl"),
    )
```

### 48.4 استراتيجيات الجدولة (Scheduling)

بمجرد تصنيف العينات، هناك أكثر من طريقة لترتيبها فعليًا أثناء التدريب:

| الاستراتيجية | الوصف | الأنسب لـ |
|---|---|---|
| **Sequential blocks** | تدريب كامل على Level 1 أولًا، ثم Level 2 بالكامل، وهكذا | تجارب استكشافية أولى — أسهل للتشخيص (أي مستوى يسبب مشاكل؟) |
| **Weighted mixing** | كل batch يحتوي مزيجًا من كل المستويات، لكن بأوزان تتحول تدريجيًا من "أغلبية Level 1" إلى "أغلبية Level 6" عبر التدريب | أكثر استقرارًا عمليًا — يمنع "نسيان" المستويات الأولى (catastrophic forgetting) بحلول نهاية التدريب |
| **Epoch-based shift** | Epoch الأول: كل المستويات بتوزيع متساوٍ. Epoch الأخير: توزيع منحاز أكثر للمستويات الصعبة | توازن بين البساطة والاستقرار — نقطة انطلاق موصى بها لـv0.1 |

### 48.5 `curriculum/scheduler.py`

```python
# curriculum/scheduler.py
"""
ينفّذ استراتيجية Epoch-based shift: يُنتج ملف train.jsonl منفصل
لكل epoch، بتوزيع مستويات يتحول تدريجيًا نحو الصعوبة الأعلى.
"""
import json
import random
from pathlib import Path
from collections import defaultdict

def load_levels(levels_path: Path) -> dict[str, int]:
    result = {}
    with levels_path.open() as f:
        for line in f:
            record = json.loads(line)
            result[record["sample_id"]] = record["level"]
    return result

def epoch_weights(epoch_index: int, total_epochs: int) -> dict[int, float]:
    """يُرجع وزن نسبي لكل مستوى (1-6) عند epoch معيّن.
    epoch 0: توزيع منحاز شديدًا للمستويات المبكرة.
    آخر epoch: توزيع منحاز أكثر (لكن ليس حصريًا) للمستويات المتأخرة."""
    progress = epoch_index / max(1, total_epochs - 1)  # 0.0 -> 1.0

    weights = {}
    for level in range(1, 7):
        early_bias = max(0.3, 1.0 - (level - 1) * 0.15)
        late_bias = max(0.3, level * 0.15)
        weights[level] = early_bias * (1 - progress) + late_bias * progress
    return weights

def build_epoch_dataset(
    train_path: Path, levels: dict[str, int],
    epoch_index: int, total_epochs: int, seed: int
) -> list[dict]:
    samples_by_level = defaultdict(list)
    with train_path.open() as f:
        for line in f:
            sample = json.loads(line)
            level = levels.get(sample["sample_id"], 1)
            samples_by_level[level].append(sample)

    weights = epoch_weights(epoch_index, total_epochs)
    rng = random.Random(seed + epoch_index)

    epoch_samples = []
    for level, samples in samples_by_level.items():
        weight = weights[level]
        n_to_include = max(1, int(len(samples) * weight))
        selected = rng.sample(samples, min(n_to_include, len(samples)))
        epoch_samples.extend(selected)

    rng.shuffle(epoch_samples)
    return epoch_samples

def build_all_epoch_files(
    train_path: Path, levels_path: Path, output_dir: Path,
    total_epochs: int = 3, seed: int = 42
):
    levels = load_levels(levels_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    for epoch_index in range(total_epochs):
        epoch_samples = build_epoch_dataset(
            train_path, levels, epoch_index, total_epochs, seed
        )
        out_path = output_dir / f"epoch_{epoch_index}.jsonl"
        with out_path.open("w") as f:
            for s in epoch_samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"epoch_{epoch_index}.jsonl: {len(epoch_samples)} samples")

if __name__ == "__main__":
    build_all_epoch_files(
        train_path=Path("dataset/v0.1/splits/train.jsonl"),
        levels_path=Path("curriculum/output/train_levels.jsonl"),
        output_dir=Path("curriculum/output/epoch_datasets"),
        total_epochs=3,
    )
```

> **ملاحظة عملية:** دمج هذا مع `train_sft.py` (الفصل 46) يتطلب تعديل بسيط — تحميل `epoch_N.jsonl` مختلف لكل epoch بدل ملف `train.jsonl` ثابت واحد عبر كل الـepochs. هذا تفصيل تنفيذي يُترَك للتكامل الفعلي وقت التشغيل، بحسب واجهة الحلقة التدريبية المستخدمة (`SFTTrainer` القياسي يفترض dataset واحد ثابت — دمج curriculum ديناميكي يتطلب إما `Trainer` مخصص أو استدعاء `trainer.train()` منفصل لكل epoch على التوالي).

> **Definition of Done — الجزء الخامس والعشرون:** توزيع المستويات الستة موثَّق فعليًا (`classify_dataset` نُفِّذ على `train.jsonl` الكامل)، مع وجود عينات في كل مستوى (لا مستوى فارغ تمامًا — لو وُجد، هذا يشير لفجوة حقيقية في مصادر الفصول 14-16 يجب سدّها قبل المتابعة)، وملفات `epoch_N.jsonl` الثلاثة منتجة فعليًا مع تحقق يدوي أن التحول في التوزيع بين `epoch_0` و`epoch_2` واضح ومطابق للمتوقَّع.

---

[← الجزء الرابع والعشرون](./part-24-sft.md) · [الفهرس](./README.md) · [الجزء السادس والعشرون →](./part-26-synthetic-data.md)
