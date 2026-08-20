[← الجزء الخامس والعشرون](./part-25-curriculum.md) · [الفهرس](./README.md)

# الجزء السادس والعشرون: Synthetic Data

## الفصل 49: Synthetic Data

بحلول هذه المرحلة، مصادر الـDataset الحقيقية (Patches، Hard Negatives، Crafted insufficient-context) قد لا تكفي حجميًا لتغطية كل فئات الـTaxonomy (الفصل 10) بتوازن كافٍ — خصوصًا الفئات النادرة تاريخيًا في AOSP (مثل بعض أنماط IPC النادرة). هذا الفصل يبني طريقة **آمنة ومنضبطة** لتوليد بيانات إضافية، دون الوقوع في الفخ الأخطر: بيانات تخيّلية لا تعكس واقع AOSP الفعلي.

### 49.1 القاعدة الحاسمة لهذا الفصل بالكامل

```
Real AOSP code
     ↓
Real security concept (من مكتبة الفصل 9، أو Taxonomy الفصل 10)
     ↓
Generated question/task
     ↓
Generated analysis
     ↓
Verification (إلزامي — لا استثناء)
     ↓
Quality score (الفصل 51)
     ↓
Dataset
```

**وليس مطلقًا:**

```
❌ Generate random vulnerable Android code من الصفر
```

الفرق جوهري: في النهج الأول، **الكود حقيقي دائمًا** (مأخوذ فعليًا من مستودعات AOSP المُجمَّعة في الجزء السادس) — فقط السؤال أو زاوية التحليل هي المُولَّدة. في النهج الثاني (المرفوض)، حتى الكود نفسه مُتخيَّل — وهذا يعني أن النموذج يتعلّم من أنماط قد لا تُشبه الكود الحقيقي في تركيبه أو أسلوبه، مما يُضعف قدرته على التعميم على الكود الفعلي وقت الاستخدام.

### 49.2 متى نلجأ فعليًا للـSynthetic Generation

| السيناريو | لماذا Synthetic مبرَّر هنا |
|---|---|
| فئة من الـTaxonomy (الفصل 10) نادرة جدًا في الـPatches المتوفرة فعليًا | لا بديل واقعي غير توليد أسئلة إضافية حول نفس الكود الحقيقي القليل المتوفر، من زوايا تحليل مختلفة |
| الحاجة لمزيد من عينات `insufficient_context` متنوعة (تتجاوز ما أنتجه الفصل 32 يدويًا) | يمكن تطبيق `craft_by_removing_*` (الفصل 32.4) بشكل موسَّع آليًا على قاعدة أكبر من العينات الحقيقية |
| الحاجة لمزيد من صياغات مختلفة لنفس `security_invariant` (تنويع لغوي في `candidate_issue`) | لا يغيّر الكود أو الحكم — فقط يُنوِّع الصياغة النصية لتحسين قدرة النموذج على فهم نفس المفهوم بصياغات متعددة |

### 49.3 `synthetic/generate_task_variants.py`

```python
# synthetic/generate_task_variants.py
"""
يولّد أسئلة/زوايا تحليل إضافية حول code_context حقيقي موجود بالفعل
في عينة معتمدة (verified) — لا يُغيّر الكود نفسه أبدًا، فقط الزاوية
التي يُطلَب من النموذج التحليل من خلالها.
"""
import copy
import uuid
from dataclasses import dataclass

ADDITIONAL_TASK_ANGLES = [
    {
        "angle": "identify_all_trust_boundaries",
        "instruction_suffix": (
            "List every trust boundary crossed in this code path, "
            "not just the primary one."
        ),
    },
    {
        "angle": "rank_confidence_factors",
        "instruction_suffix": (
            "Explain specifically which pieces of evidence increase "
            "your confidence and which decrease it."
        ),
    },
    {
        "angle": "alternative_attacker_model",
        "instruction_suffix": (
            "Assume the caller is a pre-installed but non-privileged "
            "system app rather than a third-party app — does the "
            "verdict change?"
        ),
    },
]

@dataclass
class SyntheticVariant:
    sample: dict
    source_sample_id: str
    angle: str
    requires_verification: bool = True

def generate_variants(verified_sample: dict) -> list[SyntheticVariant]:
    """يُشترَط أن verified_sample يحمل بالفعل
    provenance.generation_method غير synthetic (أي مصدره حقيقي موثَّق)
    — لا نولّد variants من عينة synthetic أخرى (يمنع تراكم أخطاء)."""
    if verified_sample["provenance"]["generation_method"] in (
        "synthetic_verified",
    ):
        return []  # لا نولّد synthetic من synthetic

    variants = []
    for angle_def in ADDITIONAL_TASK_ANGLES:
        variant_sample = copy.deepcopy(verified_sample)
        variant_sample["sample_id"] = f"synth_{uuid.uuid4().hex[:12]}"
        variant_sample["provenance"]["generation_method"] = "synthetic_verified"
        variant_sample["provenance"]["reviewer"] = "pending_verification"
        variant_sample["provenance"]["label_confidence"] = "low"  # حتى التحقق
        variant_sample["provenance"]["quality_score"] = 0

        # الكود نفسه (code_context) يبقى دون أي تعديل — هذا هو الشرط الجوهري
        variants.append(SyntheticVariant(
            sample=variant_sample,
            source_sample_id=verified_sample["sample_id"],
            angle=angle_def["angle"],
        ))

    return variants
```

