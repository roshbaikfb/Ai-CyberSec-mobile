[← الجزء الخامس عشر](./part-15-secure-negatives.md) · [الفهرس](./README.md)

# الجزء السادس عشر: Insufficient Context

## الفصل 32: تعليم النموذج عدم التخمين

هذا الفصل يبني الفئة الرابعة والأخيرة من التصنيفات (الفصل 28) بشكل ممنهج ومقصود. الهدف: نموذج يقول **"لا أملك معلومات كافية"** بثقة، بدل أن يخترع إجابة تبدو معقولة.

### 32.1 لماذا هذا يقلل الـHallucination فعليًا

لو كل عينة تدريب تحمل حكمًا قاطعًا (`vulnerable` أو `secure`)، النموذج يتعلم ضمنيًا أن **كل سؤال له إجابة قاطعة** — وهذا خطأ جوهري. في الواقع، جزء كبير من عمليات المراجعة الأمنية الحقيقية تتوقف عند: "أحتاج أرى تعريف هذه الدالة قبل أن أحكم." تعليم النموذج هذا النمط صراحة، وبكثافة كافية في الـDataset، هو ما يمنعه من الانزلاق نحو التخمين الواثق عند مواجهة سيناريو مشابه لاحقًا.

### 32.2 الاستراتيجيتان لتوليد عينات Insufficient Context

| الاستراتيجية | الوصف | الميزة |
|---|---|---|
| **Natural** | Candidates حقيقية (من الفصل 22/26) حيث `unresolved_notes` غير فارغة فعليًا — أي أن الـRetriever (الفصل 25) لم يستطع حل استدعاء أمني بالفعل | تعكس واقع النظام الفعلي، بدون تصنّع |
| **Crafted** | أخذ عينة `vulnerable`/`secure` معروفة الحكم، ثم **إزالة** الجزء الحاسم من الـcontext (تعريف helper، أو الـcaller) عمدًا لصناعة حالة اضطرارية | تحكم كامل في التوازن الكمّي للـDataset، وضمان تنوّع كافٍ |

### 32.3 المصدر الطبيعي (Natural) — لا حاجة لكود إضافي

هذه العينات هي ببساطة نتيجة مباشرة لمرور Candidates عبر الـContext Builder (الفصل 26): أي Candidate حيث `AssembledContext.unresolved_notes` غير فارغة، **ووفقًا للقاعدة الافتراضية في الفصل 7.3**، يجب أن يُصنَّف تلقائيًا كمرشّح لـ`insufficient_context` ما لم توجد أدلة أخرى كافية بصرف النظر عن الجزء غير المحلول.

```python
# insufficient_context/natural_candidates.py
import json
from pathlib import Path

def filter_natural_insufficient_context(
    assembled_contexts_jsonl: Path, output_path: Path
):
    """يفلتر السياقات المُجمَّعة (مخرجات الفصل 26) التي تحتوي
    unresolved_notes غير فارغة — هذه أقوى مرشحين لعينات
    insufficient_context طبيعية (وليست مُصنَّعة)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    total, kept = 0, 0

    with assembled_contexts_jsonl.open() as fin, output_path.open("w") as fout:
        for line in fin:
            ctx = json.loads(line)
            total += 1
            if ctx.get("unresolved_notes"):
                fout.write(json.dumps(ctx, ensure_ascii=False) + "\n")
                kept += 1

    print(f"{kept}/{total} contexts have genuine unresolved dependencies "
          f"(natural insufficient_context candidates)")
```

### 32.4 المصدر المُصنَّع (Crafted) — `insufficient_context/craft_from_known.py`

