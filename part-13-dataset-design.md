[← الجزء الثاني عشر](./part-12-retrieval.md) · [الفهرس](./README.md)

# الجزء الثالث عشر: Dataset Design

بعد أن أصبح لدينا كل المكوّنات (Candidates، Context، Retrieval)، هذا الجزء يحدد الشكل النهائي الذي ستُخزَّن به عينة تدريب واحدة — العقد (Contract) الذي ستلتزم به كل الأجزاء اللاحقة (توليد العينات، Quality Scoring، التدريب، التقييم).

## الفصل 27: Dataset Schema

### 27.1 لماذا Schema غني وليس بسيطًا

ذكرنا في الفصل 1 أن الهدف النهائي ليس "الكود يحتوي ثغرة" بل سلسلة تحليل كاملة. الـSchema يجب أن يفرض هذه السلسلة بنيويًا — لا يمكن للنموذج تخطي أي خطوة لأن كل خطوة حقل منفصل مطلوب.

### 27.2 الـSchema الكامل

```json
{
  "sample_id": "aosp_android14_001234",

  "source": {
    "project": "frameworks/base",
    "android_version": "14",
    "commit_before": "f6e5d4c3...",
    "commit_after": "a1b2c3d4...",
    "file": "services/core/java/com/android/server/pm/PackageManagerService.java",
    "method": "updateUserSetting",
    "cve": null
  },

  "task": "android_framework_security_review",

  "code_context": {
    "current_method": "...",
    "caller": "...",
    "security_helpers": {
      "checkCaller": "..."
    },
    "sink": null,
    "annotations": null,
    "unresolved_notes": []
  },

  "analysis": {
    "entry_point": "updateUserSetting",
    "caller": "unknown_external_caller",
    "caller_identity": "untrusted_application_uid",
    "attacker_controlled_inputs": ["targetUserId", "key", "value"],
    "permission_checks": [],
    "appops_checks": [],
    "identity_transitions": ["clearCallingIdentity", "restoreCallingIdentity"],
    "cross_user_checks": [],
    "privileged_operations": ["settingsProvider.write"],
    "trust_boundary": "application_to_system_server",
    "security_invariant": "A caller must not perform an operation on behalf of another Android user without an explicit, verifiable cross-user authorization check performed before the caller's original identity is lost.",
    "candidate_issue": "targetUserId is caller-controlled and reaches a privileged write operation without any cross-user authorization check before clearCallingIdentity().",
    "counter_evidence": [],
    "missing_context": [],
    "confidence": 0.87
  },

  "verdict": "vulnerable",

  "provenance": {
    "generation_method": "patch_derived",
    "reviewer": "manual_v1",
    "label_confidence": "high",
    "quality_score": 27
  }
}
```

### 27.3 شرح كل حقل ولماذا هو موجود

| الحقل | لماذا لا يمكن الاستغناء عنه |
|---|---|
| `source.*` | traceability كاملة — أساسي لمنع Data Leakage (الفصل 36) ولإمكانية إعادة توليد أي عينة من مصدرها الأصلي |
| `code_context.unresolved_notes` | يجعل حالات `insufficient_context` قابلة للتحقق آليًا — لو القائمة غير فارغة والحكم `vulnerable`/`secure` قاطع، هذه إشارة تناقض تستحق مراجعة |
| `analysis.attacker_controlled_inputs` | يفرض تحديد صريح للـSources (الفصل 8) بدل تركها ضمنية في السرد |
| `analysis.trust_boundary` | يربط كل عينة بمفهوم الفصل 7 — لا عينة بدون حدود ثقة محددة |
| `analysis.security_invariant` | يربط العينة بمكتبة الفصل 9 — يتيح قياس **Security Invariant Accuracy** (الفصل 2) آليًا لاحقًا |
| `analysis.counter_evidence` | يفرض على مولّد العينة (بشريًا أو بمساعدة نموذج) التفكير في السبب المضاد، تمامًا كما يجب أن يفعل النموذج المدرَّب لاحقًا |
| `analysis.confidence` | يُستخدم لاحقًا في تدريب/تقييم Confidence Calibration (الفصل 54) |
| `provenance.generation_method` | يميّز بين عينة مشتقة من patch حقيقي (`patch_derived`)، عينة negative يدوية (`manual_negative`)، أو عينة synthetic (الفصل 49) — ضروري لمراقبة توازن مصادر الـDataset |
| `provenance.quality_score` | مرجع مباشر لنظام الفصل 51 |