> **ملاحظة تصميمية:** لاحظ أن `label_confidence` يُضبَط تلقائيًا على `"low"` لكل عينة synthetic حتى تمر بالتحقق (الفصل 50) — لا عينة synthetic تدخل الـDataset النهائي بثقة `high` أو `medium` تلقائيًا مهما بدت معقولة.

---

## الفصل 50: Teacher Model Workflow

عندما نستخدم نموذجًا أقوى (Teacher Model — مثل نموذج أكبر حجمًا أو نموذج تجاري متقدم) لتوليد نصوص التحليل (`candidate_issue`, `security_invariant` بصياغة مُعاد كتابتها، إلخ)، **لا نثق في مخرجاته مباشرة أبدًا**. هذا الفصل يبني طبقة التحقق الإلزامية.

### 50.1 لماذا لا نثق في الـTeacher Model تلقائيًا

نموذج أقوى لا يعني نموذجًا معصومًا من الخطأ — خصوصًا في مهمة متخصصة جدًا مثل تحليل أمان Android Framework، حيث حتى نماذج قوية عامة الغرض قد: تخلط بين `permission check` و`AppOps check`، تفترض تحققًا غير موجود فعليًا في الكود المُعطى، أو تستخدم مصطلحات أمنية بشكل غير دقيق تقنيًا.

### 50.2 مراحل التحقق الأربع الإلزامية

```
Teacher Model Output (خام)
        ↓
1. Consistency check (هل يتطابق مع Security Facts المستخرجة آليًا — الفصل 21؟)
        ↓
2. Comparison with patch (لو متوفر — هل يتوافق مع ما فعله الـpatch الفعلي؟)
        ↓
3. Groundedness check (هل كل ادعاء في النص له مصدر في الكود المُعطى فعليًا؟)
        ↓
4. Reviewer score (تقييم نهائي — بشري أو نظام تحقق آلي إضافي)
        ↓
اعتماد أو رفض
```

### 50.3 `synthetic/teacher_verification.py`