```python
# insufficient_context/craft_from_known.py
"""
يأخذ sample معروفة الحكم (vulnerable أو secure) من الـDataset الحالي،
ويُنتج نسخة معدَّلة منها بإزالة جزء حاسم من code_context، مع تحديث
الحكم إلى insufficient_context وتوثيق بالضبط ما أُزيل.

قاعدة صارمة: لا نُصدر نسخة crafted إلا لو كان الجزء المُزال فعلاً
ضروريًا للحكم الأصلي — إزالة جزء غير مؤثر لا تصنع حالة insufficient_context
حقيقية، بل مجرد ضوضاء.
"""
import copy
import uuid
from dataclasses import dataclass

@dataclass
class CraftedResult:
    sample: dict
    removed_element: str
    justification: str

def craft_by_removing_security_helper(original_sample: dict) -> CraftedResult | None:
    helpers = original_sample["code_context"].get("security_helpers", {})
    if not helpers:
        return None  # لا يوجد helper لإزالته أصلاً

    # نتأكد أن هذا الـhelper مذكور فعليًا في الحكم الأصلي كجزء من السبب
    candidate_issue = original_sample["analysis"]["candidate_issue"].lower()
    removable_helper = None
    for helper_name in helpers:
        if helper_name.lower() in candidate_issue or helpers[helper_name] is not None:
            removable_helper = helper_name
            break
    if not removable_helper:
        return None

    crafted = copy.deepcopy(original_sample)
    crafted["sample_id"] = f"crafted_{uuid.uuid4().hex[:12]}"
    crafted["code_context"]["security_helpers"][removable_helper] = None
    crafted["code_context"]["unresolved_notes"] = [
        f"Definition of '{removable_helper}' was intentionally withheld "
        f"to construct an insufficient-context evaluation case."
    ]
    crafted["analysis"]["candidate_issue"] = (
        f"Cannot determine outcome without visibility into "
        f"'{removable_helper}' — its behavior is decisive for this case."
    )
    crafted["analysis"]["missing_context"] = [removable_helper]
    crafted["analysis"]["confidence"] = 0.25
    crafted["verdict"] = "insufficient_context"
    crafted["provenance"]["generation_method"] = "insufficient_context_crafted"
    crafted["provenance"]["reviewer"] = "auto_crafted_v1"
    crafted["provenance"]["label_confidence"] = "medium"

    return CraftedResult(
        sample=crafted,
        removed_element=removable_helper,
        justification=(
            f"Original sample's verdict depended on the resolved definition "
            f"of '{removable_helper}'; removing it invalidates the original "
            f"verdict and creates a genuine ambiguity."
        ),
    )

def craft_by_removing_caller(original_sample: dict) -> CraftedResult | None:
    if not original_sample["code_context"].get("caller"):
        return None

    crafted = copy.deepcopy(original_sample)
    crafted["sample_id"] = f"crafted_{uuid.uuid4().hex[:12]}"
    crafted["code_context"]["caller"] = None
    crafted["code_context"]["unresolved_notes"] = [
        "Calling method not available — cannot verify whether "
        "authorization was already performed upstream."
    ]
    crafted["analysis"]["missing_context"] = ["caller method definition"]
    crafted["analysis"]["confidence"] = 0.3
    crafted["verdict"] = "insufficient_context"
    crafted["provenance"]["generation_method"] = "insufficient_context_crafted"
    crafted["provenance"]["reviewer"] = "auto_crafted_v1"
    crafted["provenance"]["label_confidence"] = "medium"

    return CraftedResult(
        sample=crafted,
        removed_element="caller",
        justification=(
            "Original verdict assumed no prior validation upstream; "
            "removing caller visibility makes that assumption unverifiable."
        ),
    )
```

### 32.5 مثال ناتج نهائي

```json
{
  "sample_id": "crafted_a1b2c3d4e5f6",
  "source": { "...": "same as original" },
  "task": "android_framework_security_review",
  "code_context": {
    "current_method": "...",
    "caller": null,
    "security_helpers": { "checkCaller": null },
    "sink": null,
    "annotations": null,
    "unresolved_notes": [
      "Definition of 'checkCaller' was intentionally withheld to construct an insufficient-context evaluation case."
    ]
  },
  "analysis": {
    "entry_point": "updateUserSetting",
    "candidate_issue": "Cannot determine outcome without visibility into 'checkCaller' — its behavior is decisive for this case.",
    "missing_context": ["checkCaller"],
    "confidence": 0.25,
    "...": "other fields carried from original"
  },
  "verdict": "insufficient_context",
  "provenance": {
    "generation_method": "insufficient_context_crafted",
    "reviewer": "auto_crafted_v1",
    "label_confidence": "medium",
    "quality_score": 0
  }
}
```

### 32.6 لماذا لا نصنع insufficient_context بحذف عشوائي

قد يبدو مغريًا حذف أي جزء عشوائي من أي عينة لتوليد كمية كبيرة من عينات `insufficient_context` بسرعة. **هذا خطأ منهجي خطير**: لو الجزء المحذوف لم يكن فعليًا مؤثرًا في الحكم الأصلي، فالحكم الصحيح للنسخة الناتجة لا يزال `vulnerable`/`secure` كما كان — والنموذج سيتعلم توصيفًا خاطئًا لـ`insufficient_context` (سيظن أن غياب أي تفصيل عشوائي كافٍ لتبرير عدم الحسم، بينما المطلوب فعليًا هو غياب معلومة **حاسمة**).

لهذا كل من `craft_by_removing_security_helper` و`craft_by_removing_caller` تتحقق أولًا أن العنصر المُراد حذفه **مذكور فعليًا كجزء من سبب الحكم الأصلي** قبل المتابعة.

> **Definition of Done — الجزء السادس عشر:** لا يقل عدد عينات `insufficient_context` النهائية (Natural + Crafted مجتمعتين) عن 20% من إجمالي الـDataset (مطابقة للتوزيع المستهدف في الفصل 28.4)، مع مراجعة يدوية لعشر عينات crafted للتأكد أن الجزء المحذوف كان فعلاً حاسمًا وليس عشوائيًا.

---

[← الجزء الخامس عشر](./part-15-secure-negatives.md) · [الفهرس](./README.md) · [الجزء السابع عشر →](./part-17-provenance.md)