### 27.4 التحقق من الـSchema برمجيًا (Pydantic)

```python
# dataset/schema.py
from pydantic import BaseModel, Field
from typing import Literal

class SourceInfo(BaseModel):
    project: str
    android_version: str
    commit_before: str | None = None
    commit_after: str | None = None
    file: str
    method: str
    cve: str | None = None

class CodeContext(BaseModel):
    current_method: str
    caller: str | None = None
    security_helpers: dict[str, str | None] = Field(default_factory=dict)
    sink: str | None = None
    annotations: str | None = None
    unresolved_notes: list[str] = Field(default_factory=list)

class Analysis(BaseModel):
    entry_point: str
    caller: str
    caller_identity: str
    attacker_controlled_inputs: list[str]
    permission_checks: list[str]
    appops_checks: list[str]
    identity_transitions: list[str]
    cross_user_checks: list[str]
    privileged_operations: list[str]
    trust_boundary: str
    security_invariant: str
    candidate_issue: str
    counter_evidence: list[str]
    missing_context: list[str]
    confidence: float = Field(ge=0.0, le=1.0)

class Provenance(BaseModel):
    generation_method: Literal[
        "patch_derived", "manual_negative", "hard_negative_mined",
        "synthetic_verified", "insufficient_context_crafted"
    ]
    reviewer: str
    label_confidence: Literal["high", "medium", "low"]
    quality_score: int = Field(ge=0, le=30)

class DatasetSample(BaseModel):
    sample_id: str
    source: SourceInfo
    task: Literal["android_framework_security_review"]
    code_context: CodeContext
    analysis: Analysis
    verdict: Literal["vulnerable", "secure", "ambiguous", "insufficient_context"]
    provenance: Provenance
```

استخدام هذا الـSchema كبوابة إلزامية:

```python
# dataset/validate.py
import json
from pathlib import Path
from dataset.schema import DatasetSample
from pydantic import ValidationError

def validate_jsonl(path: Path) -> tuple[int, int]:
    valid, invalid = 0, 0
    for i, line in enumerate(path.open()):
        try:
            DatasetSample.model_validate_json(line)
            valid += 1
        except ValidationError as e:
            invalid += 1
            print(f"Line {i}: INVALID -> {e.errors()[0]['msg']}")
    return valid, invalid

if __name__ == "__main__":
    v, iv = validate_jsonl(Path("dataset/v0.1/samples.jsonl"))
    print(f"Valid: {v}, Invalid: {iv}")
    if iv > 0:
        raise SystemExit(1)  # يمنع استخدام dataset غير صالح في التدريب
```

> **قاعدة صارمة:** لا ملف JSONL يدخل مرحلة التدريب (الجزء الرابع والعشرون) قبل أن يمر بالكامل عبر `validate.py` دون أي سجل غير صالح.

---

## الفصل 28: Dataset Labels

### 28.1 التصنيفات الأربعة الأساسية

```
vulnerable            — يوجد Evidence كافٍ لانتهاك واضح لـInvariant محدد
secure                — يوجد Evidence كافٍ لوجود تحقق كافٍ قبل العملية الحساسة
ambiguous              — السياق كافٍ لكن الحكم غير قاطع (تحقق جزئي، ظروف غير مؤكدة)
insufficient_context   — لا يمكن الحكم بدون معلومة إضافية غير متاحة في السياق المُعطى
```