```python
# synthetic/teacher_verification.py
"""
يطبّق التحقق الأربعة على مخرجات Teacher Model قبل قبولها في الـDataset.
يعتمد على Security Facts (الفصل 21) كمصدر حقيقة حتمي للمقارنة —
وليس على "شعور" بأن النص يبدو معقولاً.
"""
import re
from dataclasses import dataclass, field

@dataclass
class VerificationResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

def check_consistency_with_facts(
    teacher_output: dict, security_facts: dict
) -> tuple[bool, list[str]]:
    """يتحقق أن كل عنصر مذكور في مخرجات المعلم (مثل permission_checks)
    موجود فعليًا في Security Facts الحتمية المستخرجة آليًا."""
    issues = []
    for field_name in ["permission_checks", "appops_checks", "cross_user_checks"]:
        teacher_items = set(teacher_output.get(field_name, []))
        fact_items = set(security_facts.get(field_name, []))
        hallucinated = teacher_items - fact_items
        if hallucinated:
            issues.append(
                f"{field_name}: teacher mentioned {hallucinated} not found "
                f"in extracted security facts"
            )
    return (len(issues) == 0, issues)

def check_groundedness(
    teacher_output: dict, code_context_text: str
) -> tuple[bool, list[str]]:
    """يتحقق أن الأسماء (method/variable names) المذكورة في candidate_issue
    و counter_evidence تظهر فعليًا في نص الكود المُعطى — كشف تقريبي
    للـhallucination النصي، وليس تحققًا دلاليًا كاملاً."""
    issues = []
    text_fields = [
        teacher_output.get("candidate_issue", ""),
        " ".join(teacher_output.get("counter_evidence", [])),
    ]
    combined_text = " ".join(text_fields)

    mentioned_identifiers = set(re.findall(r"\b[a-z][a-zA-Z0-9_]{3,}\b", combined_text))
    common_words = {"this", "that", "with", "from", "before", "after", "does", "context"}
    mentioned_identifiers -= common_words

    missing = [
        ident for ident in mentioned_identifiers
        if ident not in code_context_text and len(ident) > 5
    ]
    if len(missing) > 3:  # هامش تسامح لبعض المصطلحات العامة المشروعة
        issues.append(
            f"{len(missing)} identifiers in analysis text not found in "
            f"code context — possible hallucination: {missing[:5]}"
        )
    return (len(missing) <= 3, issues)

def check_verdict_matches_patch_direction(
    teacher_output: dict, is_before_patch: bool
) -> tuple[bool, list[str]]:
    """لو العينة من نسخة 'before' patch معروف، والـverdict = 'secure'،
    هذا تناقض واضح يستحق رفضًا فوريًا (ما لم يكن الـpatch نفسه غير
    متعلق بهذه الـmethod تحديدًا — حالة نادرة تحتاج مراجعة يدوية)."""
    verdict = teacher_output.get("verdict")
    if is_before_patch and verdict == "secure":
        return (False, ["'before' snapshot marked as 'secure' — contradicts "
                         "the existence of a subsequent security patch"])
    return (True, [])

def verify_teacher_output(
    teacher_output: dict, security_facts: dict,
    code_context_text: str, is_before_patch: bool
) -> VerificationResult:
    result = VerificationResult(passed=True)

    consistent, consistency_issues = check_consistency_with_facts(
        teacher_output, security_facts
    )
    result.checks["consistency_with_facts"] = consistent
    result.issues.extend(consistency_issues)

    grounded, groundedness_issues = check_groundedness(
        teacher_output, code_context_text
    )
    result.checks["groundedness"] = grounded
    result.issues.extend(groundedness_issues)

    verdict_ok, verdict_issues = check_verdict_matches_patch_direction(
        teacher_output, is_before_patch
    )
    result.checks["verdict_direction"] = verdict_ok
    result.issues.extend(verdict_issues)

    result.passed = consistent and grounded and verdict_ok
    return result
```

### 50.4 دمج نتيجة التحقق في الـProvenance

```python
# synthetic/apply_verification.py
def apply_verification_result(sample: dict, verification: "VerificationResult") -> dict:
    if verification.passed:
        sample["provenance"]["reviewer"] = "teacher_model_verified_v1"
        sample["provenance"]["label_confidence"] = "medium"  # ليس "high" —
        # يبقى أقل من مراجعة بشرية مباشرة حتى لو اجتاز كل الفحوصات الآلية
    else:
        sample["provenance"]["reviewer"] = "teacher_model_rejected"
        sample["provenance"]["label_confidence"] = "low"
        sample["_rejection_issues"] = verification.issues  # حقل تشخيصي مؤقت،
        # يُزال قبل الدخول للـDataset النهائي، يُستخدَم فقط لمراجعة الأسباب
    return sample
```

> **قاعدة نهائية صارمة:** أي عينة `synthetic_verified` أو معتمدة عبر Teacher Model **لا تتجاوز أبدًا** `label_confidence = "medium"` تلقائيًا — الترقية إلى `"high"` تتطلب مراجعة بشرية مباشرة إضافية، بصرف النظر عن قوة الفحوصات الآلية. هذا يحافظ على تسلسل الثقة الهرمي من الفصل 39 (Ground Truth) متسقًا عبر كل مصادر الـDataset.

> **Definition of Done — الجزء السادس والعشرون:** لا يُضاف أي sample بـ`generation_method: synthetic_verified` للـDataset النهائي قبل اجتياز `verify_teacher_output` بنجاح كامل (كل الفحوصات الثلاثة `True`)، مع سجل واضح لعدد العينات المرفوضة مقابل المقبولة من كل دفعة Teacher Model generation — نسبة رفض مرتفعة جدًا (> 40%) تشير لمشكلة في الـprompt الموجَّه للـTeacher Model نفسه، تستحق تعديلاً قبل الاستمرار بنفس الطريقة.

---

[← الجزء الخامس والعشرون](./part-25-curriculum.md) · [الفهرس](./README.md) · [الجزء السابع والعشرون →](./part-27-quality-scoring.md)