### 28.2 خطورة التصنيفات الرمادية (Gray Labels)

الإغراء الطبيعي هو إضافة تصنيفات وسيطة مثل `likely_vulnerable` و`likely_secure` لالتقاط درجات الثقة الدقيقة. **هذا خطر حقيقي في مرحلة v0.1** للأسباب التالية:

- **يخلق غموضًا في الـEvaluation:** كيف تُحسَب Precision/Recall (الفصل 2) لو كان `likely_vulnerable` بين الفئتين؟ يحتاج قرارًا تعسفيًا (نصف نقطة؟ threshold؟) يعقّد المقاييس دون فائدة حقيقية.
- **يشجّع الغموض بدل الحسم:** النموذج (والمُصنِّف البشري) قد يلجأ لـ`likely_*` كخروج سهل بدل إجبار نفسه على تحديد: هل الدليل كافٍ (`vulnerable`/`secure`) أم غير كافٍ (`insufficient_context`)؟
- **حقل `confidence` موجود أصلًا لهذا الغرض:** الفرق بين "vulnerable بثقة 0.6" و"vulnerable بثقة 0.95" يُعبَّر عنه عبر `analysis.confidence`، وليس عبر تصنيف verdict منفصل.

### 28.3 متى نحتاج فعلًا فئة `ambiguous`

`ambiguous` تختلف عن `insufficient_context` بدقة يجب الحفاظ عليها:

| الفئة | السياق كافٍ؟ | مثال |
|---|---|---|
| `insufficient_context` | **لا** — ينقص تعريف method أو معلومة أساسية | `checkCaller()` مذكورة لكن تعريفها غير متاح في الـcode_context |
| `ambiguous` | **نعم** — كل المعلومات اللازمة متاحة، لكن الحكم نفسه غير قاطع بطبيعته | تحقق موجود لكنه غير مكتمل بوضوح (يتحقق من القراءة لكن ليس من الكتابة، والعملية الحالية كتابة جزئية غير واضحة الحدود) |

هذا التمييز حاسم لأن الخلط بينهما يُخفي مشكلة حقيقية مختلفة: `insufficient_context` عالٍ جدًا يعني أن الـContext Builder (الفصل 26) يحتاج تحسينًا (ربما ميزانية أكبر، أو Retriever أدق)، بينما `ambiguous` عالٍ يعني أن الكود نفسه فعلًا يحتوي حالات حدّية تستحق مراجعة بشرية إضافية.

### 28.4 توزيع مستهدف تقريبي لـv0.1

```
vulnerable            : ~30%   (من Vulnerable/Fixed pairs — الفصل 29)
secure                : ~30%   (Negatives + Hard Negatives — الفصل 30-31)
insufficient_context   : ~25%   (يُصنَّع بعناية — الفصل 32)
ambiguous               : ~15%   (أصعب فئة للحصول عليها بجودة — نُقبل نسبة أقل في v0.1)
```

> هذا التوزيع تقديري وسيُعاد ضبطه فعليًا بعد أول Baseline Benchmark (الفصل 42) بناءً على أين يخطئ النموذج أكثر.

> **Definition of Done — الجزء الثالث عشر:** الـSchema (`dataset/schema.py`) يمرّ بنجاح على 20 عينة يدوية مصمَّمة يدويًا (5 من كل تصنيف)، مع تشغيل `validate.py` بنجاح كامل بدون أي سجل غير صالح، وتوثيق صريح للفرق بين `ambiguous` و`insufficient_context` في دليل المراجعين البشريين (سيُستخدم لاحقًا في الفصل 39 — Ground Truth).

---

[← الجزء الثاني عشر](./part-12-retrieval.md) · [الفهرس](./README.md) · [الجزء الرابع عشر →](./part-14-vulnerable-fixed-pairs.md)
